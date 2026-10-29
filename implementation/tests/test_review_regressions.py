"""整体审查发现的化学约束、证据、来源与执行状态回归。"""

import io
import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.adapters.run_store import FileRunStore
from reaction_reference.adapters.sources import JsonlSource, PostgresSource
from reaction_reference.application.search import search
from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import digest, parse
from reaction_reference.domain.models import (
    LabContext,
    Material,
    Observation,
    QueryFamily,
    RConstraint,
    ReactionAnalysis,
    Reference,
    RunState,
)
from reaction_reference.evaluation.runner import MaskedSource
from reaction_reference.evidence.claims import evidence_for
from reaction_reference.interfaces.api import create_app
from reaction_reference.interfaces.sdk import Client
from reaction_reference.ranking.engine import lab_fit
from reaction_reference.retrieval.planner import _core_smarts, directed_family


def core_family(target, atom=1):
    """构造只固定中心原子的查询，暴露重复支链与边界键约束问题。"""
    smarts, ids = _core_smarts(target, [atom], [])
    return QueryFamily(
        id="center",
        layer="core",
        core_smarts=smarts,
        target_atoms=ids,
        rule_id="regression",
        rule_version="1",
        description="固定中心原子的受控查询",
    )


def reference_for(record):
    """构造仅用于证据和实验适配判断的产品参考，不虚构结构见证。"""
    product = next(m for m in record.materials if m.role == "product")
    return Reference(
        id="reference",
        record=record,
        material=product,
        family_ids=[],
        layers=[],
        witnesses=[],
        analysis=ReactionAnalysis(state="unknown"),
        molecular_weight=1.0,
    )


@pytest.mark.parametrize("smiles", ["CC(C)O", "CN(C)C"])
def test_repeated_r_blocks_cover_the_same_target_completely(smiles):
    """同一核心外的重复甲基必须一一对应，目标自身的联合覆盖应为百分之百。"""
    target = parse(smiles)
    result = match_family(core_family(target), target, target, "same")
    assert result.state == "match"
    assert max(w.target_atom_coverage for w in result.witnesses) == 1
    for witness in result.witnesses:
        mapped = [source for _, source in witness.target_to_source]
        assert len(mapped) == len(set(mapped))


def test_directed_r_constraints_preserve_multiplicity():
    """目标要求两个相同甲基时，只有一个甲基的候选不能重复使用同一支链满足条件。"""
    target = parse("CC(C)O")
    family = directed_family(core_family(target), target, {0})
    assert match_family(family, parse("CCO"), target, "missing-methyl").state == "no_match"
    assert match_family(family, target, target, "same").state == "match"


@pytest.mark.parametrize("smiles", ["C=C", "C#C"])
def test_alkyl_constraint_checks_the_attachment_bond(smiles):
    """烷基的核心连接键必须为单键，不能把双键或三键连接的碳误判为烷基。"""
    target = parse("CC")
    family = core_family(target, 0).model_copy(
        update={
            "r_constraints": [RConstraint(position=0, requirement="required", category="alkyl")],
        }
    )
    assert match_family(family, parse(smiles), target, "unsaturated").state == "no_match"
    assert match_family(family, target, target, "alkyl").state == "match"


@pytest.mark.parametrize("negative", ["failed", "recovered", "conflict"])
def test_enriched_outcome_cannot_override_conflicting_observations(amide, negative):
    """同一产品有富集与失败、普通回收或冲突证据时，不能计算合格获得命中。"""
    product = next(m for m in amide.materials if m.role == "product")
    record = amide.model_copy(
        update={
            "source": amide.source.model_copy(update={"synthetic": False}),
            "observations": [
                Observation(
                    product_instance_id=product.instance_id,
                    result=kind,
                    evidence_text="同一产品的明确报告",
                    source_location="实施例1",
                )
                for kind in ("enriched", negative)
            ],
        }
    )
    prepared, obtained, used, claims = evidence_for(record, product)
    assert not any((prepared, obtained, used))
    assert {c.predicate for c in claims} == {"enriched", negative}


