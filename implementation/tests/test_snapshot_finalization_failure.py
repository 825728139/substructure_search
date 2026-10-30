"""收尾持久化回归：中断快照无法发布时仍应保存失败终态，避免任务永久显示运行中。"""

import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.application.search import search
from reaction_reference.domain.models import RunState
from reaction_reference.interfaces.api import create_app


@pytest.mark.parametrize("requested", ["cancelled", "failed"])
@pytest.mark.parametrize("failure", [None, "snapshot", "pointer"])
def test_snapshot_finalization_failure_does_not_leave_a_running_task(
    settings, source, request_factory, monkeypatch, requested, failure
):
    """只阻断快照或指针写入，验证可写状态仍终结、默认读取明确拒绝、旧包不改且重启稳定。"""
    request = request_factory(
        options={"exhaustive_fixture": True, "include_usage": False, "include_proposals": False},
        budget={"max_tasks": 100},
    )
    original = search(request, source)
    assert original.coverage_state == "complete" and original.results
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=original.run_id,
        lifecycle="running",
        request=request,
        created_at=now,
        updated_at=now,
    )
    with TestClient(create_app(settings)) as client:
        manager = client.app.state.client.manager
        store = manager.store
        store.create(state)
        store.save_package(original)
        path = settings.store_path / state.run_id / f"snapshot-{original.snapshot_id}.json"
        original_bytes = path.read_bytes()
        atomic = store._atomic

        def write(path, content):
            """模拟大快照或最新指针不可写，但较小的任务状态文件仍可保存。"""
            if (failure == "snapshot" and path.name.startswith("snapshot-")) or (
                failure == "pointer" and path.name == "latest.json"
            ):
                raise OSError("模拟中断快照发布失败")
            atomic(path, content)

        def supervision_error(*_):
            """模拟监督异常，确认实际执行兜底不会再次因收尾快照失败而遗留运行中状态。"""
            raise RuntimeError("模拟监督失败")

        monkeypatch.setattr(store, "_atomic", write)
        if requested == "failed":
            monkeypatch.setattr(manager, "_supervise", supervision_error)
            manager._execute(state, threading.Event())
        else:
            manager._finish(state.run_id, requested)
        terminal = store.load(state.run_id)
        assert terminal.lifecycle == ("failed" if failure else requested)
        if failure:
            assert terminal.snapshot_id is None
            assert terminal.error["code"] == "snapshot_finalization_failed"
            assert terminal.error["requested_lifecycle"] == requested
            assert terminal.error["snapshot_unavailable"] is True
            if requested == "failed":
                assert terminal.error["cause"]["code"] == "supervisor_failed"
        else:
            assert terminal.snapshot_id != original.snapshot_id
            assert store.package(state.run_id).coverage_state == "partial"
        assert path.read_bytes() == original_bytes
    with TestClient(create_app(settings)) as client:
        status = client.get(f"/v1/search-runs/{state.run_id}")
        assert status.status_code == 200
        assert status.json()["lifecycle"] == terminal.lifecycle
        if failure:
            assert status.json()["latest_snapshot_id"] is None
        for endpoint in ("results", "package"):
            response = client.get(f"/v1/search-runs/{state.run_id}/{endpoint}")
            assert response.status_code == (409 if failure else 200)
        retained = client.get(
            f"/v1/search-runs/{state.run_id}/package", params={"snapshot": original.snapshot_id}
        )
        assert retained.status_code == 200
        assert retained.json() == original.model_dump(mode="json")
