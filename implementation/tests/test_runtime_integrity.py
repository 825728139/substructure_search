"""执行层回归：故障注入、并发关闭、取消、持久化及半包消息超时。"""

import asyncio
import os
import signal
import struct
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reaction_reference.adapters import execution
from reaction_reference.adapters.run_store import FileRunStore
from reaction_reference.domain.models import (
    ReferencePackage,
    RerankRequest,
    RunState,
    SearchRequest,
    Target,
)
from reaction_reference.interfaces.api import create_app
from reaction_reference.interfaces.sdk import Client
from reaction_reference.settings import Settings


def seed_run(store, request, lifecycle="succeeded"):
    """保存最小任务和资料包，隔离执行协议测试与化学计算。"""
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=uuid.uuid4().hex,
        lifecycle=lifecycle,
        request=request,
        created_at=now,
        updated_at=now,
    )
    store.create(state)
    package = ReferencePackage(
        run_id=state.run_id,
        snapshot_id="a" * 24,
        target_smiles=request.target.value,
        target_atoms=[],
        source_snapshot="fixture",
        manifest={},
        families=[],
        results=[],
        coverage_state="partial",
    )
    store.save_package(package)
    return state, package


@pytest.mark.parametrize("failure", ["dispatch", "idempotency"])
def test_submission_failure_leaves_no_queued_ghost(settings, request_factory, monkeypatch, failure):
    """幂等落盘或调度失败后，任务应结束为失败并清除内存登记。"""
    with Client(settings) as client:
        manager = client.manager
        original = manager.store.idempotency

        def rejected(*args, **kwargs):
            """模拟线程池拒绝任务。"""
            raise RuntimeError("模拟调度失败")

        def broken_binding(owner, key, request_hash, run_id=None):
            """只在写入幂等绑定时模拟失败，读取仍正常。"""
            if run_id:
                raise OSError("模拟幂等写入失败")
            return original(owner, key, request_hash)

        if failure == "dispatch":
            monkeypatch.setattr(manager._executor, "submit", rejected)
        else:
            monkeypatch.setattr(manager.store, "idempotency", broken_binding)
        with pytest.raises((RuntimeError, OSError)):
            manager.submit(request_factory(), idempotency_key="submission")
        states = [
            RunState.model_validate_json(p.read_text())
            for p in settings.store_path.glob("*/state.json")
        ]
        assert len(states) == 1 and states[0].lifecycle == "failed"
        assert not manager._cancel and not manager._futures
        if failure == "dispatch":
            assert (
                manager.submit(request_factory(), idempotency_key="submission").lifecycle
                == "failed"
            )


def test_queued_cancel_frees_capacity_immediately(settings, request_factory, monkeypatch):
    """一个任务占满执行线程时，另一个排队任务取消后应立即结束并释放接纳名额。"""
    configured = settings.model_copy(update={"max_concurrent_runs": 1, "max_queued_runs": 2})
    entered, release = threading.Event(), threading.Event()
    with Client(configured) as client:

        def blocked(state, cancellation):
            """占住唯一工作线程，直到测试明确释放。"""
            entered.set()
            release.wait(10)
            client.manager._finish(state.run_id, "cancelled")

        monkeypatch.setattr(client.manager, "_supervise", blocked)
        try:
            client.manager.submit(request_factory())
            assert entered.wait(2)
            queued = client.manager.submit(request_factory())
            started = time.monotonic()
            cancelled = client.manager.cancel(queued.run_id)
            assert cancelled.lifecycle == "cancelled"
            assert time.monotonic() - started < 1
            replacement = client.manager.submit(request_factory())
            assert client.manager.cancel(replacement.run_id).lifecycle == "cancelled"
        finally:
            release.set()


