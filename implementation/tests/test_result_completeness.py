"""结果范围回归：输入通道的局部缺口和材料关联上限不能被误报为完整或截断。"""

import json
from types import SimpleNamespace

import pytest

import reaction_reference.application.search as search_module
from reaction_reference.adapters.sources import JsonlSource, import_native
from reaction_reference.chemistry.structures import canonical
from reaction_reference.domain.models import Observation, QueryFamily
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


@pytest.mark.parametrize(
    "product,input_smiles,linked,complete",
    [
        ("*CC", "*CC", False, False),
        ("CC.[Na+]", "CC.[Na+]", False, False),
        ("C[C@H](F)Cl |&1:1|", "C[C@H](F)Cl", False, False),
        ("invalid(", "invalid(", False, False),
        ("[13CH3]CO", "[13CH3]CO", True, True),
        ("C[C@H](F)Cl", "C[C@@H](F)Cl", False, True),
    ],
)
def test_material_relations_respect_supported_identity_scope(
    tmp_path, request_factory, product, input_smiles, linked, complete
):
    """关联必须使用检索认可的具体材料身份；坏材料不抹掉有效关联，也不伪报枚举完整。"""
    producer = import_native({"id": "producer", "product_smiles": ["CCO", product]})
    producer = producer.model_copy(
        update={
            "observations": [
                Observation(
                    product_instance_id=producer.materials[-1].instance_id,
                    result="reported_prepared",
                    evidence_text="仅用于验证关联支持的测试声明，不是真实实验。",
                    source_location="测试资料",
                )
            ]
        }
    )
    consumer = import_native({"id": "consumer", "reactant_smiles": ["CCO", input_smiles]})
    consumer = consumer.model_copy(
        update={
            "materials": [m.model_copy(update={"actual_input": True}) for m in consumer.materials]
        }
    )
    references = [SimpleNamespace(record=record) for record in (producer, consumer)]
    relations, actual_complete = material_relations(references)
    expected = {"CCO"} | ({canonical(product)} if linked else set())
    assert {relation["material_smiles"] for relation in relations} == expected
    assert actual_complete is complete
    if linked:
        matching = next(r for r in relations if r["material_smiles"] == canonical(product))
        assert matching["support"] == "reported_preparation_and_use"
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n".join(json.dumps(record.model_dump()) for record in (producer, consumer)) + "\n",
        encoding="utf-8",
    )
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search_module.search(
            request_factory(
                "CCO",
                options={
                    "include_proposals": False,
                    "directed_followups": False,
                    "exhaustive_fixture": True,
                },
                budget={"max_tasks": 100},
            ),
            source,
        )
        assert {reference.record.id for reference in package.results} == {
            producer.id,
            consumer.id,
        }
        assert {relation["material_smiles"] for relation in package.material_relations} == expected
        assert package.feature_status["returned_material_relations"].state == (
            "completed" if complete else "partial"
        )
    finally:
        source.close()
