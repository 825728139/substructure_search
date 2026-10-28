from rdkit import Chem
from rdkit.Chem import BRICS
from rdkit.Chem.Scaffolds import MurckoScaffold

from reaction_reference.chemistry.structures import digest, outside_blocks
from reaction_reference.domain.models import QueryFamily, RConstraint
from reaction_reference.rules import load_rules


def functional_matches(mol):
    rules, _ = load_rules()
    found: list[tuple[str, tuple[int, ...], int]] = []
    for rule in sorted(rules["functional_groups"], key=lambda r: -r["priority"]):
        query = Chem.MolFromSmarts(rule["smarts"])
        found.extend(
            (rule["id"], match, rule["priority"]) for match in mol.GetSubstructMatches(query)
        )
    return found


def _close_units(seed, groups, mol, *, adjacent=False):
    result = set(seed)
    for _, match, _ in groups:
        if result.intersection(match) or (
            adjacent
            and any(
                n.GetIdx() in result
                for index in match
                for n in mol.GetAtomWithIdx(index).GetNeighbors()
            )
        ):
            result.update(match)
    return result


def _core_smarts(mol, atom_ids, groups):
    atom_ids = set(atom_ids)
    atom_ids |= {
        n.GetIdx()
        for i in list(atom_ids)
        for n in mol.GetAtomWithIdx(i).GetNeighbors()
        if n.GetAtomicNum() == 1 and n.GetIsotope()
    }
    atom_ids = sorted(atom_ids)
    index = {old: new for new, old in enumerate(atom_ids)}
    rw = Chem.RWMol()
    hydroxyl = {match[0] for name, match, _ in groups if name == "hydroxyl"}
    for old in atom_ids:
        atom = mol.GetAtomWithIdx(old)
        isotope = str(atom.GetIsotope()) if atom.GetIsotope() else ""
        aromatic = "a" if atom.GetIsAromatic() else "A"
        charge = atom.GetFormalCharge()
        q = f"{isotope}#{atom.GetAtomicNum()};{aromatic};{charge:+d}"
        if old in hydroxyl:
            q += ";H1;X2"
        query_atom = Chem.AtomFromSmarts(f"[{q}]")
        query_atom.SetAtomMapNum(old + 1)
        rw.AddAtom(query_atom)
    for bond in mol.GetBonds():
        a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if a in index and b in index:
            rw.AddBond(index[a], index[b], bond.GetBondType())
    smarts = Chem.MolToSmarts(rw.GetMol())
    restored = Chem.MolFromSmarts(smarts)
    return smarts, [a.GetAtomMapNum() - 1 for a in restored.GetAtoms()]


