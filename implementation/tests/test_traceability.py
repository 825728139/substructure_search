"""来源追溯回归：输出结论和诊断必须保留原始引用及文件位置。"""

import json

import pytest

from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import ReactionAnalysis, Reference
from reaction_reference.evidence.claims import evidence_for, summary_items


@pytest.mark.parametrize(
    "patch_kind", ["outcome", "another_input", "empty_input_map", "same_input"]
)
def test_partial_review_preserves_unmodified_input_citations(source, amide, tmp_path, patch_kind):
    """只更新产品观察或另一个输入时，已审核且未修改的底物引用必须保留。"""
    inputs = [material for material in amide.materials if material.role == "reactant"]
    existing = {inputs[0].instance_id: "此前审核的第一种底物引用"}
    record = amide.model_copy(
        update={"raw": {**amide.raw, "evidence_review": {"input_evidence": existing}}}
    )
    changes = (
        {"observations": [observation.model_dump() for observation in record.observations]}
        if patch_kind == "outcome"
        else {"actual_input_evidence": {inputs[1].instance_id: "此次补充的第二种底物引用"}}
        if patch_kind == "another_input"
        else {"actual_input_evidence": {inputs[0].instance_id: "此次修正的第一种底物引用"}}
        if patch_kind == "same_input"
        else {"actual_input_evidence": {}}
    )
    path = tmp_path / "review.jsonl"
    path.write_text(
        json.dumps(
            {
                "record_id": record.id,
                "expected_source_hash": digest(record.model_dump(), 64),
                "reviewer": "本次审核人员",
                "reviewed_at": "2026-10-30",
                **changes,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    updated = AnnotatedSource(source, path)._apply(record)
    expected = {**existing, **changes.get("actual_input_evidence", {})}
    assert updated.raw["evidence_review"]["input_evidence"] == expected
    assert record.raw["evidence_review"]["input_evidence"] == existing


@pytest.mark.parametrize(
    "review",
    [None, {"input_evidence": []}, {"input_evidence": {"other-material": "其他材料的引用"}}],
)
def test_absent_or_unrelated_citations_do_not_create_evidence_text(amide, review):
    """缺失、旧格式或属于其他实例的引用保持未知，不把其他材料的引用填进当前结论。"""
    record = amide.model_copy(update={"raw": {**amide.raw, "evidence_review": review}})
    material = next(material for material in record.materials if material.role == "reactant")
    claims = evidence_for(record, material)[3]
    used = next(claim for claim in claims if claim.predicate == "used_as_input")
    assert used.evidence_text is None


def test_observation_claim_keeps_its_specific_source_location(amide):
    """观察的精确出处不能被整条来源记录的粗定位替换，原记录也不能被改写。"""
    location = "实施例1，第4段，产物分离记录"
    product = amide.materials[-1]
    observation = amide.observations[0].model_copy(update={"source_location": location})
    record = amide.model_copy(
        update={
            "source": amide.source.model_copy(update={"location": "整条记录第1至9段"}),
            "observations": [observation],
        }
    )
    claims = evidence_for(record, product)[3]
    assert claims and claims[0].source.location == location
    assert claims[0].source.record_id == record.source.record_id
    assert claims[0].source.experiment_id == record.source.experiment_id
    assert record.source.location == "整条记录第1至9段"


def test_input_citations_survive_claim_and_summary_export(amide):
    """已有审核输入引用应进入对应使用结论及模型摘要，不能被丢掉或串到另一底物上。"""
    inputs = [material for material in amide.materials if material.role == "reactant"]
    citations = {
        material.instance_id: f"实施例1：明确投入第{index + 1}种底物，原文引用。"
        for index, material in enumerate(inputs)
    }
    record = amide.model_copy(
        update={"raw": {**amide.raw, "evidence_review": {"input_evidence": citations}}}
    )
    references = []
    for material in inputs:
        claims = evidence_for(record, material)[3]
        used = next(claim for claim in claims if claim.predicate == "used_as_input")
        assert used.evidence_text == citations[material.instance_id]
        references.append(
            Reference(
                id=material.instance_id,
                record=record,
                material=material,
                family_ids=[],
                layers=["fragment"],
                witnesses=[],
                analysis=ReactionAnalysis(state="unknown"),
                molecular_weight=1.0,
                claims=claims,
            )
        )
    summary, status, omitted = summary_items(references, [], 65536)
    assert status == "complete" and omitted == 0
    for item in json.loads(summary):
        assert item["claims"][0]["evidence_text"] == citations[item["reference_id"]]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_jsonl_error_line_uses_physical_file_location(tmp_path, newline):
    """空白行可以忽略，但坏记录诊断行号必须指向文件中的实际位置。"""
    path = tmp_path / "records.jsonl"
    lines = ["", json.dumps({"id": 1, "product_smiles": ["CCO"]}), "  ", "{broken"]
    path.write_bytes((newline.join(lines) + newline).encode())
    source = JsonlSource(path, max_records=2)
    try:
        assert len(source.records) == 1
        assert source.issues[0]["line"] == 4
        assert source.issues[0]["code"] == "invalid_record"
    finally:
        source.close()
