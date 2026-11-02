"""目标驱动的有限查询规划：按三层规则生成可解释家族，保留原子对应；不预先猜测开闭环反应位置。"""

import json
from itertools import combinations

from rdkit import Chem
from rdkit.Chem import BRICS
from rdkit.Chem.Scaffolds import MurckoScaffold

from reaction_reference.chemistry.structures import digest, outside_blocks
from reaction_reference.domain.models import QueryFamily, RConstraint
from reaction_reference.rules import load_rules


def functional_matches(mol):
    """按规则优先级识别官能团，返回（规则名、目标原子元组、优先级）列表。

    允许重叠匹配，结果用于固定功能单元及解释；不能将重叠条目数量直接视为独立反应位点数量。
    """
    rules, _ = load_rules()
    found: list[tuple[str, tuple[int, ...], int]] = []
    # 高优先级官能团先处理，避免后续核心补全受随机规则顺序影响。
    for rule in sorted(rules["functional_groups"], key=lambda r: -r["priority"]):
        query = Chem.MolFromSmarts(rule["smarts"])
        found.extend(
            (rule["id"], match, rule["priority"]) for match in mol.GetSubstructMatches(query)
        )
    return found


def _close_units(seed, groups, mol, *, adjacent=False):
    """把与 seed 相交的功能单元补入核心原子集合并返回新集合。

    adjacent=True 时也检查与当前核心相邻的单元；反复补齐直到集合稳定，避免官能团命中顺序决定是否保留整个连接单元。仅加入已有目标原子，迭代有限。
    """
    result = set(seed)
    while True:
        previous = set(result)
        for _, match, _ in groups:
            if result.intersection(match) or (
                adjacent
                and any(
                    n.GetIdx() in result
                    for index in match
                    for n in mol.GetAtomWithIdx(index).GetNeighbors()
                )
            ):
                result.update(match)
        if result == previous:
            return result


def _core_smarts(mol, atom_ids, groups):
    """为选定目标原子构造带目标映射号的固定核心 SMARTS。

    返回（SMARTS、查询原子顺序对应的原目标索引）。保留元素、芳香性、电荷、同位素和相邻同位素氢；羟基额外锁定 H/X 角色。序列化后重新读映射号，避免遍历顺序变化造成位点错配。
    """
    atom_ids = set(atom_ids)
    atom_ids |= {
        n.GetIdx()
        for i in list(atom_ids)
        for n in mol.GetAtomWithIdx(i).GetNeighbors()
        if n.GetAtomicNum() == 1 and n.GetIsotope()
    }
    atom_ids = sorted(atom_ids)
    index = {old: new for new, old in enumerate(atom_ids)}
    rw = Chem.RWMol()
    hydroxyl = {match[0] for name, match, _ in groups if name == "hydroxyl"}
    for old in atom_ids:
        atom = mol.GetAtomWithIdx(old)
        isotope = str(atom.GetIsotope()) if atom.GetIsotope() else ""
        aromatic = "a" if atom.GetIsAromatic() else "A"
        charge = atom.GetFormalCharge()
        q = f"{isotope}#{atom.GetAtomicNum()};{aromatic};{charge:+d}"
        if old in hydroxyl:
            q += ";H1;X2"
        query_atom = Chem.AtomFromSmarts(f"[{q}]")
        query_atom.SetAtomMapNum(old + 1)
        rw.AddAtom(query_atom)
    for bond in mol.GetBonds():
        a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if a in index and b in index:
            rw.AddBond(index[a], index[b], bond.GetBondType())
    smarts = Chem.MolToSmarts(rw.GetMol())
    restored = Chem.MolFromSmarts(smarts)
    return smarts, [a.GetAtomMapNum() - 1 for a in restored.GetAtoms()]


