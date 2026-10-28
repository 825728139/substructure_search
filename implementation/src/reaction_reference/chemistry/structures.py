import hashlib
import json

from rdkit import Chem, DataStructs
from rdkit.Chem import Descriptors, rdFingerprintGenerator


class StructureError(ValueError):
    pass


def digest(value, length=24):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:length]


def parse(smiles, *, target=False):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        raise StructureError("Structure cannot be parsed")
    if target:
        if any(a.GetAtomicNum() == 0 for a in mol.GetAtoms()):
            raise StructureError(
                "The synthesis target must be a concrete molecule, without dummy atoms"
            )
        if not any(a.GetAtomicNum() == 6 for a in mol.GetAtoms()):
            raise StructureError("The target must be a concrete organic molecule")
        if len(Chem.GetMolFrags(mol)) != 1:
            raise StructureError(
                "Select one concrete organic target component; salt/component intent is ambiguous"
            )
        if mol.GetNumHeavyAtoms() > 500:
            raise StructureError("The online target limit is 500 heavy atoms")
        if mol.GetStereoGroups():
            raise StructureError(
                "Enhanced stereochemical groups are not supported; supply one concrete stereochemical target"
            )
    return mol


def parse_material(smiles):
    mol = parse(smiles)
    if len(Chem.GetMolFrags(mol)) != 1 or any(a.GetAtomicNum() == 0 for a in mol.GetAtoms()):
        raise StructureError(
            "A source material must be one concrete graph, without unresolved components or dummy atoms"
        )
    if mol.GetStereoGroups():
        raise StructureError(
            "Enhanced stereochemical source groups require an unsupported comparison view"
        )
    return mol


def without_maps(mol):
    result = Chem.Mol(mol)
    for atom in result.GetAtoms():
        atom.SetAtomMapNum(0)
    return result


def canonical(value, *, stereo=True):
    mol = parse(value) if isinstance(value, str) else Chem.Mol(value)
    mol = without_maps(mol)
    if not stereo:
        Chem.RemoveStereochemistry(mol)
    return Chem.MolToSmiles(mol, isomericSmiles=True)


def meets_target(candidate, target):
    """Complete connectivity plus declared target stereo/isotopes/charge, not containment."""
    candidate, target = without_maps(candidate), without_maps(target)
    if (
        candidate.GetNumAtoms() != target.GetNumAtoms()
        or candidate.GetNumBonds() != target.GetNumBonds()
    ):
        return False
    # A stereo-removed key preserves isotopes, charge, atom count and full connectivity.
    if canonical(candidate, stereo=False) != canonical(target, stereo=False):
        return False
    return candidate.HasSubstructMatch(target, useChirality=True)


FP_GENERATOR = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def similarity(left, right):
    return float(
        DataStructs.TanimotoSimilarity(
            FP_GENERATOR.GetFingerprint(without_maps(left)),
            FP_GENERATOR.GetFingerprint(without_maps(right)),
        )
    )


def descriptors(mol):
    return {
        "molecular_weight": Descriptors.MolWt(mol),  # type: ignore[attr-defined]  # RDKit dynamically registers descriptors
        "heavy_atoms": mol.GetNumHeavyAtoms(),
    }


def atom_table(mol):
    return [
        {
            "atom_uid": f"target:{i}",
            "index": i,
            "element": a.GetSymbol(),
            "isotope": a.GetIsotope(),
            "charge": a.GetFormalCharge(),
        }
        for i, a in enumerate(mol.GetAtoms())
    ]


def fragment_key(mol, atoms, positions):
    """A query fragment with labeled boundary dummies, never a proposed material."""
    atoms = set(atoms)
    atoms |= {
        n.GetIdx()
        for i in list(atoms)
        for n in mol.GetAtomWithIdx(i).GetNeighbors()
        if n.GetAtomicNum() == 1 and n.GetIsotope()
    }
    rw = Chem.RWMol()
    remap = {}
    for index in sorted(atoms):
        atom = Chem.Atom(mol.GetAtomWithIdx(index))
        atom.SetAtomMapNum(0)
        remap[index] = rw.AddAtom(atom)
    for bond in mol.GetBonds():
        a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if a in atoms and b in atoms:
            rw.AddBond(remap[a], remap[b], bond.GetBondType())
        elif (a in atoms and b in positions) or (b in atoms and a in positions):
            outside, core = (a, b) if a in atoms else (b, a)
            dummy = Chem.Atom(0)
            dummy.SetAtomMapNum(positions[core] + 1)
            di = rw.AddAtom(dummy)
            rw.AddBond(remap[outside], di, bond.GetBondType())
    fragment = rw.GetMol()
    fragment.UpdatePropertyCache(strict=False)
    return Chem.MolToSmiles(fragment, isomericSmiles=True)


def outside_blocks(mol, core, *, max_visits=10000):
    positions = {a: i for i, a in enumerate(core)}
    remaining = {
        a.GetIdx() for a in mol.GetAtoms() if a.GetIdx() not in positions and a.GetAtomicNum() != 1
    }
    blocks = []
    visits = 0
    while remaining:
        root = min(remaining)
        remaining.remove(root)
        stack, group = [root], {root}
        while stack:
            index = stack.pop()
            visits += 1
            if visits > max_visits:
                raise TimeoutError("sidechain_atom_budget")
            for neighbor in mol.GetAtomWithIdx(index).GetNeighbors():
                other = neighbor.GetIdx()
                if other in remaining:
                    remaining.remove(other)
                    group.add(other)
                    stack.append(other)
        ports, bonds = [], []
        for index in group:
            for bond in mol.GetAtomWithIdx(index).GetBonds():
                neighbor = bond.GetOtherAtomIdx(index)
                if neighbor in positions:
                    ports.append(positions[neighbor])
                    bonds.append(str(bond.GetBondType()))
        if not ports:
            continue  # another disconnected component is never a joint R witness
        heavy = [mol.GetAtomWithIdx(i) for i in group]
        alkyl = all(
            a.GetAtomicNum() == 6
            and not a.GetIsAromatic()
            and not a.IsInRing()
            and a.GetFormalCharge() == 0
            and a.GetNumRadicalElectrons() == 0
            for a in heavy
        )
        alkyl = alkyl and all(
            b.GetBondType() == Chem.BondType.SINGLE
            for b in mol.GetBonds()
            if b.GetBeginAtomIdx() in group and b.GetEndAtomIdx() in group
        )
        aromatic = all(a.GetIsAromatic() for a in heavy)
        category = (
            "alkyl"
            if alkyl
            else (
                "aryl"
                if aromatic and all(a.GetAtomicNum() == 6 for a in heavy)
                else "heteroaryl"
                if aromatic
                else "other"
            )
        )
        blocks.append(
            {
                "core_positions": sorted(ports),
                "atom_indices": sorted(group),
                "fragment": fragment_key(mol, group, positions),
                "boundary_bonds": sorted(bonds),
                "heavy_atoms": len(group),
                "category": category,
            }
        )
    return blocks