def test_default_wait_includes_queue_time(settings, request_factory):
    """默认等待不能使用独立于排队时长的固定 130 秒上限；显式上限仍传递。"""
    with Client(settings) as client:
        state, _ = seed_run(client.manager.store, request_factory())

        class WaitingFuture:
            """记录等待参数，模拟已完成的任务句柄。"""

            def __init__(self):
                """保存观察到的等待上限。"""
                self.timeouts = []

            def result(self, timeout=None):
                """记录调用方是否强加了隐藏等待上限。"""
                self.timeouts.append(timeout)

        future = WaitingFuture()
        client.manager._futures[state.run_id] = future
        try:
            client.manager.wait(state.run_id)
            client.manager.wait(state.run_id, timeout=0.1)
            assert future.timeouts == [None, 0.1]
        finally:
            client.manager._futures.pop(state.run_id)


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_atomic_write_failure_removes_temporary_file(tmp_path, monkeypatch, failure):
    """原子写失败应保留旧文件，并清除未发布的临时文件。"""
    path = tmp_path / "state.json"
    path.write_text("原始内容", encoding="utf-8")

    def fail(*args, **kwargs):
        """模拟替换或同步失败。"""
        raise OSError("模拟持久化失败")

    monkeypatch.setattr(f"reaction_reference.adapters.run_store.os.{failure}", fail)
    with pytest.raises(OSError):
        FileRunStore._atomic(path, "新内容")
    assert path.read_text(encoding="utf-8") == "原始内容"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("snapshot", ["a" * 1000, "", "../../escape"])
def test_snapshot_identifier_is_validated_before_io(settings, request_factory, snapshot):
    """读写快照都应在文件系统调用前拒绝非法或超长标识。"""
    store = FileRunStore(settings.store_path)
    state, package = seed_run(store, request_factory())
    with pytest.raises(KeyError, match="snapshot"):
        store.package(state.run_id, snapshot)
    with pytest.raises(KeyError, match="snapshot"):
        store.save_package(package.model_copy(update={"snapshot_id": snapshot}))
    assert store.package(state.run_id).snapshot_id == package.snapshot_id


def test_closed_client_cannot_write_reranked_run(settings, request_factory):
    """旧客户端关闭后不能越过新协调器的目录锁继续写重排结果。"""
    old = Client(settings)
    state, _ = seed_run(old.manager.store, request_factory())
    old.close()
    with Client(settings):
        with pytest.raises(RuntimeError, match="closed"):
            old.rerank(state.run_id, RerankRequest())
    assert len(list(settings.store_path.glob("*/state.json"))) == 1


def test_close_waits_for_inflight_rerank(settings, request_factory, monkeypatch):
    """同步重排尚未落盘时，关闭不能提前释放协调器锁。"""
    import reaction_reference.interfaces.sdk as sdk

    client = Client(settings)
    state, _ = seed_run(client.manager.store, request_factory())
    entered, release, closing, closed = (*(threading.Event() for _ in range(4)),)
    errors = []
    original = sdk.rank_references

    def blocked_rank(*args, **kwargs):
        """将重排暂停在持久化前。"""
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    def rerank():
        """在线程中执行重排并保存异常，供主测试检查。"""
        try:
            client.rerank(state.run_id, RerankRequest())
        except Exception as exc:
            errors.append(exc)

    def close():
        """通知测试已开始关闭，再等待关闭完成。"""
        closing.set()
        client.close()
        closed.set()

    monkeypatch.setattr(sdk, "rank_references", blocked_rank)
    worker = threading.Thread(target=rerank)
    closer = threading.Thread(target=close)
    worker.start()
    try:
        assert entered.wait(2)
        closer.start()
        assert closing.wait(2)
        assert not closed.wait(0.1)
    finally:
        release.set()
        worker.join(3)
        if closer.ident:
            closer.join(3)
        client.close()
    assert not errors and closed.is_set()


def test_lifespan_exception_still_releases_resources(settings):
    """应用生命周期因异常退出时，仍需关闭客户端并释放目录锁。"""
    app = create_app(settings)

    async def failing_lifespan():
        """模拟生命周期内部异常，而非普通 HTTP 业务错误。"""
        async with app.router.lifespan_context(app):
            raise RuntimeError("模拟生命周期异常")

    try:
        with pytest.raises(RuntimeError, match="模拟生命周期异常"):
            asyncio.run(failing_lifespan())
        assert app.state.client.manager._closed
        with Client(settings):
            pass
    finally:
        app.state.client.close()


