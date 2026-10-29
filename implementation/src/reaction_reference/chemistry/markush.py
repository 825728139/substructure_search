"""Markush 家族的编译、逐映射 R 条件核验与联合覆盖统计；结构命中和实验事实在不同模块判断。"""

from collections import Counter

from rdkit import Chem

from reaction_reference.chemistry.structures import digest, outside_blocks
from reaction_reference.domain.models import MatchResult, RBlock, Witness


def compile_family(family):
    """从 QueryFamily 的 SMARTS/CXSMARTS 恢复查询 Mol 和原生 generic 属性。

    检查查询原子与 target_atoms 一一对应、核心连通及 R 相等位点合法性。非法表达式抛出 ValueError；不支持的断开核心抛出 NotImplementedError。
    """
    query = Chem.MolFromSmarts(family.core_smarts)
    if query is None or query.GetNumAtoms() != len(family.target_atoms):
        raise ValueError("Invalid core query or target correspondence")
    if len(Chem.GetMolFrags(query)) != 1:
        raise NotImplementedError("Disconnected anchors require a supported path semantics")
    Chem.SetGenericQueriesFromProperties(query)
    for positions in family.equal_r_positions:
        if len(positions) < 2 or any(p < 0 or p >= query.GetNumAtoms() for p in positions):
            raise ValueError("Invalid R-equality positions")
    return query


def _predicates(family, molecule, embedding, blocks):
    """检查某一次固定核心映射下的全部 R 条件，返回 bool。

    embedding 按查询顺序给出来源原子；blocks 必须来自这同一次映射。核验必需/可选/氢、完整块类别和碳数、精确 R 及 R 相等；桥连相等语义尚未支持时抛出 NotImplementedError。
    """
    by_position = {
        p: [b for b in blocks if p in b["core_positions"]] for p in range(len(embedding))
    }
    constrained = {c.position for c in family.r_constraints}
    if not family.allow_extra_substitution and any(
        v for p, v in by_position.items() if p not in constrained
    ):
        return False
    # 同一核心位置可能连接多个相同支链；必需块必须按份数匹配，不能反复使用一个块。
    required = Counter(
        (c.position, c.exact_fragment)
        for c in family.r_constraints
        if c.requirement == "required" and c.exact_fragment is not None
    )
    for (position, fragment), count in required.items():
        if sum(b["fragment"] == fragment for b in by_position[position]) < count:
            return False
    for constraint in family.r_constraints:
        values = by_position[constraint.position]
        if constraint.requirement == "hydrogen":
            if (
                values
                or molecule.GetAtomWithIdx(embedding[constraint.position]).GetTotalNumHs(
                    includeNeighbors=True
                )
                == 0
            ):
                return False
            continue
        if not values:
            if constraint.requirement == "required":
                return False
            continue
        if constraint.exact_fragment is not None and not any(
            b["fragment"] == constraint.exact_fragment for b in values
        ):
            return False
        for block in values:
            if constraint.category != "any":
                if len(block["core_positions"]) != 1 or block["category"] != constraint.category:
                    return False
            if constraint.max_carbons is not None:
                carbons = sum(
                    molecule.GetAtomWithIdx(i).GetAtomicNum() == 6 for i in block["atom_indices"]
                )
                if carbons > constraint.max_carbons:
                    return False
    for positions in family.equal_r_positions:
        # R 端口编号因位置而异；比较支链是否相同时，仅去掉端口的临时映射号。
        signatures = []
        for position in positions:
            values = by_position[position]
            if any(len(b["core_positions"]) != 1 for b in values):
                raise NotImplementedError("R equality on a bridge is not supported")
            local = []
            for block in values:
                fragment = Chem.MolFromSmiles(block["fragment"])
                if fragment is None:
                    raise NotImplementedError("R equality on an unsanitizable cut fragment")
                for atom in fragment.GetAtoms():
                    atom.SetAtomMapNum(0)
                local.append(Chem.MolToSmiles(fragment))
            signatures.append(sorted(local))
        if any(value != signatures[0] for value in signatures[1:]):
            return False
    return True


