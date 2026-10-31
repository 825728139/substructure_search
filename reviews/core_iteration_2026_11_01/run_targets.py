"""复测用户指定四个目标，使用统一基准与正式v3适配器，目标仅作为评测数据。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reviews/live_benchmark_2026_10_31"))


def main():
    """加载归档的原始四目标，沿用基准脚本的连接、预算和计时，不修改业务查询。"""
    import benchmark

    targets = json.loads(Path(__file__).with_name("targets.json").read_text())
    benchmark.TARGETS = [(t["id"], t["label"], t["smiles"], t["selection_reason"]) for t in targets]
    benchmark.main()


if __name__ == "__main__":
    main()
