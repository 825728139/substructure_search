from rdkit import Chem

from reaction_reference.chemistry.structures import digest, outside_blocks
from reaction_reference.domain.models import MatchResult, RBlock, Witness


def compile_family(family):
    query = Chem.MolFromSmarts(family.core_smarts)
    if query is None or query.GetNumAtoms() != len(family.target_atoms):
        raise ValueError("Invalid core query or target correspondence")
    if len(Chem.GetMolFrags(query)) != 1:
        raise NotImplementedError("Disconnected anchors require a supported path semantics")
    Chem.SetGenericQueriesFromProperties(query)
    for positions in family.equal_r_positions:
        if len(positions) < 2 or any(p < 0 or p >= query.GetNumAtoms() for p in positions):
            raise ValueError("Invalid R-equality positions")
    return query


def _predicates(family, molecule, embedding, blocks):
    by_position = {
        p: [b for b in blocks if p in b["core_positions"]] for p in range(len(embedding))
    }
    constrained = {c.position for c in family.r_constraints}
    if not family.allow_extra_substitution and any(
        v for p, v in by_position.items() if p not in constrained
    ):
        return False
    for constraint in family.r_constraints:
        values = by_position[constraint.position]
        if constraint.requirement == "hydrogen":
            if (
                values
                or molecule.GetAtomWithIdx(embedding[constraint.position]).GetTotalNumHs(
                    includeNeighbors=True
                )
                == 0
            ):
                return False
            continue
        if not values:
            if constraint.requirement == "required":
                return False
            continue
        if constraint.exact_fragment is not None and not any(
            b["fragment"] == constraint.exact_fragment for b in values
        ):
            return False
        for block in values:
            if constraint.category != "any":
                if len(block["core_positions"]) != 1 or block["category"] != constraint.category:
                    return False
            if constraint.max_carbons is not None:
                carbons = sum(
                    molecule.GetAtomWithIdx(i).GetAtomicNum() == 6 for i in block["atom_indices"]
                )
                if carbons > constraint.max_carbons:
                    return False
    for positions in family.equal_r_positions:
        # Port labels differ by position: remove ONLY dummy map numbers for equality.
        signatures = []
        for position in positions:
            values = by_position[position]
            if any(len(b["core_positions"]) != 1 for b in values):
                raise NotImplementedError("R equality on a bridge is not supported")
            local = []
            for block in values:
                fragment = Chem.MolFromSmiles(block["fragment"])
                if fragment is None:
                    raise NotImplementedError("R equality on an unsanitizable cut fragment")
                for atom in fragment.GetAtoms():
                    atom.SetAtomMapNum(0)
                local.append(Chem.MolToSmiles(fragment))
            signatures.append(sorted(local))
        if any(value != signatures[0] for value in signatures[1:]):
            return False
    return True


