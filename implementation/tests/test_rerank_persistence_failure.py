"""同步重排持久化回归：创建和终态更新失败也须收尾，清理异常不能替换最初错误。"""

from datetime import UTC, datetime

import pytest

from reaction_reference.application.search import search
from reaction_reference.domain.models import RerankRequest, RunState
from reaction_reference.interfaces.sdk import Client


@pytest.mark.parametrize("failure", [None, "create_before", "create_after", "terminal", "cleanup"])
def test_rerank_persistence_boundaries_finish_or_preserve_original_error(
    settings, source, request_factory, monkeypatch, failure
):
    """对创建、成功终态及失败清理注入异常，验证可写派生任务终结且原任务不被修改。"""
    request = request_factory(
        options={"exhaustive_fixture": True, "include_usage": False, "include_proposals": False},
        budget={"max_tasks": 100},
    )
    package = search(request, source)
    now = datetime.now(UTC).isoformat()
    parent = RunState(
        run_id=package.run_id,
        lifecycle="succeeded",
        request=request,
        created_at=now,
        updated_at=now,
        snapshot_id=package.snapshot_id,
    )
    original_error = OSError("首次重排持久化失败")
    cleanup_error = OSError("失败终态也无法写入")
    created = []
    injected = False
    with Client(settings) as client:
        store = client.manager.store
        store.create(parent)
        store.save_package(package)
        parent_path = settings.store_path / parent.run_id / "state.json"
        parent_bytes = parent_path.read_bytes()
        create, save, update = store.create, store.save_package, store.update

        def create_run(state):
            """可在创建状态前或状态已写入后抛错，模拟不同持久化失败边界。"""
            created.append(state.run_id)
            if failure == "create_before":
                raise original_error
            create(state)
            if failure == "create_after":
                raise original_error

        def save_package(derived):
            """失败清理场景先让快照保存失败，原错误应始终返回调用方。"""
            if failure == "cleanup":
                raise original_error
            save(derived)

        def update_run(state, revision):
            """成功终态只失败一次；清理场景则阻断失败终态，确认异常不会被替换。"""
            nonlocal injected
            if failure == "terminal" and state.lifecycle == "succeeded" and not injected:
                injected = True
                raise original_error
            if failure == "cleanup" and state.lifecycle == "failed":
                raise cleanup_error
            return update(state, revision)

        with monkeypatch.context() as fault:
            fault.setattr(store, "create", create_run)
            fault.setattr(store, "save_package", save_package)
            fault.setattr(store, "update", update_run)
            if failure:
                with pytest.raises(OSError) as error:
                    client.rerank(parent.run_id, RerankRequest())
                assert error.value is original_error
            else:
                result = client.rerank(parent.run_id, RerankRequest())
                assert result.lifecycle == "succeeded"
        assert len(created) == 1
        derived_id = created[0]
        assert parent_path.read_bytes() == parent_bytes
        assert store.package(parent.run_id).model_dump(mode="json") == package.model_dump(
            mode="json"
        )
        if failure == "create_before":
            assert not (settings.store_path / derived_id).exists()
        else:
            state = store.load(derived_id)
            assert state.lifecycle == (
                "running" if failure == "cleanup" else "failed" if failure else "succeeded"
            )
            if failure in ("create_after", "terminal"):
                assert state.error["code"] == "rerank_persistence_failed"
            if failure == "terminal":
                retained = store.package(derived_id)
                assert retained.coverage_state == "partial" and "failed" in retained.stop_reasons
    if failure != "create_before":
        with Client(settings) as restarted:
            recovered = restarted.manager.store.load(derived_id)
            assert recovered.lifecycle == ("failed" if failure else "succeeded")
            if failure == "cleanup":
                assert recovered.error["code"] == "coordinator_restarted"
