"""全局代码复审回归：跨模块输出、去重及异常路径必须保持一致。"""

import json

import pytest
from rdkit import Chem

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.analogs.transfer import generate_proposals
from reaction_reference.application.budget import Budget
from reaction_reference.application.search import search
from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import meets_target, parse
from reaction_reference.domain.models import (
    BudgetConfig,
    Material,
    Observation,
    QueryFamily,
    ReactionRecord,
    Reference,
    SourceRef,
)
from reaction_reference.evaluation.runner import evaluate
from reaction_reference.ports.sources import Candidate, CandidatePage
from reaction_reference.reaction_analysis.analyze import analyze_reaction
from reaction_reference.retrieval.planner import exact_family, initial_families
from reaction_reference.rules import load_rules


@pytest.fixture
def symmetric_reduction():
    """构造有完整输入/产物依据的对称酮还原示例，触发等价模板映射。"""
    return ReactionRecord(
        id="symmetric-reduction",
        source=SourceRef(
            namespace="test", record_id="reduction", experiment_id="reduction", synthetic=True
        ),
        materials=[
            Material(instance_id="input", role="reactant", smiles="CC(=O)C", actual_input=True),
            Material(instance_id="product", role="product", smiles="CC(O)C"),
        ],
        observations=[
            Observation(
                product_instance_id="product",
                result="reported_prepared",
                evidence_text="还原并分离产物的测试数据",
                source_location="合成测试段落",
            )
        ],
        event_scope="documented_step",
        documented_step_ref="合成测试段落",
        mapped_reaction_smiles="[CH3:1][C:2](=[O:3])[CH3:4]>>[CH3:1][CH:2]([OH:3])[CH3:4]",
        retro_template="[C:1]([O:2])([C:3])[C:4]>>[C:1](=[O:2])([C:3])[C:4]",
    )


def test_symmetric_replay_returns_unique_proposals(symmetric_reduction):
    """两个等价逆向映射不能占用两个建议名额或产生相同建议 ID。"""
    record = symmetric_reduction
    reference = Reference(
        id="reduction-reference",
        record=record,
        material=record.materials[-1],
        family_ids=[],
        layers=["whole"],
        witnesses=[],
        analysis=analyze_reaction(record),
        molecular_weight=60.0,
    )
    proposals, reason = generate_proposals(
        reference, parse("CCC(O)CC"), Budget(BudgetConfig(max_tasks=100))
    )
    assert reason is None
    assert len(proposals) == len({proposal.id for proposal in proposals}) == 1
    assert proposals[0].proposed_reactants == ["CCC(=O)CC"]


def test_search_counts_and_displays_symmetric_proposal_once(
    symmetric_reduction, tmp_path, request_factory
):
    """端到端资料包、统计与展示列表只能保留一次相同替换建议。"""
    path = tmp_path / "symmetric.jsonl"
    path.write_text(symmetric_reduction.model_dump_json() + "\n", encoding="utf-8")
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                "CCC(O)CC",
                budget={"max_tasks": 100},
                options={"exhaustive_fixture": True, "include_usage": False},
            ),
            source,
        )
    finally:
        source.close()
    assert package.proposals
    assert len(package.proposals) == len({proposal.id for proposal in package.proposals}) == 1
    assert package.statistics["proposals"] == 1
    assert len(package.displayed_proposal_ids) == len(set(package.displayed_proposal_ids)) == 1


