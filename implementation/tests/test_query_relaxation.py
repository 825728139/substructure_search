"""无匹配后局部放宽：区分完整查询范围、超时和预算中断，保留原核心约束。"""

import json
from dataclasses import replace
from importlib import import_module

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.retrieval.planner import (
    initial_families,
    progressive_followups,
    relax_exact_attachments,
)


def exact_tail_query():
    """用真实氨基吡啶支链匹配构造自动精确补查，避免伪造位点覆盖。"""
    target = parse("c1ccncc1NCCCCC")
    parent = next(f for f in initial_families(target) if f.rule_id == "complete_ring_system")
    witnesses = match_family(parent, parse("c1ccncc1NCCO"), target, "source").witnesses
    return target, progressive_followups(parent, target, witnesses)[0]


def test_relaxation_preserves_attachment_nitrogen_and_target_correspondence():
    """放开远端链后可匹配羟乙基，但连接仲胺与目标原子对应仍正确。"""
    target, exact = exact_tail_query()
    relaxed = relax_exact_attachments(exact, target)
    assert relaxed.parent_id == exact.id
    assert match_family(exact, parse("c1ccncc1NCCO"), target, "tail").state == "no_match"
    result = match_family(relaxed, parse("c1ccncc1NCCO"), target, "tail")
    assert result.state == "match"
    assert match_family(relaxed, parse("c1ccncc1N(C)CCO"), target, "tertiary").state == "no_match"
    assert progressive_followups(relaxed, target, result.witnesses) == []
    for witness in result.witnesses:
        source = parse("c1ccncc1NCCO")
        assert all(
            target.GetAtomWithIdx(a).GetAtomicNum() == source.GetAtomWithIdx(b).GetAtomicNum()
            for a, b in witness.target_to_source
        )


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("complete", True),
        ("partial", False),
        ("timeout", False),
        ("budget", False),
        ("near_only", False),
    ],
)
def test_pipeline_relaxes_only_completed_scope_without_match(
    tmp_path, request_factory, monkeypatch, mode, expected
):
    """完整且无匹配才生成放宽家族；超时、候选范围不完整或任务中断不能充当无命中。"""
    _, exact = exact_tail_query()
    module = import_module("reaction_reference.application.search")
    monkeypatch.setattr(module, "initial_families", lambda *_: [exact])
    path = tmp_path / "source.jsonl"
    path.write_text(json.dumps({"id": "tail", "product_smiles": ["c1ccncc1NCCO"]}) + "\n")
    source = JsonlSource(path, exhaustive=True)
    source.max_selection_stage = 1 if mode == "near_only" else 0
    original = source.candidate_page

    def page(family, role, cursor, limit, target, stage=0):
        """仅模拟查询范围状态，正常情况仍执行真实候选匹配。"""
        if mode == "timeout" or (mode == "near_only" and stage == 1):
            raise TimeoutError("模拟超时")
        result = original(family, role, cursor, limit, target, stage)
        return replace(result, scope_complete=False) if mode == "partial" else result

    monkeypatch.setattr(source, "candidate_page", page)
    try:
        package = search(
            request_factory(
                "c1ccncc1NCCCCC",
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 4 if mode == "budget" else 100},
            ),
            source,
        )
        relaxed = [f for f in package.families if f.rule_id == "relaxed_attachment_environment"]
        # 预算可能在生成后、执行前耗尽；要求没有把未执行的查询当作已获得匹配。
        if mode != "budget":
            assert bool(relaxed) == expected
        assert bool(package.results) == expected
        if expected:
            assert package.results[0].family_ids == [relaxed[0].id]
            assert not package.results[0].target_requirements_satisfied
            assert not package.results[0].obtainment_hit
    finally:
        source.close()


def test_relaxation_retains_original_core_atom_predicates():
    """放宽远端链不能抹掉原核心的芳环氢数限制。"""
    from rdkit import Chem

    target, exact = exact_tail_query()
    query = Chem.MolFromSmarts(exact.core_smarts)
    for atom in query.GetAtoms():
        target_atom = target.GetAtomWithIdx(exact.target_atoms[atom.GetIdx()])
        atom.ExpandQuery(Chem.AtomFromSmarts(f"[H{target_atom.GetTotalNumHs()}]"))
    constrained = exact.model_copy(update={"core_smarts": Chem.MolToSmarts(query)})
    relaxed = relax_exact_attachments(constrained, target)
    assert match_family(relaxed, parse("c1ccncc1NCCO"), target, "plain").state == "match"
    assert match_family(relaxed, parse("Cc1ccncc1NCCO"), target, "extra-core").state == "no_match"
