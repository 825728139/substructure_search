"""任务协调器及 spawn 计算进程：父进程独占文件写入，子进程只传递可序列化进度和结果。"""

import multiprocessing
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from reaction_reference.adapters.run_store import FileRunStore
from reaction_reference.chemistry.structures import canonical, digest, parse
from reaction_reference.domain.models import ReferencePackage, RunState, SearchRequest


def _worker(config, request_json, run_id, output):
    """在独立进程中恢复请求和来源、执行检索，并通过队列返回进度/结果或受限错误。

    config/request_json/run_id 都可序列化，不跨进程传 RDKit 对象或连接；finally 关闭来源。输出中的连接配置不进入结果 manifest。
    """
    from reaction_reference.application.search import search
    from reaction_reference.bootstrap import open_source
    from reaction_reference.settings import Settings

    source = None
    try:
        request = SearchRequest.model_validate_json(request_json)
        source = open_source(Settings(**config), exhaustive=request.options.exhaustive_fixture)
        result = search(
            request,
            source,
            run_id=run_id,
            # 进度回调只序列化资料包送入队列；文件保存由父进程负责。
            on_progress=lambda p: output.put(("progress", p.model_dump_json())),
        )
        output.put(("result", result.model_dump_json()))
    except Exception as exc:
        output.put(
            (
                "error",
                {
                    "code": "worker_failed",
                    "type": type(exc).__name__,
                    "message": str(exc)[:400]
                    if isinstance(exc, ValueError)
                    else "Source or calculation failed; inspect the internal diagnostic.",
                },
            )
        )
    finally:
        if source is not None:
            source.close()


class CapacityExceeded(RuntimeError):
    """活跃及排队任务达到容量或协调器已关闭；HTTP 层转换为 429。"""

    pass