def _aromatic_domains(mol):
    """返回由芳香键连接的芳香原子域，联苯的单键不合并两个域。

    用于保留稠合体系中的完整芳香部分，不要求相邻非芳香环也存在；不产生断键方案或预测环变化。
    """
    remaining = {a.GetIdx() for a in mol.GetAtoms() if a.GetIsAromatic()}
    domains = []
    while remaining:
        root = min(remaining)
        remaining.remove(root)
        domain, stack = {root}, [root]
        while stack:
            atom = stack.pop()
            for bond in mol.GetAtomWithIdx(atom).GetBonds():
                other = bond.GetOtherAtomIdx(atom)
                if bond.GetIsAromatic() and other in remaining:
                    remaining.remove(other)
                    domain.add(other)
                    stack.append(other)
        domains.append(domain)
    return domains


def _attachment_environment(target, core, block, groups):
    """保留支链连接原子及其一层重原子邻域，并补齐相交官能团和完整环。

    仅在该实际连通块内扩展，不沿核心把其他支链带入。闭包直到稳定，避免规则顺序截断酰胺、酯或稠环；多端口桥连块完整保留。远端变化只是查询放宽，不证明化学等价。
    """
    allowed = set(block["atom_indices"])
    if len(block["core_positions"]) > 1:
        return allowed
    roots = {
        i
        for i in allowed
        if any(n.GetIdx() in core for n in target.GetAtomWithIdx(i).GetNeighbors())
    }
    local = roots | {
        n.GetIdx()
        for i in roots
        for n in target.GetAtomWithIdx(i).GetNeighbors()
        if n.GetIdx() in allowed
    }
    units = [set(atoms) & allowed for _, atoms, _ in groups]
    units += [set(ring) & allowed for ring in target.GetRingInfo().AtomRings()]
    while True:
        previous = set(local)
        for unit in units:
            if unit & local:
                local.update(unit)
        if local == previous:
            return local


def _attachment_seeds(target, core, groups, limit=12):
    """生成核心与一条、两条实际支链的连通组合，保持原始连接位置。

    每项先尝试连接端环境，再保留完整块；同一桥连块完整加入，不能把多端口块拆成互不相关的支链。单项与双项组合交替，最多返回limit项，防止支链子集指数爆炸；不预测切断反应，也不声明取代可迁移。
    """
    blocks = outside_blocks(target, sorted(core))
    # 优先包含已识别功能单元的块，其次是含杂原子的块；只是查询机会分配，不是活性评分。
    blocks.sort(
        key=lambda block: (
            -max(
                (
                    priority
                    for _, atoms, priority in groups
                    if set(atoms) & set(block["atom_indices"])
                ),
                default=0,
            ),
            -sum(
                target.GetAtomWithIdx(i).GetAtomicNum() not in (1, 6) for i in block["atom_indices"]
            ),
            len(block["atom_indices"]),
            tuple(block["atom_indices"]),
        )
    )
    singles = iter((block,) for block in blocks)
    pairs = combinations(blocks, 2)
    result: list[tuple[set[int], str]] = []
    seen: set[tuple[int, ...]] = set()
    while len(result) < limit:
        added = False
        round_variants = []
        for stream, count in ((singles, 1), (pairs, 2)):
            choice = next(stream, None)
            if choice is None:
                continue
            added = True
            full = set(core).union(*(set(block["atom_indices"]) for block in choice))
            local = set(core).union(
                *(_attachment_environment(target, core, block, groups) for block in choice)
            )
            variants = (
                [(local, f"core_attachment_environment:{count}")] if local != full else []
            ) + [(full, f"core_attachment_combination:{count}")]
            round_variants.append(variants)
        # 先给单支链与双支链各一次机会，再补同一组合的完整远端版本。
        for variant_index in (0, 1):
            for variants in round_variants:
                if variant_index >= len(variants):
                    continue
                atoms, rule = variants[variant_index]
                atoms = _close_units(atoms, groups, target)
                key = tuple(sorted(atoms))
                if key not in seen and atoms != set(core):
                    seen.add(key)
                    result.append((atoms, rule))
                if len(result) >= limit:
                    break
            if len(result) >= limit:
                break
        if not added:
            break
    return result