class TrackedChannel:
    """只跟踪关闭状态的通信句柄替身，用于进程启动失败。"""

    def __init__(self):
        """初始化未关闭状态。"""
        self.closed = False

    def close(self):
        """记录资源已释放。"""
        self.closed = True

    def cancel_join_thread(self):
        """兼容旧队列接口，使反例观察实际资源清理。"""
        pass


class BrokenProcess:
    """模拟进程在启动时失败且未产生存活子进程。"""

    def __init__(self):
        """记录尚未关闭的进程句柄。"""
        self.closed = False

    def start(self):
        """抛出受控启动失败。"""
        raise OSError("模拟进程启动失败")

    def is_alive(self):
        """失败启动没有存活进程。"""
        return False

    def close(self):
        """记录进程对象资源关闭。"""
        self.closed = True


class BrokenContext:
    """跟踪旧队列或新管道及进程句柄，验证所有失败路径的清理。"""

    def __init__(self):
        """保存实际分配的资源。"""
        self.channels = []
        self.processes = []

    def Queue(self):
        """兼容旧实现的队列分配。"""
        channel = TrackedChannel()
        self.channels.append(channel)
        return channel

    def Pipe(self, duplex=False):
        """创建两端独立的通信句柄替身。"""
        channels = (TrackedChannel(), TrackedChannel())
        self.channels.extend(channels)
        return channels

    def Process(self, **kwargs):
        """创建启动必然失败的进程替身。"""
        process = BrokenProcess()
        self.processes.append(process)
        return process


@pytest.mark.parametrize("failure", ["config", "start"])
def test_process_start_failure_closes_allocated_resources(
    settings, request_factory, monkeypatch, failure
):
    """配置或启动失败时，任务失败状态之外还必须关闭已分配通信与进程资源。"""
    context = BrokenContext()
    with Client(settings) as client:
        state, _ = seed_run(client.manager.store, request_factory(), lifecycle="queued")
        monkeypatch.setattr(execution.multiprocessing, "get_context", lambda _: context)
        if failure == "config":

            def bad_config(_):
                """模拟序列化配置构造失败。"""
                raise ValueError("模拟配置失败")

            monkeypatch.setattr(type(settings), "worker_config", bad_config)
        client.manager._execute(state, threading.Event())
        assert client.manager.store.load(state.run_id).lifecycle == "failed"
        assert all(channel.closed for channel in context.channels)
        assert all(process.closed for process in context.processes)


def partial_frame_worker(config, request_json, run_id, output):
    """发送消息头和不完整消息体后停住，模拟真实进程通信半包。"""
    connection = output if hasattr(output, "send") else output._writer
    os.write(connection.fileno(), struct.pack("!i", 1000000))
    os.write(connection.fileno(), b"partial")
    Path(config["source_path"]).write_text(str(os.getpid()))
    time.sleep(20)


def partial_frame_scenario(directory):
    """在隔离进程中验证半包消息不能阻止硬超时；不执行化学检索。"""
    execution._worker = partial_frame_worker
    marker = Path(directory) / "partial-frame.marker"
    settings = Settings(store_path=Path(directory) / "runs", source_path=marker)
    with Client(settings) as client:
        state = client.manager.submit(
            SearchRequest(target=Target(value="CCO"), budget={"time_ms": 2000})
        )
        terminal = client.manager.wait(state.run_id)
        assert marker.exists(), "测试未进入半包状态"
        assert terminal.lifecycle == "timed_out"


def test_incomplete_process_message_cannot_block_timeout(tmp_path):
    """真实管道只收到半包时，外层监督仍须按预算结束；测试自身另有进程级兜底。"""
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--partial-frame", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 0, stdout + stderr
    except subprocess.TimeoutExpired:
        pytest.fail("半包接收阻塞了硬超时监督")
    finally:
        if process.poll() is None:
            # 先结束本测试进程组，让资源跟踪器有机会完成清理。
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=2)


