"""单协调器文件运行仓库：目录锁、revision、不可变资料快照与原子持久化。"""

import fcntl
import json
import os
import threading
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import ReferencePackage, RunState


class RevisionConflict(ValueError):
    """状态修订、幂等请求或快照内容冲突；HTTP 层转换为 409。"""

    pass


class FileRunStore:
    """单机文件存储；原子写入配合一个协调器使用，不提供分布式事务。"""

    def __init__(self, root):
        """建立运行根目录和线程锁；跨进程互斥需额外调用 acquire_coordinator。"""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._coordinator = None

    def acquire_coordinator(self):
        """获取运行目录的非阻塞排他文件锁；已有协调器占用时抛出 RuntimeError。

        锁文件可以保留在磁盘上，锁的实际生命周期由打开的文件描述符决定。
        """
        stream = (self.root / ".coordinator.lock").open("a+")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            raise RuntimeError(
                "A coordinator already owns this run directory; use one API worker"
            ) from None
        self._coordinator = stream

    def close(self):
        """释放当前持有的协调器文件锁；未持锁或已关闭时不做操作。"""
        with self._lock:
            if self._coordinator:
                fcntl.flock(self._coordinator.fileno(), fcntl.LOCK_UN)
                self._coordinator.close()
                self._coordinator = None

    def _directory(self, run_id):
        """校验 run_id 是 32 位小写十六进制字符串，返回对应目录路径。

        非法值抛出 KeyError，避免用户输入变成任意文件路径。
        """
        if not run_id or any(c not in "0123456789abcdef" for c in run_id) or len(run_id) != 32:
            raise KeyError("Invalid run ID")
        return self.root / run_id

    @staticmethod
    def _snapshot_path(directory, snapshot_id):
        """校验快照标识为至多 64 位的非空小写十六进制字符串，返回受限文件路径。"""
        if (
            not isinstance(snapshot_id, str)
            or not snapshot_id
            or len(snapshot_id) > 64
            or any(c not in "0123456789abcdef" for c in snapshot_id)
        ):
            raise KeyError("Invalid snapshot ID")
        return directory / f"snapshot-{snapshot_id}.json"

    @staticmethod
    def _atomic(path, content):
        """把文本写入同目录临时文件，经 fsync 后原子替换目标，再同步目录。

        保证读者看到完整旧文件或完整新文件；本函数执行磁盘 I/O，写入错误向上传播。
        """
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            # 失败时尽力清理未发布文件，清理异常不覆盖原始写入异常。
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def create(self, state):
        """创建一个新运行目录并持久化初始 RunState；同 ID 目录存在时拒绝覆盖。"""
        with self._lock:
            directory = self._directory(state.run_id)
            directory.mkdir(exist_ok=False)
            self._atomic(directory / "state.json", state.model_dump_json())

    def load(self, run_id, owner=None):
        """读取并校验指定 run 的状态，返回 RunState。

        可选 owner 限制访问范围；不存在或归属不符统一抛出 KeyError，不暴露其他范围的运行信息。
        """
        with self._lock:
            path = self._directory(run_id) / "state.json"
            if not path.is_file():
                raise KeyError("Run not found")
            state = RunState.model_validate_json(path.read_text(encoding="utf-8"))
            if state.run_id != run_id:
                raise RevisionConflict("Stored run identity does not match its directory")
            if owner is not None and state.owner != owner:
                raise KeyError("Run not found")
            return state

    def update(self, state, expected_revision):
        """按 expected_revision 更新非终态运行并返回递增 revision 后的状态。

        修订冲突或试图改写终态时抛出 RevisionConflict；调用方不能通过旧状态覆盖取消/成功结果。
        """
        with self._lock:
            previous = self.load(state.run_id)
            if previous.revision != expected_revision:
                raise RevisionConflict("Run revision changed")
            if previous.lifecycle in ("succeeded", "cancelled", "timed_out", "failed"):
                raise RevisionConflict("Terminal run cannot be changed")
            state = state.model_copy(update={"revision": expected_revision + 1})
            self._atomic(self._directory(state.run_id) / "state.json", state.model_dump_json())
            return state

    def save_package(self, package):
        """保存不可变 ReferencePackage 快照，并原子更新 latest 指针。

        同 snapshot_id 只能重写完全相同的内容；内容冲突抛出 RevisionConflict，防止分页已绑定快照发生变化。
        """
        with self._lock:
            directory = self._directory(package.run_id)
            path = self._snapshot_path(directory, package.snapshot_id)
            content = package.model_dump_json()
            if path.exists() and path.read_text(encoding="utf-8") != content:
                raise RevisionConflict("An immutable snapshot cannot be replaced")
            if not path.exists():
                self._atomic(path, content)
            self._atomic(
                directory / "latest.json", json.dumps({"snapshot_id": package.snapshot_id})
            )

    def package(self, run_id, snapshot_id=None):
        """读取指定快照，或在未指定时读取 latest 指向的资料包。

        运行尚无快照时返回 None；显式快照不存在或 ID 非法抛出 KeyError。返回对象经过 ReferencePackage 契约校验。
        """
        directory = self._directory(run_id)
        if snapshot_id is None:
            latest = directory / "latest.json"
            if not latest.is_file():
                return None
            snapshot_id = json.loads(latest.read_text(encoding="utf-8"))["snapshot_id"]
        path = self._snapshot_path(directory, snapshot_id)
        if not path.is_file():
            raise KeyError("Snapshot not found")
        package = ReferencePackage.model_validate_json(path.read_text(encoding="utf-8"))
        if package.run_id != run_id or package.snapshot_id != snapshot_id:
            raise RevisionConflict("Stored snapshot identity does not match the requested file")
        return package

    def idempotency(self, owner, key, request_hash, run_id=None):
        """查找或绑定 owner 范围内的幂等键，返回先前 run_id 或 None。

        同键同请求摘要可复用；同键不同请求抛出 RevisionConflict。提供 run_id 才写入绑定文件。
        """
        with self._lock:
            path = self.root / f"idempotency-{digest([owner, key])}.json"
            if path.is_file():
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved["request_hash"] != request_hash:
                    raise RevisionConflict("Idempotency key is bound to a different request")
                return saved["run_id"]
            if run_id:
                self._atomic(path, json.dumps({"request_hash": request_hash, "run_id": run_id}))
            return None

    def interrupt_snapshot(self, run_id, reason):
        """为中断任务保存带停止原因的部分范围快照，返回新快照 ID 或 None。

        原快照保持不可变；没有资料包时不创建空包。相同中断原因重复处理时复用已保存快照。
        """
        with self._lock:
            package = self.package(run_id)
            if package is None:
                return None
            if package.coverage_state == "partial" and reason in package.stop_reasons:
                return package.snapshot_id
            interrupted = package.model_copy(
                update={
                    "coverage_state": "partial",
                    "stop_reasons": sorted(set(package.stop_reasons + [reason])),
                    "snapshot_id": digest([package.snapshot_id, reason]),
                }
            )
            self.save_package(interrupted)
            return interrupted.snapshot_id

    def recover_interrupted(self):
        """启动时将遗留 queued/running 标为 failed，并保留已经写入的资料快照。

        进程重启后原只读来源会话已失效，因此不自动续接旧游标或伪造完整性。
        """
        for path in self.root.glob("*/state.json"):
            state = self.load(path.parent.name)
            if state.lifecycle in ("queued", "running"):
                snapshot_id = self.interrupt_snapshot(state.run_id, "coordinator_restarted")
                self.update(
                    state.model_copy(
                        update={
                            "lifecycle": "failed",
                            "snapshot_id": snapshot_id,
                            "updated_at": datetime.now(UTC).isoformat(),
                            "error": {
                                "code": "coordinator_restarted",
                                "message": "Existing source snapshot cannot be resumed; retained results remain readable.",
                            },
                        }
                    ),
                    state.revision,
                )
