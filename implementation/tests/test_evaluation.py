import json

from reaction_reference.evaluation.runner import evaluate


def test_masking_removes_target_records_and_unreviewed_is_not_scored(fixture_path, tmp_path):
    targets = tmp_path / "targets.jsonl"
    targets.write_text(
        json.dumps(
            {
                "id": "unit-case",
                "target_smiles": "CCNC(=O)c1ccccc1",
                "label_state": "unreviewed",
                "useful_method_record_ids": None,
            }
        )
        + "\n"
    )
    output = tmp_path / "evaluation.json"
    evaluate(fixture_path, targets, output)
    report = json.loads(output.read_text())
    observed, masked = report["cases"]
    assert observed["structural_exact_target_found"]
    assert not masked["structural_exact_target_found"]
    assert masked["excluded_record_ids"]
    assert observed["annotated_method_recall"] is None
    assert observed["method_relevance_label_state"] == "unreviewed_not_scored"