def test_cancelled_waiter_receives_terminal_state(settings, request_factory, monkeypatch):
    """已经开始等待排队任务的调用方，应收到取消终态而非 Future 的取消异常。"""
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
    results, errors = [], []
    configured = settings.model_copy(update={"max_concurrent_runs": 1})
    with Client(configured) as client:

        def blocked(state, cancellation):
            """占住唯一工作线程，让第二个任务保持排队。"""
            entered.set()
            release.wait(5)
            client.manager._finish(state.run_id, "cancelled")

        def wait_for_run(run_id):
            """收集真实等待调用的返回或异常。"""
            try:
                results.append(client.manager.wait(run_id))
            except Exception as exc:
                errors.append(exc)

        monkeypatch.setattr(client.manager, "_supervise", blocked)
        worker = None
        try:
            client.manager.submit(request_factory())
            assert entered.wait(2)
            queued = client.manager.submit(request_factory())
            future = client.manager._futures[queued.run_id]
            original = future.result

            def observed_result(timeout=None):
                """确认等待线程已捕获该 future，再允许主线程发起取消。"""
                waiting.set()
                return original(timeout)

            monkeypatch.setattr(future, "result", observed_result)
            worker = threading.Thread(target=wait_for_run, args=(queued.run_id,))
            worker.start()
            assert waiting.wait(2)
            assert client.manager.cancel(queued.run_id).lifecycle == "cancelled"
            worker.join(2)
            assert not errors and results[0].lifecycle == "cancelled"
        finally:
            release.set()
            if worker is not None:
                worker.join(2)


def test_rerank_does_not_block_cancelling_other_job(settings, request_factory, monkeypatch):
    """保护重排生命周期时不能持有全局协调锁做计算，从而阻塞另一任务的取消。"""
    import reaction_reference.interfaces.sdk as sdk

    job_entered, rank_entered, release = threading.Event(), threading.Event(), threading.Event()
    errors = []
    with Client(settings) as client:
        source, _ = seed_run(client.manager.store, request_factory())
        original = sdk.rank_references

        def running(state, cancellation):
            """模拟会响应取消信号的运行中任务。"""
            job_entered.set()
            assert cancellation.wait(5)
            client.manager._finish(state.run_id, "cancelled")

        def blocked_rank(*args, **kwargs):
            """暂时阻塞排序，让取消请求与同步写操作重叠。"""
            rank_entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        def rerank():
            """捕获并发排序错误，确保测试不会忽略后台失败。"""
            try:
                client.rerank(source.run_id, RerankRequest())
            except Exception as exc:
                errors.append(exc)

        monkeypatch.setattr(client.manager, "_supervise", running)
        monkeypatch.setattr(sdk, "rank_references", blocked_rank)
        running_job = client.manager.submit(request_factory())
        assert job_entered.wait(2)
        thread = threading.Thread(target=rerank)
        thread.start()
        try:
            assert rank_entered.wait(2)
            started = time.monotonic()
            assert client.manager.cancel(running_job.run_id).lifecycle == "cancelled"
            assert time.monotonic() - started < 1
        finally:
            release.set()
            thread.join(3)
        assert not errors


def test_lifespan_cancellation_still_closes_client(settings):
    """取消作用域已取消时，生命周期的清理仍须完整执行。"""
    import anyio

    app = create_app(settings)

    async def cancelled_scope():
        """在应用生命周期内部取消作用域并交出控制权。"""
        with anyio.CancelScope() as scope:
            async with app.router.lifespan_context(app):
                scope.cancel()
                await anyio.sleep(0)

    try:
        asyncio.run(cancelled_scope())
        assert app.state.client.manager._closed
        with Client(settings):
            pass
    finally:
        app.state.client.close()


