"""目标母核与反应位置的排序特征；仅描述图上贡献，不预测反应可行性。"""

from rdkit import Chem

from reaction_reference.ranking.scoring import scoring_policy
from reaction_reference.rules import load_rules


def target_regions(target):
    """划分完整环系、无环功能锚点骨架及连接端功能单元，返回原目标索引。

    环系共享原子时合并；每个环原子的权重为环系独立环数加一，突出桥环/稠环。
    无环目标用官能团锚点之间的路径，缺少锚点时使用完整重原子框架。
    支链头部只补齐直接接到环系/骨架的官能团，不沿整条支链传播。
    """
    if target is None:
        return {"core_weights": {}, "head_bonds": set(), "core_bonds": set()}
    policy = scoring_policy()["core_definition"]
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
    weights = {}
    for system in systems:
        edges = sum(
            b.GetBeginAtomIdx() in system and b.GetEndAtomIdx() in system for b in target.GetBonds()
        )
        for atom in system:
            weights[atom] = policy["ring_base_weight"] + policy["ring_cycle_weight"] * (
                edges - len(system) + 1
            )
    if not weights:
        anchors = (
            set().union(*units)
            if units
            else {a.GetIdx() for a in target.GetAtoms() if a.GetAtomicNum() > 1}
        )
        ordered = sorted(anchors)
        core = set(anchors)
        for other in ordered[1:]:
            core.update(Chem.GetShortestPath(target, ordered[0], other))
        weights = dict.fromkeys(core, policy["acyclic_atom_weight"])
    core_atoms = set(weights)
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
            head_bonds.update(
                tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx())))
                for b in target.GetBonds()
                if {b.GetBeginAtomIdx(), b.GetEndAtomIdx()} <= head
            )
    return {"core_weights": weights, "head_bonds": head_bonds, "core_bonds": core_bonds}


def scaffold_relevance(reference, target, regions):
    """用同一方法见证计算母核覆盖、目标覆盖和中心位置，避免跨见证拼接虚高评分。

    输出独立评分维度：加权母核覆盖、目标覆盖及中心位置奖励，母核内部1，
    骨架与支链头部0.8，其他位置0。系数是可解释的工程启发式，未经专家校准。
    中心必须属于所选见证；缺少可确认位置时不追加中心奖励。
    """
    center_values = scoring_policy()["center_values"]
    method_id = reference.coverage.get("method_witness_id")
    witness = next((w for w in reference.witnesses if w.id == method_id), None)
    if witness is None:
        witness = max(
            reference.witnesses, key=lambda w: (w.target_atom_coverage, w.id), default=None
        )
    matched = {t for t, _ in witness.target_to_source} if witness else set()
    weights = regions["core_weights"]
    core_coverage = (
        sum(v for k, v in weights.items() if k in matched) / sum(weights.values()) if weights else 0
    )
    target_count = target.GetNumHeavyAtoms() if target is not None else 0
    coverage = (
        len([i for i in matched if target.GetAtomWithIdx(i).GetAtomicNum() > 1]) / target_count
        if target_count
        else 0
    )
    projection = reference.coverage.get("projected_changes", {})
    changes = {
        tuple(sorted(pair))
        for pair in projection.get("formed_target_bonds", [])
        if set(pair) <= matched
    }
    changed_atoms = set(projection.get("changed_target_atoms", [])) & matched
    if changes & regions["core_bonds"] or (not changes and changed_atoms & set(weights)):
        location = "core_internal"
    elif changes & regions["head_bonds"] or (
        not changes and changed_atoms & {i for pair in regions["head_bonds"] for i in pair}
    ):
        location = "core_branch_head"
    else:
        location = "branch_remote_or_unresolved"
    bonus = center_values[location]
    return {
        "state": "known" if witness else "unknown",
        "core_atom_indices": sorted(weights),
        "matched_target_atoms": sorted(matched),
        "weighted_core_coverage": core_coverage,
        "target_atom_coverage": coverage,
        "center_location": location,
        "center_bonus": bonus,
        "witness_id": witness.id if witness else None,
        "support": "target_topology_and_single_method_witness",
        "limitations": [
            "heuristic_weights_not_expert_calibrated",
            "not_a_chemical_feasibility_prediction",
        ],
    }
