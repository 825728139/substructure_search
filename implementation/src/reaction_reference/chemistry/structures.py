"""基础结构工具：解析具体分子、比较完整目标、描述目标原子和提取带连接位点的 R 块。所有原子索引均属于传入分子的解析顺序。"""

import hashlib
import json

from rdkit import Chem, DataStructs
from rdkit.Chem import Descriptors, rdFingerprintGenerator


class StructureError(ValueError):
    """结构无法解析或超出当前化学比较能力时抛出的输入错误。"""

    pass


def digest(value, length=24):
    """为可 JSON 序列化的数据生成稳定 SHA-256 摘要。

    字典键排序后按 UTF-8 编码，返回前 length 个十六进制字符；用于对象身份和缓存键，不用于加密或口令保存。
    """
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:length]


def parse(smiles, *, target=False):
    """将 SMILES 解析为 RDKit Mol；无效或空结构抛出 StructureError。

    设 target=True 时额外要求具体、单组分、含碳、至多 500 重原子且无增强立体组。返回分子的原子顺序沿用输入解析顺序，不在这里做盐拆分或互变异构体归一化。
    """
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
    """解析一个来源材料，拒绝多组分、虚原子和当前不支持的增强立体组。

    返回具体 Mol；错误抛出 StructureError，由来源适配器记录为局部问题，不冒充一次真实的子结构未命中。
    """
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
    """复制 Mol 并清除反应原子映射号，返回新分子。

    原子顺序、元素、同位素、电荷和立体信息保留；不修改调用方持有的对象。
    """
    result = Chem.Mol(mol)
    for atom in result.GetAtoms():
        atom.SetAtomMapNum(0)
    return result


def canonical(value, *, stereo=True):
    """为 SMILES 或 Mol 生成去映射号的规范 SMILES 身份键。

    stereo=False 只移除立体标记，同位素和电荷仍保留。规范字符串的遍历顺序不能拿来解释原分子的原子索引。
    """
    mol = parse(value) if isinstance(value, str) else Chem.Mol(value)
    mol = without_maps(mol)
    if not stereo:
        Chem.RemoveStereochemistry(mol)
    return Chem.MolToSmiles(mol, isomericSmiles=True)


def meets_target(candidate, target):
    """判断候选是否满足完整目标的连接、同位素、电荷及已指定的立体要求。

    先检查全分子大小与去立体身份，再进行有手性的匹配，返回 bool。目标未指定手性时可接受相应已指定构型的候选；仅包含目标片段不足以通过。
    """
    candidate, target = without_maps(candidate), without_maps(target)
    if (
        candidate.GetNumAtoms() != target.GetNumAtoms()
        or candidate.GetNumBonds() != target.GetNumBonds()
    ):
        return False
    # 仅移除立体标记的身份键仍保留同位素、电荷、原子数和完整连接关系。
    if canonical(candidate, stereo=False) != canonical(target, stereo=False):
        return False
    return candidate.HasSubstructMatch(target, useChirality=True)


FP_GENERATOR = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def similarity(left, right):
    """返回两个 Mol 的 radius=2、2048 位 Morgan 指纹 Tanimoto 相似度。

    只用于候选优先级和解释，不能用作保证完整子结构召回的必要筛选条件。
    """
    return float(
        DataStructs.TanimotoSimilarity(
            FP_GENERATOR.GetFingerprint(without_maps(left)),
            FP_GENERATOR.GetFingerprint(without_maps(right)),
        )
    )


def descriptors(mol):
    """计算具体 Mol 的平均摩尔质量（g/mol）和重原子数，返回字典。

    比较对象是这个材料实例，不是多产品反应整侧的总质量。
    """
    return {
        "molecular_weight": Descriptors.MolWt(mol),  # type: ignore[attr-defined]  # RDKit 在运行时动态注册这些描述符。
        "heavy_atoms": mol.GetNumHeavyAtoms(),
    }


def atom_table(mol):
    """按传入 Mol 的原子顺序生成目标原子表，含 target:index、元素、同位素和电荷。

    结果为资料包中的位点解释提供参照；index 为从 0 开始的本地索引。
    """
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
    """把指定片段转为带边界虚原子的结构签名，用于比较完整 R 块。

    atoms 为片段原子集合，positions 将核心原子索引映射到核心位点。虚原子映射号取位点加 1，保留边界键型和同位素氢；返回查询片段字符串，不能把它当作真实可投料分子。
    """
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
    """从给定核心外提取完整连通 R 块及其所有连接位点。

    core 的顺序定义核心位点；返回每块的原子索引、带端口签名、边界键和有限类别。一个桥连块可同时接多个核心位置；显式氢不计重原子支链。访问超过 max_visits 时抛出 TimeoutError，不返回伪完整结果。
    """
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
            continue  # 另一个不连通组分不能作为同一核心映射下的联合 R 见证。
        heavy = [mol.GetAtomWithIdx(i) for i in group]
        alkyl = all(
            a.GetAtomicNum() == 6
            and not a.GetIsAromatic()
            and not a.IsInRing()
            and a.GetFormalCharge() == 0
            and a.GetNumRadicalElectrons() == 0
            for a in heavy
        )
        # 烷基必须通过单键连接核心；孤立在核心外的一个碳也可能是烯基或炔基端点。
        alkyl = (
            alkyl
            and all(bond == "SINGLE" for bond in bonds)
            and all(
                b.GetBondType() == Chem.BondType.SINGLE
                for b in mol.GetBonds()
                if b.GetBeginAtomIdx() in group and b.GetEndAtomIdx() in group
            )
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