def match_family(
    family,
    molecule,
    target,
    source_id,
    role="product",
    *,
    max_mappings=128,
    max_visits=10000,
    checkpoint=lambda: None,
):
    try:
        query = compile_family(family)
    except NotImplementedError as exc:
        return MatchResult(state="unsupported", enumeration_complete=False, reasons=[str(exc)])
    params = Chem.SubstructMatchParameters()
    params.uniquify = False  # type: ignore[assignment]
    params.useGenericMatchers = family.use_generic_matchers
    params.maxMatches = max_mappings + 1
    embeddings = molecule.GetSubstructMatches(query, params)
    complete = len(embeddings) <= max_mappings
    try:
        target_blocks = outside_blocks(target, family.target_atoms, max_visits=max_visits)
    except TimeoutError as exc:
        return MatchResult(state="unknown", enumeration_complete=False, reasons=[str(exc)])
    witnesses, seen, reasons = [], set(), []
    checked = 0
    for embedding in embeddings[:max_mappings]:
        checkpoint()
        checked += 1
        inverse = {a: i for i, a in enumerate(embedding)}
        extra = []
        for bond in molecule.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if (
                a in inverse
                and b in inverse
                and query.GetBondBetweenAtoms(inverse[a], inverse[b]) is None
            ):
                extra.append((min(inverse[a], inverse[b]), max(inverse[a], inverse[b])))
        if extra and family.core_topology_policy == "forbid_extra_internal_edges":
            continue
        try:
            blocks = outside_blocks(molecule, embedding, max_visits=max_visits)
            if not _predicates(family, molecule, embedding, blocks):
                continue
        except (TimeoutError, NotImplementedError) as exc:
            complete = False
            reasons.append(str(exc))
            continue
        correspondence = dict(zip(family.target_atoms, embedding, strict=False))
        covered_r = set()
        # Extend only exact whole-block correspondences, not independent best R assignments.
        for tb in target_blocks:
            for sb in blocks:
                if (
                    tb["core_positions"] == sb["core_positions"]
                    and tb["fragment"] == sb["fragment"]
                ):
                    # Obtain the outside correspondence by matching an induced query with
                    # the already fixed core. This avoids assuming sorted atom IDs align.
                    atom_ids = sorted(set(family.target_atoms) | set(tb["atom_indices"]))
                    tagged = Chem.Mol(target)
                    for atom in tagged.GetAtoms():
                        atom.SetAtomMapNum(atom.GetIdx() + 1)
                    extended_smarts = Chem.MolFragmentToSmarts(tagged, atomsToUse=atom_ids)
                    extended_query = Chem.MolFromSmarts(extended_smarts)
                    if extended_query is None:
                        continue
                    ep = Chem.SubstructMatchParameters()
                    ep.uniquify = False  # type: ignore[assignment]
                    ep.maxMatches = max_mappings + 1
                    # Coverage describes connectivity, not a stereochemical outcome.
                    # A cut fragment can have an undefined tetrahedral context.
                    ep.useChirality = False  # type: ignore[assignment]
                    extensions = molecule.GetSubstructMatches(extended_query, ep)
                    if len(extensions) > max_mappings:
                        complete = False
                        reasons.append("r_correspondence_enumeration_limit")
                    for match in extensions[:max_mappings]:
                        checkpoint()
                        pairs = {
                            atom.GetAtomMapNum() - 1: match[atom.GetIdx()]
                            for atom in extended_query.GetAtoms()
                        }
                        if all(
                            pairs[a] == b
                            for a, b in zip(family.target_atoms, embedding, strict=False)
                        ):
                            additions = {a: pairs[a] for a in tb["atom_indices"]}
                            if set(additions.values()) != set(sb["atom_indices"]):
                                continue
                            if len(set(correspondence.values()) | set(additions.values())) == len(
                                correspondence
                            ) + len(additions):
                                correspondence.update(additions)
                                covered_r.update(tb["core_positions"])
                            break
                    break
        key = (tuple(sorted(correspondence.items())), tuple(b["fragment"] for b in blocks))
        if key in seen:
            continue
        seen.add(key)
        covered_bonds = 0
        for bond in target.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if a in correspondence and b in correspondence:
                other = molecule.GetBondBetweenAtoms(correspondence[a], correspondence[b])
                covered_bonds += other is not None and other.GetBondType() == bond.GetBondType()
        heavy_covered = sum(target.GetAtomWithIdx(a).GetAtomicNum() > 1 for a in correspondence)
        witnesses.append(
            Witness(
                id=digest([family.id, source_id, key]),
                family_id=family.id,
                source_structure_id=source_id,
                matched_role=role,
                target_to_source=sorted(correspondence.items()),
                core_source_atoms=list(embedding),
                blocks=[RBlock(**b) for b in blocks],
                matched_r_positions=sorted(covered_r),
                extra_core_edges=extra,
                target_atom_coverage=heavy_covered / max(1, target.GetNumHeavyAtoms()),
                target_bond_coverage=covered_bonds / max(1, target.GetNumBonds()),
            )
        )
    if len(witnesses) > 1:
        witnesses = [
            w.model_copy(update={"mapping_status": "alternative_witness"}) for w in witnesses
        ]
    return MatchResult(
        state="match" if witnesses else "no_match" if complete else "unknown",
        witnesses=witnesses,
        mappings_checked=checked,
        enumeration_complete=complete,
        reasons=sorted(set(reasons)),
    )


def coverage_summary(witnesses, target, enumeration_complete):
    if not witnesses:
        return {
            "joint_witness": None,
            "sitewise_union": [],
            "enumeration_complete": enumeration_complete,
        }
    best = max(witnesses, key=lambda w: (w.target_atom_coverage, w.target_bond_coverage, w.id))
    return {
        "joint_witness": {
            "witness_id": best.id,
            "atom_coverage": best.target_atom_coverage,
            "bond_coverage": best.target_bond_coverage,
            "r_positions": best.matched_r_positions,
        },
        "sitewise_union": sorted({a for w in witnesses for a, _ in w.target_to_source}),
        "sitewise_union_atom_coverage": len(
            {
                a
                for w in witnesses
                for a, _ in w.target_to_source
                if target.GetAtomWithIdx(a).GetAtomicNum() > 1
            }
        )
        / target.GetNumHeavyAtoms(),
        "enumeration_complete": enumeration_complete,
        "best_found_is_proven_maximum": False,
        "maximum_scope": "best_found_within_evaluated_families_and_mappings",
        "coverage_semantics": "connectivity_with_elements_isotopes_and_bond_types; stereo_validated_separately_for_complete_target",
    }
