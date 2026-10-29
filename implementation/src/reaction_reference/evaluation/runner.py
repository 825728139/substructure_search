"""有限真实目标评测：分别运行保留/屏蔽目标来源记录的任务，未经审核的相关性不计得分。"""

import json
import time
from dataclasses import replace
from pathlib import Path

from rdkit import rdBase

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.chemistry.structures import (
    canonical,
    digest,
    meets_target,
    parse,
    similarity,
)
from reaction_reference.domain.models import BudgetConfig, SearchOptions, SearchRequest, Target
from reaction_reference.rules import code_fingerprint, load_rules


class MaskedSource:
    """评测装饰器，按完整目标要求排除所有含该产物的反应记录，而非只排展示卡片。"""

    def __init__(self, source, target):
        """从固定样本找出满足 target 的产品记录 ID，并据此建立派生来源快照。

        整个记录被排除，避免通过其反应物使用通道再次泄漏目标来源；不是对已确认制备标签的推断。
        """
        self.source = source
        self.issues = source.issues
        self.target = target
        self.excluded = {
            r.id
            for r in source.records
            if any(
                m.role == "product" and meets_target(parse(m.smiles), target) for m in r.materials
            )
        }
        self.snapshot_id = digest(
            [source.snapshot_id, sorted(self.excluded), "entire_source_record_mask"]
        )

    def candidate_page(self, *args, **kwargs):
        """委托原来源取页后移除被屏蔽记录，保留原范围、耗尽状态与游标。

        过滤后空页仍可能有 next_cursor，不能将空页当作查询结束。
        """
        page = self.source.candidate_page(*args, **kwargs)
        return replace(
            page, items=[item for item in page.items if item.record.id not in self.excluded]
        )

    def hydrate(self, record):
        """委托底层来源加载一个未被屏蔽的已命中记录，不创建新证据。"""
        return self.source.hydrate(record)

    def close(self):
        """不关闭底层共享来源；评测主函数负责在两种任务完成后统一释放。"""
        pass


def select_targets(source_path, output, count=12):
    """从有限非合成产品中用最远优先的指纹距离选出结构多样的目标。

    source_path 为样本 JSONL，output 写目标 JSONL，count 为 1–100。标签默认 unreviewed，返回数量/路径；结构多样性选样不等同于有用方法人工标注或独立泛化集。
    """
    if not 1 <= count <= 100:
        raise ValueError("Target count must be 1..100")
    source = JsonlSource(source_path)
    candidates: dict = {}
    for item, mol, _ in source.candidates:
        if item.material.role != "product" or item.record.source.synthetic:
            continue
        try:
            parse(item.material.smiles, target=True)
        except ValueError:
            continue
        candidates.setdefault(canonical(mol), (mol, item.record))
    if len(candidates) < count:
        raise ValueError(
            f"Only {len(candidates)} distinct concrete non-synthetic targets are available"
        )
    keys = sorted(candidates)
    chosen = [keys[0]]
    distances = {s: 1 - similarity(candidates[s][0], candidates[chosen[0]][0]) for s in keys[1:]}
    while len(chosen) < count:
        # 选离当前目标集合最远的候选；规范结构字符串用于稳定并列次序。
        selected = max(distances, key=lambda s: (distances[s], s))
        chosen.append(selected)
        del distances[selected]
        for key in distances:
            distances[key] = min(
                distances[key], 1 - similarity(candidates[key][0], candidates[selected][0])
            )
    rows = [
        {
            "id": f"real-target-{i + 1:02}",
            "target_smiles": key,
            "source": candidates[key][1].source.model_dump(),
            "source_record_id": candidates[key][1].id,
            "label_state": "unreviewed",
            "useful_method_record_ids": None,
        }
        for i, key in enumerate(chosen)
    ]
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    source.close()
    return {"targets": len(rows), "label_state": "unreviewed", "path": str(destination)}


def evaluate(source_path, targets_path, output, *, max_tasks=100):
    """逐目标运行保留来源与屏蔽全部目标产物记录两种任务并写入 JSON 报告。

    source_path/targets_path 是固定样本和显式目标集，max_tasks 限制每次搜索。只对 reviewed 且有标签的目标计算正例标注召回；未知标签不填成 0 或满分。报告记录代码/规则/来源哈希、耗时、范围与停止原因，不能外推千万级性能。
    """
    targets = [
        json.loads(line) for line in Path(targets_path).read_text().splitlines() if line.strip()
    ]
    if not 1 <= len(targets) <= 100:
        raise ValueError("Evaluation requires 1..100 explicit targets")
    source = JsonlSource(source_path, exhaustive=True)
    results = []
    for row in targets:
        target = parse(row["target_smiles"], target=True)
        for mode in ("observed_target", "masked_target_preparation_records"):
            selected = source if mode == "observed_target" else MaskedSource(source, target)
            request = SearchRequest(
                target=Target(value=row["target_smiles"]),
                options=SearchOptions(exhaustive_fixture=True),
                budget=BudgetConfig(max_tasks=max_tasks, time_ms=10000, max_candidates=10000),
            )
            started = time.monotonic()
            package = search(request, selected)
            returned = {ref.record.id for ref in package.results if ref.material.role == "product"}
            displayed = {
                ref.record.id
                for ref in package.results
                if ref.id in package.displayed_reference_ids and ref.material.role == "product"
            }
            gold = row.get("useful_method_record_ids")
            reviewed = row.get("label_state") == "reviewed" and gold is not None
            eligible = set(gold or []) - getattr(selected, "excluded", set())
            results.append(
                {
                    "target_id": row["id"],
                    "target_smiles": package.target_smiles,
                    "mode": mode,
                    "excluded_record_ids": sorted(getattr(selected, "excluded", set())),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "statistics": package.statistics,
                    "coverage_state": package.coverage_state,
                    "stop_reasons": package.stop_reasons,
                    "source_issue_count": len(package.source_issues),
                    "structural_exact_target_found": any(
                        ref.material.role == "product" and ref.target_requirements_satisfied
                        for ref in package.results
                    ),
                    "returned_record_ids": sorted(returned),
                    "displayed_record_ids": sorted(displayed),
                    "method_relevance_label_state": "reviewed"
                    if reviewed
                    else "unreviewed_not_scored",
                    "annotated_method_recall": len(eligible & returned) / len(eligible)
                    if reviewed and eligible
                    else None,
                    "annotated_display_recall": len(eligible & displayed) / len(eligible)
                    if reviewed and eligible
                    else None,
                    "annotation_exhaustiveness": "positive_only_precision_not_inferred",
                    "summary_bytes": len(package.summary.encode()),
                }
            )
    report = {
        "schema_version": "1",
        "implementation_hash": code_fingerprint(),
        "rule_hash": load_rules()[1],
        "rdkit_version": rdBase.rdkitVersion,
        "source_snapshot": source.snapshot_id,
        "targets_hash": digest(targets, 64),
        "target_count": len(targets),
        "case_count": len(results),
        "cases": results,
        "limits": [
            "bounded_sample_not_full_corpus",
            "structural_hits_are_not_method_relevance_labels",
            "masking_uses_complete_target_connectivity_and_requirements_not_preparation_counts",
            "not_a_model_training_or_route_success_evaluation",
            "no_10_million_reaction_performance_claim",
        ],
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    source.close()
    return {
        "targets": len(targets),
        "cases": len(results),
        "path": str(destination),
        "method_relevance": "see_explicit_label_state_per_case",
    }