class RunManager:
    """单协调器运行管理器；线程池监督独立计算进程，FileRunStore 保存终态及快照。"""

    def __init__(self, settings):
        """获取目录协调锁、恢复中断状态，再按设置创建有界工作并发的监督线程池。

        settings 控制来源、运行目录和容量；多个管理器不能同时写同一目录。
        """
        self.settings = settings
        self.store = FileRunStore(settings.store_path)
        self.store.acquire_coordinator()
        try:
            self.store.recover_interrupted()
            self._executor = ThreadPoolExecutor(
                max_workers=settings.max_concurrent_runs, thread_name_prefix="rr-supervisor"
            )
        except Exception:
            # 初始化失败时立即释放外部资源，不依赖异常对象何时被垃圾回收。
            self.store.close()
            raise
        self._lock = threading.RLock()
        self._cancel = {}
        self._futures = {}
        self._closed = False

    def submit(self, request, *, owner="internal", idempotency_key=None):
        """验证目标和排除材料结构后接纳检索，保存 queued 状态并返回 RunState。

        owner 限定范围，idempotency_key 可复用同一请求；检查容量、禁止对 PG 声称有限样本穷尽。随后在监督线程中启动计算，函数本身不等待完成。
        """
        parse(request.target.value, target=True)
        if request.lab_context:
            try:
                for smiles in request.lab_context.excluded_material_smiles:
                    canonical(smiles)
            except ValueError as exc:
                raise ValueError("Excluded material structure cannot be parsed") from exc
        if request.options.exhaustive_fixture and self.settings.source_kind == "postgres":
            raise ValueError("exhaustive_fixture is only available for a bounded JSONL source")
        with self._lock:
            request_hash = digest(request.model_dump())
            if idempotency_key:
                previous = self.store.idempotency(owner, idempotency_key, request_hash)
                if previous:
                    return self.store.load(previous, owner)
            active = sum(not f.done() for f in self._futures.values())
            if self._closed or active >= self.settings.max_queued_runs:
                raise CapacityExceeded("Run queue is full")
            run_id = uuid.uuid4().hex
            now = datetime.now(UTC).isoformat()
            state = RunState(
                run_id=run_id,
                lifecycle="queued",
                request=request,
                created_at=now,
                updated_at=now,
                owner=owner,
            )
            self.store.create(state)
            cancellation = threading.Event()
            self._cancel[run_id] = cancellation
            if idempotency_key:
                self.store.idempotency(owner, idempotency_key, request_hash, run_id)
            self._futures[run_id] = self._executor.submit(self._execute, state, cancellation)
            # 完成回调忽略 future 参数，只清除此任务的内存登记。
            self._futures[run_id].add_done_callback(lambda _: self._release(run_id))
            return state

    def _release(self, run_id):
        """任务 future 完成后清除其内存登记和取消事件，持久化结果继续保留。

        作为完成回调运行，用锁避免与提交、取消或关闭时的枚举竞争。
        """
        with self._lock:
            self._futures.pop(run_id, None)
            self._cancel.pop(run_id, None)

    def _execute(self, state, cancellation):
        """执行监督边界并兜底保存 failed，避免启动/监督异常把状态永远留在 running。

        调用 _supervise；受限错误只保存异常类型，不返回原生堆栈或连接内容。
        """
        try:
            self._supervise(state, cancellation)
        except Exception as exc:
            self._finish(
                state.run_id,
                "failed",
                {
                    "code": "supervisor_failed",
                    "type": type(exc).__name__,
                    "message": "Task supervision failed",
                },
            )

    def _supervise(self, state, cancellation):
        """启动 spawn 子进程，接收进度并强制执行截止时间和取消。

        父线程把阶段包落盘；成功、报错、进程异常退出、硬超时和取消分别终结。终止后必要时 kill/join，保留的阶段包强制标记 partial；源 SQL 另有自身超时。
        """
        if cancellation.is_set():
            self._finish(state.run_id, "cancelled")
            return
        state = self.store.update(state.model_copy(update={"lifecycle": "running"}), state.revision)
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        process = context.Process(
            target=_worker,
            args=(
                self.settings.worker_config(),
                state.request.model_dump_json(),
                state.run_id,
                output,
            ),
        )
        process.start()
        deadline = time.monotonic() + state.request.budget.time_ms / 1000
        terminal, error, package = None, None, None
        try:
            while terminal is None:
                if cancellation.is_set():
                    terminal = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    terminal = "timed_out"
                    break
                try:
                    kind, data = output.get(timeout=0.05)
                except queue.Empty:
                    if not process.is_alive():
                        terminal, error = (
                            "failed",
                            {
                                "code": "worker_exited",
                                "message": "Worker exited before publishing a result",
                            },
                        )
                    continue
                if kind in ("progress", "result"):
                    package = ReferencePackage.model_validate_json(data)
                    self.store.save_package(package)
                    if kind == "result":
                        terminal = "succeeded"
                elif kind == "error":
                    terminal, error = "failed", data
            if terminal in ("cancelled", "timed_out", "failed") and process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            self._finish(state.run_id, terminal, error, package.snapshot_id if package else None)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            output.close()
            output.cancel_join_thread()

    def _finish(self, run_id, lifecycle, error=None, snapshot_id=None):
        """在锁内把非终态 run 写为给定终态并返回状态。

        已有终态直接返回，避免迟到工作结果覆盖先发生的取消或失败；snapshot_id 只指向已保存的资料包。
        """
        with self._lock:
            state = self.store.load(run_id)
            if state.lifecycle in ("succeeded", "cancelled", "timed_out", "failed"):
                return state
            # 正常监督与异常兜底共用同一收尾，避免任务失败但资料包仍宣称完整。
            if lifecycle != "succeeded":
                snapshot_id = self.store.interrupt_snapshot(run_id, lifecycle)
            return self.store.update(
                state.model_copy(
                    update={
                        "lifecycle": lifecycle,
                        "error": error,
                        "snapshot_id": snapshot_id,
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                ),
                state.revision,
            )

    def cancel(self, run_id, owner="internal"):
        """请求取消 owner 范围内的运行，短暂等待监督器停止工作后返回实际状态。

        若已成功或失败则不改写终态；等待超时也不伪造 cancelled，调用方可继续读取真实状态。
        """
        state = self.store.load(run_id, owner)
        if state.lifecycle in ("queued", "running"):
            cancellation = self._cancel.get(run_id)
            if cancellation:
                cancellation.set()
            future = self._futures.get(run_id)
            if future:
                try:
                    future.result(timeout=3)
                except TimeoutError:
                    pass
        return self.store.load(run_id, owner)

    def wait(self, run_id, timeout=130):
        """等待本管理器登记的 future 结束，再从磁盘返回真实 RunState。

        已完成并移出内存登记的运行直接读状态；超过 timeout 会向调用方抛出等待超时。
        """
        future = self._futures.get(run_id)
        if future:
            future.result(timeout=timeout)
        return self.store.load(run_id)

    def close(self):
        """停止接纳任务，向所有登记作业发取消信号，等待监督线程清理后释放目录锁。

        先复制事件列表再取消，避免完成回调同时移除登记导致遍历错误。
        """
        with self._lock:
            self._closed = True
            cancellations = list(self._cancel.values())
        for cancellation in cancellations:
            cancellation.set()
        self._executor.shutdown(wait=True, cancel_futures=False)
        self.store.close()
