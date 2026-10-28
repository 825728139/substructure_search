import json

from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.chemistry.structures import digest
from reaction_reference.evidence.claims import evidence_for


def annotation(record, **updates):
    row = {
        "record_id": record.id,
        "expected_source_hash": digest(record.model_dump(), 64),
        "reviewer": "test-only",
        "reviewed_at": "2026-10-29",
        "observations": [o.model_dump() for o in record.observations],
        "event_scope": record.event_scope,
        "documented_step_ref": record.documented_step_ref,
        "step_count": 1,
    }
    row.update(updates)
    return row


def test_review_bound_to_record_hash(source, amide, tmp_path):
    path = tmp_path / "annotation.jsonl"
    path.write_text(json.dumps(annotation(amide, expected_source_hash="f" * 64)) + "\n")
    wrapper = AnnotatedSource(source, path)
    assert wrapper._apply(amide) == amide
    assert wrapper.issues[-1]["code"] == "evidence_overlay_source_hash_mismatch"


def test_review_does_not_erase_synthetic_origin(source, amide, tmp_path):
    path = tmp_path / "annotation.jsonl"
    path.write_text(json.dumps(annotation(amide)) + "\n")
    result = AnnotatedSource(source, path)._apply(amide)
    assert result.source.synthetic
    assert not evidence_for(result, result.materials[-1])[0]
    assert result.raw["evidence_review"]["reviewer"] == "test-only"
