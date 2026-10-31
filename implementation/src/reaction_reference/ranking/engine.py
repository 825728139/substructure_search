"""参考排序和实验能力适配：先区分方法资格与证据，再按明确偏好组织展示，保留所有已评估候选。"""

from reaction_reference.chemistry.structures import canonical, parse
from reaction_reference.ranking.features import condition_issues, features


def lab_fit(reference, context):
    """将参考条件与 LabContext 的温度、压力、设备和排除材料要求比较。

    返回（pass/fail/unknown/not_applicable、原因列表）；任一已知违规优先为 fail。缺失资料不能证明符合要求，但已知温度端点足以证明越界时仍为 fail；倒置范围保持 unknown。记录未分配到明确操作步骤时，不把净记录条件当作已确认步骤条件。
    """
    if context is None:
        return "not_applicable", ["lab_context_not_configured"]
    conditions = reference.record.conditions
    issues = condition_issues(conditions)
    failures, unknown, tested = [], [], 0
    checks = [
        (
            context.max_temperature_c,
            conditions.temperature_max_c,
            "temperature_max",
            lambda a, b: b <= a,  # 来源最高温度不能超过实验上限。
        ),
        (
            context.min_temperature_c,
            conditions.temperature_min_c,
            "temperature_min",
            lambda a, b: b >= a,  # 来源最低温度不能低于实验下限。
        ),
        # 压力谓词同样按“来源值不超过实验上限”判断，单位为 kPa。
        (context.max_pressure_kpa, conditions.pressure_max_kpa, "pressure", lambda a, b: b <= a),
    ]
    for requirement, actual, label, predicate in checks:
        if requirement is None:
            continue
        tested += 1
        if label.startswith("temperature") and "temperature" in issues:
            if issues["temperature"] not in unknown:
                unknown.append(issues["temperature"])
            continue
        if actual is None:
            # 只报告最低 100°C 也足以否定最高 50°C 的能力；低温方向同理。
            # 另一端未越界只能保留未知，不能把它补成缺失端点后判通过。
            opposite = (
                conditions.temperature_min_c
                if label == "temperature_max"
                else conditions.temperature_max_c
                if label == "temperature_min"
                else None
            )
            if opposite is not None and not predicate(requirement, opposite):
                failures.append(label + "_outside_capability")
            else:
                unknown.append(label + "_unknown")
        elif not predicate(requirement, actual):
            failures.append(label + "_outside_capability")
    if context.excluded_material_smiles:
        tested += 1
        excluded = {canonical(s) for s in context.excluded_material_smiles}
        found = set()
        identity_unknown = False
        for material in reference.record.materials:
            try:
                found.add(canonical(material.smiles))
            except ValueError:
                identity_unknown = True
        # 脏材料只增加未知项，不能抹掉其他已识别材料触发的明确禁用结论。
        if excluded & found:
            failures.append("explicitly_excluded_material")
        if identity_unknown:
            unknown.append("material_identity_unknown")
        # 来源材料列表不完整时，“没有列出禁用物”不能视为已确认符合限制。
        # 自由元数据不做布尔强制转换，只有明确的 True 才能证明清单完整。
        if reference.record.raw.get("material_inventory_complete") is not True:
            unknown.append("material_inventory_completeness_unknown")
    if context.available_equipment is not None:
        tested += 1
        if conditions.equipment is None:
            unknown.append("equipment_requirements_unknown")
        elif not set(conditions.equipment) <= set(context.available_equipment):
            failures.append("required_equipment_unavailable")
    if reference.record.event_scope != "documented_step":
        unknown.append("condition_event_scope_not_assigned")
    return (
        "fail" if failures else "unknown" if unknown else "pass" if tested else "not_applicable",
        failures + unknown,
    )


def _priority(reference):
    """返回参考的方法/证据优先级，数值越小越优先。

    满足完整目标且有获得证据的记录优先；仅图推定或未确认输入不得获得已报告方法相同的资格。
    """
    if reference.target_requirements_satisfied and reference.obtainment_hit:
        return 0
    if not reference.obtainment_hit and not reference.use_hit:
        # 图推定的方法标签不构成实验支持，不能先于结构覆盖把相关骨架压在无关小片段后面。
        return 6
    return {
        "connection_method": 1,
        "local_method": 2,
        "modification": 3,
        "target_outcome": 3,
        "usage": 4,
        "structure_clue": 5,
        "unknown": 6,
    }[reference.contribution]


