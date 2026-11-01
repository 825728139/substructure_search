"""新目标的只读化学方法检索审查，目标预期在首次查询前固定。"""

import json
import sys
from pathlib import Path


def main():
    """加载预先固定的六个目标与化学问题，沿用正式来源和统一默认预算。"""
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "reviews/live_benchmark_2026_10_31"))
    import benchmark

    targets = json.loads(Path(__file__).with_name("targets.json").read_text())
    benchmark.TARGETS = [(t["id"], t["label"], t["smiles"], t["expectation"]) for t in targets]
    benchmark.main()


if __name__ == "__main__":
    main()
