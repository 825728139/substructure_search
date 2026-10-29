"""坏记录与损坏运行文件的隔离回归，避免局部问题阻断整个服务。"""

import json
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.adapters.run_store import FileRunStore, RevisionConflict
from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.domain.models import ReferencePackage, RunState
from reaction_reference.interfaces.api import create_app
from reaction_reference.interfaces.sdk import Client


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "bad row",
        None,
        12,
        False,
        {"id": 1, "product_smiles": False},
        {"id": 1, "product_smiles": 0},
        {"id": 1, "product_smiles": {}},
        {"id": 1, "details": False},
        {"id": 1, "details": []},
    ],
)
def test_invalid_row_is_isolated_and_valid_rows_survive(tmp_path, bad):
    """非法行类型和伪空数组必须记录问题，随后合法记录继续进入候选池。"""
    path = tmp_path / "source.jsonl"
    path.write_text(
        json.dumps(bad) + "\n" + json.dumps({"id": 2, "product_smiles": ["CCO"]}) + "\n"
    )
    source = JsonlSource(path)
    assert [record.id for record in source.records] == ["patent:2"]
    assert len(source.issues) == 1 and source.issues[0]["code"] == "invalid_record"
    assert len(source.candidates) == 1


@pytest.mark.parametrize(
    "fields", [{}, {"details": None, "product_smiles": None}, {"details": {}, "product_smiles": []}]
)
def test_optional_missing_or_null_source_fields_remain_supported(tmp_path, fields):
    """可选字段缺失、显式 null 和合法空数组仍按既有来源约定接受。"""
    path = tmp_path / "source.jsonl"
    path.write_text(json.dumps({"id": 1, **fields}) + "\n")
    source = JsonlSource(path)
    assert len(source.records) == 1 and not source.issues


def running_state(store, request):
    """保存可正常恢复的运行中状态。"""
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=uuid.uuid4().hex,
        lifecycle="running",
        request=request,
        created_at=now,
        updated_at=now,
    )
    store.create(state)
    return state


@pytest.mark.parametrize("corruption", ["invalid_json", "wrong_identity"])
def test_corrupt_run_is_reported_without_blocking_other_runs(settings, request_factory, corruption):
    """一个坏状态文件不能阻断另一有效任务的重启收尾，原坏文件保持原样。"""
    store = FileRunStore(settings.store_path)
    good = running_state(store, request_factory())
    bad = running_state(store, request_factory())
    path = settings.store_path / bad.run_id / "state.json"
    content = (
        "{broken"
        if corruption == "invalid_json"
        else bad.model_copy(update={"run_id": "f" * 32}).model_dump_json()
    )
    path.write_text(content)
    with Client(settings) as client:
        assert client.manager.store.load(good.run_id).lifecycle == "failed"
        assert any(issue["run_id"] == bad.run_id for issue in client.manager.store.recovery_issues)
        with pytest.raises(RevisionConflict):
            client.manager.store.load(bad.run_id)
    assert path.read_text() == content


def test_unrelated_directory_does_not_participate_in_recovery(settings, request_factory):
    """运行根目录下的备忘或备份目录不是任务，不能因同名状态文件阻断启动。"""
    store = FileRunStore(settings.store_path)
    state = running_state(store, request_factory())
    unrelated = settings.store_path / "notes"
    unrelated.mkdir()
    (unrelated / "state.json").write_text("unrelated")
    with Client(settings) as client:
        assert client.manager.store.load(state.run_id).lifecycle == "failed"
        assert not client.manager.store.recovery_issues
    assert (unrelated / "state.json").read_text() == "unrelated"


@pytest.mark.parametrize("broken", ["bad_pointer", "missing_snapshot", "bad_package"])
def test_corrupt_snapshot_does_not_block_terminal_recovery(settings, request_factory, broken):
    """状态有效但阶段包损坏时仍能标记任务中断，明确快照不可读且不改写原坏文件。"""
    store = FileRunStore(settings.store_path)
    state = running_state(store, request_factory())
    package = ReferencePackage(
        run_id=state.run_id,
        snapshot_id="a" * 24,
        target_smiles="CCO",
        target_atoms=[],
        source_snapshot="fixture",
        manifest={},
        families=[],
        results=[],
        coverage_state="partial",
    )
    store.save_package(package)
    directory = settings.store_path / state.run_id
    if broken == "bad_pointer":
        path = directory / "latest.json"
        path.write_text("[]")
    elif broken == "missing_snapshot":
        path = directory / "latest.json"
        path.write_text(json.dumps({"snapshot_id": "b" * 24}))
    else:
        path = directory / f"snapshot-{package.snapshot_id}.json"
        path.write_text("{broken")
    original = path.read_text()
    with Client(settings) as client:
        recovered = client.manager.store.load(state.run_id)
        assert recovered.lifecycle == "failed"
        assert recovered.error["snapshot_unavailable"] is True
        assert recovered.snapshot_id is None
        assert any(i["code"] == "unreadable_snapshot" for i in client.manager.store.recovery_issues)
    assert path.read_text() == original


def test_health_reports_isolated_recovery_issues(settings):
    """服务就绪响应应披露被隔离的旧任务，不能静默掩盖本地损坏。"""
    run_id = "a" * 32
    path = settings.store_path / run_id
    path.mkdir(parents=True)
    (path / "state.json").write_text("{broken")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["recovery_issues"] == [
            {"run_id": run_id, "code": "unreadable_run", "type": "RevisionConflict"}
        ]


def test_real_storage_io_failure_still_blocks_startup(settings, request_factory, monkeypatch):
    """真实权限或存储 I/O 错误不能当作单条数据损坏忽略，应明确阻止不可靠启动。"""
    store = FileRunStore(settings.store_path)
    running_state(store, request_factory())

    def unreadable(*args, **kwargs):
        """模拟文件系统拒绝读取。"""
        raise PermissionError("模拟运行目录不可读")

    monkeypatch.setattr(FileRunStore, "load", unreadable)
    with pytest.raises(PermissionError):
        Client(settings)
