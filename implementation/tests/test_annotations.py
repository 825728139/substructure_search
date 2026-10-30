"""回归测试：审核证据的来源哈希与合成来源边界。"""

import json

from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.chemistry.structures import digest
from reaction_reference.evidence.claims import evidence_for
from reaction_reference.ports.sources import CandidatePage


def annotation(record, **updates):
    """构造绑定记录哈希的测试审核行；updates 用于模拟哈希错误或特定审核输入。"""
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
    """确认来源哈希不符时拒绝旧审核，原记录保留并记录局部问题。"""
    path = tmp_path / "annotation.jsonl"
    path.write_text(json.dumps(annotation(amide, expected_source_hash="f" * 64)) + "\n")
    wrapper = AnnotatedSource(source, path)
    assert wrapper._apply(amide) == amide
    assert wrapper.issues[-1]["code"] == "evidence_overlay_source_hash_mismatch"


def test_review_does_not_erase_synthetic_origin(source, amide, tmp_path):
    """确认有效审核也不能把合成示例升级为真实文献制备证据。"""
    path = tmp_path / "annotation.jsonl"
    path.write_text(json.dumps(annotation(amide)) + "\n")
    result = AnnotatedSource(source, path)._apply(amide)
    assert result.source.synthetic
    assert not evidence_for(result, result.materials[-1])[0]
    assert result.raw["evidence_review"]["reviewer"] == "test-only"


def test_overlay_accepts_the_declared_minimum_source_protocol(amide, tmp_path):
    """审核装饰器必须支持已声明的最小来源协议，不能强制访问协议外的可选能力属性。"""

    class MinimalSource:
        """仅提供来源端口要求的方法和字段，不声明可选选择阶段或 I/O 提示。"""

        snapshot_id = "minimal-source"
        issues = []
        closed = False

        def candidate_page(self, *args, **kwargs):
            """提供一个合法空页，验证包装后仍可正常委托查询。"""
            return CandidatePage([], None, True, True, "test")

        def hydrate(self, record):
            """完整来源无需额外加载，返回原记录。"""
            return record

        def close(self):
            """记录调用方释放了来源。"""
            self.closed = True

    path = tmp_path / "review.jsonl"
    path.write_text(json.dumps(annotation(amide, observations=[])) + "\n", encoding="utf-8")
    source = MinimalSource()
    wrapper = AnnotatedSource(source, path)
    try:
        assert not wrapper.candidate_page(None, "product", 0, 10, "CCO").items
        assert wrapper.hydrate(amide).observations == []
    finally:
        wrapper.close()
    assert source.closed
