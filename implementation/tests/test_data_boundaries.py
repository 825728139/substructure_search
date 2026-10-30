"""数据边界回归：来源身份、重排校验、快照归属和样本原子导出。"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reaction_reference.adapters import export as sample_export
from reaction_reference.adapters.run_store import FileRunStore, RevisionConflict
from reaction_reference.adapters.sources import JsonlSource, import_native
from reaction_reference.domain.models import (
    LabContext,
    ReferencePackage,
    RerankRequest,
    RunState,
)
from reaction_reference.interfaces.sdk import Client


def empty_snapshot(store, request):
    """保存无命中资料包，让校验测试不依赖任何化学匹配结果。"""
    run_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=run_id,
        lifecycle="succeeded",
        request=request,
        created_at=now,
        updated_at=now,
    )
    package = ReferencePackage(
        run_id=run_id,
        snapshot_id="a" * 24,
        target_smiles=request.target.value,
        target_atoms=[],
        source_snapshot="fixture",
        manifest={},
        families=[],
        results=[],
        coverage_state="partial",
    )
    store.create(state)
    store.save_package(package)
    return state, package


@pytest.mark.parametrize(
    "missing",
    [
        {"document_id": None},
        {"document_id": " "},
        {"paragraph_nums": None},
        {"paragraph_nums": []},
        {"paragraph_nums": [""]},
        {"paragraph_nums": [None]},
        {"paragraph_nums": ["10", None]},
        {"paragraph_nums": " "},
        {"paragraph_reaction_ordinal": None},
        {"paragraph_reaction_ordinal": ""},
        {"paragraph_reaction_ordinal": False},
    ],
)
def test_incomplete_source_locator_does_not_merge_different_records(missing):
    """实验定位不完整时按来源记录身份计数，不能把不同反应拼成同一实验。"""
    locator = {
        "document_id": "US-example",
        "paragraph_nums": [10],
        "paragraph_reaction_ordinal": 0,
        **missing,
    }
    first = import_native({"id": 1, "product_smiles": ["CCO"], **locator})
    second = import_native({"id": 2, "product_smiles": ["CCO"], **locator})
    assert first.source.experiment_id != second.source.experiment_id


def test_complete_source_locator_still_groups_duplicate_experiment_records():
    """完整文献、段落与反应序号仍表示同一实验，序号零是合法值。"""
    locator = {"document_id": "US-example", "paragraph_nums": [10], "paragraph_reaction_ordinal": 0}
    first = import_native({"id": 1, "product_smiles": ["CCO"], **locator})
    second = import_native({"id": 2, "product_smiles": ["CCO"], **locator})
    assert first.source.experiment_id == second.source.experiment_id


def test_native_record_components_cannot_collide_at_delimiters(tmp_path):
    """命名空间和记录编号中的分隔符不能把不同合法记录拼成同一个 ID 并一起丢弃。"""
    rows = [
        {"source_namespace": "archive:collection", "id": "entry"},
        {"source_namespace": "archive", "id": "collection:entry"},
        {"source_namespace": "archive%3Acollection", "id": "entry"},
    ]
    path = tmp_path / "identities.jsonl"
    path.write_text(
        "".join(json.dumps({**row, "product_smiles": ["CCO"]}) + "\n" for row in rows),
        encoding="utf-8",
    )
    source = JsonlSource(path)
    try:
        assert len(source.records) == 3 and not source.issues
        assert len({record.id for record in source.records}) == 3
        assert {record.source.namespace for record in source.records} == {
            row["source_namespace"] for row in rows
        }
    finally:
        source.close()


def test_experiment_components_cannot_collide_at_delimiters():
    """不同命名空间及文档的完整实验定位也必须保持唯一，字面转义符不能产生新碰撞。"""
    locators = [
        {"source_namespace": "archive", "document_id": "collection:document"},
        {"source_namespace": "archive:collection", "document_id": "document"},
        {"source_namespace": "archive", "document_id": "collection%3Adocument"},
    ]
    records = [
        import_native(
            {"id": index, "paragraph_nums": [10], "paragraph_reaction_ordinal": 0, **locator}
        )
        for index, locator in enumerate(locators, 1)
    ]
    assert len({record.source.experiment_id for record in records}) == 3


@pytest.mark.parametrize("record_id", [None, "", " ", True])
def test_missing_native_record_id_is_rejected(record_id):
    """导出行缺少有效记录 ID 时应隔离该行，不能转换成共享的 None 或空身份。"""
    with pytest.raises(ValueError, match="record ID"):
        import_native({"id": record_id, "product_smiles": ["CCO"]})


def test_empty_rerank_validates_exclusions_before_creating_run(settings, request_factory):
    """即使没有参考项触发排序循环，无效实验排除结构仍应拒绝且不创建派生任务。"""
    with Client(settings) as client:
        state, _ = empty_snapshot(client.manager.store, request_factory())
        request = RerankRequest(lab_context=LabContext(excluded_material_smiles=["invalid("]))
        with pytest.raises(ValueError, match="[Ee]xcluded"):
            client.rerank(state.run_id, request)
        assert len(list(settings.store_path.glob("*/state.json"))) == 1


@pytest.mark.parametrize("part", ["state", "package_run", "package_snapshot"])
def test_stored_identity_must_match_requested_file(settings, request_factory, part):
    """文件内容误放到其他任务或快照路径时必须报冲突，不能返回错配资料。"""
    store = FileRunStore(settings.store_path)
    state, package = empty_snapshot(store, request_factory())
    directory = settings.store_path / state.run_id
    if part == "state":
        (directory / "state.json").write_text(
            state.model_copy(update={"run_id": "f" * 32}).model_dump_json()
        )
        with pytest.raises(RevisionConflict):
            store.load(state.run_id)
    else:
        changes = {"run_id": "f" * 32} if part == "package_run" else {"snapshot_id": "b" * 24}
        path = directory / f"snapshot-{package.snapshot_id}.json"
        path.write_text(package.model_copy(update=changes).model_dump_json())
        with pytest.raises(RevisionConflict):
            store.package(state.run_id)


class SampleConnection:
    """仅在内存返回样本的连接替身，不访问真实来源。"""

    def __init__(self):
        """准备两条具有非 ASCII 文本的记录，供完整导出和半途失败使用。"""
        self.rows = [{"id": 1, "document_id": "中文来源"}, {"id": 2, "document_id": "第二条"}]

    def __enter__(self):
        """返回受上下文管理的连接替身。"""
        return self

    def __exit__(self, *_):
        """内存连接没有外部资源。"""
        return None

    def execute(self, *args, **kwargs):
        """接受只读查询并保留统一的结果读取入口。"""
        return self

    def fetchone(self):
        """返回固定快照标识。"""
        return {"snapshot": "test-snapshot"}

    def fetchall(self):
        """返回有限样本记录。"""
        return self.rows


def sample_connection(monkeypatch):
    """替换连接函数，保证导出回归只访问本地临时文件。"""
    connection = SampleConnection()

    def connect(*args, **kwargs):
        """返回已准备的内存连接。"""
        return connection

    monkeypatch.setattr("psycopg.connect", connect)
    return connection


def test_failed_export_is_not_published_and_can_retry(tmp_path, monkeypatch):
    """第二条记录序列化失败时，不能留下看似完整的最终文件，并且允许同路径重试。"""
    sample_connection(monkeypatch)
    destination = tmp_path / "sample.jsonl"
    original = json.dumps

    def fail_second(value, *args, **kwargs):
        """只模拟第二条记录写入前的失败，使旧实现已经写出第一行。"""
        if value.get("id") == 2:
            raise ValueError("模拟样本序列化失败")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(sample_export.json, "dumps", fail_second)
    with pytest.raises(ValueError, match="模拟样本"):
        sample_export.export_sample("test-only", destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))
    monkeypatch.setattr(sample_export.json, "dumps", original)
    result = sample_export.export_sample("test-only", destination)
    assert result["records"] == 2
    rows = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["document_id"] == "中文来源"
    assert all(row["export_snapshot"] == "test-snapshot" for row in rows)


def test_export_never_overwrites_existing_file(tmp_path, monkeypatch):
    """同名文件已存在时保持原样，不论其内容是否是有效 JSONL。"""
    sample_connection(monkeypatch)
    destination = tmp_path / "sample.jsonl"
    destination.write_text("已有文件", encoding="utf-8")
    with pytest.raises(FileExistsError):
        sample_export.export_sample("test-only", destination)
    assert destination.read_text(encoding="utf-8") == "已有文件"


def test_concurrent_export_keeps_the_first_published_file(tmp_path, monkeypatch):
    """另一写入者在最终发布前抢先创建文件时，不覆盖它，并清理本次临时文件。"""
    sample_connection(monkeypatch)
    destination = tmp_path / "sample.jsonl"
    original = sample_export.os.link

    def publish_race(source, target):
        """模拟检查路径为空后，另一进程恰好先发布结果。"""
        Path(target).write_text("另一项导出", encoding="utf-8")
        return original(source, target)

    monkeypatch.setattr(sample_export.os, "link", publish_race)
    with pytest.raises(FileExistsError):
        sample_export.export_sample("test-only", destination)
    assert destination.read_text(encoding="utf-8") == "另一项导出"
    assert not list(tmp_path.glob("*.tmp"))


def test_export_publication_failure_does_not_leave_output(tmp_path, monkeypatch):
    """最终发布失败时也应删除临时文件，避免无效导出占用目标路径。"""
    sample_connection(monkeypatch)
    destination = tmp_path / "sample.jsonl"

    def failed_publish(*args):
        """模拟目标文件发布时的权限错误。"""
        raise PermissionError("模拟发布失败")

    monkeypatch.setattr(sample_export.os, "link", failed_publish)
    with pytest.raises(PermissionError):
        sample_export.export_sample("test-only", destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))