def test_dirty_material_does_not_hide_known_excluded_material(amide):
    """某个材料解析失败时，仍须保留另一个已识别材料触发的明确禁用结论。"""
    record = amide.model_copy(
        update={
            "materials": amide.materials
            + [
                Material(instance_id="excluded", role="solvent", smiles="CCO"),
                Material(instance_id="dirty", role="reagent", smiles="invalid("),
            ]
        }
    )
    fit, reasons = lab_fit(reference_for(record), LabContext(excluded_material_smiles=["CCO"]))
    assert fit == "fail"
    assert "explicitly_excluded_material" in reasons
    assert "material_identity_unknown" in reasons


def test_whitespace_input_citation_does_not_create_use_evidence(source, amide, tmp_path):
    """只有空白字符的审核引用不能把未知投料升级为确认使用。"""
    materials = [m.model_copy(update={"actual_input": None}) for m in amide.materials]
    record = amide.model_copy(update={"materials": materials})
    reactant = next(m for m in materials if m.role == "reactant")
    annotation = {
        "record_id": record.id,
        "expected_source_hash": digest(record.model_dump(), 64),
        "reviewer": "审查人员",
        "reviewed_at": "2026-10-29",
        "actual_input_evidence": {reactant.instance_id: " \t\n"},
    }
    path = tmp_path / "evidence.jsonl"
    path.write_text(json.dumps(annotation) + "\n")
    overlay = AnnotatedSource(source, path)
    result = overlay._apply(record)
    assert (
        next(m for m in result.materials if m.instance_id == reactant.instance_id).actual_input
        is None
    )
    assert overlay.issues[-1]["code"] == "invalid_evidence_overlay"


def test_masking_uses_validated_products_and_skips_dirty_ones(amide, tmp_path):
    """脏产品先于有效目标产品时，评测屏蔽仍应排除整条目标记录而非崩溃。"""
    product = next(m for m in amide.materials if m.role == "product")
    record = amide.model_copy(
        update={
            "materials": [
                Material(instance_id="dirty-product", role="product", smiles="invalid("),
                *amide.materials,
            ]
        }
    )
    path = tmp_path / "dirty.jsonl"
    path.write_text(record.model_dump_json() + "\n")
    source = JsonlSource(path)
    masked = MaskedSource(source, parse(product.smiles))
    assert masked.excluded == {record.id}
    assert source.issues


def test_source_index_capability_uses_indexed_columns():
    """索引名称提到产品列不能冒充该列已建索引，必须匹配实际索引键列。"""
    source = PostgresSource.__new__(PostgresSource)
    source._indexes = {"reactants_mol", "product_fp"}
    assert not source._has_index("products_mol")
    assert source._has_index("reactants_mol")
    assert source._has_index("product_fp")
    source._indexes = {
        "CREATE INDEX products_mol_gist ON reaction.reactions USING gist (reactants_mol)"
    }
    assert not source._has_index("products_mol")


@pytest.mark.parametrize("overlay", [False, True])
def test_source_files_are_read_with_a_memory_bound(tmp_path, monkeypatch, source, overlay):
    """来源和证据文件必须先限定读取字节数，不能把整个大文件读入内存后才检查大小。"""
    path = tmp_path / "bounded.jsonl"
    limit = (32 if overlay else 256) * 1024 * 1024

    class BoundedReader(io.BytesIO):
        """模拟拒绝无界读取的文件，不分配超大测试数据。"""

        def read(self, size=-1):
            """允许在声明大小上限内读取并留出一个溢出哨兵字节。"""
            assert 0 < size <= limit + 1
            return super().read(size)

    original = Path.open

    def open_file(self, *args, **kwargs):
        """只替换被检查的输入路径，其余文件读取仍使用真实文件。"""
        return BoundedReader() if self == path else original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    if overlay:
        AnnotatedSource(source, path)
    else:
        JsonlSource(path)


def saved_running_package(settings, request_factory, source):
    """保存仍在运行但已有完整范围快照的任务，模拟发布包后进程异常退出。"""
    request = request_factory(
        options={
            "exhaustive_fixture": True,
            "include_usage": False,
            "include_proposals": False,
            "directed_followups": False,
        },
        budget={"max_tasks": 100},
    )
    run_id = uuid.uuid4().hex
    package = search(request, source, run_id=run_id)
    assert package.coverage_state == "complete"
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=run_id, lifecycle="running", request=request, created_at=now, updated_at=now
    )
    store = FileRunStore(settings.store_path)
    store.create(state)
    store.save_package(package)
    return state, package


