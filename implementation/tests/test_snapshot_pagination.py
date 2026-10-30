"""分页快照回归：最新结果变化和服务重启不能让旧游标串到另一份结果。"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.application.search import search
from reaction_reference.domain.models import RunState
from reaction_reference.interfaces.api import create_app


@pytest.mark.parametrize("restart", [False, True])
def test_cursor_keeps_original_snapshot_after_latest_changes(
    settings, source, request_factory, restart
):
    """发布新快照后，旧游标和指定快照导出仍读取旧内容；固定密钥使重启后行为一致。"""
    settings = settings.model_copy(update={"cursor_secret": "pagination-test-key"})
    request = request_factory(options={"include_proposals": False}, budget={"max_tasks": 100})
    run_id = uuid.uuid4().hex
    package = search(request, source, run_id=run_id)
    assert len(package.displayed_reference_ids) >= 2
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=run_id,
        lifecycle="running",
        request=request,
        created_at=now,
        updated_at=now,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        store = app.state.client.manager.store
        store.create(state)
        store.save_package(package)
        first = client.get(f"/v1/search-runs/{run_id}/results", params={"limit": 1}).json()
        assert first["snapshot_id"] == package.snapshot_id
        assert first["results"][0]["item"]["id"] == package.displayed_reference_ids[0]
        cursor = first["next_cursor"]
        assert cursor
        latest = package.model_copy(
            update={
                "snapshot_id": "f" * 24,
                "results": [],
                "displayed_reference_ids": [],
                "statistics": {"display_items": 0},
                "summary": "[]",
            }
        )
        store.save_package(latest)
        store.update(
            state.model_copy(update={"lifecycle": "succeeded", "snapshot_id": latest.snapshot_id}),
            state.revision,
        )
        if not restart:
            assert_snapshot_pages(client, run_id, cursor, package, latest.snapshot_id)
    if restart:
        with TestClient(create_app(settings)) as client:
            assert_snapshot_pages(client, run_id, cursor, package, latest.snapshot_id)


def assert_snapshot_pages(client, run_id, cursor, original, latest_snapshot_id):
    """核对旧游标、新首屏及指定快照导出各自绑定正确的不可变内容。"""
    second = client.get(f"/v1/search-runs/{run_id}/results", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200, second.text
    assert second.json()["snapshot_id"] == original.snapshot_id
    assert second.json()["results"][0]["item"]["id"] == original.displayed_reference_ids[1]
    assert second.json()["statistics"] == original.statistics
    current = client.get(f"/v1/search-runs/{run_id}/results").json()
    assert current["snapshot_id"] == latest_snapshot_id and not current["results"]
    exported = client.get(
        f"/v1/search-runs/{run_id}/package", params={"snapshot": original.snapshot_id}
    )
    assert exported.status_code == 200
    assert exported.json() == original.model_dump(mode="json")
