"""第二轮复审：真实反应变化的目标投影、环变化未知状态及回放前提。"""

import pytest
from pydantic import ValidationError

from reaction_reference.analogs.transfer import generate_proposals
from reaction_reference.application.budget import Budget, BudgetExceeded
from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import (
    BudgetConfig,
    Material,
    QueryFamily,
    ReactionRecord,
    Reference,
    SourceRef,
)
from reaction_reference.reaction_analysis.analyze import analyze_reaction, project_changes


def graph_record(mapped):
    """构造明确标记为合成示例的两侧图，用于验证图解释而非实验可行性。"""
    left, right = mapped.split(">>")
    materials = [
        Material(instance_id=f"{role}:{i}", role=role, smiles=smiles)
        for role, side in [("reactant", left), ("product", right)]
        for i, smiles in enumerate(side.split("."))
    ]
    return ReactionRecord(
        id="graph",
        source=SourceRef(
            namespace="test", record_id="graph", experiment_id="graph", synthetic=True
        ),
        materials=materials,
        mapped_reaction_smiles=mapped,
    )


@pytest.mark.parametrize(
    "mapped",
    [
        "[OH:1]C1CCC1>>[OH:1]CCCC",
        "[OH:1]CCCC>>[OH:1]C1CCC1",
        "[CH3:1][OH:2].C1CCC1>>[CH3:1][OH:2]",
    ],
)
def test_unresolved_ring_changes_are_not_reported_as_retained(mapped):
    """未映射区域或未跟踪片段涉及环变化时，不能宣称全反应保留环拓扑。"""
    analysis = analyze_reaction(graph_record(mapped))
    assert "ring_topology_retained" not in analysis.topology
    assert "ring_topology_unknown" in analysis.topology
    assert "cycle_rank_changed_but_event_unresolved" in analysis.reasons


def test_fully_mapped_unchanged_ring_is_retained():
    """完整映射且环图不变时，仍可报告环拓扑保留。"""
    side = "[CH2:1]1[CH2:2][CH2:3]1"
    assert analyze_reaction(graph_record(side + ">>" + side)).topology == ["ring_topology_retained"]


@pytest.mark.parametrize(
    "mapped,target_text,query",
    [
        ("[CH3:1][O:2][NH2:3]>>[CH2:1]1[O:2][NH:3]1", "CON", "[#6]-[#8]-[#7]"),
        ("[CH3:1].[CH3:2]>>[CH3:1][CH3:2]", "C=C", "[#6]~[#6]"),
    ],
)
def test_projected_formation_must_be_an_actual_target_bond(mapped, target_text, query):
    """来源成键投影必须在目标中存在且键型一致，宽泛核心匹配不能制造目标成键。"""
    record = graph_record(mapped)
    material = next(m for m in record.materials if m.role == "product")
    target = parse(target_text)
    family = QueryFamily(
        id="query",
        layer="core",
        core_smarts=query,
        target_atoms=list(range(target.GetNumAtoms())),
        rule_id="test",
        rule_version="1",
        description="允许记录额外内部边",
        core_topology_policy="record_extra_internal_edges",
    )
    witness = match_family(family, parse(material.smiles), target, "source").witnesses[0]
    analysis = analyze_reaction(record)
    assert analysis.formed
    projected = project_changes(record, material, witness, analysis, target=target)
    assert not projected["formed_target_bonds"]


def amide_reference(amide):
    """构造已有来源酰胺反应的最小回放参考。"""
    return Reference(
        id="amide",
        record=amide,
        material=amide.materials[-1],
        family_ids=[],
        layers=["whole"],
        witnesses=[],
        analysis=analyze_reaction(amide),
        molecular_weight=149.0,
    )


def test_failed_source_replays_consume_attempt_budget(amide, monkeypatch):
    """自回放即使没有复现来源产物也必须计入尝试预算，不能无额度继续调用。"""
    rule = {"id": "identity", "forward": "[C:1].[C:2]>>[C:1].[C:2]", "retro": "[C:1]>>[C:1].[C:2]"}

    def rules(_):
        """提供只返回原输入、无法得到酰胺产物的受控规则。"""
        return [rule]

    monkeypatch.setattr("reaction_reference.analogs.transfer.source_rules", rules)
    budget = Budget(BudgetConfig(max_tasks=4))
    for _ in range(3):
        budget.task("earlier_work", "test")
    with pytest.raises(BudgetExceeded, match="task_budget"):
        generate_proposals(amide_reference(amide), parse("CCCNC(=O)c1ccccc1"), budget)
    assert budget.events[-1].kind == "transfer_replay"


def test_documented_step_requires_nonblank_citation(amide):
    """步骤引用只有空白时，不能将记录校验为明确的单步反应。"""
    data = amide.model_dump()
    data["documented_step_ref"] = " \t\n"
    with pytest.raises(ValidationError):
        ReactionRecord.model_validate(data)


def test_transfer_rechecks_blank_step_citation(amide):
    """即使调用方通过复制构造了未重校验记录，回放仍应拒绝空白步骤引用。"""
    record = amide.model_copy(update={"documented_step_ref": " \t"})
    proposals, reason = generate_proposals(
        amide_reference(amide).model_copy(update={"record": record}),
        parse("CCCNC(=O)c1ccccc1"),
        Budget(BudgetConfig()),
    )
    assert not proposals and reason == "source_step_not_assigned"
