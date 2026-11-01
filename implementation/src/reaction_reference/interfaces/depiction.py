"""已保存参考分子的 SVG 绘制；图上的索引属于该材料，目标位置通过见证表对应。"""

from rdkit import Chem
from rdkit.Chem import rdChemReactions
from rdkit.Chem.Draw import rdMolDraw2D

from reaction_reference.chemistry.structures import parse


def query_images(target_smiles, families):
    """绘制目标、每个真实家族的SMARTS及固定原子高亮；R约束额外绘制源端必要条件。"""
    from reaction_reference.chemistry.markush import candidate_smarts

    def draw(molecule, atoms=()):
        """生成单分子SVG；高亮仅表示查询固定位置，不表示实验已验证。"""
        drawer = rdMolDraw2D.MolDraw2DSVG(520, 300)
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule, highlightAtoms=list(atoms))
        drawer.FinishDrawing()
        return drawer.GetDrawingText()

    target = parse(target_smiles, target=True)
    items = []
    for family in families:
        query = Chem.MolFromSmarts(family.core_smarts)
        for atom in query.GetAtoms():
            atom.SetAtomMapNum(0)
        prefilter = Chem.MolFromSmarts(candidate_smarts(family))
        for atom in prefilter.GetAtoms():
            atom.SetAtomMapNum(0)
        items.append(
            {
                "family": family.model_dump(mode="json"),
                "target_svg": draw(target, family.target_atoms),
                "query_svg": draw(query),
                "prefilter_svg": draw(prefilter),
            }
        )
    return {"target_svg": draw(target), "queries": items}


def reaction_svg(reference):
    """按实际来源材料角色绘制反应物到产物，不用目标推断或补造缺失反应物。"""
    reaction = rdChemReactions.ChemicalReaction()
    for material in reference.record.materials:
        if material.role not in ("reactant", "product"):
            continue
        molecule = parse(material.smiles)
        for atom in molecule.GetAtoms():
            atom.SetAtomMapNum(0)
        if material.role == "reactant":
            reaction.AddReactantTemplate(molecule)
        else:
            reaction.AddProductTemplate(molecule)
    drawer = rdMolDraw2D.MolDraw2DSVG(1100, 350)
    drawer.DrawReaction(reaction)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


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
