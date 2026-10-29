"""回归测试：真实目标屏蔽与未知标签不计分。"""

import json

from reaction_reference.evaluation.runner import evaluate


def test_masking_removes_target_records_and_unreviewed_is_not_scored(fixture_path, tmp_path):
    """确认屏蔽移除全部目标来源产品，未审核相关性标签不会产生伪召回得分。"""
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
