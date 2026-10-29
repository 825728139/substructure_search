"""材料实例级证据分账与下游模型摘要：来源报告、结构推定和未观察建议保持分离。"""

from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import Claim


def evidence_for(record, material):
    """判断一个材料实例的来源支持，返回（制备命中、获得命中、使用命中、Claim 列表）。

    产品观察必须有非空文本与位置；冲突/失败/回收会限制阳性结论，输入使用要求 actual_input=True。合成示例可生成演示 Claim，但三个真实文献计数标志始终为 False。
    """
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
    # 合成示例可验证图逻辑，但必须与真实文献统计隔离。
    qualified = not record.source.synthetic
    return (
        prepared and qualified,
        (prepared or enriched) and qualified,
        actual_use and qualified,
        claims,
    )


def summary_items(references, proposals, max_bytes):
    """把选中参考和建议转为受 UTF-8 字节预算约束的 JSON 摘要。

    返回（摘要字符串、complete/truncated/unavailable、省略条数）。按整条目追加，不能把半条证据切成可误读的 JSON；一个条目也放不下时摘要为空，而完整证据仍在资料包中。
    """
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
