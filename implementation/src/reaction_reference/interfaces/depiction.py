"""已保存参考分子的 SVG 绘制；图上的索引属于该材料，目标位置通过见证表对应。"""

import math
from xml.etree import ElementTree as ET

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

from reaction_reference.chemistry.structures import parse

ET.register_namespace("", "http://www.w3.org/2000/svg")


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
    """按来源角色逐个排版分子，独立绘图区避免多材料挤在固定反应画布中。

    每个分子重新生成二维坐标，按坐标跨度分配空间；加号、箭头单独占位。
    盐的点分组分仍属于原材料，不拆成额外反应物；不补造缺失材料。
    """
    sides: dict[str, list] = {"reactant": [], "product": []}
    for material in reference.record.materials:
        if material.role not in sides:
            continue
        molecule = parse(material.smiles)
        for atom in molecule.GetAtoms():
            atom.SetAtomMapNum(0)
        # 丢弃可能携带的三维或拥挤坐标；RDKit负责同一材料内点分组分的二维排布。
        rdDepictor.Compute2DCoords(molecule, clearConfs=True)
        points = molecule.GetConformer().GetPositions()
        width = max(180, math.ceil(float(points[:, 0].max() - points[:, 0].min()) * 24 + 100))
        height = max(220, math.ceil(float(points[:, 1].max() - points[:, 1].min()) * 24 + 100))
        sides[material.role].append((molecule, width, height))
    height = max((h for side in sides.values() for _, _, h in side), default=220)
    namespace = "http://www.w3.org/2000/svg"
    root = ET.Element(f"{{{namespace}}}svg", {"height": str(height)})
    offset = 0
    for role in ("reactant", "product"):
        if role == "product":
            # 箭头占独立区域，即使某一侧材料缺失也保留来源方向。
            ET.SubElement(
                root,
                f"{{{namespace}}}path",
                {
                    "d": f"M {offset + 12},{height / 2} h 66 m -12,-7 l 12,7 l -12,7",
                    "fill": "none",
                    "stroke": "#20362f",
                    "stroke-width": "2",
                },
            )
            offset += 90
        for index, (molecule, width, _) in enumerate(sides[role]):
            if index:
                symbol = ET.SubElement(
                    root,
                    f"{{{namespace}}}text",
                    {
                        "x": str(offset + 20),
                        "y": str(height / 2),
                        "text-anchor": "middle",
                        "dominant-baseline": "central",
                        "font-size": "26",
                    },
                )
                symbol.text = "+"
                offset += 40
            drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
            drawer.drawOptions().fixedBondLength = 36  # type: ignore[assignment]
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule)
            drawer.FinishDrawing()
            panel = ET.fromstring(drawer.GetDrawingText())
            panel.set("x", str(offset))
            panel.set("y", "0")
            panel.set("overflow", "hidden")
            panel.set("data-role", role)
            root.append(panel)
            offset += width
    root.set("width", str(offset))
    root.set("viewBox", f"0 0 {offset} {height}")
    return ET.tostring(root, encoding="unicode")


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