def rank_references(
    references, profile="reference_first", context=None, max_display=18, target_smiles=None
):
    """返回（全部已评估参考的排序副本、选中展示的参考 ID 列表）。

    profile 选择参考优先、实验适配或操作偏好；context 只改变适配判断，不改结构和来源事实。补充九方向字段后采用确定性排序，保留完整目标获得记录并轮流分配三层展示位置；max_display 只裁剪展示，不删除候选池。
    """
    enriched = []
    target_heavy_atoms = parse(target_smiles).GetNumHeavyAtoms() if target_smiles else None
    for reference in references:
        fit, reasons = lab_fit(reference, context)
        ranking_features = reference.ranking_features or features(reference, target_smiles)
        issues = condition_issues(reference.record.conditions)
        if issues:
            # 冻结参考可能来自旧版本；补充当前异常解释时不修改旧快照中的事实字典。
            operation = ranking_features.get("operation_equipment", {})
            ranking_features = {
                **ranking_features,
                "operation_equipment": {
                    **operation,
                    "limitations": list(
                        dict.fromkeys(operation.get("limitations", []) + list(issues.values()))
                    ),
                },
            }
        enriched.append(
            reference.model_copy(
                update={
                    "lab_fit": fit,
                    "lab_reasons": reasons,
                    "ranking_features": ranking_features,
                }
            )
        )

    def key(ref):
        """为单个参考生成可传递且稳定的排序元组。

        先排方法与证据，再在明确偏好下比较已知信息组及温度偏离 25°C/时长；实验适配模式增加能力分组。未知条件不填成容易操作，最终使用参考 ID 固定并列顺序。
        """
        joint = ref.coverage.get("joint_witness") or {}
        coverage = joint.get("atom_coverage", 0)
        # 用同一见证的共享重原子同时衡量两侧覆盖，避免“大分子包含目标小片段”获得虚高优先级。
        balanced_coverage = (
            2
            * coverage
            * target_heavy_atoms
            / (target_heavy_atoms + parse(ref.material.smiles).GetNumHeavyAtoms())
            if target_heavy_atoms
            else coverage
        )
        evidence = (
            0
            if ref.obtainment_hit
            else 1
            if any(c.support == "source_reported" for c in ref.claims)
            else 2
        )
        # 缺失条件不获得低温或容易操作的奖励。
        # 先固定信息可用分组，再用排序键比较，避免成对比较出现循环次序。
        conditions = ref.record.conditions
        issues = condition_issues(conditions)
        availability = (
            conditions.temperature_min_c is not None
            and conditions.temperature_max_c is not None
            and "temperature" not in issues,
            conditions.duration_seconds is not None and "duration" not in issues,
        )
        process: tuple = ()
        if profile == "process_reference":
            # 只在同等已知字段分组中比较条件数值。
            # 未知温度/时间不能按零值或容易操作处理。
            burden = (
                max(abs(conditions.temperature_min_c - 25), abs(conditions.temperature_max_c - 25))
                if availability[0]
                else 0,
                conditions.duration_seconds if availability[1] else 0,
            )
            process = (
                sum(not known for known in availability),
                tuple(not known for known in availability),
                burden,
            )
        base = (
            _priority(ref),
            evidence,
            -balanced_coverage,
            -joint.get("atom_coverage", 0),
            *process,
            -ref.similarity,
            ref.id,
        )
        if profile != "reference_first" and context is not None:
            return ({"pass": 0, "unknown": 1, "not_applicable": 1, "fail": 2}[ref.lab_fit],) + base
        return base

    ordered = sorted(enriched, key=key)
    selected, used = [], set()
    # 完整目标的已报告获得记录全局保留；即使只是脱保护，也不被分层配额挤掉。
    exact = next((r for r in ordered if r.target_requirements_satisfied and r.obtainment_hit), None)
    if exact:
        selected.append(exact)
        used.add(exact.id)
    for _ in range(4):
        for layer in ("whole", "core", "fragment"):
            candidate = next((r for r in ordered if layer in r.layers and r.id not in used), None)
            if candidate and len(selected) < max_display:
                selected.append(candidate)
                used.add(candidate.id)
    for ref in ordered:
        if ref.id not in used and len(selected) < max_display:
            selected.append(ref)
            used.add(ref.id)
    positions = {r.id: i + 1 for i, r in enumerate(selected)}
    enriched = [r.model_copy(update={"display_position": positions.get(r.id)}) for r in ordered]
    return enriched, [r.id for r in selected]
