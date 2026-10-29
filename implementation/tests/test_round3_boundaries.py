"""第三轮复审：部分审核、异常条件、请求校验与初始化资源释放。"""

import json

import pytest

from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.adapters.run_store import FileRunStore
from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import Conditions, LabContext, ReactionAnalysis, Reference
from reaction_reference.interfaces.sdk import Client
from reaction_reference.ranking.engine import lab_fit, rank_references


def overlay(source, record, path, **updates):
    """应用只包含调用方提供字段的审核补丁。"""
    data = {
        "record_id": record.id,
        "expected_source_hash": digest(record.model_dump(), 64),
        "reviewer": "审查人员",
        "reviewed_at": "2026-10-29",
        **updates,
    }
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    return AnnotatedSource(source, path)._apply(record)


def test_partial_input_review_preserves_existing_outcome_and_step(source, amide, tmp_path):
    """仅审核实际输入时，已有产品观察和步骤依据不应被默认空值删除。"""
    materials = [
        m.model_copy(update={"actual_input": None}) if m.role == "reactant" else m
        for m in amide.materials
    ]
    record = amide.model_copy(update={"materials": materials})
    reactant = next(m for m in materials if m.role == "reactant")
    result = overlay(
        source,
        record,
        tmp_path / "review.jsonl",
        actual_input_evidence={reactant.instance_id: "实施例1原料段"},
    )
    assert result.observations == record.observations
    assert result.event_scope == record.event_scope
    assert result.documented_step_ref == record.documented_step_ref
    assert result.step_count == record.step_count
    assert (
        next(m for m in result.materials if m.instance_id == reactant.instance_id).actual_input
        is True
    )


def test_omitted_review_field_differs_from_explicit_clear(source, amide, tmp_path):
    """未提供产品观察与明确清空观察是不同操作，内容和审核哈希都应体现区别。"""
    preserved = overlay(source, amide, tmp_path / "preserved.jsonl")
    cleared = overlay(source, amide, tmp_path / "cleared.jsonl", observations=[])
    assert preserved.observations == amide.observations and preserved.observations
    assert cleared.observations == []
    assert (
        preserved.raw["evidence_review"]["annotation_hash"]
        != cleared.raw["evidence_review"]["annotation_hash"]
    )


def reference(record, name):
    """构造方法和证据资格相同的参考，隔离操作条件对排序的影响。"""
    return Reference(
        id=name,
        record=record,
        material=record.materials[-1],
        family_ids=[],
        layers=["whole"],
        witnesses=[],
        analysis=ReactionAnalysis(state="unknown"),
        molecular_weight=149.0,
    )


def test_inverted_temperature_range_is_not_a_capability_pass(amide):
    """下限高于上限的来源温度范围不能被用于判定实验能力已满足。"""
    record = amide.model_copy(
        update={"conditions": Conditions(temperature_min_c=26, temperature_max_c=24)}
    )
    fit, reasons = lab_fit(reference(record, "bad"), LabContext(max_temperature_c=25))
    assert fit == "unknown"
    assert "inverted_temperature_range" in reasons


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize(
    "conditions,reason",
    [
        (
            Conditions(temperature_min_c=26, temperature_max_c=24, duration_seconds=1),
            "inverted_temperature_range",
        ),
        (
            Conditions(temperature_min_c=25, temperature_max_c=25, duration_seconds=-30),
            "negative_duration",
        ),
    ],
)
def test_invalid_conditions_do_not_receive_easy_operation_priority(
    amide, conditions, reason, cached
):
    """倒置温度和负时长应保持异常/未知，不得优于有完整可信数值的同等参考。"""
    invalid = reference(amide.model_copy(update={"conditions": conditions}), "invalid")
    if cached:
        invalid = invalid.model_copy(
            update={"ranking_features": {"operation_equipment": {"limitations": ["existing_fact"]}}}
        )
    valid = reference(
        amide.model_copy(
            update={
                "conditions": Conditions(
                    temperature_min_c=50, temperature_max_c=50, duration_seconds=60
                )
            }
        ),
        "valid",
    )
    ranked, _ = rank_references([invalid, valid], profile="process_reference")
    assert ranked[0].id == "valid"
    bad = next(r for r in ranked if r.id == "invalid")
    assert reason in bad.ranking_features["operation_equipment"]["limitations"]
    if cached:
        assert invalid.ranking_features["operation_equipment"]["limitations"] == ["existing_fact"]


def test_subzero_temperature_and_zero_duration_remain_valid(amide):
    """正常低温和零时长不应被当作倒置范围或负时长处理。"""
    record = amide.model_copy(
        update={
            "conditions": Conditions(
                temperature_min_c=-10, temperature_max_c=-10, duration_seconds=0
            )
        }
    )
    fit, _ = lab_fit(
        reference(record, "cold"), LabContext(min_temperature_c=-20, max_temperature_c=20)
    )
    assert fit == "pass"


def test_constructor_failure_releases_coordinator_lock(settings, monkeypatch):
    """初始化异常被调用方保留时，目录锁仍需立即释放，允许修复后再次初始化。"""
    original = FileRunStore.recover_interrupted

    def fail(_):
        """模拟读取遗留状态时的初始化错误。"""
        raise ValueError("模拟恢复失败")

    monkeypatch.setattr(FileRunStore, "recover_interrupted", fail)
    with pytest.raises(ValueError, match="模拟恢复失败") as error:
        Client(settings)
    assert error.value.__traceback__ is not None
    monkeypatch.setattr(FileRunStore, "recover_interrupted", original)
    with Client(settings):
        pass


def test_invalid_exclusion_is_rejected_before_creating_job(settings, request_factory, monkeypatch):
    """无效排除结构必须在提交入口报错，不能先保存和调度一个必然失败的任务。"""
    with Client(settings) as client:

        def unexpected_submission(*args, **kwargs):
            """一旦越过请求校验进入调度，立即暴露回归。"""
            raise AssertionError("无效请求进入了执行队列")

        monkeypatch.setattr(client.manager._executor, "submit", unexpected_submission)
        request = request_factory(lab_context=LabContext(excluded_material_smiles=["invalid("]))
        with pytest.raises(ValueError, match="[Ee]xcluded"):
            client.manager.submit(request)
        assert not list(settings.store_path.glob("*/state.json"))


def test_rerank_records_current_implementation_without_erasing_origin(
    settings, request_factory, source
):
    """旧资料重排后须同时保留检索版本和本次排序版本，避免把新结果归给旧代码。"""
    from datetime import UTC, datetime

    from reaction_reference.application.search import search
    from reaction_reference.domain.models import RerankRequest, RunState
    from reaction_reference.rules import code_fingerprint

    with Client(settings) as client:
        request = request_factory(options={"include_proposals": False, "include_usage": False})
        package = search(request, source)
        package = package.model_copy(
            update={
                "manifest": {**package.manifest, "implementation_hash": "previous-implementation"},
                "snapshot_id": digest([package.snapshot_id, "previous-implementation"]),
            }
        )
        now = datetime.now(UTC).isoformat()
        state = RunState(
            run_id=package.run_id,
            lifecycle="succeeded",
            request=request,
            created_at=now,
            updated_at=now,
            snapshot_id=package.snapshot_id,
        )
        client.manager.store.create(state)
        client.manager.store.save_package(package)
        result = client.rerank(state.run_id, RerankRequest())
        reranked = client.manager.store.package(result.run_id)
        assert reranked.manifest["implementation_hash"] == "previous-implementation"
        assert reranked.manifest["rerank_implementation_hash"] == code_fingerprint()
        assert reranked.manifest["reranked_at"] == result.created_at
