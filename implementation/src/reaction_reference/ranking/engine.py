from reaction_reference.chemistry.structures import canonical
from reaction_reference.ranking.features import features


def lab_fit(reference, context):
    if context is None:
        return "not_applicable", ["lab_context_not_configured"]
    conditions = reference.record.conditions
    failures, unknown, tested = [], [], 0
    checks = [
        (
            context.max_temperature_c,
            conditions.temperature_max_c,
            "temperature_max",
            lambda a, b: b <= a,
        ),
        (
            context.min_temperature_c,
            conditions.temperature_min_c,
            "temperature_min",
            lambda a, b: b >= a,
        ),
        (context.max_pressure_kpa, conditions.pressure_max_kpa, "pressure", lambda a, b: b <= a),
    ]
    for requirement, actual, label, predicate in checks:
        if requirement is None:
            continue
        tested += 1
        if actual is None:
            unknown.append(label + "_unknown")
        elif not predicate(requirement, actual):
            failures.append(label + "_outside_capability")
    if context.excluded_material_smiles:
        tested += 1
        excluded = {canonical(s) for s in context.excluded_material_smiles}
        try:
            found = {canonical(m.smiles) for m in reference.record.materials}
            if excluded & found:
                failures.append("explicitly_excluded_material")
            # Absence from an incomplete source list is not a confirmed exclusion pass.
            if not reference.record.raw.get("material_inventory_complete", False):
                unknown.append("material_inventory_completeness_unknown")
        except ValueError:
            unknown.append("material_identity_unknown")
    if context.available_equipment is not None:
        tested += 1
        if conditions.equipment is None:
            unknown.append("equipment_requirements_unknown")
        elif not set(conditions.equipment) <= set(context.available_equipment):
            failures.append("required_equipment_unavailable")
    if reference.record.event_scope != "documented_step":
        unknown.append("condition_event_scope_not_assigned")
    return (
        "fail" if failures else "unknown" if unknown else "pass" if tested else "not_applicable",
        failures + unknown,
    )


def _priority(reference):
    if reference.target_requirements_satisfied and reference.obtainment_hit:
        return 0
    if not reference.obtainment_hit and not reference.use_hit:
        return (
            5
            if reference.contribution in ("connection_method", "local_method", "modification")
            else 6
        )
    return {
        "connection_method": 1,
        "local_method": 2,
        "modification": 3,
        "target_outcome": 3,
        "usage": 4,
        "structure_clue": 5,
        "unknown": 6,
    }[reference.contribution]


def rank_references(
    references, profile="reference_first", context=None, max_display=18, target_smiles=None
):
    enriched = []
    for reference in references:
        fit, reasons = lab_fit(reference, context)
        enriched.append(
            reference.model_copy(
                update={
                    "lab_fit": fit,
                    "lab_reasons": reasons,
                    "ranking_features": reference.ranking_features
                    or features(reference, target_smiles),
                }
            )
        )

    def key(ref):
        joint = ref.coverage.get("joint_witness") or {}
        evidence = (
            0
            if ref.obtainment_hit
            else 1
            if any(c.support == "source_reported" for c in ref.claims)
            else 2
        )
        # Missing conditions do not receive lower temperature/easier-operation scores.
        # Fixed known-field groups prevent a cyclic pairwise comparator.
        conditions = ref.record.conditions
        availability = (
            conditions.temperature_min_c is not None and conditions.temperature_max_c is not None,
            conditions.duration_seconds is not None,
        )
        process: tuple = ()
        if profile == "process_reference":
            # Compare only within an explicit equal-information group. Unknown
            # fields never stand in for zero temperature/time or easy operation.
            burden = (
                max(abs(conditions.temperature_min_c - 25), abs(conditions.temperature_max_c - 25))
                if availability[0]
                else 0,
                conditions.duration_seconds if availability[1] else 0,
            )
            process = (
                sum(not known for known in availability),
                tuple(not known for known in availability),
                burden,
            )
        base = (
            _priority(ref),
            evidence,
            -joint.get("atom_coverage", 0),
            *process,
            -ref.similarity,
            ref.id,
        )
        if profile != "reference_first" and context is not None:
            return ({"pass": 0, "unknown": 1, "not_applicable": 1, "fail": 2}[ref.lab_fit],) + base
        return base

    ordered = sorted(enriched, key=key)
    selected, used = [], set()
    # Preserve a reported complete-target outcome globally, even for deprotection.
    exact = next((r for r in ordered if r.target_requirements_satisfied and r.obtainment_hit), None)
    if exact:
        selected.append(exact)
        used.add(exact.id)
    for _ in range(4):
        for layer in ("whole", "core", "fragment"):
            candidate = next((r for r in ordered if layer in r.layers and r.id not in used), None)
            if candidate and len(selected) < max_display:
                selected.append(candidate)
                used.add(candidate.id)
    for ref in ordered:
        if ref.id not in used and len(selected) < max_display:
            selected.append(ref)
            used.add(ref.id)
    positions = {r.id: i + 1 for i, r in enumerate(selected)}
    enriched = [r.model_copy(update={"display_position": positions.get(r.id)}) for r in ordered]
    return enriched, [r.id for r in selected]
