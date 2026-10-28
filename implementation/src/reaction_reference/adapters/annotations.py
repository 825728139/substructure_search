"""Immutable reviewed evidence overlays bound to an exact source-record hash."""

from pathlib import Path

from pydantic import Field

from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import EventScope, Model, Observation


class EvidenceAnnotation(Model):
    record_id: str
    expected_source_hash: str = Field(min_length=24, max_length=64)
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    observations: list[Observation] = Field(default_factory=list)
    event_scope: EventScope = "unknown"
    documented_step_ref: str | None = None
    step_count: int | None = Field(default=None, ge=1)
    actual_input_evidence: dict[str, str] = Field(default_factory=dict)


class AnnotatedSource:
    def __init__(self, source, path):
        self.source = source
        self.max_selection_stage = source.max_selection_stage
        self.hydration_requires_io = source.hydration_requires_io
        self.selection_policy = source.selection_policy
        self.selection_failure_fallback = getattr(source, "selection_failure_fallback", False)
        self.issues = source.issues
        payload = Path(path).read_bytes()
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError("Evidence overlay exceeds the bounded 32 MiB input size")
        self.annotations: dict[str, EvidenceAnnotation] = {}
        for line in payload.splitlines():
            if not line.strip():
                continue
            annotation = EvidenceAnnotation.model_validate_json(line)
            if annotation.record_id in self.annotations:
                raise ValueError("Duplicate evidence overlay record ID")
            self.annotations[annotation.record_id] = annotation
        self.snapshot_id = digest([source.snapshot_id, digest(payload.decode(), 64)], 64)
        self._records = {}

    def _apply(self, record):
        if record.id in self._records:
            return self._records[record.id]
        annotation = self.annotations.get(record.id)
        if annotation is None:
            return record
        source_hash = record.raw.get("source_record_hash") or digest(record.model_dump(), 64)
        if annotation.expected_source_hash != source_hash:
            self.issues.append(
                {"record_id": record.id, "code": "evidence_overlay_source_hash_mismatch"}
            )
            self._records[record.id] = record
            return record
        try:
            ids = {m.instance_id for m in record.materials if m.role == "reactant"}
            if not set(annotation.actual_input_evidence) <= ids or not all(
                annotation.actual_input_evidence.values()
            ):
                raise ValueError(
                    "Input evidence must refer to actual reactant instances and contain citations"
                )
            data = record.model_dump()
            data.update(
                observations=[o.model_dump() for o in annotation.observations],
                event_scope=annotation.event_scope,
                documented_step_ref=annotation.documented_step_ref,
                step_count=annotation.step_count,
            )
            for material in data["materials"]:
                if material["instance_id"] in annotation.actual_input_evidence:
                    material["actual_input"] = True
            data["raw"]["evidence_review"] = {
                "reviewer": annotation.reviewer,
                "reviewed_at": annotation.reviewed_at,
                "input_evidence": annotation.actual_input_evidence,
                "annotation_hash": digest(annotation.model_dump(), 64),
            }
            result = type(record).model_validate(data)
        except ValueError as exc:
            self.issues.append(
                {
                    "record_id": record.id,
                    "code": "invalid_evidence_overlay",
                    "reason": str(exc)[:300],
                }
            )
            result = record
        self._records[record.id] = result
        return result

    def candidate_page(self, *args, **kwargs):
        return self.source.candidate_page(*args, **kwargs)

    def hydrate(self, record):
        return self._apply(self.source.hydrate(record))

    def close(self):
        self.source.close()
