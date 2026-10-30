"""导出文件完整性回归：写入中途失败不能截断旧结果，也不能发布新的半份 JSON。"""

import json
import stat
from contextlib import contextmanager
from pathlib import Path

import pytest

from reaction_reference.evaluation.runner import evaluate, select_targets
from reaction_reference.interfaces.cli import _write
from reaction_reference.schema_export import export_schemas


class InterruptedWrite:
    """包装真实文本流，先写出并刷出部分内容，再模拟磁盘写入异常。"""

    def __init__(self, stream, error):
        """保存真实文件和待抛异常，供所有导出路径使用同一故障。"""
        self.stream, self.error = stream, error

    def write(self, content):
        """确实落盘部分文本后失败，防止只测试序列化前错误而漏掉文件截断。"""
        self.stream.write(content[: max(1, len(content) // 2)])
        self.stream.flush()
        raise self.error

    def __getattr__(self, name):
        """其余文件操作委托真实流，兼容刷新和文件描述符访问。"""
        return getattr(self.stream, name)


def render_artifact(kind, destination, source_path, targets_path):
    """调用各自真实导出入口，不用模拟业务结果代替实际报告或契约。"""
    if kind == "cli":
        _write({"current": "新结果"}, destination)
    elif kind == "targets":
        select_targets(source_path, destination, count=1)
    elif kind == "evaluation":
        evaluate(source_path, targets_path, destination)
    else:
        export_schemas(destination.parent)


@pytest.mark.parametrize("kind", ["cli", "targets", "evaluation", "schema", "openapi"])
@pytest.mark.parametrize("case", ["existing_failure", "new_failure", "success"])
def test_export_artifact_is_complete_or_keeps_previous_file(tmp_path, monkeypatch, kind, case):
    """五种导出在部分写入失败时保留旧文件或保持目标不存在，成功替换保持文件权限。"""
    destination = (
        tmp_path
        / "contracts"
        / ("openapi.json" if kind == "openapi" else "SearchRequest.schema.json")
        if kind in ("schema", "openapi")
        else tmp_path / "result.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous = '{"previous":"完整旧结果"}\n'
    if case != "new_failure":
        destination.write_text(previous, encoding="utf-8")
        destination.chmod(0o600)
    source_path, targets_path = tmp_path / "source.jsonl", tmp_path / "targets.jsonl"
    source_path.write_text(json.dumps({"id": 1, "product_smiles": ["CCO"]}) + "\n")
    targets_path.write_text(json.dumps({"id": "one", "target_smiles": "CCO"}) + "\n")
    original_open = Path.open
    write_error = OSError("模拟部分内容写入后失败")

    def open_with_fault(path, mode="r", *args, **kwargs):
        """只中断目标及同目录临时文件写入，其他打开操作直接返回真实流。"""
        stream = original_open(path, mode, *args, **kwargs)
        selected = path.parent == destination.parent and (
            path == destination or path.suffix == ".tmp"
        )
        if "w" not in mode or not selected:
            return stream

        @contextmanager
        def partial_stream():
            """仅为目标写入提供故障上下文，始终关闭实际文件描述符。"""
            with stream:
                yield InterruptedWrite(stream, write_error)

        return partial_stream()

    with monkeypatch.context() as fault:
        if case != "success":
            fault.setattr(Path, "open", open_with_fault)
            with pytest.raises(OSError) as error:
                render_artifact(kind, destination, source_path, targets_path)
            assert error.value is write_error
        else:
            render_artifact(kind, destination, source_path, targets_path)
    if case == "existing_failure":
        assert destination.read_text(encoding="utf-8") == previous
    elif case == "new_failure":
        assert not destination.exists()
    else:
        content = json.loads(destination.read_text(encoding="utf-8"))
        assert content and "previous" not in content
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert not list(destination.parent.glob("*.tmp"))
