"""只读比较四个原始目标及其等价反转SMILES，使用正式生产适配器与统一预算。"""

import json
import sys
from pathlib import Path

from rdkit import Chem


def main():
    """建立原始/反转目标对，验证结构身份后交给统一计时器，不修改原始输入文件。"""
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "reviews/live_benchmark_2026_10_31"))
    import benchmark

    targets = json.loads((root / "reviews/core_iteration_2026_11_01/targets.json").read_text())
    pairs = []
    for target in targets:
        molecule = Chem.MolFromSmiles(target["smiles"])
        reordered = Chem.RenumberAtoms(molecule, list(reversed(range(molecule.GetNumAtoms()))))
        equivalent = Chem.MolToSmiles(reordered, canonical=False, isomericSmiles=True)
        assert Chem.MolToSmiles(Chem.MolFromSmiles(equivalent)) == Chem.MolToSmiles(molecule)
        pairs.append((target["id"], target["label"], target["smiles"], "原始用户目标"))
        pairs.append(
            (target["id"] + "R", target["label"] + "等价反转", equivalent, "仅改变原子遍历顺序")
        )
    benchmark.TARGETS = pairs
    benchmark.main()


if __name__ == "__main__":
    main()
