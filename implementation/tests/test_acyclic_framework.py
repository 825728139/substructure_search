"""完整无环框架不能用环内路径冒充，其他局部查询仍保持独立范围。"""

from rdkit import Chem

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.retrieval.planner import _core_smarts, functional_matches, initial_families


def test_whole_acyclic_framework_rejects_path_inside_lactam():
    """足够大的内酰胺可包含无环酰胺路径，但不应作为完整无环框架匹配。"""
    target = parse("CCNC(=O)CC")
    cyclic = parse("O=C1NCCCCCCCCCC1")
    old, _ = _core_smarts(target, set(range(target.GetNumAtoms())), functional_matches(target))
    assert cyclic.HasSubstructMatch(Chem.MolFromSmarts(old))
    family = next(f for f in initial_families(target) if f.rule_id == "acyclic_full_framework")
    assert not cyclic.HasSubstructMatch(Chem.MolFromSmarts(family.core_smarts))
    assert match_family(family, cyclic, target, "cyclic").state == "no_match"
    assert match_family(family, parse("CCCCNC(=O)CCCC"), target, "longer-chain").state == "match"
    assert match_family(family, target, target, "self").state == "match"
    assert (
        match_family(family, parse("CCN(C)C(=O)CC"), target, "tertiary-amide").state == "no_match"
    )


def test_whole_framework_page_uses_budget_before_repeated_family_prefixes(
    tmp_path, request_factory
):
    """同一有界预算下，完整无环框架六条页能处理更多不同记录，不被同前缀家族耗尽。"""
    from reaction_reference.adapters.sources import JsonlSource, import_native
    from reaction_reference.application.search import search

    target = "CCCCNC(=O)CCCCC"
    path = tmp_path / "acyclic.jsonl"
    path.write_text(
        "\n".join(
            import_native({"id": i, "product_smiles": [target]}).model_dump_json()
            for i in range(1, 7)
        )
        + "\n"
    )
    counts = []
    for preferred, requested in ((2, 100), (6, 100), (6, 2)):
        source = JsonlSource(path, exhaustive=False)
        source.preferred_page_size = 2
        source.whole_framework_page_size = preferred
        source.hydration_requires_io = True
        try:
            package = search(
                request_factory(
                    target,
                    options={
                        "include_exact_identity": False,
                        "include_usage": False,
                        "include_proposals": False,
                        "directed_followups": False,
                    },
                    budget={"max_tasks": 16, "page_size": requested},
                ),
                source,
            )
            counts.append(len(package.results))
            assert len(package.tasks) <= 16
        finally:
            source.close()
    assert counts[1] == 6 and counts[0] < counts[1]
    assert counts[2] == counts[0]
