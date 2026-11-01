"""目标驱动的有限查询规划：按三层规则生成可解释家族，保留原子对应；不预先猜测开闭环反应位置。"""

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

    adjacent=True 时也检查与当前核心相邻的单元；按已排序规则单次遍历，后续规则可看到已扩展的集合，不是任意深度的闭包求解。
    """
    result = set(seed)
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
    aromatic_domains = _aromatic_domains(target)
    for name, match, _ in groups:
        neighborhood = set(match)
        for atom in match:
            neighborhood.update(
                n.GetIdx()
                for n in target.GetAtomWithIdx(atom).GetNeighbors()
                if n.GetAtomicNum() > 1
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
    seeds["fragment"] = aromatic_seeds + seeds["fragment"]
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
            if rule.startswith("core_attachment_environment:"):
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
            smarts, ids = _core_smarts(target, atoms, groups)
            if rule.startswith("core_attachment_environment:"):
                # 完全包含其重原子邻居的局部原子锁定H/X；边界原子仍允许远端变化。
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
    constraints = []
    for block in blocks:
        if set(block["core_positions"]) & set(positions):
            # 桥连块可能两次连接同一核心原子，但它仍是一个实际支链块。
            for position in sorted(set(block["core_positions"])):
                constraints.append(
                    RConstraint(
                        position=position, requirement="required", exact_fragment=block["fragment"]
                    )
                )
    if not constraints:
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

    max_families 是本次家族上限；预算仅为 3 且启用补查时，严格整体、核心、分片各留一个位置。较大预算下给后续定向家族预留空间；预览和真实检索共用此入口。
    """
    planned = plan_families(target, max(3, max_families - (3 if include_exact else 2)))
    if not include_exact:
        return planned
    if max_families == 3:
        return [exact_family(target)] + [
            next(f for f in planned if f.layer == layer) for layer in ("core", "fragment")
        ]
    return ([exact_family(target)] + planned)[:max_families]
