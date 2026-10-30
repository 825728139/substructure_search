"""来源身份校验回归：空标识不能参与缓存、证据关联或实验去重。"""

import json

import pytest

from reaction_reference.adapters.sources import JsonlSource


@pytest.mark.parametrize(
    "identifier", ["record", "namespace", "source_record", "experiment", "material"]
)
@pytest.mark.parametrize("value", ["", " \t "])
def test_blank_native_identifier_is_isolated(tmp_path, amide, identifier, value):
    """五类必要身份字段为空时应隔离当前原生记录，不能影响下一条合法来源。"""
    row = amide.model_dump()
    if identifier == "record":
        row["id"] = value
    elif identifier == "material":
        row["materials"][0]["instance_id"] = value
    else:
        field = {
            "namespace": "namespace",
            "source_record": "record_id",
            "experiment": "experiment_id",
        }[identifier]
        row["source"][field] = value
    path = tmp_path / "records.jsonl"
    path.write_text(
        json.dumps(row) + "\n" + json.dumps({"id": "valid", "product_smiles": ["CCO"]}) + "\n",
        encoding="utf-8",
    )
    source = JsonlSource(path)
    try:
        assert [record.id for record in source.records] == ["patent:valid"]
        assert len(source.issues) == 1
        assert source.issues[0]["code"] == "invalid_record"
        assert source.issues[0]["line"] == 1
        assert len(source.candidates) == 1
    finally:
        source.close()


def test_identifier_validation_preserves_valid_identity_text(tmp_path, amide):
    """合法标识可含中文、标点和外围空格，校验不能擅自归一化为其他记录的编号。"""
    row = amide.model_dump()
    row["id"] = " 记录:1 "
    row["source"].update(namespace=" 内部来源 ", record_id=" 来源:1 ", experiment_id=" 实验:1 ")
    row["materials"][0]["instance_id"] = " 材料:1 "
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    source = JsonlSource(path)
    try:
        assert not source.issues
        loaded = source.records[0]
        assert loaded.id == row["id"]
        assert loaded.source.model_dump() == row["source"]
        assert loaded.materials[0].instance_id == " 材料:1 "
    finally:
        source.close()