def plan_families(target, max_families=12):
    """按规范原子遍历规划家族，再将查询映射回用户原始目标索引。

    仅消除SMILES书写起点和原子排序对有限查询选择的影响；不改目标电荷、同位素、立体或互变形式。对称等价位点允许等价对应，身份仍通过具体见证核验。
    """
    ordering_view = Chem.Mol(target)
    for atom in ordering_view.GetAtoms():
        atom.SetAtomMapNum(0)
    Chem.MolToSmiles(ordering_view, canonical=True, isomericSmiles=True)
    order = json.loads(ordering_view.GetProp("_smilesAtomOutputOrder"))
    ordered = Chem.RenumberAtoms(target, order)
    planned = _plan_ordered_families(ordered, max_families)
    families = []
    for family in planned:
        query = Chem.MolFromSmarts(family.core_smarts)
        for atom in query.GetAtoms():
            atom.SetAtomMapNum(order[family.target_atoms[atom.GetIdx()]] + 1)
        expression = Chem.MolToSmarts(query)
        ids = [atom.GetAtomMapNum() - 1 for atom in Chem.MolFromSmarts(expression).GetAtoms()]
        families.append(
            family.model_copy(
                update={
                    "id": digest((family.layer, tuple(ids), expression)),
                    "core_smarts": expression,
                    "target_atoms": ids,
                    "description": f"{family.layer}: {family.rule_id}; 固定原目标原子 {ids}，其他取代可变",
                }
            )
        )
    return families


