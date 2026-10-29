"""九方向可解释特征：只计算当前结构与来源实际支持的字段，资料未接入时保留 unknown。"""

from collections import Counter

from reaction_reference.chemistry.structures import descriptors, parse
from reaction_reference.retrieval.planner import functional_matches


def _feature(value, support, *, state="known", limitations=None):
    """把一个特征值封装为状态、支持依据和限制的统一字典。

    value=None 不自动转成低负担、低风险或零值；state 由调用方按已知范围明确给出。
    """
    return {"state": state, "value": value, "support": support, "limitations": limitations or []}


def condition_issues(conditions):
    """标记来源中的倒置温度范围和负时长；保留原始数值供核查，正常低温和零时长有效。"""
    issues = {}
    if (
        conditions.temperature_min_c is not None
        and conditions.temperature_max_c is not None
        and conditions.temperature_min_c > conditions.temperature_max_c
    ):
        issues["temperature"] = "inverted_temperature_range"
    if conditions.duration_seconds is not None and conditions.duration_seconds < 0:
        issues["duration"] = "negative_duration"
    return issues


def features(reference, target_smiles=None):
    """为具体 Reference 提取九方向解释信息，返回特征字典。

    target_smiles 可选，用于质量比与官能团差异；来源与目标均使用具体材料。供应、危害、放大等没有资料供应器的方向返回 unknown；官能团计数只做环境差异线索，不预测反应活性或选择性。
    """
    record = reference.record
    structural = descriptors(parse(reference.material.smiles))
    target = descriptors(parse(target_smiles)) if target_smiles else None
    groups = Counter(name for name, _, _ in functional_matches(parse(reference.material.smiles)))
    desired = (
        Counter(name for name, _, _ in functional_matches(parse(target_smiles)))
        if target_smiles
        else Counter()
    )
    observations = [
        o.model_dump()
        for o in record.observations
        if o.product_instance_id == reference.material.instance_id
    ]
    source = {
        "record_id": record.id,
        "material_instance_id": reference.material.instance_id,
        "event_scope": record.event_scope,
        "stage_id": record.conditions.stage_id,
    }
    return {
        "method_relevance": _feature(
            {
                "contribution": reference.contribution,
                "projected_changes": reference.coverage.get("projected_changes"),
                "classes": reference.analysis.reaction_classes,
                "joint_coverage": reference.coverage.get("joint_witness"),
            },
            "graph_inference_and_scoped_observation",
        ),
        "transfer_burden": _feature(
            {
                "source_molecular_weight": structural["molecular_weight"],
                "target_molecular_weight": target["molecular_weight"] if target else None,
                "molecular_weight_ratio": structural["molecular_weight"]
                / target["molecular_weight"]
                if target
                else None,
                "target_requirements_satisfied": reference.target_requirements_satisfied,
            },
            "computed_from_concrete_material",
            state="partial",
            limitations=[
                "mass_similarity_does_not_establish_method_transfer",
                "new_input_feasibility_unverified",
            ],
        ),
        "reactivity_selectivity": _feature(
            {
                "source_group_counts": dict(groups),
                "target_group_counts": dict(desired),
                "additional_target_functional_units": dict(desired - groups),
            },
            "reviewed_functional_group_patterns",
            state="partial",
            limitations=[
                "overlapping_patterns_are_not_independent_reaction_sites",
                "electronic_steric_and_selectivity_effects_not_predicted",
            ],
        ),
        "evidence_quality": _feature(
            {
                "preparation_hit": reference.preparation_hit,
                "obtainment_hit": reference.obtainment_hit,
                "use_hit": reference.use_hit,
                "synthetic": record.source.synthetic,
                "claims": [c.id for c in reference.claims],
                "mapping_support": reference.analysis.mapping_support,
                "source": source,
            },
            "source_annotations_and_mapping_validation",
        ),
        "material_supply": _feature(
            None,
            "no_provider",
            state="unknown",
            limitations=["structure_presence_does_not_establish_availability_or_price"],
        ),
        "operation_equipment": _feature(
            {
                "conditions": record.conditions.model_dump(),
                "one_pot": record.one_pot,
                "step_count": record.step_count,
                "reactant_count": sum(m.role == "reactant" for m in record.materials),
                "source": source,
            },
            "source_reported_fields",
            state="partial",
            limitations=["missing_workup_and_stage_requirements_not_inferred"]
            + list(condition_issues(record.conditions).values()),
        ),
        "hazard_process_regulation": _feature(
            None,
            "no_provider",
            state="unknown",
            limitations=["not_a_safety_assessment", "missing_hazard_information_is_not_a_pass"],
        ),
        "output_isolation": _feature(
            observations or None,
            "product_bound_observations",
            state="known"
            if observations and any(o["yield_pct"] is not None for o in observations)
            else "partial",
            limitations=[
                "yield_comparison_requires_same_product_and_yield_type",
                "synthetic_values_not_experimental_evidence",
            ]
            if record.source.synthetic
            else ["purification_and_scale_comparability_not_inferred"],
        ),
        "scale_resource_waste": _feature(
            None,
            "no_quantified_process_inventory",
            state="unknown",
            limitations=["no_scale_extrapolation_or_PMI_from_reaction_formula"],
        ),
    }
