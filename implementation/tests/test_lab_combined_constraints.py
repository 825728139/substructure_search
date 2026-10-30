"""实验限制组合回归：已知违规优先，未知资料保留，排序及模型摘要保持同一结论。"""

import json

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.domain.models import Conditions, LabContext


@pytest.mark.parametrize("profile", ["lab_fit", "process_reference"])
def test_combined_constraints_survive_sorting_summary_and_source_order(
    tmp_path, request_factory, amide, profile
):
    """通过真实导入与检索验证九种组合，压力/设备违规不能被缺失项掩盖，输入顺序不改变结论。"""
    cases = [
        ("pass", {}, "documented_step", True, "pass", []),
        (
            "boundary",
            {"pressure_max_kpa": 200, "equipment": []},
            "documented_step",
            True,
            "pass",
            [],
        ),
        (
            "pressure_fail",
            {"pressure_max_kpa": 201, "equipment": None},
            "documented_step",
            True,
            "fail",
            ["pressure_outside_capability", "equipment_requirements_unknown"],
        ),
        (
            "equipment_fail",
            {"pressure_max_kpa": None, "equipment": ["autoclave"]},
            "documented_step",
            True,
            "fail",
            ["pressure_unknown", "required_equipment_unavailable"],
        ),
        (
            "pressure_missing",
            {"pressure_max_kpa": None},
            "documented_step",
            True,
            "unknown",
            ["pressure_unknown"],
        ),
        (
            "equipment_missing",
            {"equipment": None},
            "documented_step",
            True,
            "unknown",
            ["equipment_requirements_unknown"],
        ),
        (
            "unassigned_step",
            {},
            "source_record_net",
            True,
            "unknown",
            ["condition_event_scope_not_assigned"],
        ),
        (
            "temperature_missing_pressure_fail",
            {"temperature_min_c": None, "temperature_max_c": None, "pressure_max_kpa": 201},
            "documented_step",
            True,
            "fail",
            ["temperature_min_unknown", "temperature_max_unknown", "pressure_outside_capability"],
        ),
        (
            "inventory_unknown",
            {},
            "documented_step",
            None,
            "unknown",
            ["material_inventory_completeness_unknown"],
        ),
    ]
    rows = []
    expected = {}
    for name, condition_updates, scope, inventory, fit, reasons in cases:
        record = amide.model_copy(
            update={
                "id": name,
                "source": amide.source.model_copy(
                    update={"record_id": name, "experiment_id": name}
                ),
                "event_scope": scope,
                "conditions": Conditions(
                    **{
                        **amide.conditions.model_dump(),
                        "pressure_max_kpa": 100,
                        **condition_updates,
                    }
                ),
                "raw": {**amide.raw, "material_inventory_complete": inventory},
            }
        )
        rows.append(record.model_dump_json())
        expected[name] = fit, reasons
    outcomes = []
    for reverse in (False, True):
        path = tmp_path / f"conditions-{reverse}.jsonl"
        path.write_text("\n".join(reversed(rows) if reverse else rows) + "\n")
        source = JsonlSource(path, exhaustive=True)
        try:
            package = search(
                request_factory(
                    amide.materials[-1].smiles,
                    ranking_profile=profile,
                    lab_context=LabContext(
                        min_temperature_c=20,
                        max_temperature_c=30,
                        max_pressure_kpa=200,
                        available_equipment=["stirrer"],
                        excluded_material_smiles=["CCO"],
                    ),
                    options={
                        "exhaustive_fixture": True,
                        "include_usage": False,
                        "include_proposals": False,
                        "directed_followups": False,
                    },
                    budget={"max_tasks": 100},
                ),
                source,
            )
        finally:
            source.close()
        assert len(package.results) == len(cases) and not package.source_issues
        assert not package.statistics["preparation_hits"]
        summary = {entry["reference_id"]: entry for entry in json.loads(package.summary)}
        groups = []
        for reference in package.results:
            fit, reasons = expected[reference.record.id]
            assert reference.lab_fit == fit
            assert set(reasons) <= set(reference.lab_reasons)
            assert summary[reference.id]["lab_fit"] == fit
            assert summary[reference.id]["lab_reasons"] == reference.lab_reasons
            groups.append({"pass": 0, "unknown": 1, "fail": 2}[fit])
        assert groups == sorted(groups)
        outcomes.append([(r.id, r.lab_fit, r.lab_reasons) for r in package.results])
    assert outcomes[0] == outcomes[1]