def _plan_ordered_families(target, max_families=12):
    """自动生成整体、核心、分片三层的有限 QueryFamily 列表。

    环状目标使用 Murcko 骨架、完整环系和官能团邻域；无环目标使用全框架或功能锚点路径。核心补充完整支链的单项与双项组合，分片补充 BRICS 非环边界。轮流取各层种子以保留各层机会，按层和目标原子集合去重，最多返回 max_families 个家族；这不是所有可能骨架或专家查询策略的穷举。
    """
    rules, _ = load_rules()
    groups = functional_matches(target)
    all_atoms = {a.GetIdx() for a in target.GetAtoms() if a.GetAtomicNum() > 1}
    scaffold = MurckoScaffold.GetScaffoldForMol(target)
    scaffold_match = target.GetSubstructMatch(scaffold) if scaffold.GetNumAtoms() else ()
    whole = (
        _close_units(set(scaffold_match), groups, target, adjacent=True)
        if scaffold_match
        else all_atoms
    )
    seeds = {
        "whole": [
            (
                whole,
                "whole_murcko_with_adjacent_functional_units"
                if scaffold_match
                else "acyclic_full_framework",
            )
        ],
        "core": [],
        "fragment": [],
    }
    rings = [set(r) for r in target.GetRingInfo().AtomRings()]
    systems = []
    while rings:
        group = rings.pop(0)
        changed = True
        while changed:
            changed = False
            for ring in rings[:]:
                if group & ring:
                    group |= ring
                    rings.remove(ring)
                    changed = True
        systems.append(group)
    # 先安排连接更复杂的完整环系，再比较杂原子数与大小；规范索引仅用于稳定并列。
    # 这是检索问题的排序，不是合成难度或反应可行性评分。
    systems.sort(
        key=lambda system: (
            -(
                sum(
                    b.GetBeginAtomIdx() in system and b.GetEndAtomIdx() in system
                    for b in target.GetBonds()
                )
                - len(system)
                + 1
            ),
            -sum(target.GetAtomWithIdx(i).GetAtomicNum() not in (1, 6) for i in system),
            -len(system),
            tuple(sorted(system)),
        )
    )
    for system in systems:
        seeds["core"].append((_close_units(system, groups, target), "complete_ring_system"))
    anchors = set()
    for _, match, _ in groups:
        anchors.update(match)
    if not systems:
        # 无环单组分是树：同一根锚点到其余锚点的路径并集，等于全部两两路径的并集。
        # 固定原始锚点列表，不能把路径中新加入的原子再次当作待连接锚点。
        anchor_ids = sorted(anchors)
        if anchor_ids:
            for other in anchor_ids[1:]:
                anchors.update(Chem.GetShortestPath(target, anchor_ids[0], other))
        seeds["core"].append(
            (_close_units(anchors or all_atoms, groups, target), "acyclic_functional_anchor_paths")
        )
    aromatic_seeds = []
    local_seeds = []
    aromatic_domains = _aromatic_domains(target)
    for name, match, _ in groups:
        neighborhood = set(match)
        for atom in match:
            neighborhood.update(
                n.GetIdx()
                for n in target.GetAtomWithIdx(atom).GetNeighbors()
                if n.GetAtomicNum() > 1
            )
        # 直接连接环境不强制带上整个环系；通过后续环内外谓词保留局部拓扑角色。
        local_seeds.append(
            (
                _close_units(neighborhood, groups, target),
                f"functional_connection_environment:{name}",
            )
        )
        # 环外官能团连接混合稠合环系时，补查完整芳香域，避免强制保留非芳香杂环而漏掉前体。
        # 仅在确实省去非芳香环原子时增加家族；完整环系查询仍保留，不把它当成开环预测。
        if not any(target.GetAtomWithIdx(i).IsInRing() for i in match):
            for domain in aromatic_domains:
                if neighborhood & domain and any(domain < system for system in systems):
                    aromatic_seeds.append(
                        (
                            _close_units(neighborhood | domain, groups, target),
                            f"aromatic_domain_functional_neighborhood:{name}",
                        )
                    )
        # 官能团邻域若碰到环系，则保留完整环系；此处不猜测开环前体。
        for system in systems:
            if neighborhood & system:
                neighborhood |= system
        seeds["fragment"].append(
            (_close_units(neighborhood, groups, target), f"functional_neighborhood:{name}")
        )
    seeds["fragment"] = aromatic_seeds + local_seeds + seeds["fragment"]
    for (a, b), _ in BRICS.FindBRICSBonds(target):
        if target.GetBondBetweenAtoms(a, b).IsInRing():
            continue
        cut = Chem.RWMol(target)
        cut.RemoveBond(a, b)
        for component in Chem.GetMolFrags(cut):
            heavy = set(component) & all_atoms
            if len(heavy) >= 2:
                seeds["fragment"].append(
                    (_close_units(heavy, groups, target), "nonring_boundary_fragment")
                )
    if not seeds["fragment"]:
        seeds["fragment"].append((all_atoms, "full_chain_local_fallback"))
    if not seeds["core"]:
        seeds["core"].append((whole, "framework_core_fallback"))
    # 每个核心优先覆盖裸骨架、单/双位点，再安排同一组合的不同远端精度。
    bare_cores = list(seeds["core"])
    attachment_streams = []
    environment_atoms: dict[tuple, set[int]] = {}
    for core, _ in bare_cores:
        candidates = _attachment_seeds(target, core, groups, limit=max_families)
        attachment_streams.append(iter(candidates))
        for atoms, rule in candidates:
            if rule.startswith(("core_attachment_environment:", "core_attachment_combination:")):
                identity = (tuple(sorted(atoms)), rule)
                # 相同查询由不同核心派生时，只约束共同的支链部分，不能误锁核心R位点。
                local = set(atoms) - set(core)
                environment_atoms[identity] = environment_atoms.get(identity, local) & local
    seeds["core"] = []
    attachments = []
    for bare, stream in zip(bare_cores, attachment_streams, strict=True):
        # 对每个核心先覆盖裸骨架、单连接、双连接三个问题，再切换核心。
        # 同一支链的局部/完整版本不能抢占双位点关系的首轮机会。
        seeds["core"].append(bare)
        deferred = []
        selected_counts = set()
        for candidate in stream:
            count = candidate[1].rsplit(":", 1)[-1]
            if count not in selected_counts:
                seeds["core"].append(candidate)
                selected_counts.add(count)
            else:
                deferred.append(candidate)
            if len(selected_counts) == 2:
                break
        deferred.extend(stream)
        # 后续完整版本仍可在预算充足时被选择，不能永久删除。
        attachments.extend(deferred)
    seeds["core"].extend(attachments)
    families: list[QueryFamily] = []
    seen: set[tuple] = set()
    # 按层轮流取种子，使整体、核心、分片都有进入有限家族预算的机会。
    while len(families) < max_families and any(seeds.values()):
        for layer in ("whole", "core", "fragment"):
            if not seeds[layer] or len(families) >= max_families:
                continue
            atoms, rule = seeds[layer].pop(0)
            if not atoms:
                continue
            # 单独苯环缺少连接端信息，容易召回与目标合成无关的芳环转化。
            # 仍用它派生带支链查询；杂芳环、稠环及完整苯目标不受此限制。
            if (
                len(atoms) == 6
                and atoms != all_atoms
                and any(atoms == set(ring) for ring in target.GetRingInfo().AtomRings())
                and all(
                    target.GetAtomWithIdx(i).GetAtomicNum() == 6
                    and target.GetAtomWithIdx(i).GetIsAromatic()
                    and not target.GetAtomWithIdx(i).GetIsotope()
                    for i in atoms
                )
            ):
                continue
            smarts, ids = _core_smarts(target, atoms, groups)
            if rule == "acyclic_full_framework":
                # 完整无环框架不能仅凭环中的一段路径命中；局部类比仍由其他家族提供。
                query = Chem.MolFromSmarts(smarts)
                for atom in query.GetAtoms():
                    atom.ExpandQuery(Chem.AtomFromSmarts("[!R]"))
                    original = target.GetAtomWithIdx(ids[atom.GetIdx()])
                    # 无环内部连接及杂原子保留H/X；末端碳仍允许链延长类比。
                    if original.GetAtomicNum() != 6 or original.GetDegree() > 1:
                        atom.ExpandQuery(
                            Chem.AtomFromSmarts(
                                f"[H{original.GetTotalNumHs(includeNeighbors=True)};X{original.GetTotalDegree()}]"
                            )
                        )
                smarts = Chem.MolToSmarts(query)
            if rule.startswith("functional_connection_environment:"):
                query = Chem.MolFromSmarts(smarts)
                fixed = set(ids)
                for position, original in enumerate(ids):
                    atom = target.GetAtomWithIdx(original)
                    query_atom = query.GetAtomWithIdx(position)
                    query_atom.ExpandQuery(
                        Chem.AtomFromSmarts("[R]" if atom.IsInRing() else "[!R]")
                    )
                    if all(
                        n.GetAtomicNum() == 1 or n.GetIdx() in fixed for n in atom.GetNeighbors()
                    ):
                        query_atom.ExpandQuery(
                            Chem.AtomFromSmarts(
                                f"[H{atom.GetTotalNumHs(includeNeighbors=True)};X{atom.GetTotalDegree()}]"
                            )
                        )
                for bond in query.GetBonds():
                    source_bond = target.GetBondBetweenAtoms(
                        ids[bond.GetBeginAtomIdx()], ids[bond.GetEndAtomIdx()]
                    )
                    bond.ExpandQuery(Chem.BondFromSmarts("@" if source_bond.IsInRing() else "!@"))
                smarts = Chem.MolToSmarts(query)
            if rule.startswith(("core_attachment_environment:", "core_attachment_combination:")):
                # 完整支链与局部环境都锁定内部原子的H/X；局部边界仍允许远端变化。
                # 这是目标连接端的结构约束，避免CH3与CF3、一级与三级中心静默等同。
                query = Chem.MolFromSmarts(smarts)
                fixed = set(ids)
                local = environment_atoms[(tuple(sorted(atoms)), rule)]
                for position, original in enumerate(ids):
                    atom = target.GetAtomWithIdx(original)
                    if original in local and all(
                        n.GetAtomicNum() == 1 or n.GetIdx() in fixed for n in atom.GetNeighbors()
                    ):
                        query.GetAtomWithIdx(position).ExpandQuery(
                            Chem.AtomFromSmarts(
                                f"[H{atom.GetTotalNumHs(includeNeighbors=True)};X{atom.GetTotalDegree()}]"
                            )
                        )
                smarts = Chem.MolToSmarts(query)
            key = (layer, tuple(ids), smarts)
            if key in seen:
                continue
            seen.add(key)
            families.append(
                QueryFamily(
                    id=digest(key),
                    layer=layer,
                    core_smarts=smarts,
                    target_atoms=ids,
                    rule_id=rule,
                    rule_version=rules["version"],
                    description=f"{layer}: {rule}; fixed atoms {ids}; other substituents variable",
                )
            )
    return families


