"""建议回放上限回归：保留已验证建议，同时准确披露因局部数量上限停止的范围。"""

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.analogs.transfer import generate_proposals
from reaction_reference.application.budget import Budget
from reaction_reference.application.search import search
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import BudgetConfig, Reference
from reaction_reference.reaction_analysis.analyze import analyze_reaction
from reaction_reference.rules import load_rules


@pytest.fixture
def halide_transfer_case(amide):
    """构造三种仅用于程序测试的酰卤图回放规则，不表示其条件或实验可行性等价。"""
    registered = load_rules()[0]["transfer_rules"][0]
    rules = [
        {
            **registered,
            "id": f"test-halide-{halide}",
            "forward": registered["forward"].replace("[Cl]", "[Cl,Br,I]"),
            "retro": registered["retro"].replace("[Cl]", f"[{halide}]"),
        }
        for halide in ("Cl", "Br", "I")
    ]
    reference = Reference(
        id="transfer-limit",
        record=amide,
        material=amide.materials[-1],
        family_ids=[],
        layers=["whole"],
        witnesses=[],
        analysis=analyze_reaction(amide),
        molecular_weight=149,
    )
    return reference, parse("CCNC(=O)c1ccc(F)cc1"), rules


@pytest.mark.parametrize("rule_count", [1, 3])
def test_per_reference_proposal_limit_reports_stopped_enumeration(
    halide_transfer_case, monkeypatch, rule_count
):
    """有第三种可回放输入时，保留前两条并报告局部停止；只有一条的对照仍正常完成。"""
    reference, target, rules = halide_transfer_case
    monkeypatch.setattr(
        "reaction_reference.analogs.transfer.source_rules", lambda _: rules[:rule_count]
    )
    proposals, reason = generate_proposals(reference, target, Budget(BudgetConfig(max_tasks=100)))
    assert len(proposals) == min(rule_count, 2)
    assert len({tuple(p.proposed_reactants) for p in proposals}) == len(proposals)
    assert all(
        p.target_found and p.enumeration_complete and p.validation_complete for p in proposals
    )
    assert reason == ("per_reference_proposal_limit" if rule_count == 3 else None)
    if rule_count == 3:
        monkeypatch.setattr("reaction_reference.analogs.transfer.source_rules", lambda _: rules[2:])
        extra, extra_reason = generate_proposals(
            reference, target, Budget(BudgetConfig(max_tasks=100))
        )
        assert extra_reason is None and len(extra) == 1
        assert extra[0].proposed_reactants not in [p.proposed_reactants for p in proposals]


def test_local_proposal_limit_keeps_results_and_marks_transfer_partial(
    halide_transfer_case, monkeypatch, tmp_path, request_factory
):
    """完整检索包须保留两条有效建议，将局部上限写入替换分析的部分状态及原因。"""
    reference, _, rules = halide_transfer_case
    monkeypatch.setattr("reaction_reference.analogs.transfer.source_rules", lambda _: rules)
    path = tmp_path / "records.jsonl"
    path.write_text(reference.record.model_dump_json() + "\n", encoding="utf-8")
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                "CCNC(=O)c1ccc(F)cc1",
                options={
                    "exhaustive_fixture": True,
                    "include_usage": False,
                    "directed_followups": False,
                },
                budget={"max_tasks": 100},
            ),
            source,
        )
        assert len(package.proposals) == package.statistics["proposals"] == 2
        assert set(package.displayed_proposal_ids) == {
            proposal.id for proposal in package.proposals
        }
        status = package.feature_status["single_reactant_transfer"]
        assert status.state == "partial"
        assert "per_reference_proposal_limit" in status.reason
    finally:
        source.close()
