from collections import Counter

from rdkit import Chem

from reaction_reference.chemistry.structures import canonical, parse
from reaction_reference.domain.models import BondChange, ReactionAnalysis


def _bonds(mol):
    return {
        tuple(sorted((b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum()))): str(
            b.GetBondType()
        )
        for b in mol.GetBonds()
        if b.GetBeginAtom().GetAtomMapNum() and b.GetEndAtom().GetAtomMapNum()
    }


def _atoms(mol):
    return {a.GetAtomMapNum(): a for a in mol.GetAtoms() if a.GetAtomMapNum()}


def _resonance_pairs(left, right, changed):
    """Only two reviewed terminal-oxygen motifs; never arbitrary minimum edits."""
    la, ra = _atoms(left), _atoms(right)
    lb, rb = _bonds(left), _bonds(right)
    ignored = set()
    for number in la.keys() & ra.keys():
        left_atom, right_atom = la[number], ra[number]
        if (
            left_atom.GetAtomicNum() not in (6, 7)
            or left_atom.GetAtomicNum() != right_atom.GetAtomicNum()
        ):
            continue
        lo = [a for a in left_atom.GetNeighbors() if a.GetAtomicNum() == 8]
        ro = [a for a in right_atom.GetNeighbors() if a.GetAtomicNum() == 8]
        labels = {a.GetAtomMapNum() for a in lo}
        if (
            len(lo) != 2
            or len(ro) != 2
            or not all(labels)
            or labels != {a.GetAtomMapNum() for a in ro}
        ):
            continue
        atoms_l, atoms_r = [la[i] for i in labels], [ra[i] for i in labels]
        if any(
            a.GetDegree() != 1
            or a.GetTotalNumHs(includeNeighbors=True) != 0
            or a.GetNumRadicalElectrons()
            for a in atoms_l + atoms_r
        ):
            continue
        if any(
            (la[i].GetAtomicNum(), la[i].GetIsotope()) != (ra[i].GetAtomicNum(), ra[i].GetIsotope())
            for i in labels
        ):
            continue
        if left_atom.GetFormalCharge() != right_atom.GetFormalCharge():
            continue
        # Nitro: central N+, oxygens 0/-1. Carboxylate: central C0, oxygens 0/-1.
        if (left_atom.GetAtomicNum(), left_atom.GetFormalCharge()) not in ((7, 1), (6, 0)):
            continue
        if any(
            sorted(a.GetFormalCharge() for a in group) != [-1, 0] for group in (atoms_l, atoms_r)
        ):
            continue
        pairs = {tuple(sorted((number, i))) for i in labels}
        if (
            pairs <= changed
            and sorted(lb.get(p) for p in pairs) == ["DOUBLE", "SINGLE"]
            and sorted(rb.get(p) for p in pairs) == ["DOUBLE", "SINGLE"]
        ):
            for pair in pairs:
                # Charge must move with the double bond, not change the material charge.
                oxygen = next(i for i in pair if i != number)
                if (lb[pair] == "DOUBLE" and la[oxygen].GetFormalCharge() != 0) or (
                    rb[pair] == "DOUBLE" and ra[oxygen].GetFormalCharge() != 0
                ):
                    break
            else:
                ignored.update(pairs)
    return ignored


def _cycle_rank(mol):
    return mol.GetNumBonds() - mol.GetNumAtoms() + len(Chem.GetMolFrags(mol))