def directed_family(parent, target, positions):
    """针对缺失核心位点，将目标实际 R 块加为精确约束后返回子家族。

    parent 保留原核心与目标对应，positions 是查询核心的位置而非目标全分子索引。没有可约束 R 块时返回 None；不猜测新反应或虚构前体。
    """
    blocks = outside_blocks(target, parent.target_atoms)
    constraints = list(parent.r_constraints)
    requested = []
    for block in blocks:
        if set(block["core_positions"]) & set(positions):
            # 桥连块可能两次连接同一核心原子，但它仍是一个实际支链块。
            for position in sorted(set(block["core_positions"])):
                constraint = RConstraint(
                    position=position, requirement="required", exact_fragment=block["fragment"]
                )
                requested.append(constraint)
                # 同位点多个相同支链需要保留份数；已有父约束只抵扣对应份数。
                if requested.count(constraint) > constraints.count(constraint):
                    constraints.append(constraint)
    if constraints == parent.r_constraints:
        return None
    return parent.model_copy(
        update={
            "id": digest([parent.id, [c.model_dump() for c in constraints]]),
            "parent_id": parent.id,
            "r_constraints": constraints,
            "trigger": "missing_site_or_joint_assignment",
            "description": f"Directed follow-up at target core positions {sorted(set(positions))}",
        }
    )


