"""Audit a local, read-only reaction export; no database connection or credentials.

Input is JSONL containing reaction fields plus details and stored_*_smiles.
This checks representations, not experimental validity or synthetic feasibility.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import rdChemReactions


def audit(path: Path) -> dict:
    RDLogger.DisableLog("rdApp.warning")
    RDLogger.DisableLog("rdApp.error")
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    stats = Counter(
        {"records": 0, "parseable_reaction_smiles": 0, "reaction_smiles_with_atom_maps": 0}
    )
    issues = defaultdict(set)
    templates = {str(radius): Counter() for radius in range(1, 5)}
    role_stats = defaultdict(Counter)
    products = defaultdict(list)
    reactions = defaultdict(list)

    def canonical(smiles):
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            raise ValueError("SMILES parse failed")
        for atom in molecule.GetAtoms():
            atom.SetAtomMapNum(0)
        return Chem.MolToSmiles(molecule, isomericSmiles=True)

    roles = ("product", "reactant", "reagent", "catalyst", "solvent")
    for row in rows:
        rid = row["id"]
        stats["records"] += 1
        for role in roles:
            structures = row[f"{role}_smiles"]
            for smiles in structures:
                role_stats[role]["smiles_entries"] += 1
                molecule = Chem.MolFromSmiles(smiles)
                if molecule is None:
                    role_stats[role]["invalid_smiles"] += 1
                    issues[f"invalid_{role}_smiles"].add(rid)
                    continue
                role_stats[role]["parseable_smiles"] += 1
                if len(Chem.GetMolFrags(molecule)) > 1:
                    role_stats[role]["disconnected_entries"] += 1
                    issues[f"disconnected_{role}_entry"].add(rid)
                if any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms()):
                    issues[f"wildcard_{role}_entry"].add(rid)
            details = (row.get("details") or {}).get(role + "s", [])
            detail_canons = []
            for detail in details:
                role_stats[role]["detail_entries"] += 1
                role_stats[role]["details_with_id"] += bool(detail[1])
                if not detail[2]:
                    role_stats[role]["details_missing_smiles"] += 1
                    issues[f"details_missing_{role}_smiles"].add(rid)
                    continue
                try:
                    detail_canons.append(canonical(detail[2]))
                except ValueError:
                    role_stats[role]["invalid_detail_smiles"] += 1
                    issues[f"invalid_detail_{role}_smiles"].add(rid)
            try:
                if Counter(detail_canons) != Counter(canonical(s) for s in structures):
                    issues[f"detail_{role}_multiplicity_or_identity_difference"].add(rid)
            except ValueError:
                pass

        for role in ("product", "reactant"):
            try:
                expected = canonical(".".join(row[f"{role}_smiles"]))
                actual = canonical(row[f"stored_{role}_smiles"])
                if actual != expected:
                    issues[f"stored_{role}_mol_difference"].add(rid)
            except (ValueError, TypeError):
                issues[f"stored_{role}_mol_uncheckable"].add(rid)

        products[tuple(sorted(row["product_smiles"]))].append(rid)
        reactions[row["reaction_smiles"]].append(rid)
        try:
            reaction = rdChemReactions.ReactionFromSmarts(row["reaction_smiles"], useSmiles=True)
            assert reaction is not None
            stats["parseable_reaction_smiles"] += 1
            molecules = list(reaction.GetReactants()) + list(reaction.GetProducts())
            if any(a.GetAtomMapNum() for m in molecules for a in m.GetAtoms()):
                stats["reaction_smiles_with_atom_maps"] += 1
        except (ValueError, RuntimeError, AssertionError):
            issues["unparseable_reaction_smiles"].add(rid)

        candidates = [Chem.MolFromSmiles(s) for s in row["product_smiles"]]
        for radius in range(1, 5):
            counts = templates[str(radius)]
            try:
                template = rdChemReactions.ReactionFromSmarts(row[f"reaction_center_r{radius}"])
                assert template is not None
                counts["parseable"] += 1
                queries = list(
                    template.GetReactants()
                )  # Stored direction is products >> reactants.
                counts["single_product_template"] += len(queries) == 1
                # Multiple template components can be disjoint regions of the same product.
                # Combine them for this representation check, preserving all query atoms.
                query = queries[0]
                for fragment in queries[1:]:
                    query = Chem.CombineMols(query, fragment)
                for chirality, label in ((False, "connectivity"), (True, "strict_stereo")):
                    if any(
                        m is not None and m.HasSubstructMatch(query, useChirality=chirality)
                        for m in candidates
                    ):
                        counts[f"source_product_match_{label}"] += 1
                    else:
                        issues[f"r{radius}_source_product_{label}_mismatch"].add(rid)
            except (ValueError, RuntimeError, AssertionError, TypeError):
                issues[f"r{radius}_unparseable_template"].add(rid)

    return {
        "scope": "representation_audit_only_not_experiment_or_mapping_validation",
        "checked_at": datetime.now(UTC).isoformat(),
        "rdkit_version": rdBase.rdkitVersion,
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "counts": dict(stats),
        "roles": dict(role_stats),
        "templates": templates,
        "unique_product_arrays": len(products),
        "unique_reaction_smiles": len(reactions),
        "repeated_product_groups": [ids for ids in products.values() if len(ids) > 1],
        "repeated_reaction_groups": [ids for ids in reactions.values() if len(ids) > 1],
        "issues": {
            name: {"records": len(ids), "example_ids": sorted(ids)[:12]}
            for name, ids in sorted(issues.items())
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.snapshot)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
