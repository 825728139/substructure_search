"""Demonstrate query and prefilter semantics, not retrieval performance."""

import json
from pathlib import Path

from rdkit import Chem, DataStructs, rdBase
from rdkit.Chem import rdFingerprintGenerator

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
    "limitation": "These cases do not prove prefilter safety for every SMARTS, Markush or chemical view.",
}
Path(__file__).with_name("query_semantics_checks.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
)
print("3 query-semantics and 5 fingerprint-screening examples verified; no performance benchmark.")
