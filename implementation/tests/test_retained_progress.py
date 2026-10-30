"""真实进程中断回归：有结果快照后取消、超时和关闭，仍须保留证据并释放子进程。"""

import multiprocessing
import os
import threading
import time

import pytest

from reaction_reference.adapters import execution
from reaction_reference.application.search import search
from reaction_reference.bootstrap import open_source
from reaction_reference.domain.models import SearchRequest
from reaction_reference.interfaces.sdk import Client
from reaction_reference.settings import Settings


def retained_progress_worker(config, request_json, run_id, output):
    """生成真实检索资料后仅发送阶段包并等待中断，隔离快照收尾与化学计算速度。

    受控工作进程不发送完成消息；父进程必须主动终止它，不能靠正常退出让测试通过。
    """
    request = SearchRequest.model_validate_json(request_json)
    source = open_source(Settings(**config), exhaustive=request.options.exhaustive_fixture)
    try:
        package = search(request, source, run_id=run_id)
    finally:
        source.close()
    package = package.model_copy(
        update={"manifest": {**package.manifest, "worker_pid": os.getpid()}}
    )
    try:
        output.send(("progress", package.model_dump_json()))
        threading.Event().wait(30)
    finally:
        output.close()


@pytest.mark.parametrize("interruption", ["cancel", "deadline", "shutdown"])
def test_interrupt_after_progress_preserves_evidence_and_stops_worker(
    settings, request_factory, monkeypatch, interruption
):
    """阶段包落盘后的三种中断均创建部分快照，保留原包及证据，重启不改终态。"""
    monkeypatch.setattr(execution, "_worker", retained_progress_worker)
    request = request_factory(
        options={
            "exhaustive_fixture": True,
            "include_usage": False,
            "include_proposals": False,
            "directed_followups": False,
        },
        # 本用例验证有阶段包后的中断，不把 spawn 和真实检索必须四秒完成作为前提。
        budget={"max_tasks": 100, "time_ms": 15000},
    )
    with Client(settings) as client:
        manager = client.manager
        state = manager.submit(request)
        deadline = time.monotonic() + 12
        original = None
        while time.monotonic() < deadline:
            original = manager.store.package(state.run_id)
            if original is not None:
                break
            time.sleep(0.01)
        assert original is not None and original.results
        assert original.coverage_state == "complete"
        assert manager.store.load(state.run_id).lifecycle == "running"
        worker_pid = original.manifest["worker_pid"]
        assert worker_pid in {process.pid for process in multiprocessing.active_children()}
        if interruption == "cancel":
            terminal = manager.cancel(state.run_id)
        elif interruption == "deadline":
            terminal = manager.wait(state.run_id, timeout=20)
        else:
            client.close()
            terminal = manager.store.load(state.run_id)
        expected = "timed_out" if interruption == "deadline" else "cancelled"
        assert terminal.lifecycle == expected
        retained = manager.store.package(state.run_id)
        assert retained.snapshot_id == terminal.snapshot_id != original.snapshot_id
        assert retained.coverage_state == "partial" and expected in retained.stop_reasons
        assert retained.results == original.results
        assert retained.summary == original.summary
        assert manager.store.package(state.run_id, original.snapshot_id) == original
        assert worker_pid not in {process.pid for process in multiprocessing.active_children()}
        with pytest.raises(ProcessLookupError):
            os.kill(worker_pid, 0)
    with Client(settings) as restarted:
        assert restarted.manager.store.load(state.run_id) == terminal
        assert restarted.manager.store.package(state.run_id) == retained
        assert restarted.manager.store.package(state.run_id, original.snapshot_id) == original
