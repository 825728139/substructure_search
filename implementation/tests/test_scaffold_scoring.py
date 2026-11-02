"""评分框架回归：母核贡献、支链方向、权重可补偿性与逐项解释。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import Reference, RerankRequest, RunState
from reaction_reference.interfaces.sdk import Client
from reaction_reference.ranking import scoring
from reaction_reference.ranking.engine import rank_references
from reaction_reference.ranking.scaffold import target_regions


def bridge_examples():
    """读取真实复杂桥环目标的三条方法，保留反应结构与全部一致见证。"""
    payload = json.loads(
        (Path(__file__).parent / "fixtures/scaffold_score_ranking.json").read_text()
    )
    return payload["target_smiles"], [
        Reference.model_validate_json(json.dumps(r)) for r in payload["references"]
    ]


def test_bridge_formation_beats_exact_ethyl_ester_tail_environment():
    """母核构建覆盖胜过小片段的零环境差异，不依赖候选输入顺序。"""
    target, references = bridge_examples()
    for order in (references, list(reversed(references))):
        ranked, displayed = rank_references(order, target_smiles=target)
        shown = [r for r in ranked if r.id in displayed]
        assert {r.record.source.record_id for r in shown[:2]} == {"9033888", "9392974"}
        assert shown[-1].record.source.record_id == "62248"
        spatial = shown[-1].ranking_features["target_scaffold_relevance"]
        assert spatial["weighted_core_coverage"] == 0
        assert spatial["center_bonus"] == 0
        assert spatial["center_location"] == "branch_remote_or_unresolved"
        assert all(
            r.ranking_features["target_scaffold_relevance"]["center_location"] == "core_internal"
            for r in shown[:2]
        )


def test_score_is_sum_of_visible_components_and_query_labels_do_not_change_it():
    """分数可以逐项复算；更换召回层标签不能凭空改变同一结构方法的价值。"""
    target, references = bridge_examples()
    ranked, _ = rank_references(references, target_smiles=target)
    for reference in ranked:
        score = reference.ranking_features["score"]
        assert score["total"] == pytest.approx(
            sum(c["points"] for c in score["components"].values())
        )
        assert 0 <= score["total"] <= 100
        assert all(0 <= c["value"] <= 1 for c in score["components"].values())
        assert all(
            c["points"] == pytest.approx(c["value"] * c["weight"])
            for c in score["components"].values()
        )
        relabeled = reference.model_copy(
            update={"layers": ["whole"], "family_ids": ["different-query"]}
        )
        refreshed, _ = rank_references([relabeled], target_smiles=target)
        assert refreshed[0].ranking_features["score"]["total"] == pytest.approx(score["total"])


def test_weights_can_trade_off_instead_of_hard_priority(monkeypatch):
    """仅提高环境分权重会改变结果，证明框架按总分而非隐藏的母核优先级排序。"""
    target, references = bridge_examples()
    policy = json.loads(json.dumps(scoring.scoring_policy()))
    policy["weights"] = dict.fromkeys(policy["weights"], 0)
    policy["weights"]["environment_match"] = 100
    monkeypatch.setattr(scoring, "scoring_policy", lambda: policy)
    ranked, _ = rank_references(references, target_smiles=target)
    assert ranked[0].record.source.record_id == "62248"


def test_benzamide_connection_is_head_not_core_internal():
    """苯甲酰胺的C—N键属于直接连接官能团，应判为支链头部而非母核内部。"""
    payload = json.loads(
        (Path(__file__).parent / "fixtures/target_center_ranking.json").read_text()
    )
    references = [Reference.model_validate_json(json.dumps(r)) for r in payload["references"]]
    ranked, _ = rank_references(references, target_smiles=payload["target_smiles"])
    reference = next(r for r in ranked if r.record.source.record_id == "2174992")
    spatial = reference.ranking_features["target_scaffold_relevance"]
    assert spatial["weighted_core_coverage"] == 1
    assert spatial["center_location"] == "core_branch_head"
    assert spatial["center_bonus"] == 0.8


@pytest.mark.parametrize("smiles", ["CCCCNC(=O)CCC", "CCCCCC", "CC(O)CNCCO"])
def test_acyclic_target_has_real_functional_or_chain_core(smiles):
    """无环目标也有功能锚点骨架，索引属于实际目标，不把缺少环当作没有母核。"""
    target = parse(smiles)
    regions = target_regions(target)
    assert regions["core_weights"]
    assert set(regions["core_weights"]) <= set(range(target.GetNumAtoms()))
    assert all(value > 0 for value in regions["core_weights"].values())


def test_ethyl_ester_tail_does_not_become_branch_head():
    """即使酯直接连接苯环，O—乙基的远端成键也不能冒充母核与支链头部成键。"""
    regions = target_regions(parse("CCOC(=O)c1ccccc1"))
    assert (1, 2) not in regions["head_bonds"]
    assert (2, 3) in regions["head_bonds"]
    assert (3, 5) in regions["head_bonds"]


def test_search_and_frozen_rerank_use_original_target_atom_order(
    tmp_path, settings, request_factory
):
    """复杂桥环输入规范化后原子序不同，初检和冻结重排都必须沿用见证的原输入编号。"""
    target, references = bridge_examples()
    path = tmp_path / "methods.jsonl"
    path.write_text("\n".join(r.record.model_dump_json() for r in references))
    source = JsonlSource(path, exhaustive=True)
    request = request_factory(
        target, options={"include_proposals": False}, budget={"max_tasks": 160}
    )
    try:
        package = search(request, source)
    finally:
        source.close()
    assert package.target_input_smiles != package.target_smiles
    expected, _ = rank_references(package.results, target_smiles=target)
    by_id = {r.id: r for r in expected}
    for reference in package.results:
        assert reference.ranking_features["score"] == by_id[reference.id].ranking_features["score"]
        if reference.record.source.record_id in {"9033888", "9392974"}:
            assert reference.ranking_features["target_scaffold_relevance"][
                "weighted_core_coverage"
            ] == pytest.approx(21 / 43)
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=package.run_id,
        lifecycle="succeeded",
        request=request,
        created_at=now,
        updated_at=now,
        snapshot_id=package.snapshot_id,
    )
    with Client(settings) as client:
        client.manager.store.create(state)
        client.manager.store.save_package(package)
        derived = client.rerank(package.run_id, RerankRequest(ranking_profile="reference_first"))
        frozen = client.manager.store.package(derived.run_id)
        for reference in frozen.results:
            assert (
                reference.ranking_features["score"] == by_id[reference.id].ranking_features["score"]
            )
