"""检查有数量上限的 JSONB 反应导出样本；只读取本地文件，不连接来源。

核对结构表示与可追溯性；本检查不证明实验结果或反应机理。
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import rdChemReactions


def audit(path: Path) -> dict:
    """读取有限 JSONL 样本，检查字段、材料身份与份数、映射及模板自回放，返回计数和问题定位；不连接来源。"""
    RDLogger.DisableLog("rdApp.warning")
    RDLogger.DisableLog("rdApp.error")
    payload = path.read_bytes()
    rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    counts = Counter()
    issues = defaultdict(list)
    role_entries = Counter()
    template_counts = {str(radius): Counter() for radius in range(1, 5)}

    def record(name, ok, rid):
        """累计指定检查项的通过次数；失败时把来源记录编号加入对应问题列表。"""
        counts[name] += bool(ok)
        if not ok:
            issues[name].append(rid)

    def canon(smiles):
        """解析结构并移除映射号，返回保留立体的规范 SMILES；无效输入抛出 ValueError。"""
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError("Unparseable SMILES")
        for atom in mol.GetAtoms():
            atom.SetAtomMapNum(0)
        return Chem.MolToSmiles(mol, isomericSmiles=True)

    for row in rows:
        rid = row["id"]
        details = row.get("details") or {}
        aam = details.get("aam_result") or {}
        role_resolution = details.get("role_resolution") or {}
        record("details_present", bool(details), rid)
        for field in ("raw_reaction", "aam_result", "role_resolution"):
            record(f"{field}_present", bool(details.get(field)), rid)
        counts["records_with_role_promotions"] += bool(role_resolution.get("promotions"))
        counts["records_with_mapping_multiplicity"] += bool(
            role_resolution.get("mapped_input_multiplicity")
        )
        record(
            "no_balancing_copies_materialized",
            role_resolution.get("added_balancing_copies_materialized") == 0,
            rid,
        )
        record("final_score_matches_aam", row["final_score"] == aam.get("final_score"), rid)
        for field in ("temperature_text", "time_text", "pressure_text"):
            counts[f"nonempty_{field}"] += bool(details.get(field))
        for field in ("temperature", "time", "pressure"):
            counts[f"nonempty_raw_{field}"] += bool(details.get("raw_reaction", {}).get(field))

        for role in ("product", "reactant", "reagent", "catalyst", "solvent"):
            entries = details.get(role + "s", [])
            role_entries[role] += len(entries)
            try:
                canonical_entries = [canon(e["smiles"]) for e in entries if e.get("smiles")]
                record(
                    f"{role}_detail_identity_and_multiplicity_match",
                    Counter(canonical_entries) == Counter(canon(s) for s in row[role + "_smiles"]),
                    rid,
                )
            except (ValueError, TypeError, AttributeError):
                record(f"{role}_detail_identity_and_multiplicity_match", False, rid)

        mapped = row.get("mapped_reaction_smiles")
        try:
            left, _, right = mapped.split(">")
            left_mol, right_mol = Chem.MolFromSmiles(left), Chem.MolFromSmiles(right)
            if left_mol is None or right_mol is None:
                raise ValueError("Mapped reaction is not parseable")
            counts["mapped_reaction_parseable"] += 1
            left_maps = [a.GetAtomMapNum() for a in left_mol.GetAtoms() if a.GetAtomMapNum()]
            right_maps = [a.GetAtomMapNum() for a in right_mol.GetAtoms() if a.GetAtomMapNum()]
            record(
                "map_labels_unique_per_side",
                len(left_maps) == len(set(left_maps)) and len(right_maps) == len(set(right_maps)),
                rid,
            )
            record("all_product_atoms_mapped", len(right_maps) == right_mol.GetNumAtoms(), rid)
            record("product_maps_present_on_input", set(right_maps) <= set(left_maps), rid)
            identity = {
                a.GetAtomMapNum(): (a.GetAtomicNum(), a.GetIsotope())
                for a in left_mol.GetAtoms()
                if a.GetAtomMapNum()
            }
            record(
                "mapped_element_and_isotope_consistent",
                all(
                    identity.get(a.GetAtomMapNum()) == (a.GetAtomicNum(), a.GetIsotope())
                    for a in right_mol.GetAtoms()
                ),
                rid,
            )
            record(
                "mapped_product_matches_product_array",
                canon(right) == canon(".".join(row["product_smiles"])),
                rid,
            )
            selected = aam.get("aam_filter", {}).get("aam", {}).get("rxnmapper_v2", {})
            record(
                "mapped_string_matches_stored_rxnmapper_v2",
                mapped == selected.get("mapped_reaction"),
                rid,
            )
        except (ValueError, TypeError, AttributeError):
            record("mapped_reaction_parseable", False, rid)

        # 一个来源反应模板可以同时描述多个观察到的产物。
        # 这里自检的是反应整侧，不能据此认定同一个分子满足 Markush 条件。
        molecules = [Chem.MolFromSmiles(".".join(row["product_smiles"]))]
        for radius in range(1, 5):
            try:
                template = rdChemReactions.ReactionFromSmarts(row[f"reaction_center_r{radius}"])
                queries = list(template.GetReactants())
                query = queries[0]
                for fragment in queries[1:]:
                    query = Chem.CombineMols(query, fragment)
                template_counts[str(radius)]["parseable"] += 1
                for stereo, name in ((False, "connectivity_match"), (True, "strict_stereo_match")):
                    matched = any(
                        m is not None and m.HasSubstructMatch(query, useChirality=stereo)
                        for m in molecules
                    )
                    template_counts[str(radius)][name] += matched
                    if not matched:
                        issues[f"radius_{radius}_{name}"].append(rid)
            except (ValueError, TypeError, AttributeError, IndexError, RuntimeError):
                issues[f"radius_{radius}_parseable"].append(rid)

    return {
        "scope": "bounded_early_and_recent_sample_during_import_not_population_estimate",
        "rdkit_version": rdBase.rdkitVersion,
        "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
        "sampled_at": rows[0]["sampled_at"],
        "sample_size": len(rows),
        "sample_windows": dict(Counter(r["sample_window"] for r in rows)),
        "sources": dict(Counter(r["source_namespace"] for r in rows)),
        "document_count": len({(r["source_namespace"], r["document_id"]) for r in rows}),
        "counts": dict(counts),
        "role_entry_counts": dict(role_entries),
        "templates": template_counts,
        "source_aam_status": dict(Counter(r["details"]["aam_result"].get("status") for r in rows)),
        "source_inner_classification": dict(
            Counter(
                r["details"]["aam_result"]["aam_filter"].get("score", {}).get("classification")
                for r in rows
            )
        ),
        "issues": {k: {"count": len(v), "example_ids": v[:10]} for k, v in issues.items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.snapshot)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
