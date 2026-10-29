"""演示查询与预筛选的语义；不作为检索性能基准。"""

import json
from pathlib import Path

from rdkit import Chem, DataStructs, rdBase
from rdkit.Chem import Descriptors, rdFingerprintGenerator

plain = Chem.MolFromSmiles("CCO")
explicit_oh = Chem.MolFromSmarts("[C]-[C]-[OX2H1+0]")
rows = []
for smiles, expected in [("CCO", True), ("CC[O-]", False), ("CCOC", False)]:
    mol = Chem.MolFromSmiles(smiles)
    actual = mol.HasSubstructMatch(explicit_oh)
    assert actual == expected
    assert mol.HasSubstructMatch(plain)
    rows.append({"candidate": smiles, "plain_molecule_query": True, "explicit_oh_query": actual})

# 即使整分子相似度很低，候选仍可能包含所需的苯酚固定片段。
# 显式的氢数和电荷条件用于区分苯酚与芳醚。
query_smarts = "[OX2H1+0]-c1ccccc1"
query = Chem.MolFromSmarts(query_smarts)
reference = Chem.MolFromSmiles("Oc1ccccc1")
generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
query_morgan = generator.GetFingerprint(reference)
query_pattern = Chem.PatternFingerprint(query, fpSize=2048)
screening = []
for name, smiles, expected in [
    ("same_structure", "Oc1ccccc1", True),
    ("larger_molecule", "Oc1ccc(CCNC(=O)CCOCCOCC)cc1", True),
    ("bulky_substituents", "CC(C)(C)c1cc(O)cc(C(C)(C)C)c1OCCOCCOCC", True),
    ("ether_is_not_phenol", "COc1ccccc1", False),
    ("missing_aromatic_core", "CCO", False),
]:
    candidate = Chem.MolFromSmiles(smiles)
    assert candidate is not None
    actual = candidate.HasSubstructMatch(query)
    morgan = generator.GetFingerprint(candidate)
    pattern = Chem.PatternFingerprint(candidate, fpSize=2048)
    pattern_pass = DataStructs.AllProbeBitsMatch(query_pattern, pattern)
    assert actual == expected, name
    assert not actual or pattern_pass, name
    screening.append(
        {
            "case": name,
            "smiles": smiles,
            "exact_substructure_match": actual,
            "morgan_tanimoto": DataStructs.TanimotoSimilarity(query_morgan, morgan),
            "morgan_bit_containment": DataStructs.AllProbeBitsMatch(query_morgan, morgan),
            "pattern_screen_pass": pattern_pass,
        }
    )

assert screening[1]["morgan_tanimoto"] < 0.5 and screening[2]["morgan_tanimoto"] < 0.5
assert not screening[1]["morgan_bit_containment"]
assert screening[3]["morgan_tanimoto"] > screening[1]["morgan_tanimoto"]
assert screening[3]["pattern_screen_pass"] and not screening[3]["exact_substructure_match"]

# 先取全局前 K 个再应用体量窗口，会改变最终选出的候选集合。
# 这里的窗口仅用于示例，不是建议的运行默认值。
selection_target = Chem.MolFromSmiles("CCNC(=O)c1ccccc1")
selection_fp = generator.GetFingerprint(selection_target)
selection_rows = []
for name, smiles in [
    ("higher_similarity_outside_window", "CCCCCNC(=O)c1ccccc1"),
    ("lower_similarity_inside_window", "COc1ccc(C(=O)NCC)cc1"),
]:
    candidate = Chem.MolFromSmiles(smiles)
    assert candidate is not None
    selection_rows.append(
        {
            "case": name,
            "smiles": smiles,
            "molecular_weight": Descriptors.MolWt(candidate),
            "similarity": DataStructs.TanimotoSimilarity(
                selection_fp, generator.GetFingerprint(candidate)
            ),
        }
    )
ordered = sorted(selection_rows, key=lambda row: (-row["similarity"], row["case"]))
global_top1_then_window = [
    row["case"] for row in ordered[:1] if 140 <= row["molecular_weight"] <= 180
]
window_then_top1 = [row["case"] for row in ordered if 140 <= row["molecular_weight"] <= 180][:1]
assert not global_top1_then_window
assert window_then_top1 == ["lower_similarity_inside_window"]

# 含两个产物的反应整侧，其描述符不同于任意一个具体产物。
# 本例明确指定要比较的产物，不按分子大小猜选。
aggregate = Chem.MolFromSmiles("CCNC(=O)c1ccccc1.CCCCCCCCCCCC")
fragments = Chem.GetMolFrags(aggregate, asMols=True)
selected_smiles = Chem.MolToSmiles(selection_target)
selected = next(m for m in fragments if Chem.MolToSmiles(m) == selected_smiles)
largest = max(fragments, key=lambda m: m.GetNumHeavyAtoms())
assert Chem.MolToSmiles(largest) != selected_smiles
aggregate_similarity = DataStructs.TanimotoSimilarity(
    selection_fp, generator.GetFingerprint(aggregate)
)
selected_similarity = DataStructs.TanimotoSimilarity(
    selection_fp, generator.GetFingerprint(selected)
)
assert aggregate_similarity < selected_similarity == 1.0
assert Descriptors.MolWt(aggregate) > 2 * Descriptors.MolWt(selected)

