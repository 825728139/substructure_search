"""状态读取竞态回归：任务在两次读取之间终结，接口仍须报告已保存的失败终态。"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.application.search import search
from reaction_reference.domain.models import RunState
from reaction_reference.interfaces.api import create_app


@pytest.mark.parametrize("finish_between_reads", [False, True])
def test_status_reloads_terminal_state_when_snapshot_becomes_unavailable(
    settings, source, request_factory, monkeypatch, finish_between_reads
):
    """在状态读取后、快照读取前注入真实失败收尾，避免旧 running 状态导致错误的 409。"""
    request = request_factory(
        options={"exhaustive_fixture": True, "include_usage": False, "include_proposals": False},
        budget={"max_tasks": 100},
    )
    package = search(request, source)
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=package.run_id,
        lifecycle="running",
        request=request,
        created_at=now,
        updated_at=now,
    )
    with TestClient(create_app(settings)) as client:
        manager = client.app.state.client.manager
        store = manager.store
        store.create(state)
        store.save_package(package)
        read_package, atomic = store.package, store._atomic
        entered = False

        def fail_snapshot_write(path, content):
            """只阻断新的中断快照，状态文件仍可写入真实失败终态。"""
            if path.name.startswith("snapshot-"):
                raise OSError("模拟中断快照不可写")
            atomic(path, content)

        def read_after_transition(run_id, snapshot_id=None):
            """首次读取快照前执行失败收尾，精确控制并发写入相对于状态读取的位置。"""
            nonlocal entered
            if not entered:
                entered = True
                assert store.load(run_id).lifecycle == "running"
                if finish_between_reads:
                    manager._finish(run_id, "cancelled")
            return read_package(run_id, snapshot_id)

        monkeypatch.setattr(store, "_atomic", fail_snapshot_write)
        monkeypatch.setattr(store, "package", read_after_transition)
        response = client.get(f"/v1/search-runs/{state.run_id}")
        assert response.status_code == 200, response.text
        assert entered
        body = response.json()
        if finish_between_reads:
            assert body["lifecycle"] == "failed"
            assert body["error"]["code"] == "snapshot_finalization_failed"
            assert body["latest_snapshot_id"] is None and body["statistics"] == {}
            assert body["revision"] == store.load(state.run_id).revision
        else:
            assert body["lifecycle"] == "running" and body["error"] is None
            assert body["latest_snapshot_id"] == package.snapshot_id
        retained = client.get(
            f"/v1/search-runs/{state.run_id}/package", params={"snapshot": package.snapshot_id}
        )
        assert retained.status_code == 200
        assert retained.json() == package.model_dump(mode="json")