def test_deadline_includes_process_startup(settings, request_factory, monkeypatch):
    """启动准备已经耗尽预算时，即使结果已可读取，也不能获得额外运行时间。"""
    clock = [0.0]
    with Client(settings) as client:
        state, package = seed_run(
            client.manager.store, request_factory(budget={"time_ms": 50}), lifecycle="queued"
        )

        class ReadyChannel(TrackedChannel):
            """提供一个已完成消息，隔离进程启动耗时的预算边界。"""

            def recv(self):
                """返回最小结果包。"""
                return "result", package.model_dump_json()

            def get(self, timeout=None):
                """兼容旧队列，确保反例源于预算起点。"""
                return self.recv()

        class SlowStart(BrokenProcess):
            """用可控单调时钟模拟慢启动。"""

            def start(self):
                """启动耗时超过当前预算。"""
                clock[0] += 0.2

            def join(self, timeout=None):
                """模拟已完成的进程等待。"""
                pass

        class ReadyContext:
            """提供无需真实进程的确定性启动时序。"""

            def Queue(self):
                """为旧实现提供相同就绪结果。"""
                return ReadyChannel()

            def Pipe(self, duplex=False):
                """为当前实现提供收发端。"""
                return ReadyChannel(), TrackedChannel()

            def Process(self, **kwargs):
                """返回慢启动对象。"""
                return SlowStart()

        monkeypatch.setattr(execution.multiprocessing, "get_context", lambda _: ReadyContext())
        monkeypatch.setattr(execution.time, "monotonic", lambda: clock[0])
        client.manager._execute(state, threading.Event())
        assert client.manager.store.load(state.run_id).lifecycle == "timed_out"


def test_receiver_stops_when_local_queue_is_full():
    """监督循环已结束时，接收线程不能因等待本地队列空位而泄漏。"""
    import multiprocessing
    import queue

    receive, send = multiprocessing.get_context("spawn").Pipe(duplex=False)
    messages = queue.Queue(maxsize=1)
    stopping = threading.Event()
    thread = threading.Thread(
        target=execution._receive_packages, args=(receive, messages, stopping)
    )
    thread.start()
    try:
        send.send(("progress", "first"))
        send.send(("progress", "second"))
        deadline = time.monotonic() + 1
        while messages.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert messages.qsize() == 1
    finally:
        stopping.set()
        send.close()
        thread.join(1)
    assert not thread.is_alive() and receive.closed


def large_result_worker(config, request_json, run_id, output):
    """生成大于管道缓冲区的完整消息后立即退出，验证末包不会因进程退出而丢失。"""
    package = ReferencePackage(
        run_id=run_id,
        snapshot_id="b" * 24,
        target_smiles="CCO",
        target_atoms=[],
        source_snapshot="fixture",
        manifest={"payload": "x" * (4 * 1024 * 1024)},
        families=[],
        results=[],
        coverage_state="partial",
    )
    try:
        output.send(("result", package.model_dump_json()))
    finally:
        output.close()


def test_large_final_message_survives_worker_exit(settings, request_factory, monkeypatch):
    """完整的大结果必须成功落盘，不能把正常进程退出误判为缺失结果。"""
    monkeypatch.setattr(execution, "_worker", large_result_worker)
    with Client(settings) as client:
        package = client.search(request_factory("CCO"))
        assert len(package.manifest["payload"]) == 4 * 1024 * 1024
        assert client.manager.store.load(package.run_id).lifecycle == "succeeded"


def test_closed_manager_rejects_even_an_existing_idempotency_key(settings, request_factory):
    """关闭后的提交入口不能因幂等缓存命中而绕过生命周期检查。"""
    from reaction_reference.chemistry.structures import digest

    client = Client(settings)
    request = request_factory()
    state, _ = seed_run(client.manager.store, request)
    client.manager.store.idempotency(
        "internal", "closed-key", digest(request.model_dump()), state.run_id
    )
    client.close()
    with pytest.raises(RuntimeError, match="closed"):
        client.manager.submit(request, idempotency_key="closed-key")


if __name__ == "__main__" and sys.argv[1:2] == ["--partial-frame"]:
    partial_frame_scenario(sys.argv[2])
