"""序列化边界回归：不支持的元数据应隔离，合法数据在保存和恢复后保持一致。"""

import json

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import ReactionRecord


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e400", '"\\ud800"'])
def test_unserializable_native_metadata_is_isolated(tmp_path, amide, token):
    """自由元数据中的非有限数和无效 Unicode 不得静默变值，也不能阻断下一条有效记录。"""
    original = json.dumps(amide.model_dump(exclude={"raw"}))
    bad = original[:-1] + ',"raw":{"value":' + token + "}}"
    path = tmp_path / "records.jsonl"
    path.write_text(
        bad + "\n" + json.dumps({"id": 2, "product_smiles": ["CCO"]}) + "\n",
        encoding="utf-8",
    )
    source = JsonlSource(path)
    try:
        assert [record.id for record in source.records] == ["patent:2"]
        assert len(source.issues) == 1 and source.issues[0]["code"] == "invalid_record"
        assert source.issues[0]["line"] == 1
    finally:
        source.close()


def test_supported_native_metadata_survives_json_roundtrip(tmp_path, amide):
    """有限数、大整数、中文及空值在合法原生记录的 JSON 往返后保持内容与摘要一致。"""
    raw = {"integer": 9007199254740993, "fraction": 1.25, "nested": [None, "原始记录"]}
    record = amide.model_copy(update={"raw": raw})
    path = tmp_path / "records.jsonl"
    path.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    source = JsonlSource(path)
    try:
        assert not source.issues
        loaded = source.records[0]
        restored = ReactionRecord.model_validate_json(loaded.model_dump_json())
        assert restored.raw == loaded.raw == raw
        assert digest(restored.model_dump()) == digest(loaded.model_dump())
    finally:
        source.close()