@pytest.mark.parametrize("labels", ["patent:1", {"patent:1": False}, [1], [" "]])
def test_evaluation_rejects_malformed_method_labels(tmp_path, labels):
    """错误标签格式不能被 set 隐式转换成字符或字典键，再当作人工审核正例计分。"""
    source_path = tmp_path / "source.jsonl"
    source_path.write_text(
        json.dumps({"id": 1, "product_smiles": ["CCO"]}) + "\n", encoding="utf-8"
    )
    targets_path = tmp_path / "targets.jsonl"
    targets_path.write_text(
        json.dumps(
            {
                "id": "target",
                "target_smiles": "CCO",
                "label_state": "reviewed",
                "useful_method_record_ids": labels,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    with pytest.raises(ValueError, match="useful_method_record_ids"):
        evaluate(source_path, targets_path, output)
    assert not output.exists()


@pytest.mark.parametrize("task_limit", [4, 5])
@pytest.mark.parametrize("requires_io", [False, True])
def test_minimum_task_budget_can_complete_one_reference(
    amide, request_factory, monkeypatch, task_limit, requires_io
):
    """合法的四/五任务预算足够取页、核验、可选详情和一次分析，不能在取页前耗尽。"""
    import reaction_reference.application.search as module

    product = amide.materials[-1]
    family = exact_family(parse(product.smiles))
    monkeypatch.setattr(module, "initial_families", lambda *_: [family])

    class Source:
        """只有一条完整目标材料的来源，可切换是否需要额外详情 I/O。"""

        snapshot_id = "minimum-task-budget"
        max_selection_stage = 0
        hydration_requires_io = requires_io
        issues = []

        def candidate_page(self, *args):
            """一次返回完整有限来源，确保本例预算只需覆盖一次处理链。"""
            return CandidatePage([Candidate("product", product, amide)], None, True, True, "test")

        def hydrate(self, record):
            """返回原记录，详情动作是否单独计数由来源能力声明控制。"""
            return record

    package = search(
        request_factory(
            product.smiles,
            budget={"max_tasks": task_limit},
            options={
                "include_usage": False,
                "include_proposals": False,
                "directed_followups": False,
                "exhaustive_fixture": True,
            },
        ),
        Source(),
    )
    assert len(package.results) == 1
    assert package.results[0].target_requirements_satisfied
    assert len(package.tasks) == (4 if requires_io else 3)
    assert package.coverage_state == "complete" and not package.stop_reasons


@pytest.mark.parametrize("proposal_limit", [1, 12])
def test_verified_proposal_survives_later_replay_budget_exhaustion(
    amide, request_factory, monkeypatch, proposal_limit
):
    """首条建议已通过正向回放后，下一条规则耗尽预算不能抹掉这条有效部分结果。"""
    import reaction_reference.application.search as module

    record = amide.model_copy(
        update={"retro_template": load_rules()[0]["transfer_rules"][0]["retro"]}
    )
    family = QueryFamily(
        id="amide-carbonyl",
        layer="whole",
        core_smarts="[CX3]=[OX1]",
        target_atoms=[4, 5],
        rule_id="test",
        rule_version="1",
        description="保留羰基的测试家族",
    )
    monkeypatch.setattr(module, "initial_families", lambda *_: [family])

    class Source:
        """返回可由来源模板和注册模板分别自回放的同一酰胺反应。"""

        snapshot_id = "proposal-budget-prefix"
        max_selection_stage = 0
        hydration_requires_io = False
        issues = []

        def candidate_page(self, *args):
            """一次返回酰胺产物，检索链只使用三个任务额度。"""
            return CandidatePage(
                [Candidate("amide", record.materials[-1], record)], None, True, True, "test"
            )

        def hydrate(self, record):
            """完整示例无需额外详情读取。"""
            return record

    package = search(
        request_factory(
            budget={"max_tasks": 4, "max_proposals": proposal_limit},
            options={
                "include_usage": False,
                "directed_followups": False,
                "exhaustive_fixture": True,
            },
        ),
        Source(),
    )
    assert len(package.proposals) == 1
    assert package.proposals[0].target_found
    assert package.statistics["proposals"] == 1
    assert package.displayed_proposal_ids == [package.proposals[0].id]
    assert ("task_budget" in package.stop_reasons) is (proposal_limit > 1)
    assert package.feature_status["single_reactant_transfer"].state == "partial"


@pytest.mark.parametrize(
    "row",
    [None, [], {"id": None, "target_smiles": "CCO"}, {"id": "target", "target_smiles": ["CCO"]}],
)
def test_invalid_evaluation_row_is_rejected_before_source_access(tmp_path, row):
    """非法目标行在读取来源前得到输入错误，不泄漏类型异常或启动无效评测。"""
    targets = tmp_path / "targets.jsonl"
    targets.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Evaluation target"):
        evaluate(tmp_path / "not-read.jsonl", targets, tmp_path / "output.json")


@pytest.mark.parametrize("label_state", ["reviewed", "unreviewed"])
def test_valid_evaluation_labels_preserve_reviewed_only_scoring(tmp_path, label_state):
    """合法标签只在已审核时计分，屏蔽组剔除被屏蔽正例且不伪造零或满分。"""
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps({"id": 1, "product_smiles": ["CCO"]}) + "\n", encoding="utf-8")
    targets = tmp_path / "targets.jsonl"
    targets.write_text(
        json.dumps(
            {
                "id": "target",
                "target_smiles": "CCO",
                "label_state": label_state,
                "useful_method_record_ids": ["patent:1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    evaluate(source, targets, output)
    observed, masked = json.loads(output.read_text(encoding="utf-8"))["cases"]
    assert observed["annotated_method_recall"] == (1.0 if label_state == "reviewed" else None)
    assert masked["annotated_method_recall"] is None
    assert not masked["structural_exact_target_found"]


def test_reordered_target_self_matches_keep_complete_joint_coverage():
    """对环系、无环、同位素及立体目标改变原子遍历顺序，核对预筛、身份和联合覆盖。"""
    examples = [
        "CCO",
        "CC(C)O",
        "CC(=O)NCC",
        "CCCNC(=O)c1ccccc1",
        "c1ccc2ccccc2c1",
        "C1CCC2(CC1)CCCC2",
        "C1CC2CCC1C2",
        "NCC(=O)O",
        "CC(C)(C)OC(=O)N[C@@H](C)c1ccccc1",
        "C/C=C/C(=O)N",
        "[2H]OC(C)C",
        "C[13CH2]CO",
        "CCC(O)CC",
        "[O-][N+](=O)c1ccccc1",
        "C1CCCCC1C2CCCCC2",
    ]
    from rdkit import DataStructs

    for smiles in examples:
        target = parse(smiles, target=True)
        for alternate in Chem.MolToRandomSmilesVect(target, 8, randomSeed=731):
            candidate = parse(alternate)
            assert meets_target(candidate, target), (smiles, alternate)
            for family in initial_families(target):
                query = Chem.MolFromSmarts(family.core_smarts)
                assert DataStructs.AllProbeBitsMatch(
                    Chem.PatternFingerprint(query), Chem.PatternFingerprint(candidate)
                ), (smiles, alternate, family.rule_id)
                matched = match_family(family, candidate, target, "permuted", max_mappings=2048)
                assert matched.enumeration_complete, (smiles, alternate, family.rule_id)
                assert matched.state == "match", (smiles, alternate, family.rule_id)
                assert max(w.target_atom_coverage for w in matched.witnesses) == 1, (
                    smiles,
                    alternate,
                    family.rule_id,
                )