def analyze_reaction(record):
    if not record.mapped_reaction_smiles:
        return ReactionAnalysis(
            state="unknown", event_scope=record.event_scope, reasons=["mapping_missing"]
        )
    try:
        left_text, agent_text, right_text = record.mapped_reaction_smiles.split(">")
        left = parse(left_text + ("." + agent_text if agent_text else ""))
        right = parse(right_text)
    except (ValueError, TypeError):
        return ReactionAnalysis(
            state="unknown", event_scope=record.event_scope, reasons=["invalid_mapped_reaction"]
        )
    try:
        for side, role in ((left, "reactant"), (right, "product")):
            available = Counter(canonical(m) for m in Chem.GetMolFrags(side, asMols=True))
            declared = Counter(canonical(m.smiles) for m in record.materials if m.role == role)
            if declared - available:
                return ReactionAnalysis(
                    state="unknown",
                    event_scope=record.event_scope,
                    reasons=["mapped_endpoints_do_not_reconcile_with_material_instances"],
                )
    except ValueError:
        return ReactionAnalysis(
            state="unknown",
            event_scope=record.event_scope,
            reasons=["invalid_declared_material_structure"],
        )
    for side in (left, right):
        labels = [a.GetAtomMapNum() for a in side.GetAtoms() if a.GetAtomMapNum()]
        if len(labels) != len(set(labels)):
            return ReactionAnalysis(
                state="unknown",
                event_scope=record.event_scope,
                reasons=["duplicate_positive_atom_maps"],
            )
    la, ra = _atoms(left), _atoms(right)
    if any(
        i not in la
        or (a.GetAtomicNum(), a.GetIsotope()) != (la[i].GetAtomicNum(), la[i].GetIsotope())
        for i, a in ra.items()
    ):
        return ReactionAnalysis(
            state="unknown",
            event_scope=record.event_scope,
            reasons=["mapping_element_isotope_or_source_conflict"],
        )
    lb, rb = _bonds(left), _bonds(right)
    formed = [
        BondChange(maps=k, after=rb[k])
        for k in sorted(rb.keys() - lb.keys())
        if set(k) <= la.keys()
    ]
    broken, detached, untracked = [], [], []
    for pair in sorted(lb.keys() - rb.keys()):
        surviving = sum(i in ra for i in pair)
        if surviving == 2:
            broken.append(BondChange(maps=pair, before=lb[pair]))
        elif surviving == 1:
            detached.append(pair)
        else:
            untracked.append(pair)
    changed = {k for k in lb.keys() & rb.keys() if lb[k] != rb[k]}
    ignored = _resonance_pairs(left, right, changed)
    order = [BondChange(maps=k, before=lb[k], after=rb[k]) for k in sorted(changed - ignored)]
    representation = [BondChange(maps=k, before=lb[k], after=rb[k]) for k in sorted(ignored)]
    resonance_atoms = {i for pair in ignored for i in pair}
    atom_changes = []
    for label in sorted(la.keys() & ra.keys()):
        before, after = la[label], ra[label]
        for name, getter in (
            ("formal_charge", lambda a: a.GetFormalCharge()),
            ("hydrogen_count", lambda a: a.GetTotalNumHs(includeNeighbors=True)),
            ("radical_electrons", lambda a: a.GetNumRadicalElectrons()),
        ):
            if getter(before) != getter(after) and not (
                name == "formal_charge" and label in resonance_atoms
            ):
                atom_changes.append(
                    {
                        "map": label,
                        "property": name,
                        "before": getter(before),
                        "after": getter(after),
                    }
                )
    sources = {}
    for component, atoms in enumerate(Chem.GetMolFrags(left)):
        for index in atoms:
            label = left.GetAtomWithIdx(index).GetAtomMapNum()
            if label:
                sources[label] = component
    topology = []
    right_cycles, left_cycles = _cycle_rank(right), _cycle_rank(left)
    changed_pairs = {change.maps for change in formed + broken} | set(detached)
    for pair in changed_pairs:
        if set(pair) <= ra.keys():
            bond = right.GetBondBetweenAtoms(ra[pair[0]].GetIdx(), ra[pair[1]].GetIdx())
            if bond and bond.IsInRing() and pair in {c.maps for c in formed}:
                topology.append("ring_closure")
        if set(pair) <= la.keys():
            bond = left.GetBondBetweenAtoms(la[pair[0]].GetIdx(), la[pair[1]].GetIdx())
            if bond and bond.IsInRing() and pair in ({c.maps for c in broken} | set(detached)):
                topology.append("ring_opening")
    if "ring_closure" in topology and "ring_opening" in topology:
        topology.append("ring_reorganization")
    if not topology:
        topology.append(
            "ring_topology_retained"
            if not formed and not broken and not detached
            else "no_identified_ring_change"
        )
    classes = []
    carbonyl = Chem.MolFromSmarts("[CX3](=[OX1])-[NX3]")
    for match in right.GetSubstructMatches(carbonyl):
        c, _, n = [right.GetAtomWithIdx(i).GetAtomMapNum() for i in match]
        if tuple(sorted((c, n))) in {change.maps for change in formed}:
            classes.append("acyl_C_N_connection")
    if formed:
        classes.append("bond_formation")
    for change in formed:
        a, b = (ra[n] for n in change.maps)
        elements = sorted((a.GetAtomicNum(), b.GetAtomicNum()))
        if elements == [6, 6]:
            classes.append("C_C_connection")
        elif elements in ([6, 7], [6, 8], [6, 16]):
            carbon = a if a.GetAtomicNum() == 6 else b
            hetero = b if a.GetAtomicNum() == 6 else a
            prefix = (
                "aryl_"
                if carbon.GetIsAromatic()
                else "sp3_"
                if carbon.GetHybridization() == Chem.HybridizationType.SP3
                else ""
            )
            classes.append(prefix + "C_" + hetero.GetSymbol() + "_connection")
            if any(
                n.GetAtomicNum() == 8
                and right.GetBondBetweenAtoms(carbon.GetIdx(), n.GetIdx()).GetBondType()
                == Chem.BondType.DOUBLE
                for n in carbon.GetNeighbors()
            ):
                classes.append("acyl_C_" + hetero.GetSymbol() + "_connection")
    for change in order:
        if sorted(ra[n].GetAtomicNum() for n in change.maps) == [6, 8]:
            if change.before == "DOUBLE" and change.after == "SINGLE":
                classes.append("C_O_bond_order_decrease")
            elif change.before == "SINGLE" and change.after == "DOUBLE":
                classes.append("C_O_bond_order_increase")
    if order:
        classes.append("bond_order_transformation")
    if not formed and not broken and not detached and not order:
        classes.append("no_resolved_heavy_bond_edit")
    reasons = []
    complete_maps = all(a.GetAtomMapNum() for m in (left, right) for a in m.GetAtoms())
    if not complete_maps:
        reasons.append("partial_mapping")
    if untracked or detached:
        reasons.append("untracked_leaving_fragment_fate")
    if record.event_scope != "documented_step":
        reasons.append("changes_apply_to_source_record_endpoints_not_an_assigned_step")
    if (
        right_cycles != left_cycles
        and "ring_closure" not in topology
        and "ring_opening" not in topology
    ):
        reasons.append("cycle_rank_changed_but_event_unresolved")
    return ReactionAnalysis(
        state="analyzed" if complete_maps else "partial",
        formed=formed,
        broken=broken,
        order_changed=order,
        representation_only=representation,
        atom_property_changes=atom_changes,
        detached_boundaries=detached,
        untracked_input_bonds=untracked,
        atom_sources=sources,
        topology=sorted(set(topology)),
        reaction_classes=sorted(set(classes)),
        event_scope=record.event_scope,
        reasons=reasons,
    )


