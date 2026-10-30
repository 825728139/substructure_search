"""结果范围回归：输入通道的局部缺口和材料关联上限不能被误报为完整或截断。"""

from types import SimpleNamespace

import pytest

import reaction_reference.application.search as search_module
from reaction_reference.adapters.sources import import_native
from reaction_reference.domain.models import QueryFamily
from reaction_reference.evidence.relations import material_relations
from reaction_reference.ports.sources import Candidate, CandidatePage


@pytest.mark.parametrize("gap", ["none", "mapping", "scope", "source_issue", "hydration"])
def test_usage_status_respects_actual_evaluated_scope(request_factory, monkeypatch, gap):
    """输入通道已读完但核验、来源范围或详情有缺口时，只能声明部分完成。"""
    family = QueryFamily(
        id="usage-fragment",
        layer="fragment",
        core_smarts="[C]",
        target_atoms=[0],
        rule_id="test",
        rule_version="1",
        description="输入检索完整性回归",
    )
    monkeypatch.setattr(search_module, "initial_families", lambda *_: [family])
    record = import_native({"id": "input-record", "reactant_smiles": ["CC"]})

    class Source:
        """产品通道为空、输入通道返回一个双碳材料的受控有限来源。"""

        snapshot_id = "usage-scope-test"
        max_selection_stage = 0
        issues = [{"code": "invalid_record"}] if gap == "source_issue" else []

        def candidate_page(self, family, role, cursor, *args):
            """返回已经耗尽的一页，可单独标记输入选择范围不完整。"""
            items = [Candidate("input-structure", record.materials[0], record)]
            return CandidatePage(
                items if role == "reactant" else [],
                None,
                True,
                not (role == "reactant" and gap == "scope"),
                "fixed_dataset_scan",
            )

        def hydrate(self, record):
            """按用例模拟详情失败，其余情况返回同一个完整材料记录。"""
            if gap == "hydration":
                raise TimeoutError("详情读取超时")
            return record

    package = search_module.search(
        request_factory(
            "CC",
            options={
                "include_proposals": False,
                "directed_followups": False,
                "exhaustive_fixture": True,
            },
            budget={"max_tasks": 100, "max_mappings": 1 if gap == "mapping" else 128},
        ),
        Source(),
    )
    assert package.results and not package.stop_reasons
    assert package.feature_status["usage_lookup"].state == (
        "completed" if gap == "none" else "partial"
    )
    assert package.coverage_state == ("complete" if gap == "none" else "partial")


@pytest.mark.parametrize("count", [99, 100, 101])
def test_material_relation_limit_only_marks_real_omission(count):
    """实际关联少于、恰好等于或超过默认上限时，只有确实遗漏关联才报告截断。"""
    producer = import_native({"id": "producer", "product_smiles": ["CCO"]})
    consumers = [
        import_native({"id": f"consumer-{index}", "reactant_smiles": ["CCO"]})
        for index in range(count)
    ]
    references = [SimpleNamespace(record=record) for record in [producer, *consumers]]
    relations, complete = material_relations(references)
    assert len(relations) == min(count, 100)
    assert complete is (count <= 100)
