"""回归测试：命令行来源选择及服务运行期间的只读状态查看。"""

import json
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reaction_reference.domain.models import ReferencePackage, RunState
from reaction_reference.interfaces.cli import main
from reaction_reference.interfaces.sdk import Client
from reaction_reference.settings import Settings


@pytest.mark.parametrize(
    "arguments,expected_kind,expected_path",
    [
        ([], "postgres", "configured"),
        (["--source", "fixture"], "jsonl", "fixture"),
        (["--source-path", "explicit.jsonl"], "jsonl", "explicit.jsonl"),
    ],
)
def test_cli_source_selection_honors_environment_and_explicit_flags(
    monkeypatch, tmp_path, arguments, expected_kind, expected_path
):
    """未显式选择来源时尊重环境；显式示例使用包内数据，显式文件路径选择 JSONL。"""
    configured = tmp_path / "configured.jsonl"
    monkeypatch.setenv("RR_SOURCE_KIND", "postgres")
    monkeypatch.setenv("RR_SOURCE_PATH", str(configured))
    captured = []

    class SearchClient:
        """捕获 CLI 实际装配的设置，避免测试发起来源连接。"""

        def __init__(self, settings):
            """记录当前命令选择的来源配置。"""
            captured.append(settings)

        def __enter__(self):
            """返回检索客户端替身。"""
            return self

        def __exit__(self, *_):
            """替身没有需要释放的外部资源。"""
            return None

        def search(self, request):
            """返回空资料包，使本例只观察检索命令的配置选择。"""
            return ReferencePackage(
                run_id="a" * 32,
                snapshot_id="b" * 24,
                target_smiles=request.target.value,
                target_atoms=[],
                source_snapshot="fixture",
                manifest={},
                families=[],
                results=[],
                coverage_state="complete",
            )

    monkeypatch.setattr("reaction_reference.interfaces.cli.Client", SearchClient)
    assert main(["search", "--target", "CCO", *arguments]) == 0
    assert captured[0].source_kind == expected_kind
    expected = (
        configured
        if expected_path == "configured"
        else (
            Settings.model_fields["source_path"].get_default(call_default_factory=True)
            if expected_path == "fixture"
            else Path(expected_path)
        )
    )
    assert captured[0].source_path == expected


@pytest.mark.parametrize("kind", ["fixture", "postgres"])
def test_cli_rejects_incompatible_source_path(kind, monkeypatch, tmp_path):
    """示例或 PG 模式不能同时指定 JSONL 路径，避免悄悄使用与命令含义不同的来源。"""
    monkeypatch.setenv("RR_STORE_PATH", str(tmp_path / "runs"))
    assert (
        main(["preview", "--target", "CCO", "--source", kind, "--source-path", "other.jsonl"]) == 1
    )


def test_inspect_run_reads_while_coordinator_is_active(
    settings, request_factory, monkeypatch, capsys
):
    """服务持有协调锁时，命令行仍能只读查看任务，且不更改任务生命周期。"""
    monkeypatch.setenv("RR_STORE_PATH", str(settings.store_path))
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=uuid.uuid4().hex,
        lifecycle="queued",
        request=request_factory(),
        created_at=now,
        updated_at=now,
    )
    with Client(settings) as client:
        client.manager.store.create(state)
        assert main(["inspect-run", state.run_id]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["run_id"] == state.run_id and output["lifecycle"] == "queued"
        assert client.manager.store.load(state.run_id) == state


@pytest.mark.parametrize("active", [False, True])
def test_preview_does_not_acquire_coordinator_or_recover_runs(
    settings, request_factory, monkeypatch, capsys, active
):
    """预览在服务运行时可用，在服务停止时也不能把遗留任务标记为恢复失败。"""
    from reaction_reference.adapters.run_store import FileRunStore

    monkeypatch.setenv("RR_STORE_PATH", str(settings.store_path))
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=uuid.uuid4().hex,
        lifecycle="running",
        request=request_factory(),
        created_at=now,
        updated_at=now,
    )
    with Client(settings) if active else nullcontext():
        store = FileRunStore(settings.store_path)
        store.create(state)
        assert main(["preview", "--target", state.request.target.value]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["families"]
        assert store.load(state.run_id) == state
