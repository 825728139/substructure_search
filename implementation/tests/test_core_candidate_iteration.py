"""核心候选迭代回归：家族公平处理与未经实验证实候选的结构排序。"""

import json
from pathlib import Path

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.domain.models import Reference
from reaction_reference.ports.sources import CandidatePage
from reaction_reference.ranking.engine import rank_references


def test_unverified_method_label_does_not_hide_more_relevant_core():
    """真实匹配反例中，普通酯的图方法标签不能把覆盖更多目标的桥环线索压到后面。"""
    payload = json.loads((Path(__file__).parent / "fixtures/graph_clue_ranking.json").read_text())
    references = [Reference.model_validate_json(json.dumps(r)) for r in payload["references"]]
    for ordering in [references, list(reversed(references))]:
        ranked, displayed = rank_references(ordering, target_smiles=payload["target_smiles"])
        assert ranked[0].record.source.record_id == "3153963"
        assert ranked[0].contribution == "structure_clue"
        assert not ranked[0].preparation_hit and not ranked[0].obtainment_hit
        assert displayed[0] == ranked[0].id


@pytest.mark.parametrize("limit", [1, 3, 18])
def test_display_follows_rank_instead_of_query_layer_quota(limit):
    """真实成环先例不能因分片入口被整体层侧链改造挤掉，展示应保持实际排序。"""
    payload = json.loads(
        (Path(__file__).parent / "fixtures/display_order_ranking.json").read_text()
    )
    references = [Reference.model_validate_json(json.dumps(r)) for r in payload["references"]]
    for ordering in (references, list(reversed(references))):
        ranked, displayed = rank_references(
            ordering, target_smiles=payload["target_smiles"], max_display=limit
        )
        assert ranked[0].record.source.record_id == "2223370"
        assert displayed == [r.id for r in ranked[:limit]]
        assert [r.display_position for r in ranked[:limit]] == list(
            range(1, min(limit, len(ranked)) + 1)
        )
        assert all(r.display_position is None for r in ranked[limit:])
        assert len(ranked) == len(references)
        assert not any(r.obtainment_hit for r in ranked)


@pytest.mark.parametrize("exhaustive", [False, True])
def test_source_small_pages_give_other_families_a_turn(
    tmp_path, amide, request_factory, monkeypatch, exhaustive
):
    """在线小页策略让后续家族进入预算；显式固定样本穷尽仍使用请求页大小。"""
    path = tmp_path / "many.jsonl"
    path.write_text(
        "\n".join(amide.model_copy(update={"id": f"copy-{i}"}).model_dump_json() for i in range(20))
        + "\n"
    )
    source = JsonlSource(path, exhaustive=exhaustive)
    source.preferred_page_size = 1
    source.hydration_requires_io = True
    calls = []
    original = source.candidate_page

    def record_page(family, role, cursor, limit, target, stage=0):
        """记录真实来源取页参数，不模拟核验和返回数据。"""
        calls.append((family.id, limit))
        return original(family, role, cursor, limit, target, stage)

    monkeypatch.setattr(source, "candidate_page", record_page)
    try:
        package = search(
            request_factory(
                options={
                    "include_usage": False,
                    "include_proposals": False,
                    "exhaustive_fixture": exhaustive,
                },
                budget={"max_tasks": 40, "page_size": 100},
            ),
            source,
        )
        assert package.results and calls
        if exhaustive:
            assert all(limit == 100 for _, limit in calls)
        else:
            assert all(limit == 1 for _, limit in calls)
            assert len({family for family, _ in calls}) >= 2
        assert len({r.id for r in package.results}) == len(package.results)
    finally:
        source.close()


@pytest.mark.parametrize("failure", [False, True])
def test_fragment_empty_or_failed_near_pool_keeps_independent_search(
    tmp_path, amide, request_factory, monkeypatch, failure
):
    """分片近邻无命中或查询失败时仍执行独立子结构流，不能将相似初选当成硬过滤。"""
    from importlib import import_module

    from reaction_reference.chemistry.structures import parse
    from reaction_reference.retrieval.planner import initial_families

    module = import_module("reaction_reference.application.search")
    smiles = next(m.smiles for m in amide.materials if m.role == "product")
    family = next(f for f in initial_families(parse(smiles)) if f.layer == "fragment")
    monkeypatch.setattr(module, "initial_families", lambda *_: [family])
    path = tmp_path / "fragment.jsonl"
    path.write_text(amide.model_dump_json() + "\n")
    source = JsonlSource(path, exhaustive=False)
    source.fragment_selection_stages = True
    source.selection_failure_fallback = True
    source.max_selection_stage = 1
    original = source.candidate_page
    stages = []

    def page(family, role, cursor, limit, target, stage=0):
        """仅模拟有界初选缺失，独立阶段仍用真实材料和完整匹配。"""
        stages.append(stage)
        if stage == 0:
            if failure:
                raise TimeoutError("模拟近邻查询超时")
            return CandidatePage([], None, True, True, "bounded_near_pool")
        return original(family, role, cursor, limit, target, stage)

    monkeypatch.setattr(source, "candidate_page", page)
    try:
        package = search(
            request_factory(
                smiles,
                options={"include_usage": False, "include_proposals": False},
            ),
            source,
        )
        assert stages == [0, 1]
        assert any(r.record.id == amide.id for r in package.results)
        assert package.coverage_state == "partial"
        assert bool(package.source_issues) == failure
    finally:
        source.close()
