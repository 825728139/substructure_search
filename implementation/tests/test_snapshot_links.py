"""结果引用回归：损坏快照不得通过分页、导出或重排传播，失败写入不得推进最新指针。"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.adapters.run_store import FileRunStore, RevisionConflict
from reaction_reference.application.search import search
from reaction_reference.domain.models import RunState
from reaction_reference.interfaces.api import create_app


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "duplicate_reference",
        "duplicate_proposal",
        "missing_display_reference",
        "missing_display_proposal",
        "duplicate_display_reference",
        "duplicate_display_proposal",
        "orphan_proposal",
    ],
)
def test_corrupt_snapshot_links_are_rejected_by_read_endpoints(
    settings, source, request_factory, damage
):
    """真实检索快照的引用损坏时统一返回冲突，不能报不存在、重复卡片或导出错配内容。"""
    request = request_factory(budget={"max_tasks": 100})
    package = search(request, source)
    assert package.results and package.proposals
    assert package.displayed_reference_ids and package.displayed_proposal_ids
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=package.run_id,
        lifecycle="succeeded",
        request=request,
        created_at=now,
        updated_at=now,
        snapshot_id=package.snapshot_id,
    )
    with TestClient(create_app(settings)) as client:
        store = client.app.state.client.manager.store
        store.create(state)
        store.save_package(package)
        content = package.model_dump(mode="json")
        if damage in ("duplicate_reference", "duplicate_proposal"):
            pool = "results" if damage == "duplicate_reference" else "proposals"
            content[pool].append(content[pool][0])
        elif damage in ("missing_display_reference", "missing_display_proposal"):
            pool = (
                "displayed_reference_ids"
                if damage == "missing_display_reference"
                else "displayed_proposal_ids"
            )
            content[pool][0] = "missing"
        elif damage in ("duplicate_display_reference", "duplicate_display_proposal"):
            pool = (
                "displayed_reference_ids"
                if damage == "duplicate_display_reference"
                else "displayed_proposal_ids"
            )
            content[pool].append(content[pool][0])
        elif damage == "orphan_proposal":
            content["proposals"][0]["source_reference_id"] = "missing"
        path = settings.store_path / package.run_id / f"snapshot-{package.snapshot_id}.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        expected = 200 if damage is None else 409
        for endpoint in ("results", "package"):
            response = client.get(f"/v1/search-runs/{package.run_id}/{endpoint}")
            assert response.status_code == expected, (endpoint, response.text)
        response = client.post(f"/v1/search-runs/{package.run_id}/rerank", json={})
        assert response.status_code == (202 if damage is None else 409), response.text


def test_invalid_copied_snapshot_cannot_replace_latest(settings, source, request_factory):
    """绕过模型构造的复制更新也须检查引用，写入失败后最新快照仍可完整读取。"""
    package = search(request_factory(budget={"max_tasks": 100}), source)
    store = FileRunStore(settings.store_path)
    (settings.store_path / package.run_id).mkdir()
    store.save_package(package)
    invalid = package.model_copy(
        update={"snapshot_id": "f" * 24, "displayed_reference_ids": ["missing"]}
    )
    with pytest.raises(RevisionConflict):
        store.save_package(invalid)
    assert store.package(package.run_id).model_dump(mode="json") == package.model_dump(mode="json")
    assert not (
        settings.store_path / package.run_id / f"snapshot-{invalid.snapshot_id}.json"
    ).exists()