# 缓存的局部原子索引不能直接复制到原子顺序不同的表示上。
cache_query = Chem.MolFromSmarts("[CX3](=[OX1])-[NX3]")
cache_target = Chem.MolFromSmiles("CCNC(=O)c1ccccc1")
old_match = cache_target.GetSubstructMatch(cache_query)
new_order = list(reversed(range(cache_target.GetNumAtoms())))
renumbered = Chem.RenumberAtoms(cache_target, new_order)
new_match = renumbered.GetSubstructMatch(cache_query)
old_to_new = {old: new for new, old in enumerate(new_order)}
rebound = tuple(old_to_new[index] for index in old_match)
assert Chem.MolToSmiles(cache_target) == Chem.MolToSmiles(renumbered)
assert old_match != new_match and rebound == new_match
stale_symbols = [renumbered.GetAtomWithIdx(index).GetSymbol() for index in old_match]
correct_symbols = [renumbered.GetAtomWithIdx(index).GetSymbol() for index in rebound]
assert stale_symbols != ["C", "O", "N"] and correct_symbols == ["C", "O", "N"]

# 通用基团标签不属于普通 SMARTS；查询序列化后恢复时，
# 必须同时恢复属性和匹配器设置，仅解析 CXSMARTS 还不够。
generic_parameters = Chem.SubstructMatchParameters()
generic_parameters.useGenericMatchers = True
transport_examples = []
for group, expected in [("ARY", [True, False, False, False]), ("ALK", [False, False, True, False])]:
    original_query = Chem.MolFromSmarts(f"OC* |$;;{group}$|")
    Chem.SetGenericQueriesFromProperties(original_query)
    ordinary_smarts = Chem.MolToSmarts(original_query)
    cxsmarts = Chem.MolToCXSmarts(original_query)
    plain_restored = Chem.MolFromSmarts(ordinary_smarts)
    Chem.SetGenericQueriesFromProperties(plain_restored)
    properties_only = Chem.MolFromSmarts(cxsmarts)
    restored = Chem.MolFromSmarts(cxsmarts)
    Chem.SetGenericQueriesFromProperties(restored)
    candidates = ["c1ccccc1CO", "C1CCCCC1CO", "CCO", "c1ccncc1CO"]
    stages = {
        "original": original_query,
        "plain_smarts_restored": plain_restored,
        "cxsmarts_without_activation": properties_only,
        "cxsmarts_fully_restored": restored,
    }
    stage_matches = {
        name: [
            Chem.MolFromSmiles(s).HasSubstructMatch(query, generic_parameters) for s in candidates
        ]
        for name, query in stages.items()
    }
    assert stage_matches["original"] == expected
    assert stage_matches["cxsmarts_fully_restored"] == expected
    assert all(stage_matches["plain_smarts_restored"])
    assert all(stage_matches["cxsmarts_without_activation"])
    transport_examples.append(
        {
            "generic_group": group,
            "ordinary_smarts": ordinary_smarts,
            "cxsmarts": cxsmarts,
            "candidates": candidates,
            "stage_matches": stage_matches,
        }
    )
assert transport_examples[0]["ordinary_smarts"] == transport_examples[1]["ordinary_smarts"]
assert transport_examples[0]["cxsmarts"] != transport_examples[1]["cxsmarts"]

result = {
    "rdkit_version": rdBase.rdkitVersion,
    "scope": "illustrative_query_and_screening_semantics_not_performance_benchmark",
    "query": "[C]-[C]-[OX2H1+0]",
    "checks": rows,
    "screening_query": query_smarts,
    "screening_fingerprint_bits": 2048,
    "morgan_radius": 2,
    "illustrative_similarity_threshold": 0.5,
    "screening_examples": screening,
    "reaction_reference_value_assessed": False,
    "generic_query_transport_example": {
        "families": transport_examples,
        "plain_smarts_collides_across_different_families": True,
        "scope": "Pinned RDKit serialization counterexamples; no production IR or worker transport tested.",
    },
    "cached_index_rebinding_example": {
        "query": Chem.MolToSmarts(cache_query),
        "same_canonical_structure": True,
        "old_match": old_match,
        "new_match": new_match,
        "rebound_match": rebound,
        "stale_symbols": stale_symbols,
        "correct_symbols": correct_symbols,
        "scope": "Atom-order counterexample only; no production cache implementation tested.",
    },
    "selection_order_example": {
        "scope": "illustrative_not_runtime_thresholds",
        "target_smiles": selected_smiles,
        "window_g_per_mol": [140, 180],
        "k": 1,
        "candidates": selection_rows,
        "global_topk_then_window": global_top1_then_window,
        "window_then_topk": window_then_top1,
    },
    "representation_consistency_example": {
        "selected_product_smiles": selected_smiles,
        "aggregate_smiles": Chem.MolToSmiles(aggregate),
        "selected_product_molecular_weight": Descriptors.MolWt(selected),
        "aggregate_molecular_weight": Descriptors.MolWt(aggregate),
        "selected_product_similarity": selected_similarity,
        "aggregate_similarity": aggregate_similarity,
        "largest_fragment_is_selected_product": False,
    },
    "limitation": "These cases do not prove prefilter safety for every SMARTS, Markush or chemical view.",
}
Path(__file__).with_name("query_semantics_checks.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
)
print(
    "Query predicates, screening, selection order, representations, cached-index rebinding and generic-query transport verified; no performance benchmark."
)
