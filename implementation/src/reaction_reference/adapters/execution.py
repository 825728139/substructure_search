import multiprocessing
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from reaction_reference.adapters.run_store import FileRunStore
from reaction_reference.chemistry.structures import digest, parse
from reaction_reference.domain.models import ReferencePackage, RunState, SearchRequest


def _worker(config, request_json, run_id, output):
    """Only serializable data crosses the process boundary, never RDKit objects."""
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
    pass


class RunManager:
    def __init__(self, settings):
        self.settings = settings
        self.store = FileRunStore(settings.store_path)
        self.store.acquire_coordinator()
        self.store.recover_interrupted()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_runs, thread_name_prefix="rr-supervisor"
        )
        self._lock = threading.RLock()
        self._cancel = {}
        self._futures = {}
        self._closed = False

    def submit(self, request, *, owner="internal", idempotency_key=None):
        parse(request.target.value, target=True)
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
            self._futures[run_id].add_done_callback(lambda _: self._release(run_id))
            return state

    def _release(self, run_id):
        with self._lock:
            self._futures.pop(run_id, None)
            self._cancel.pop(run_id, None)

    def _execute(self, state, cancellation):
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
            if package is not None and terminal != "succeeded":
                package = package.model_copy(
                    update={
                        "coverage_state": "partial",
                        "stop_reasons": sorted(set(package.stop_reasons + [terminal])),
                        "snapshot_id": digest([package.snapshot_id, terminal]),
                    }
                )
                self.store.save_package(package)
            self._finish(state.run_id, terminal, error, package.snapshot_id if package else None)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            output.close()
            output.cancel_join_thread()

    def _finish(self, run_id, lifecycle, error=None, snapshot_id=None):
        with self._lock:
            state = self.store.load(run_id)
            if state.lifecycle in ("succeeded", "cancelled", "timed_out", "failed"):
                return state
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
        future = self._futures.get(run_id)
        if future:
            future.result(timeout=timeout)
        return self.store.load(run_id)

    def close(self):
        with self._lock:
            self._closed = True
            cancellations = list(self._cancel.values())
        for cancellation in cancellations:
            cancellation.set()
        self._executor.shutdown(wait=True, cancel_futures=False)
        self.store.close()
