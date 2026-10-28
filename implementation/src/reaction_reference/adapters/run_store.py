import fcntl
import json
import os
import threading
import uuid
from pathlib import Path

from reaction_reference.chemistry.structures import digest
from reaction_reference.domain.models import ReferencePackage, RunState


class RevisionConflict(ValueError):
    pass


class FileRunStore:
    """Single-coordinator file store with atomic writes and revision checks."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._coordinator = None

    def acquire_coordinator(self):
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
        if self._coordinator:
            fcntl.flock(self._coordinator.fileno(), fcntl.LOCK_UN)
            self._coordinator.close()
            self._coordinator = None

    def _directory(self, run_id):
        if not run_id or any(c not in "0123456789abcdef" for c in run_id) or len(run_id) != 32:
            raise KeyError("Invalid run ID")
        return self.root / run_id

    @staticmethod
    def _atomic(path, content):
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def create(self, state):
        with self._lock:
            directory = self._directory(state.run_id)
            directory.mkdir(exist_ok=False)
            self._atomic(directory / "state.json", state.model_dump_json())

    def load(self, run_id, owner=None):
        with self._lock:
            path = self._directory(run_id) / "state.json"
            if not path.is_file():
                raise KeyError("Run not found")
            state = RunState.model_validate_json(path.read_text())
            if owner is not None and state.owner != owner:
                raise KeyError("Run not found")
            return state

    def update(self, state, expected_revision):
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
        with self._lock:
            directory = self._directory(package.run_id)
            path = directory / f"snapshot-{package.snapshot_id}.json"
            content = package.model_dump_json()
            if path.exists() and path.read_text() != content:
                raise RevisionConflict("An immutable snapshot cannot be replaced")
            if not path.exists():
                self._atomic(path, content)
            self._atomic(
                directory / "latest.json", json.dumps({"snapshot_id": package.snapshot_id})
            )

    def package(self, run_id, snapshot_id=None):
        directory = self._directory(run_id)
        if snapshot_id is None:
            latest = directory / "latest.json"
            if not latest.is_file():
                return None
            snapshot_id = json.loads(latest.read_text())["snapshot_id"]
        if any(c not in "0123456789abcdef" for c in snapshot_id):
            raise KeyError("Invalid snapshot ID")
        path = directory / f"snapshot-{snapshot_id}.json"
        if not path.is_file():
            raise KeyError("Snapshot not found")
        return ReferencePackage.model_validate_json(path.read_text())

    def idempotency(self, owner, key, request_hash, run_id=None):
        with self._lock:
            path = self.root / f"idempotency-{digest([owner, key])}.json"
            if path.is_file():
                saved = json.loads(path.read_text())
                if saved["request_hash"] != request_hash:
                    raise RevisionConflict("Idempotency key is bound to a different request")
                return saved["run_id"]
            if run_id:
                self._atomic(path, json.dumps({"request_hash": request_hash, "run_id": run_id}))
            return None

    def recover_interrupted(self):
        for path in self.root.glob("*/state.json"):
            state = RunState.model_validate_json(path.read_text())
            if state.lifecycle in ("queued", "running"):
                self.update(
                    state.model_copy(
                        update={
                            "lifecycle": "failed",
                            "error": {
                                "code": "coordinator_restarted",
                                "message": "Existing source snapshot cannot be resumed; retained results remain readable.",
                            },
                        }
                    ),
                    state.revision,
                )
