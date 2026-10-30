"""实验统计回归：来源内重复抽取归并，来源命名空间之间的同名实验不能误合并。"""

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search


@pytest.mark.parametrize(
    "namespaces,expected",
    [
        (["source-a", "source-b"], 2),
        (["source-a", "source-a"], 1),
        (["source-a", "source-a", "source-b"], 2),
    ],
)
def test_experiment_counts_include_source_namespace(
    tmp_path, amide, request_factory, namespaces, expected
):
    """全局及三层的实验、制备和使用统计必须统一采用带来源范围的实验身份。"""
    rows = []
    for index, namespace in enumerate(namespaces):
        record = amide.model_copy(
            update={
                "id": f"count-record-{index}",
                "source": amide.source.model_copy(
                    update={
                        "namespace": namespace,
                        "record_id": f"count-record-{index}",
                        "experiment_id": "experiment-1",
                        # 仅用于测试已报告事实的计数，不是真实实验数据。
                        "synthetic": False,
                    }
                ),
            }
        )
        rows.append(record.model_dump_json())
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                "CCN",
                options={
                    "exhaustive_fixture": True,
                    "include_proposals": False,
                    "directed_followups": False,
                },
                budget={"max_tasks": 100},
            ),
            source,
        )
        assert len(package.results) == 2 * len(namespaces)
        assert package.statistics["unique_experiments"] == expected
        assert package.statistics["preparation_hits"] == expected
        assert package.statistics["usage_hits"] == expected
        for layer in ("whole", "core", "fragment"):
            counts = package.statistics["by_layer"][layer]
            assert counts["unique_experiments"] == expected
            assert counts["qualified_preparation_experiments"] == expected
    finally:
        source.close()
