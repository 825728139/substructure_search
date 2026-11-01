"""独立结构查询任务审查：不将软件正反例当作真实化学先例或专家盲测。"""

import argparse
import json
from pathlib import Path

from rdkit import Chem
from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.retrieval.planner import initial_families
from reaction_reference.rules import code_fingerprint


def evaluate(task):
    """寻找默认计划中覆盖指定连接背景、接受正例且拒绝反例的非精确家族。"""
    target = parse(task["target"])
    anchors = target.GetSubstructMatches(Chem.MolFromSmarts(task["anchor"]))
    candidates = []
    for family in initial_families(target):
        if family.relation == "strict" or not any(
            set(a) <= set(family.target_atoms) for a in anchors
        ):
            continue
        positive = match_family(family, parse(task["positive"]), target, "positive").state
        negative = match_family(family, parse(task["negative"]), target, "negative").state
        candidates.append(
            {
                "rule": family.rule_id,
                "smarts": family.core_smarts,
                "positive": positive,
                "negative": negative,
            }
        )
    return {
        "id": task["id"],
        "question": task["question"],
        "passed": any(c["positive"] == "match" and c["negative"] == "no_match" for c in candidates),
        "candidates": candidates,
    }


def main():
    """从相邻固定任务清单读取结构问题，在标准输出返回可复核结果。"""
    parser = argparse.ArgumentParser(description="核查固定结构任务，不声明专家验证")
    parser.add_argument("--tasks", type=Path, default=Path(__file__).with_name("query_tasks.json"))
    args = parser.parse_args()
    tasks = json.loads(args.tasks.read_text())
    results = [evaluate(task) for task in tasks]
    print(
        json.dumps(
            {
                "implementation_hash": code_fingerprint(),
                "expert_validated": False,
                "passed": sum(r["passed"] for r in results),
                "total": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