def match_family(
    family,
    molecule,
    target,
    source_id,
    role="product",
    *,
    max_mappings=128,
    max_visits=10000,
    checkpoint=lambda: None,  # 单独调用默认不检查预算；编排器注入全局检查函数。
):
    """在一个具体来源分子上核验家族并返回 MatchResult 与一致的匹配见证。

    family 描述固定核心和 R 谓词，target 是原始目标 Mol，source_id/role 标明结构及通道。先枚举核心映射，再检查完整 R 块；覆盖扩展必须固定原核心且落在同一个实际支链块。保留对称方向直到后过滤完成，使用 N+1 哨兵识别截断。

    max_mappings/max_visits 限制枚举和遍历；checkpoint 由编排器注入以检查全局预算，异常向上传播。找到见证时可返回 match 且枚举不完整；未找到且已截断只能返回 unknown。本函数不赋予制备证据，也不证明目标立体结果。
    """
    try:
        query = compile_family(family)
    except NotImplementedError as exc:
        return MatchResult(state="unsupported", enumeration_complete=False, reasons=[str(exc)])
    params = Chem.SubstructMatchParameters()
    # 先保留所有对称方向，再逐个检查 R 条件；过早去重可能漏掉合法方向。
    params.uniquify = False  # type: ignore[assignment]
    params.useGenericMatchers = family.use_generic_matchers
    # 多取一个哨兵映射，用于分辨“恰好 N 个”和“还有未枚举的映射”。
    params.maxMatches = max_mappings + 1
    embeddings = molecule.GetSubstructMatches(query, params)
    complete = len(embeddings) <= max_mappings
    try:
        target_blocks = outside_blocks(target, family.target_atoms, max_visits=max_visits)
    except TimeoutError as exc:
        return MatchResult(state="unknown", enumeration_complete=False, reasons=[str(exc)])
    witnesses, seen, reasons = [], set(), []
    checked = 0
    for embedding in embeddings[:max_mappings]:
        checkpoint()
        checked += 1
        inverse = {a: i for i, a in enumerate(embedding)}
        extra = []
        for bond in molecule.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if (
                a in inverse
                and b in inverse
                and query.GetBondBetweenAtoms(inverse[a], inverse[b]) is None
            ):
                extra.append((min(inverse[a], inverse[b]), max(inverse[a], inverse[b])))
        if extra and family.core_topology_policy == "forbid_extra_internal_edges":
            continue
        try:
            blocks = outside_blocks(molecule, embedding, max_visits=max_visits)
            if not _predicates(family, molecule, embedding, blocks):
                continue
        except (TimeoutError, NotImplementedError) as exc:
            complete = False
            reasons.append(str(exc))
            continue
        correspondence = dict(zip(family.target_atoms, embedding, strict=False))
        covered_r = set()
        used_source_blocks = set()
        # 只用完整 R 块的一致对应扩展覆盖，不能把不同映射的最佳支链任意拼在一起。
        for tb in target_blocks:
            for block_index, sb in enumerate(blocks):
                if (
                    block_index not in used_source_blocks
                    and tb["core_positions"] == sb["core_positions"]
                    and tb["fragment"] == sb["fragment"]
                ):
                    # 扩展查询必须仍满足本次已固定的核心映射。
                    # 通过真实子图匹配取原子对应，不能假设两侧排序后的编号恰好对齐。
                    atom_ids = sorted(set(family.target_atoms) | set(tb["atom_indices"]))
                    tagged = Chem.Mol(target)
                    for atom in tagged.GetAtoms():
                        atom.SetAtomMapNum(atom.GetIdx() + 1)
                    extended_smarts = Chem.MolFragmentToSmarts(tagged, atomsToUse=atom_ids)
                    extended_query = Chem.MolFromSmarts(extended_smarts)
                    if extended_query is None:
                        continue
                    ep = Chem.SubstructMatchParameters()
                    ep.uniquify = False  # type: ignore[assignment]
                    ep.maxMatches = max_mappings + 1
                    # 这里的覆盖只描述连接关系；切片后四面体环境可能不完整。
                    # 完整目标的立体要求由 meets_target 单独核验。
                    ep.useChirality = False  # type: ignore[assignment]
                    extensions = molecule.GetSubstructMatches(extended_query, ep)
                    if len(extensions) > max_mappings:
                        complete = False
                        reasons.append("r_correspondence_enumeration_limit")
                    for match in extensions[:max_mappings]:
                        checkpoint()
                        pairs = {
                            atom.GetAtomMapNum() - 1: match[atom.GetIdx()]
                            for atom in extended_query.GetAtoms()
                        }
                        if all(
                            pairs[a] == b
                            for a, b in zip(family.target_atoms, embedding, strict=False)
                        ):
                            additions = {a: pairs[a] for a in tb["atom_indices"]}
                            if set(additions.values()) != set(sb["atom_indices"]):
                                continue
                            if len(set(correspondence.values()) | set(additions.values())) == len(
                                correspondence
                            ) + len(additions):
                                correspondence.update(additions)
                                covered_r.update(tb["core_positions"])
                                used_source_blocks.add(block_index)
                                break
                    # 当前块无法在固定核心下扩展时，继续寻找其他实际支链块。
                    if block_index in used_source_blocks:
                        break
        key = (tuple(sorted(correspondence.items())), tuple(b["fragment"] for b in blocks))
        if key in seen:
            continue
        seen.add(key)
        covered_bonds = 0
        for bond in target.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if a in correspondence and b in correspondence:
                other = molecule.GetBondBetweenAtoms(correspondence[a], correspondence[b])
                covered_bonds += other is not None and other.GetBondType() == bond.GetBondType()
        heavy_covered = sum(target.GetAtomWithIdx(a).GetAtomicNum() > 1 for a in correspondence)
        witnesses.append(
            Witness(
                id=digest([family.id, source_id, key]),
                family_id=family.id,
                source_structure_id=source_id,
                matched_role=role,
                target_to_source=sorted(correspondence.items()),
                core_source_atoms=list(embedding),
                blocks=[RBlock(**b) for b in blocks],
                matched_r_positions=sorted(covered_r),
                extra_core_edges=extra,
                target_atom_coverage=heavy_covered / max(1, target.GetNumHeavyAtoms()),
                target_bond_coverage=covered_bonds / max(1, target.GetNumBonds()),
            )
        )
    if len(witnesses) > 1:
        witnesses = [
            w.model_copy(update={"mapping_status": "alternative_witness"}) for w in witnesses
        ]
    return MatchResult(
        state="match" if witnesses else "no_match" if complete else "unknown",
        witnesses=witnesses,
        mappings_checked=checked,
        enumeration_complete=complete,
        reasons=sorted(set(reasons)),
    )


