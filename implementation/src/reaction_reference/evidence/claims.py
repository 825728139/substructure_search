from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import Claim


def evidence_for(record, material):
    observations = [o for o in record.observations if o.product_instance_id == material.instance_id]
    supported = [
        o
        for o in observations
        if o.evidence_text
        and o.evidence_text.strip()
        and o.source_location
        and o.source_location.strip()
    ]
    conflicting = any(o.result == "conflict" for o in supported) or (
        any(o.result == "reported_prepared" for o in supported)
        and any(o.result in ("failed", "recovered") for o in supported)
    )
    prepared = any(o.result == "reported_prepared" for o in supported) and not conflicting
    enriched = any(o.result == "enriched" for o in supported) and not conflicting
    actual_use = material.role == "reactant" and material.actual_input is True
    claims = []
    for observation in supported:
        claims.append(
            Claim(
                id=digest([record.id, material.instance_id, observation.model_dump()]),
                subject_id=material.instance_id,
                predicate=observation.result,
                support="synthetic_illustration" if record.source.synthetic else "source_reported",
                source=record.source,
                evidence_text=observation.evidence_text,
                limitations=["synthetic_fixture_not_literature"] if record.source.synthetic else [],
            )
        )
    if actual_use:
        claims.append(
            Claim(
                id=digest([record.id, material.instance_id, "used"]),
                subject_id=material.instance_id,
                predicate="used_as_input",
                support="synthetic_illustration" if record.source.synthetic else "source_reported",
                source=record.source,
                limitations=["synthetic_fixture_not_literature"] if record.source.synthetic else [],
            )
        )
    # Synthetic fixtures can exercise graph logic but never create literature counts.
    qualified = not record.source.synthetic
    return (
        prepared and qualified,
        (prepared or enriched) and qualified,
        actual_use and qualified,
        claims,
    )


def summary_items(references, proposals, max_bytes):
    entries = []
    for ref in references:
        entries.append(
            {
                "kind": "synthetic_example" if ref.record.source.synthetic else "source_reference",
                "reference_id": ref.id,
                "source": ref.record.source.model_dump(),
                "product_or_input": ref.material.smiles,
                "contribution": ref.contribution,
                "contribution_support": ref.contribution_support,
                "reaction_analysis": {
                    "state": ref.analysis.state,
                    "mapping_support": ref.analysis.mapping_support,
                    "classes": ref.analysis.reaction_classes,
                    "formed": [c.model_dump() for c in ref.analysis.formed],
                    "broken": [c.model_dump() for c in ref.analysis.broken],
                    "order_changed": [c.model_dump() for c in ref.analysis.order_changed],
                    "atom_property_changes": ref.analysis.atom_property_changes,
                    "topology": ref.analysis.topology,
                },
                "target_witness": {
                    "id": ref.coverage.get("method_witness_id"),
                    "projection": ref.coverage.get("projected_changes"),
                    "joint_coverage": ref.coverage.get("joint_witness"),
                    "atom_order": "target_input_smiles_parse_order",
                    "semantics": "connectivity_correspondence; not_stereochemical_outcome_proof",
                },
                "conditions": ref.record.conditions.model_dump(),
                "lab_fit": ref.lab_fit,
                "lab_reasons": ref.lab_reasons,
                "event_scope": ref.record.event_scope,
                "preparation_hit": ref.preparation_hit,
                "reactants": [m.smiles for m in ref.record.materials if m.role == "reactant"],
                "reason": ref.reasons,
                "limitations": ref.unresolved,
                "claims": [c.model_dump() for c in ref.claims],
            }
        )
    for proposal in proposals:
        entries.append({"kind": "proposal_not_observed", "proposal": proposal.model_dump()})
    import json

    selected: list[dict] = []
    for entry in entries:
        candidate = json.dumps(selected + [entry], ensure_ascii=False, separators=(",", ":"))
        if len(candidate.encode()) > max_bytes:
            break
        selected.append(entry)
    if entries and not selected:
        return "", "unavailable", len(entries)
    summary = json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
    return (
        summary,
        "complete" if len(selected) == len(entries) else "truncated",
        len(entries) - len(selected),
    )
