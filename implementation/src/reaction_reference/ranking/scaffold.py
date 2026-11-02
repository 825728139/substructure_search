"""目标母核与反应位置的排序特征；仅描述图上贡献，不预测反应可行性。"""

from reaction_reference.chemistry.regions import structural_regions
from reaction_reference.ranking.scoring import scoring_policy
from reaction_reference.reaction_analysis.region_support import has_region_method


def target_regions(target):
    """划分完整环系、无环功能锚点骨架及连接端功能单元，返回原目标索引。

    环系共享原子时合并；每个环原子的权重为环系独立环数加一，突出桥环/稠环。
    无环目标用官能团锚点之间的路径，缺少锚点时使用完整重原子框架。
    支链头部只补齐直接接到环系/骨架的官能团，不沿整条支链传播。
    """
    if target is None:
        return {"core_weights": {}, "head_bonds": set(), "core_bonds": set()}
    regions = structural_regions(target)
    policy = scoring_policy()["core_definition"]
    weights = {}
    for system in regions["core_regions"]:
        edges = sum(
            b.GetBeginAtomIdx() in system and b.GetEndAtomIdx() in system for b in target.GetBonds()
        )
        weight = (
            policy["ring_base_weight"] + policy["ring_cycle_weight"] * (edges - len(system) + 1)
            if regions["ring_based"]
            else policy["acyclic_atom_weight"]
        )
        weights.update(dict.fromkeys(system, weight))
    return {
        "core_weights": weights,
        "head_bonds": regions["head_bonds"],
        "core_bonds": regions["core_bonds"],
    }


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
    if has_region_method(projection):
        # 区域级支持不能伪装成唯一原子位置，使用单独可审核的分值。
        location = projection["region_consensus"]["kind"] + "_region_consensus"
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