def test_restart_marks_retained_snapshot_partial(settings, request_factory, source):
    """重启恢复必须同步标记保留快照的范围和停止原因，并保留原快照不变。"""
    state, original = saved_running_package(settings, request_factory, source)
    with Client(settings) as client:
        restored = client.manager.store.load(state.run_id)
        package = client.manager.store.package(state.run_id)
        assert restored.lifecycle == "failed"
        assert package.coverage_state == "partial"
        assert "coordinator_restarted" in package.stop_reasons
        assert restored.snapshot_id == package.snapshot_id != original.snapshot_id
        assert (
            client.manager.store.package(state.run_id, original.snapshot_id).coverage_state
            == "complete"
        )


def test_supervisor_exception_marks_retained_snapshot_partial(
    settings, request_factory, source, monkeypatch
):
    """监督过程自身异常时，兜底失败处理也必须更新已经保存的快照范围。"""
    with Client(settings) as client:
        state, original = saved_running_package(settings, request_factory, source)

        def fail_supervision(*_):
            """模拟阶段包落盘后监督器自身发生异常。"""
            raise RuntimeError("supervisor fault")

        monkeypatch.setattr(client.manager, "_supervise", fail_supervision)
        client.manager._execute(state, threading.Event())
        package = client.manager.store.package(state.run_id)
        assert package.coverage_state == "partial"
        assert "failed" in package.stop_reasons
        assert package.snapshot_id != original.snapshot_id


def test_non_ascii_authorization_is_rejected_without_server_error(settings):
    """错误令牌包含非 ASCII 字符时应返回未认证，不能触发字符串比较的服务器异常。"""
    configured = settings.model_copy(update={"api_token": "test-token"})
    with TestClient(create_app(configured)) as client:
        response = client.get("/v1/capabilities", headers=[(b"authorization", b"Bearer \xff")])
        assert response.status_code == 401


@pytest.mark.parametrize("write_fails", [False, True])
def test_rerank_succeeds_only_after_snapshot_is_saved(
    settings, request_factory, source, monkeypatch, write_fails
):
    """重排必须在快照落盘后才标记成功；写盘失败时任务不能留下虚假的成功状态。"""
    from reaction_reference.domain.models import RerankRequest

    with Client(settings) as client:
        state, _ = saved_running_package(settings, request_factory, source)
        store = client.manager.store
        save = store.save_package
        observed = []

        def save_snapshot(package):
            """记录落盘前的任务状态，并可模拟文件写入失败。"""
            observed.append(store.load(package.run_id))
            if write_fails:
                raise OSError("模拟快照写盘失败")
            save(package)

        monkeypatch.setattr(store, "save_package", save_snapshot)
        if write_fails:
            with pytest.raises(OSError):
                client.rerank(state.run_id, RerankRequest())
        else:
            result = client.rerank(state.run_id, RerankRequest())
            assert result.lifecycle == "succeeded"
            assert store.package(result.run_id).snapshot_id == result.snapshot_id
        assert observed[0].lifecycle == "running"
        assert observed[0].snapshot_id is None
        terminal = store.load(observed[0].run_id)
        assert terminal.lifecycle == ("failed" if write_fails else "succeeded")


def test_progress_snapshot_does_not_complete_unstarted_phases(source, request_factory):
    """初始阶段包不能把尚未开始的输入检索或替换回放标记为已完成。"""
    snapshots = []
    package = search(
        request_factory(budget={"max_tasks": 100}), source, on_progress=snapshots.append
    )
    first = snapshots[0]
    assert first.statistics["received_candidates"] == 0
    assert first.feature_status["usage_lookup"].state == "not_evaluated"
    assert first.feature_status["single_reactant_transfer"].state == "not_evaluated"
    assert package.feature_status["usage_lookup"].state in ("completed", "partial")
    assert package.feature_status["single_reactant_transfer"].state in ("completed", "partial")
