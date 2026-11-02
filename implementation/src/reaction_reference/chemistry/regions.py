"""目标母核及支链连接区域的纯结构划分，反应分析和评分共用同一原子索引定义。"""

from rdkit import Chem

from reaction_reference.rules import load_rules


def structural_regions(target):
    """按完整环系或无环功能锚点路径划分母核，保留直接连接头部及完整环系边界。

    支链头部仅扩展首个连接原子的功能单元，排除酯/醚远端烷基碳。
    返回的是图上区域，不表示独立的合成切断方案，也不使用任何打分参数。
    """
    rules, _ = load_rules()
    units = [
        set(match)
        for rule in rules["functional_groups"]
        for match in target.GetSubstructMatches(Chem.MolFromSmarts(rule["smarts"]))
    ]
    systems: list[set[int]] = []
    for ring in target.GetRingInfo().AtomRings():
        merged = set(ring)
        while any(merged & other for other in systems):
            for other in systems[:]:
                if merged & other:
                    merged |= other
                    systems.remove(other)
        systems.append(merged)
    if not systems:
        anchors = (
            set().union(*units)
            if units
            else {a.GetIdx() for a in target.GetAtoms() if a.GetAtomicNum() > 1}
        )
        ordered = sorted(anchors)
        core = set(anchors)
        for other in ordered[1:]:
            core.update(Chem.GetShortestPath(target, ordered[0], other))
        systems = [core]
    core_atoms = set().union(*systems)
    head_regions = []
    core_bonds = set()
    head_bonds: set[tuple[int, int]] = set()
    for bond in target.GetBonds():
        pair = {bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()}
        if pair <= core_atoms:
            core_bonds.add(tuple(sorted(pair)))
        elif len(pair & core_atoms) == 1:
            head = set(pair)
            outside = pair - core_atoms
            # 只扩展直接含首个支链原子的功能单元，避免醚等重叠模式串联到远端。
            for unit in units:
                root = target.GetAtomWithIdx(next(iter(outside)))
                if unit & outside and (
                    root.GetAtomicNum() != 6
                    or root.GetHybridization() != Chem.HybridizationType.SP3
                ):
                    # 酯的烷氧基碳、醚的远端烷基不算连接头部，不能奖励O—乙基尾部成键。
                    head |= {
                        i
                        for i in unit
                        if target.GetAtomWithIdx(i).GetAtomicNum() != 6
                        or target.GetAtomWithIdx(i).GetHybridization() != Chem.HybridizationType.SP3
                    }
            head_regions.append(head)
            head_bonds.update(
                tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx())))
                for b in target.GetBonds()
                if {b.GetBeginAtomIdx(), b.GetEndAtomIdx()} <= head
            )
    return {
        "core_regions": systems,
        "head_regions": head_regions,
        "head_bonds": head_bonds,
        "core_bonds": core_bonds,
        "ring_based": bool(target.GetRingInfo().AtomRings()),
    }
