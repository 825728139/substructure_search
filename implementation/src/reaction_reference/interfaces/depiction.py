"""已保存参考分子的 SVG 绘制；图上的索引属于该材料，目标位置通过见证表对应。"""

from rdkit.Chem.Draw import rdMolDraw2D

from reaction_reference.chemistry.structures import parse


def reference_svg(reference):
    """绘制 Reference 的具体材料，按最佳已发现单见证高亮覆盖原子。

    返回 SVG 文本并标来源材料本地索引；高亮是连接覆盖示意，不代表立体结果或实验可行性。
    """
    molecule = parse(reference.material.smiles)
    # 以覆盖最高的单见证确定绿色高亮，用 ID 保持并列结果稳定。
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