def progressive_followups(parent, target, witnesses, limit=2):
    """根据已核验见证逐个补查缺失支链，再尝试尚未共存的位点组合。

    各位点分别出现不能视为同一分子共同满足。桥连块的全部端口作为一个问题；精确约束继承父查询。没有见证不把查询失败推断成化学缺口，最多返回limit项，不预测前体或条件。
    """
    if (
        not witnesses
        or limit <= 0
        or parent.trigger == "completed_exact_attachment_scope_without_match"
    ):
        return []
    blocks = outside_blocks(target, parent.target_atoms)
    desired = {p for block in blocks for p in block["core_positions"]}
    covered = [set(w.matched_r_positions) for w in witnesses]
    if not desired or any(desired <= positions for positions in covered):
        return []
    missing = [
        set(block["core_positions"])
        for block in blocks
        if not any(set(block["core_positions"]) <= positions for positions in covered)
    ]
    # 位点问题按目标位置稳定排列；先单块再联合，不能一次锁死全部尚无依据的支链。
    questions = sorted(missing, key=lambda positions: tuple(sorted(positions))) + [desired]
    result: list[QueryFamily] = []
    for positions in questions:
        child = directed_family(parent, target, positions)
        if child and all(child.id != existing.id for existing in result):
            child = child.model_copy(
                update={
                    "trigger": "missing_attachment_block"
                    if positions != desired
                    else "missing_joint_assignment",
                    "description": f"根据已核验命中补查核心位点 {sorted(positions)}；保留其他位点变化空间",
                }
            )
            result.append(child)
            if len(result) >= limit:
                break
    return result


