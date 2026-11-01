"""命中后逐位点补查：使用真实结构见证验证缺口与联合覆盖，禁止把位点并集当共存。"""

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import QueryFamily
from reaction_reference.retrieval.planner import (
    _core_smarts,
    directed_family,
    functional_matches,
    progressive_followups,
)


def query_and_witnesses(smiles):
    """构造不对称取代吡啶的真实核心匹配，返回目标、家族与全部已核验对应。"""
    target = parse("CCc1ncc(CCC)cc1")
    core = {a.GetIdx() for a in target.GetAtoms() if a.GetIsAromatic()}
    smarts, ids = _core_smarts(target, core, functional_matches(target))
    family = QueryFamily(
        id="pyridine",
        layer="core",
        core_smarts=smarts,
        target_atoms=ids,
        rule_id="test",
        rule_version="test",
        description="乙基和丙基位点查询",
    )
    return target, family, match_family(family, parse(smiles), target, "source").witnesses


def test_missing_blocks_are_queried_separately():
    """两条目标支链都未出现时，两个补查各锁一个位点，避免一次全部锁死。"""
    target, family, witnesses = query_and_witnesses("Cc1ncc(C)cc1")
    children = progressive_followups(family, target, witnesses)
    assert len(children) == 2
    assert [{c.position for c in child.r_constraints} for child in children] == [{0}, {3}]
    assert all(child.parent_id == family.id for child in children)
    assert match_family(children[0], parse("CCc1ncc(C)cc1"), target, "ethyl").state == "match"
    assert match_family(children[1], parse("Cc1ncc(CCC)cc1"), target, "propyl").state == "match"


def test_sitewise_union_does_not_suppress_joint_query():
    """乙基和丙基分别见于不同材料时仍补查共同出现，不能用位点并集宣称满足。"""
    target, family, first = query_and_witnesses("CCc1ncc(C)cc1")
    _, _, second = query_and_witnesses("Cc1ncc(CCC)cc1")
    children = progressive_followups(family, target, first + second)
    assert len(children) == 1
    assert {c.position for c in children[0].r_constraints} == {0, 3}
    assert children[0].trigger == "missing_joint_assignment"


def test_joint_hit_and_absent_evidence_do_not_create_followups():
    """已有联合见证或尚无见证时均不凭空制造缺口。"""
    target, family, witnesses = query_and_witnesses("CCc1ncc(CCC)cc1")
    assert progressive_followups(family, target, witnesses) == []
    assert progressive_followups(family, target, []) == []
    assert progressive_followups(family, target, witnesses, limit=0) == []


def test_nested_directed_query_keeps_parent_constraints():
    """对子家族增加另一位点不能丢掉已锁定的父位点，重复补查不生成新家族。"""
    target, family, _ = query_and_witnesses("Cc1ncc(C)cc1")
    parent = directed_family(family, target, {0})
    child = directed_family(parent, target, {3})
    assert {c.position for c in child.r_constraints} == {0, 3}
    assert directed_family(child, target, {0, 3}) is None
    assert (
        match_family(child, parse("Cc1ncc(CCC)cc1"), target, "missing-parent").state == "no_match"
    )


def test_pipeline_executes_two_distinct_missing_block_followups(
    tmp_path, request_factory, monkeypatch
):
    """真实来源分页先返回缺口材料，编排器随后实际执行两个不同单块补查。"""
    import json
    from importlib import import_module

    from reaction_reference.adapters.sources import JsonlSource
    from reaction_reference.application.search import search

    _, family, _ = query_and_witnesses("Cc1ncc(C)cc1")
    module = import_module("reaction_reference.application.search")
    monkeypatch.setattr(module, "initial_families", lambda *_: [family])
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps({"id": "seed", "product_smiles": ["Cc1ncc(C)cc1"]}) + "\n")
    source = JsonlSource(path, exhaustive=True)
    source.max_selection_stage = 0
    calls = []
    original = source.candidate_page

    def page(query, role, cursor, limit, target, stage=0):
        """记录实际被执行的查询，底层仍使用真实结构匹配而非伪造命中。"""
        calls.append(query)
        return original(query, role, cursor, limit, target, stage)

    monkeypatch.setattr(source, "candidate_page", page)
    try:
        package = search(
            request_factory(
                "CCc1ncc(CCC)cc1",
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 100},
            ),
            source,
        )
        children = [query for query in calls if query.parent_id]
        assert [{c.position for c in query.r_constraints} for query in children] == [{0}, {3}]
        assert len(package.families) == 3
        assert len(package.results) == 1
        assert not package.results[0].target_requirements_satisfied
    finally:
        source.close()
