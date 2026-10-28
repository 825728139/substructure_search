"""Demonstrate query and prefilter semantics, not retrieval performance."""

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

# A fixed phenol motif can be present despite low whole-molecule similarity.
# Explicit H/charge predicates distinguish phenol from an aromatic ether.
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

# Applying a size window after a global Top-K changes the selected set.
# This is an illustrative window, not a proposed runtime default.
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

# A side containing two products has different descriptors from either product.
# The actual selected product is declared by the example, not chosen by size.
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

# A cached tuple of local atom indices cannot be copied to another ordering.
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
    "Query predicates, screening, selection order, representations and cached-index rebinding verified; no performance benchmark."
)
