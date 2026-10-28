from rdkit.Chem.Draw import rdMolDraw2D

from reaction_reference.chemistry.structures import parse


def reference_svg(reference):
    molecule = parse(reference.material.smiles)
    best = max(reference.witnesses, key=lambda w: (w.target_atom_coverage, w.id), default=None)
    atoms = sorted({s for _, s in best.target_to_source}) if best else []
    drawer = rdMolDraw2D.MolDraw2DSVG(650, 260)
    drawer.drawOptions().addAtomIndices = True  # type: ignore[assignment]
    rdMolDraw2D.PrepareAndDrawMolecule(
        drawer,
        molecule,
        highlightAtoms=atoms,
        highlightAtomColors={i: (0.65, 0.88, 0.72) for i in atoms},
    )
    drawer.FinishDrawing()
    return drawer.GetDrawingText()