def coverage_summary(witnesses, target, enumeration_complete):
    """汇总已得到的见证，分别返回最佳单见证联合覆盖和跨见证位点并集。

    witnesses 可以来自多个家族；enumeration_complete 只描述调用方已评估范围。位点并集用于发现缺口，不能当作同一分子的联合 R 组合；最佳已发现值不声明为全部可能家族的全局最优。
    """
    if not witnesses:
        return {
            "joint_witness": None,
            "sitewise_union": [],
            "enumeration_complete": enumeration_complete,
        }
    # 最佳单见证先比较原子、再比较键覆盖，最后按 ID 固定并列次序。
    best = max(witnesses, key=lambda w: (w.target_atom_coverage, w.target_bond_coverage, w.id))
    return {
        "joint_witness": {
            "witness_id": best.id,
            "atom_coverage": best.target_atom_coverage,
            "bond_coverage": best.target_bond_coverage,
            "r_positions": best.matched_r_positions,
        },
        "sitewise_union": sorted({a for w in witnesses for a, _ in w.target_to_source}),
        "sitewise_union_atom_coverage": len(
            {
                a
                for w in witnesses
                for a, _ in w.target_to_source
                if target.GetAtomWithIdx(a).GetAtomicNum() > 1
            }
        )
        / target.GetNumHeavyAtoms(),
        "enumeration_complete": enumeration_complete,
        "best_found_is_proven_maximum": False,
        "maximum_scope": "best_found_within_evaluated_families_and_mappings",
        "coverage_semantics": "connectivity_with_elements_isotopes_and_bond_types; stereo_validated_separately_for_complete_target",
    }
