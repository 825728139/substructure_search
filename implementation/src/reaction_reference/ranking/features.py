"""Nine independently inspectable dimensions; unknown never becomes a low-risk score."""

from collections import Counter

from reaction_reference.chemistry.structures import descriptors, parse
from reaction_reference.retrieval.planner import functional_matches


def _feature(value, support, *, state="known", limitations=None):
    return {"state": state, "value": value, "support": support, "limitations": limitations or []}


def features(reference, target_smiles=None):
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
            limitations=["missing_workup_and_stage_requirements_not_inferred"],
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
