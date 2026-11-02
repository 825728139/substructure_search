"""参考排序和实验能力适配：先区分方法资格与证据，再按明确偏好组织展示，保留所有已评估候选。"""

from reaction_reference.chemistry.structures import canonical, parse
from reaction_reference.domain.models import Reference
from reaction_reference.ranking.features import condition_issues, features
from reaction_reference.ranking.scaffold import scaffold_relevance, target_regions
from reaction_reference.ranking.scoring import reference_score


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


def _connection_environment_distance(reference, target, witness_id=None):
    """比较最佳覆盖见证中非芳香原子的氢数与连接数，优先保留目标连接端取代环境。

    芳环远端取代不计此项；该距离只用于结构迁移排序，不推断电子、位阻或实验可行性。
    """
    if target is None or not reference.witnesses:
        return 0
    witness = next((w for w in reference.witnesses if w.id == witness_id), None)
    if witness is None:
        witness = max(reference.witnesses, key=lambda w: (w.target_atom_coverage, w.id))
    source = parse(reference.material.smiles)
    return sum(
        abs(target.GetAtomWithIdx(t).GetTotalNumHs() - source.GetAtomWithIdx(s).GetTotalNumHs())
        + abs(target.GetAtomWithIdx(t).GetTotalDegree() - source.GetAtomWithIdx(s).GetTotalDegree())
        for t, s in witness.target_to_source
        if not target.GetAtomWithIdx(t).GetIsAromatic()
    )


def _recommendation_exclusion(reference):
    """返回主推荐排除原因；保留候选与原始分析供审查，不把未知反应中心当作已证明无关。

    输入使用不提供产物侧目标构建证据；无稳定目标中心投影的结构线索不占方法推荐位。
    完整目标产物仍保留，包括来源观察尚未补齐的记录，且不提升其获得证据标志。
    """
    if reference.material.role == "reactant":
        return "input_usage_without_target_product_transformation"
    if reference.target_requirements_satisfied:
        return None
    projected = reference.coverage.get("projected_changes", {})
    if projected.get("formed_target_bonds") or projected.get("changed_target_atoms"):
        return None
    return (
        "reaction_center_outside_target"
        if projected.get("support") == "single_mapping_inference"
        else "target_reaction_center_unresolved"
    )


def rank_references(
    references, profile="reference_first", context=None, max_display=18, target_smiles=None
):
    """返回（全部已评估参考的排序副本、选中展示的参考 ID 列表）。

    profile选择参考优先、实验适配或操作偏好；context不改结构和来源事实。
    主推荐先检查目标中心与产物资格，再依排序截取max_display项；所有候选保留，
    排除原因写入reasons。缺失来源标记不抹平方法贡献，也不自动产生实验获得证据。
    target_smiles必须保留见证绑定的原始目标原子序，不能预先规范化后重新编号。
    """
    enriched = []
    target = parse(target_smiles) if target_smiles else None
    regions = target_regions(target)
    for reference in references:
        fit, reasons = lab_fit(reference, context)
        ranking_features = reference.ranking_features or features(reference, target_smiles)
        ranking_features = {
            **ranking_features,
            "target_scaffold_relevance": scaffold_relevance(reference, target, regions),
        }
        ranking_features["score"] = reference_score(
            reference,
            target,
            ranking_features["target_scaffold_relevance"],
            _connection_environment_distance(
                reference, target, ranking_features["target_scaffold_relevance"]["witness_id"]
            ),
            profile,
            fit,
            context,
        )
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
                    "reasons": [
                        r for r in reference.reasons if not r.startswith("recommendation_excluded:")
                    ]
                    + (
                        ["recommendation_excluded:" + exclusion]
                        if (exclusion := _recommendation_exclusion(reference))
                        else []
                    ),
                }
            )
        )

    def key(ref):
        """按多维加权总分降序排序；总分完全相同才使用稳定ID，不逐项硬比较。"""
        return (-ref.ranking_features["score"]["total"], ref.id)

    ordered = sorted(enriched, key=key)
    selected: list[Reference] = []
    used: set[str] = set()
    # 仅用资格门槛过滤后按总分截取，不按层级或标签再次改写得分顺序。
    for ref in ordered:
        if (
            ref.id not in used
            and _recommendation_exclusion(ref) is None
            and len(selected) < max_display
        ):
            selected.append(ref)
            used.add(ref.id)
    positions = {r.id: i + 1 for i, r in enumerate(selected)}
    enriched = [r.model_copy(update={"display_position": positions.get(r.id)}) for r in ordered]
    return enriched, [r.id for r in selected]
