"""可解释的多维加权评分：输出每个分项的原值、权重、得分和总分。"""

from functools import lru_cache
from importlib.resources import files

from reaction_reference.chemistry.structures import parse
from reaction_reference.ranking.features import condition_issues
from reaction_reference.ranking.policy import validate_scoring_policy


@lru_cache(maxsize=1)
def scoring_policy():
    """读取随包评分权重；它是工程初始配置，不是拟合后的成功率模型。"""
    return validate_scoring_policy(
        files("reaction_reference").joinpath("resources/ranking_weights.yaml").read_text()
    )


def reference_score(reference, target, spatial, environment_distance, profile, fit, context):
    """汇总单候选分项为加权总分；所有常规维度归一到0至1，未知证据不冒充阳性。

    基础权重总和100；有来源获得证据的完整目标额外100分。
    只在明确请求操作或实验适配偏好时加入相应分项，默认不主动比较反应条件。
    """
    policy = scoring_policy()
    count = target.GetNumHeavyAtoms() if target is not None else 0
    coverage = spatial["target_atom_coverage"]
    source_count = parse(reference.material.smiles).GetNumHeavyAtoms()
    balanced = 2 * coverage * count / (count + source_count) if count else coverage
    projection = reference.coverage.get("projected_changes", {})
    method = (
        policy["method_values"]["formed_target_bond"]
        if projection.get("formed_target_bonds")
        else policy["method_values"]["changed_target_atom"]
        if projection.get("changed_target_atoms")
        else policy["method_values"]["unresolved"]
    )
    evidence = (
        policy["evidence_values"]["reported_obtained"]
        if reference.obtainment_hit
        else policy["evidence_values"]["source_reported_claim"]
        if any(c.support == "source_reported" for c in reference.claims)
        else policy["evidence_values"]["unknown"]
    )
    values = {
        "core_coverage": spatial["weighted_core_coverage"],
        "target_coverage": coverage,
        "center_position": spatial["center_bonus"],
        "balanced_coverage": balanced,
        "environment_match": 1 / (1 + environment_distance / policy["environment_distance_scale"])
        if spatial["state"] == "known"
        else policy["environment_unknown_value"],
        "method_contribution": method,
        "source_evidence": evidence,
        "similarity": reference.similarity,
    }
    components = {
        name: {
            "value": value,
            "weight": policy["weights"][name],
            "points": value * policy["weights"][name],
        }
        for name, value in values.items()
    }
    weight = policy["reported_target_bonus"]
    value = float(reference.target_requirements_satisfied and reference.obtainment_hit)
    components["reported_target"] = {"value": value, "weight": weight, "points": weight * value}
    if profile == "process_reference":
        conditions = reference.record.conditions
        issues = condition_issues(conditions)
        operation = 0.0
        process = policy["process_values"]
        if (
            conditions.temperature_min_c is not None
            and conditions.temperature_max_c is not None
            and "temperature" not in issues
        ):
            deviation = max(
                abs(conditions.temperature_min_c - process["reference_temperature_c"]),
                abs(conditions.temperature_max_c - process["reference_temperature_c"]),
            )
            operation += process["temperature_share"] / (
                1 + deviation / process["temperature_scale_c"]
            )
        if conditions.duration_seconds is not None and "duration" not in issues:
            operation += process["duration_share"] / (
                1 + conditions.duration_seconds / process["duration_scale_seconds"]
            )
        weight = policy["process_preference_weight"]
        components["process_preference"] = {
            "value": operation,
            "weight": weight,
            "points": weight * operation,
        }
    if profile != "reference_first" and context is not None:
        value = policy["lab_values"][fit]
        weight = policy["lab_fit_weight"]
        components["lab_fit"] = {"value": value, "weight": weight, "points": weight * value}
    return {
        "version": policy["version"],
        "config_sha256": policy["config_sha256"],
        "state": policy["status"],
        "total": sum(c["points"] for c in components.values()),
        "components": components,
        "limitations": ["not_a_synthesis_success_probability", "weights_require_broader_review"],
    }