def project_changes(record, material, witness, analysis):
    """Project source product changes through one consistent product correspondence."""
    if analysis.state == "unknown" or material.role != "product":
        return {"formed_target_bonds": [], "changed_target_atoms": [], "support": "unknown"}
    selected = parse(material.smiles)
    right = parse(record.mapped_reaction_smiles.split(">")[2])
    options = [
        m for m in Chem.GetMolFrags(right, asMols=True) if canonical(m) == canonical(selected)
    ]
    if not options:
        return {
            "formed_target_bonds": [],
            "changed_target_atoms": [],
            "support": "product_mapping_unresolved",
        }
    mapped = options[0]
    embeddings = mapped.GetSubstructMatches(
        selected, uniquify=False, useChirality=True, maxMatches=129
    )
    conclusions = []
    changed = analysis.formed + analysis.order_changed + analysis.broken
    for embedding in embeddings[:128]:
        source_to_target = {source: target for target, source in witness.target_to_source}
        map_to_target = {
            mapped.GetAtomWithIdx(embedding[source]).GetAtomMapNum(): target
            for source, target in source_to_target.items()
        }
        formed = [
            tuple(sorted((map_to_target[c.maps[0]], map_to_target[c.maps[1]])))
            for c in analysis.formed
            if set(c.maps) <= map_to_target.keys()
        ]
        changed_atoms = sorted(
            {map_to_target[n] for c in changed for n in c.maps if n in map_to_target}
            | {
                map_to_target[n]
                for pair in analysis.detached_boundaries
                for n in pair
                if n in map_to_target
            }
            | {
                map_to_target[c["map"]]
                for c in analysis.atom_property_changes
                if c["map"] in map_to_target
            }
        )
        conclusions.append((tuple(sorted(formed)), tuple(changed_atoms)))
    if not conclusions:
        return {"formed_target_bonds": [], "changed_target_atoms": [], "support": "unknown"}
    stable = len(set(conclusions)) == 1 and len(embeddings) <= 128 and len(options) == 1
    # Ambiguous local assignments do not produce definite target-key formation.
    return {
        "formed_target_bonds": list(conclusions[0][0]) if stable else [],
        "changed_target_atoms": list(conclusions[0][1]) if stable else [],
        "support": "single_mapping_inference" if stable else "ambiguous_product_mapping",
        "mapping_alternatives_checked": len(conclusions),
    }
