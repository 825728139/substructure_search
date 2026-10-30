"""审核证据覆盖适配器：按精确来源哈希绑定产品观察、操作范围及实际输入引用。"""

from pathlib import Path

from pydantic import Field

from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import EventScope, Model, Observation


class EvidenceAnnotation(Model):
    """单条人工审核补丁；绑定来源哈希和审核人/日期，仅覆盖显式提供的字段，不能修改来源身份。"""

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
    """来源装饰器：保持原候选选择，命中后的 hydrate 再附加经哈希核对的审核信息。"""

    def __init__(self, source, path):
        """读取有限 JSONL 审核文件并建立 record_id 索引，继承被包装来源的能力。

        文件最多 32 MiB，重复审核记录 ID 或契约错误会拒绝加载；审核文件内容参与新来源快照摘要。
        """
        self.source = source
        # 能力提示不是最小来源协议的必需字段，缺省值与检索编排器保持一致。
        self.max_selection_stage = getattr(source, "max_selection_stage", 2)
        self.hydration_requires_io = getattr(source, "hydration_requires_io", False)
        self.selection_policy = getattr(
            source, "selection_policy", "source_declared_bounded_selection"
        )
        self.selection_failure_fallback = getattr(source, "selection_failure_fallback", False)
        self.issues = source.issues
        with Path(path).open("rb") as stream:
            payload = stream.read(32 * 1024 * 1024 + 1)
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
        """将审核信息应用到一个来源记录的副本并缓存结果。

        来源哈希必须一致，输入证据必须指向实际反应物实例并有引用。仅覆盖明确提供的字段，未提供的观察和步骤信息保留；显式空列表可撤除旧观察。失败时返回原记录，合成来源标记始终保留。
        输入引用按材料 ID 局部合并；空映射不撤销已有使用事实或引用。审核人、日期和补丁哈希描述本次更新。
        """
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
                citation.strip() for citation in annotation.actual_input_evidence.values()
            ):
                raise ValueError(
                    "Input evidence must refer to actual reactant instances and contain citations"
                )
            data = record.model_dump()
            supplied = annotation.model_dump(exclude_unset=True)
            for field in ("observations", "event_scope", "documented_step_ref", "step_count"):
                if field in supplied:
                    data[field] = supplied[field]
            for material in data["materials"]:
                if material["instance_id"] in annotation.actual_input_evidence:
                    material["actual_input"] = True
            previous_review = data["raw"].get("evidence_review")
            previous_inputs = (
                previous_review.get("input_evidence") if isinstance(previous_review, dict) else None
            )
            data["raw"]["evidence_review"] = {
                "reviewer": annotation.reviewer,
                "reviewed_at": annotation.reviewed_at,
                "input_evidence": {
                    **(previous_inputs if isinstance(previous_inputs, dict) else {}),
                    **annotation.actual_input_evidence,
                },
                "annotation_hash": digest(supplied, 64),
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
        """原样委托底层来源分页，不在候选召回时提前给产品赋予审核证据。"""
        return self.source.candidate_page(*args, **kwargs)

    def hydrate(self, record):
        """先委托底层加载详情，再按记录哈希附加审核信息，返回新的或原有记录。"""
        return self._apply(self.source.hydrate(record))

    def close(self):
        """关闭被包装来源，其连接与缓存仍归原适配器管理。"""
        self.source.close()