def plan_families(target, max_families=12):
    rules, _ = load_rules()
    groups = functional_matches(target)
    all_atoms = {a.GetIdx() for a in target.GetAtoms() if a.GetAtomicNum() > 1}
    scaffold = MurckoScaffold.GetScaffoldForMol(target)
    scaffold_match = target.GetSubstructMatch(scaffold) if scaffold.GetNumAtoms() else ()
    whole = (
        _close_units(set(scaffold_match), groups, target, adjacent=True)
        if scaffold_match
        else all_atoms
    )
    seeds = {
        "whole": [
            (
                whole,
                "whole_murcko_with_adjacent_functional_units"
                if scaffold_match
                else "acyclic_full_framework",
            )
        ],
        "core": [],
        "fragment": [],
    }
    rings = [set(r) for r in target.GetRingInfo().AtomRings()]
    systems = []
    while rings:
        group = rings.pop(0)
        changed = True
        while changed:
            changed = False
            for ring in rings[:]:
                if group & ring:
                    group |= ring
                    rings.remove(ring)
                    changed = True
        systems.append(group)
    for system in systems:
        seeds["core"].append((_close_units(system, groups, target), "complete_ring_system"))
    anchors = set()
    for _, match, _ in groups:
        anchors.update(match)
    if not systems:
        for a in sorted(anchors):
            for b in sorted(anchors):
                if a < b:
                    anchors.update(Chem.GetShortestPath(target, a, b))
        seeds["core"].append(
            (_close_units(anchors or all_atoms, groups, target), "acyclic_functional_anchor_paths")
        )
    for name, match, _ in groups:
        neighborhood = set(match)
        for atom in match:
            neighborhood.update(
                n.GetIdx()
                for n in target.GetAtomWithIdx(atom).GetNeighbors()
                if n.GetAtomicNum() > 1
            )
        # Keep complete intersecting rings, never invent an open-ring precursor.
        for system in systems:
            if neighborhood & system:
                neighborhood |= system
        seeds["fragment"].append(
            (_close_units(neighborhood, groups, target), f"functional_neighborhood:{name}")
        )
    for (a, b), _ in BRICS.FindBRICSBonds(target):
        if target.GetBondBetweenAtoms(a, b).IsInRing():
            continue
        cut = Chem.RWMol(target)
        cut.RemoveBond(a, b)
        for component in Chem.GetMolFrags(cut):
            heavy = set(component) & all_atoms
            if len(heavy) >= 2:
                seeds["fragment"].append(
                    (_close_units(heavy, groups, target), "nonring_boundary_fragment")
                )
    if not seeds["fragment"]:
        seeds["fragment"].append((all_atoms, "full_chain_local_fallback"))
    if not seeds["core"]:
        seeds["core"].append((whole, "framework_core_fallback"))
    families: list[QueryFamily] = []
    seen: set[tuple] = set()
    # Round robin reserves a chance for each applicable structural layer.
    while len(families) < max_families and any(seeds.values()):
        for layer in ("whole", "core", "fragment"):
            if not seeds[layer] or len(families) >= max_families:
                continue
            atoms, rule = seeds[layer].pop(0)
            if not atoms:
                continue
            smarts, ids = _core_smarts(target, atoms, groups)
            key = (layer, tuple(ids), smarts)
            if key in seen:
                continue
            seen.add(key)
            families.append(
                QueryFamily(
                    id=digest(key),
                    layer=layer,
                    core_smarts=smarts,
                    target_atoms=ids,
                    rule_id=rule,
                    rule_version=rules["version"],
                    description=f"{layer}: {rule}; fixed atoms {ids}; other substituents variable",
                )
            )
    return families


def directed_family(parent, target, positions):
    blocks = outside_blocks(target, parent.target_atoms)
    constraints = []
    for block in blocks:
        if set(block["core_positions"]) & set(positions):
            for position in block["core_positions"]:
                constraints.append(
                    RConstraint(
                        position=position, requirement="required", exact_fragment=block["fragment"]
                    )
                )
    if not constraints:
        return None
    return parent.model_copy(
        update={
            "id": digest([parent.id, [c.model_dump() for c in constraints]]),
            "parent_id": parent.id,
            "r_constraints": constraints,
            "trigger": "missing_site_or_joint_assignment",
            "description": f"Directed follow-up at target core positions {sorted(set(positions))}",
        }
    )


def exact_family(target):
    tagged = Chem.Mol(target)
    for atom in tagged.GetAtoms():
        atom.SetAtomMapNum(atom.GetIdx() + 1)
    smarts = Chem.MolToSmarts(tagged)
    atoms = [a.GetAtomMapNum() - 1 for a in Chem.MolFromSmarts(smarts).GetAtoms()]
    return QueryFamily(
        id=digest(["strict_target", Chem.MolToSmiles(target)]),
        layer="whole",
        core_smarts=smarts,
        target_atoms=atoms,
        relation="strict",
        allow_extra_substitution=False,
        rule_id="strict_target_requirements",
        rule_version=load_rules()[0]["version"],
        description="Complete target outcome lookup; stereo and isotope requirements verified separately",
    )


def initial_families(target, max_families=12, include_exact=True):
    planned = plan_families(target, max(3, max_families - (3 if include_exact else 2)))
    if not include_exact:
        return planned
    if max_families == 3:
        return [exact_family(target)] + [
            next(f for f in planned if f.layer == layer) for layer in ("core", "fragment")
        ]
    return ([exact_family(target)] + planned)[:max_families]