def relax_exact_attachments(parent, target):
    """将自动定向家族的精确支链放宽为连接端环境，保留原核心谓词与来源链。

    仅处理能在目标实际R块中完整对账的必需精确约束；其他类别、碳数、相等或CX语义不猜测。局部环境与完整支链相同时不生成伪放宽；该函数不判断无命中，调用方须先核实查询范围完成。
    """
    if (
        parent.trigger not in ("missing_attachment_block", "missing_joint_assignment")
        or parent.relation != "structural_family"
        or not parent.r_constraints
        or parent.equal_r_positions
        or not parent.allow_extra_substitution
        or "|" in parent.core_smarts
        or any(
            c.requirement != "required"
            or c.exact_fragment is None
            or c.category != "any"
            or c.max_carbons is not None
            for c in parent.r_constraints
        )
    ):
        return None
    blocks = outside_blocks(target, parent.target_atoms)
    selected = [
        block
        for block in blocks
        if any(
            c.position in block["core_positions"] and c.exact_fragment == block["fragment"]
            for c in parent.r_constraints
        )
    ]
    if any(
        sum(
            c.position in block["core_positions"] and c.exact_fragment == block["fragment"]
            for block in selected
        )
        < parent.r_constraints.count(c)
        for c in parent.r_constraints
    ):
        return None
    core = set(parent.target_atoms)
    groups = functional_matches(target)
    local = core.union(
        *(_attachment_environment(target, core, block, groups) for block in selected)
    )
    full = core.union(*(set(block["atom_indices"]) for block in selected))
    if local == full:
        return None
    smarts, ids = _core_smarts(target, local, groups)
    query = Chem.RWMol(Chem.MolFromSmarts(smarts))
    original = Chem.MolFromSmarts(parent.core_smarts)
    if original is None or original.GetNumAtoms() != len(parent.target_atoms):
        return None
    positions = {atom: i for i, atom in enumerate(ids)}
    for old, atom in enumerate(parent.target_atoms):
        query.ReplaceAtom(positions[atom], original.GetAtomWithIdx(old))
    for bond in original.GetBonds():
        left, right = (
            positions[parent.target_atoms[i]]
            for i in (bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())
        )
        new_bond = query.GetBondBetweenAtoms(left, right)
        if new_bond is None:
            return None
        query.ReplaceBond(new_bond.GetIdx(), bond)
    # 只锁定新增局部内部原子，原核心谓词逐个复制，边界仍可接其他远端结构。
    for atom in local - core:
        original_atom = target.GetAtomWithIdx(atom)
        if all(n.GetAtomicNum() == 1 or n.GetIdx() in local for n in original_atom.GetNeighbors()):
            query.GetAtomWithIdx(positions[atom]).ExpandQuery(
                Chem.AtomFromSmarts(
                    f"[H{original_atom.GetTotalNumHs(includeNeighbors=True)};X{original_atom.GetTotalDegree()}]"
                )
            )
    expression = Chem.MolToSmarts(query)
    restored_ids = [atom.GetAtomMapNum() - 1 for atom in Chem.MolFromSmarts(expression).GetAtoms()]
    if set(restored_ids) != set(ids) or len(restored_ids) != len(ids):
        return None
    return parent.model_copy(
        update={
            "id": digest([parent.id, "relax_exact_attachments", expression]),
            "parent_id": parent.id,
            "core_smarts": expression,
            "target_atoms": restored_ids,
            "r_constraints": [],
            "rule_id": "relaxed_attachment_environment",
            "trigger": "completed_exact_attachment_scope_without_match",
            "description": "精确支链查询范围完成且无匹配后，保留连接端环境、放宽远端；不是精确支链命中",
        }
    )


def exact_family(target):
    """构造完整目标补查家族，保留 SMARTS 序列化后的目标原子对应。

    返回 relation=strict 的整体层家族；编排器仍须调用 meets_target 核验完整结构与目标立体要求，不能仅凭核心子结构命中认定目标已制得。
    """
    tagged = Chem.Mol(target)
    for atom in tagged.GetAtoms():
        atom.SetAtomMapNum(atom.GetIdx() + 1)
    smarts = Chem.MolToSmarts(tagged)
    atoms = [a.GetAtomMapNum() - 1 for a in Chem.MolFromSmarts(smarts).GetAtoms()]
    return QueryFamily(
        id=digest(["strict_target", Chem.MolToSmiles(target)]),
        layer="whole",
        core_smarts=smarts,
        target_atoms=atoms,
        relation="strict",
        allow_extra_substitution=False,
        rule_id="strict_target_requirements",
        rule_version=load_rules()[0]["version"],
        description="Complete target outcome lookup; stereo and isotope requirements verified separately",
    )


def initial_families(target, max_families=12, include_exact=True):
    """组合初始三层家族与可选的严格目标补查，返回有顺序的列表。

    max_families 是本次家族上限；预算仅为 3 且启用补查时，严格整体、核心、分片各留一个位置。较大预算下给两个定向家族和一次无匹配后的放宽预留空间；预览和真实检索共用此入口。
    """
    planned = plan_families(target, max(3, max_families - (4 if include_exact else 3)))
    if not include_exact:
        return planned
    if max_families == 3:
        return [exact_family(target)] + [
            next(f for f in planned if f.layer == layer) for layer in ("core", "fragment")
        ]
    return ([exact_family(target)] + planned)[:max_families]
