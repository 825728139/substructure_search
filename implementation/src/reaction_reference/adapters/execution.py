"""任务协调器及 spawn 计算进程：父进程独占文件写入，子进程只传递可序列化进度和结果。"""

import multiprocessing
import queue
import threading
import time
import uuid
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime

from reaction_reference.adapters.run_store import FileRunStore, RevisionConflict
from reaction_reference.chemistry.structures import canonical, digest, parse
from reaction_reference.domain.models import ReferencePackage, RunState, SearchRequest


def _worker(config, request_json, run_id, output):
    """在独立进程中恢复请求和来源、执行检索，通过单向管道发送进度/结果或受限错误。

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
            # 管道写入提供背压；阶段包由父进程接收线程转交监督循环保存。
            on_progress=lambda p: output.send(("progress", p.model_dump_json())),
        )
        output.send(("result", result.model_dump_json()))
    except Exception as exc:
        output.send(
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
        try:
            if source is not None:
                source.close()
        finally:
            output.close()


def _receive_packages(connection, messages, stopping):
    """阻塞读取完整管道消息，再交给有界本地队列；监督线程不直接等待消息体。

    子进程中途退出会产生 EOF/接收错误。停止时不再向已无人消费的队列阻塞写入；
    本线程拥有接收端并最终关闭它，消息正文不进入传输错误信息。
    """
    try:
        while not stopping.is_set():
            try:
                message = connection.recv()
                if (
                    not isinstance(message, tuple)
                    or len(message) != 2
                    or message[0] not in ("progress", "result", "error")
                ):
                    raise ValueError("Invalid worker message")
            except EOFError:
                message = (
                    "error",
                    {
                        "code": "worker_exited",
                        "message": "Worker exited before publishing a result",
                    },
                )
            except Exception as exc:
                message = (
                    "error",
                    {
                        "code": "worker_channel_failed",
                        "type": type(exc).__name__,
                        "message": "Worker message channel failed",
                    },
                )
            while not stopping.is_set():
                try:
                    messages.put(message, timeout=0.05)
                    break
                except queue.Full:
                    continue
            if message[0] in ("result", "error"):
                return
    finally:
        connection.close()


class CapacityExceeded(RuntimeError):
    """活跃及排队任务达到容量或协调器已关闭；HTTP 层转换为 429。"""

    pass


class RunManager:
    """单协调器运行管理器；线程池监督独立计算进程，FileRunStore 保存终态及快照。"""

    def __init__(self, settings):
        """获取目录协调锁、恢复中断状态，再按设置创建有界工作并发的监督线程池。

        settings 控制来源、运行目录和容量；多个管理器不能同时写同一目录。
        """
        # Settings 可变；客户端持有独立配置，避免外部修改影响已接纳任务。
        self.settings = settings.model_copy(deep=True)
        self.store = FileRunStore(self.settings.store_path)
        self.store.acquire_coordinator()
        try:
            self.store.recover_interrupted()
            self._executor = ThreadPoolExecutor(
                max_workers=self.settings.max_concurrent_runs, thread_name_prefix="rr-supervisor"
            )
        except Exception:
            # 初始化失败时立即释放外部资源，不依赖异常对象何时被垃圾回收。
            self.store.close()
            raise
        self._lock = threading.RLock()
        self._writers = threading.Condition(self._lock)
        self._active_writers = 0
        self._cancel = {}
        self._futures = {}
        self._closed = False

    @staticmethod
    def validate_lab_context(context):
        """统一校验检索及重排中的排除结构，不依赖结果池是否为空，也不创建任务。"""
        if context:
            try:
                for smiles in context.excluded_material_smiles:
                    canonical(smiles)
            except ValueError as exc:
                raise ValueError("Excluded material structure cannot be parsed") from exc

    def submit(self, request, *, owner="internal", idempotency_key=None):
        """验证目标和排除材料结构后接纳检索，保存 queued 状态并返回 RunState。

        owner 限定范围，idempotency_key 可复用同一请求；检查容量、禁止对 PG 声称有限样本穷尽。随后在监督线程中启动计算，函数本身不等待完成。
        """
        # 冻结模型只禁止字段赋值，不冻结内部列表；接纳时复制并重校验整个请求。
        request = SearchRequest.model_validate_json(request.model_dump_json())
        parse(request.target.value, target=True)
        self.validate_lab_context(request.lab_context)
        if request.options.exhaustive_fixture and self.settings.source_kind == "postgres":
            raise ValueError("exhaustive_fixture is only available for a bounded JSONL source")
        with self._lock:
            if self._closed:
                raise CapacityExceeded("Run manager is closed")
            request_hash = digest(request.model_dump())
            if idempotency_key:
                previous = self.store.idempotency(owner, idempotency_key, request_hash)
                if previous:
                    return self.store.load(previous, owner)
            active = sum(not f.done() for f in self._futures.values())
            if active >= self.settings.max_queued_runs:
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
            cancellation = threading.Event()
            try:
                self.store.create(state)
                self._cancel[run_id] = cancellation
                if idempotency_key:
                    self.store.idempotency(owner, idempotency_key, request_hash, run_id)
                self._futures[run_id] = self._executor.submit(self._execute, state, cancellation)
            except Exception as exc:
                self._cancel.pop(run_id, None)
                self._futures.pop(run_id, None)
                try:
                    self._finish(
                        run_id,
                        "failed",
                        {
                            "code": "submission_failed",
                            "type": type(exc).__name__,
                            "message": "Task submission failed",
                        },
                    )
                except (KeyError, OSError, ValueError):
                    # 存储本身不可写时保留原始异常；可读取的遗留状态在重启时恢复。
                    pass
                raise
            # 排队取消的 future 不执行工作函数，需要在完成回调中保存取消终态。
            self._futures[run_id].add_done_callback(lambda future: self._release(run_id, future))
            # 返回对象也不能与执行线程共享可变的嵌套请求字段。
            return state.model_copy(deep=True)

    def _release(self, run_id, future):
        """保存未启动任务的取消终态，再清除内存登记和取消事件。

        作为完成回调运行，用锁避免与提交、取消或关闭时的枚举竞争。
        """
        with self._lock:
            try:
                if future.cancelled():
                    self._finish(run_id, "cancelled")
            finally:
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
        """监督独立进程及其接收线程，截止时间从启动准备开始计算。

        完整消息由接收线程读取，监督循环只等待有超时的本地队列；半包不会阻塞取消。
        进程启动失败、正常终结及强制终止都关闭通信端点，并在资源收尾后保存终态。
        """
        if cancellation.is_set():
            self._finish(state.run_id, "cancelled")
            return
        deadline = time.monotonic() + state.request.budget.time_ms / 1000
        state = self.store.update(state.model_copy(update={"lifecycle": "running"}), state.revision)
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        messages: queue.Queue = queue.Queue(maxsize=1)
        stopping = threading.Event()
        process, receiver = None, None
        terminal, error, package = None, None, None
        try:
            process = context.Process(
                target=_worker,
                args=(
                    self.settings.worker_config(),
                    state.request.model_dump_json(),
                    state.run_id,
                    send,
                ),
            )
            if cancellation.is_set():
                terminal = "cancelled"
            elif time.monotonic() >= deadline:
                terminal = "timed_out"
            else:
                process.start()
                # 父进程不持有写端，子进程退出后接收线程才能可靠观察到 EOF。
                send.close()
                receiver = threading.Thread(
                    target=_receive_packages,
                    args=(receive, messages, stopping),
                    name="rr-receiver-" + state.run_id,
                    daemon=True,
                )
                receiver.start()
            while terminal is None:
                if cancellation.is_set():
                    terminal = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    terminal = "timed_out"
                    break
                try:
                    kind, data = messages.get(timeout=0.05)
                except queue.Empty:
                    # 子进程退出后，接收线程可能仍在处理最后一包，不能提前丢弃它。
                    if receiver is not None and not receiver.is_alive() and messages.empty():
                        terminal, error = (
                            "failed",
                            {
                                "code": "receiver_exited",
                                "message": "Receiver exited before publishing a result",
                            },
                        )
                    continue
                # 消息等待会交出执行权；到达的最终包不能覆盖等待期间发生的中断。
                if cancellation.is_set():
                    terminal = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    terminal = "timed_out"
                    break
                if kind in ("progress", "result"):
                    package = ReferencePackage.model_validate_json(data)
                    self.store.save_package(package)
                    if kind == "result":
                        terminal = "succeeded"
                elif kind == "error":
                    terminal, error = "failed", data
        finally:
            stopping.set()
            try:
                if process is not None:
                    try:
                        if process.is_alive():
                            if terminal != "succeeded":
                                process.terminate()
                            process.join(timeout=1)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=1)
                    finally:
                        if not process.is_alive():
                            process.close()
            finally:
                # 进程收尾异常也必须关闭父写端，让接收线程获得 EOF。
                send.close()
                if receiver is not None and receiver.ident is not None:
                    receiver.join(timeout=1)
                else:
                    receive.close()
        self._finish(state.run_id, terminal, error, package.snapshot_id if package else None)

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
                try:
                    snapshot_id = self.store.interrupt_snapshot(run_id, lifecycle)
                except (OSError, KeyError, RevisionConflict) as exc:
                    # 大快照或指针写入失败，不应阻止仍可写的小状态文件记录真实失败。
                    # 默认结果读取据此拒绝旧指针；显式指定的历史快照仍保持原样。
                    error = {
                        "code": "snapshot_finalization_failed",
                        "message": "Task stopped; interrupted snapshot could not be published",
                        "snapshot_unavailable": True,
                        "snapshot_error_type": type(exc).__name__,
                        "requested_lifecycle": lifecycle,
                        "cause": error,
                    }
                    lifecycle, snapshot_id = "failed", None
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

        排队任务直接取消并释放名额；运行任务发信号后短暂等待。已有终态不改写，等待超时也不伪造 cancelled。
        """
        future = None
        with self._lock:
            state = self.store.load(run_id, owner)
            if state.lifecycle in ("queued", "running"):
                cancellation = self._cancel.get(run_id)
                if cancellation:
                    cancellation.set()
                future = self._futures.get(run_id)
                if future is not None and future.cancel():
                    return self.store.load(run_id, owner)
        # 等待期间不能持有协调锁，运行中的监督线程需要该锁完成收尾。
        if future is not None:
            try:
                future.result(timeout=3)
            except (TimeoutError, CancelledError):
                pass
        return self.store.load(run_id, owner)

    def wait(self, run_id, timeout=None):
        """等待本管理器登记的 future 结束，再从磁盘返回真实 RunState。

        默认包括排队等待，计算时限由监督器负责；显式 timeout 则限制本次等待。
        排队取消返回保存的取消状态，不把 Future 的 CancelledError 泄漏给调用方。
        """
        with self._lock:
            future = self._futures.get(run_id)
        if future:
            try:
                future.result(timeout=timeout)
            except CancelledError:
                # Future 先唤醒等待者再执行完成回调；关闭线程可能尚未保存取消终态。
                # 共用幂等收尾，避免把已取消任务的旧 queued 状态返回给调用方。
                return self._finish(run_id, "cancelled")
        with self._lock:
            return self.store.load(run_id)

    @contextmanager
    def active_writer(self):
        """登记同步写操作的生命周期；计算期间释放协调锁，关闭等待已登记操作完成后再释放目录锁。"""
        with self._lock:
            if self._closed:
                raise CapacityExceeded("Run manager is closed")
            self._active_writers += 1
        try:
            yield
        finally:
            with self._writers:
                self._active_writers -= 1
                self._writers.notify_all()

    def close(self):
        """停止接纳任务，向所有登记作业发取消信号，等待监督线程清理后释放目录锁。

        排队作业直接取消，运行作业等待监督收尾；同步写操作结束后才释放目录锁。先复制事件列表，避免完成回调同时移除登记。
        """
        with self._lock:
            self._closed = True
            cancellations = list(self._cancel.values())
        for cancellation in cancellations:
            cancellation.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._writers:
            # 等待同步写入时释放协调锁，允许其他任务完成取消及终态保存。
            self._writers.wait_for(lambda: self._active_writers == 0)
        self.store.close()
