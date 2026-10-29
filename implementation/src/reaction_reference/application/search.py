"""核心编排入口：家族队列→来源分页→具体材料核验→反应贡献→来源约束建议→排序资料包。依赖来源端口，不直接依赖 HTTP 或具体数据库。"""

import time
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from rdkit import rdBase

from reaction_reference.analogs.transfer import generate_proposals
from reaction_reference.application.budget import Budget, BudgetExceeded
from reaction_reference.chemistry.markush import coverage_summary, match_family
from reaction_reference.chemistry.structures import (
    atom_table,
    canonical,
    descriptors,
    digest,
    meets_target,
    outside_blocks,
    parse,
    similarity,
)
from reaction_reference.domain.models import (
    FeatureStatus,
    Proposal,
    ReactionAnalysis,
    Reference,
    ReferencePackage,
)
from reaction_reference.evidence.claims import evidence_for, summary_items
from reaction_reference.evidence.relations import material_relations
from reaction_reference.ranking.engine import rank_references
from reaction_reference.reaction_analysis.analyze import analyze_reaction, project_changes
from reaction_reference.retrieval.planner import directed_family, initial_families
from reaction_reference.rules import code_fingerprint, load_rules


def search(request, source, *, run_id=None, on_progress=None):
    """执行一次目标导向的参考检索，返回 ReferencePackage，并可发布阶段快照。

    request 是已校验的 SearchRequest；source 实现候选分页和按需加载端口；run_id 可由协调器提供；on_progress 接收完整包，用于持久化阶段结果。来源资源由调用方关闭，本函数不接管连接生命周期。

    内部同时维护家族/角色/选择阶段队列、结构匹配缓存、来源加载缓存和反应分析缓存。来源或映射不足记录为局部未知；预算耗尽停止扩展，保留已完成事实并尝试有限替换分析。异常只在已定义的局部边界降级，不把未评估范围记为完整无命中。
    """
    # ① 解析目标并规划查询：所有家族位置最终都回指原始输入的原子编号。
    budget = Budget(request.budget)
    run_id = run_id or uuid.uuid4().hex
    target = parse(request.target.value, target=True)
    target_smiles = canonical(target)
    rules, rule_hash = load_rules()
    families = initial_families(
        target, request.budget.max_families, request.options.include_exact_identity
    )
    family_lookup = {f.id: f for f in families}
    states: dict[str, dict] = {}
    references: dict[str, Reference] = {}
    # 结构核验可跨实验共享；反应分析和最终引用必须仍绑定各自来源记录。
    match_cache, analysis_cache = {}, {}
    stopped: list[str] = []
    proposals: list[Proposal] = []
    proposal_reasons: list[str] = []
    seen_candidates = set()
    hydrated = {}
    # 队列项依次为：查询家族、材料角色、分页游标、候选优先阶段。
    queue = deque((family, "product", 0, 0) for family in families)
    if request.options.include_usage:
        queue.extend(
            (family, "reactant", 0, 0) for family in families if family.layer == "fragment"
        )
    use_attempts = 0
    followups = 0
    analyzed: set[str] = set()
    source_issues: list[dict] = []
    last_progress = 0.0

    def package():
        """将当前累计状态排序、汇总并封装为一个新的结果快照。

        闭包读取家族、参考、建议、预算和来源问题；计算三层范围内计数、能力状态、摘要及可追溯 manifest。快照 ID 使用内容摘要；本函数不保存文件，实际写入由 on_progress 的协调器执行。
        """
        ranked, display = rank_references(
            list(references.values()),
            request.ranking_profile,
            request.lab_context,
            max(3, request.budget.max_display - min(3, len(proposals))),
            target_smiles,
        )
        ids = set(display)
        chosen = [r for r in ranked if r.id in ids]
        # 展示顺序使用排序器分配的位置，不改变完整候选池的顺序。
        chosen.sort(key=lambda r: r.display_position or 0)
        display_proposals = proposals[: max(0, request.budget.max_display - len(display))]
        summary, summary_state, omitted = summary_items(
            chosen, display_proposals, request.budget.max_summary_bytes
        )
        complete = (
            not stopped
            and not source.issues
            and not source_issues
            and all(s.get("complete") for s in states.values())
            and not queue
        )
        if not request.options.exhaustive_fixture:
            complete = False
        source_hashes = {r.record.id: digest(r.record.model_dump()) for r in ranked}
        unsupported = [
            "arbitrary_variable_paths",
            "protection_and_tautomer_expansion",
            "automatic_stereochemical_origin_inference",
        ]
        relations, relations_complete = material_relations(ranked)
        layer_summary = {}
        for layer in ("whole", "core", "fragment"):
            layer_families = [f for f in family_lookup.values() if f.layer == layer]
            hits = [r for r in ranked if layer in r.layers and r.material.role == "product"]
            hit_ids = {i for r in hits for i in r.family_ids}
            layer_summary[layer] = {
                "generated_families": len(layer_families),
                "attempted_product_families": len(
                    {
                        s["family_id"]
                        for s in states.values()
                        if s["role"] == "product"
                        and s["family_id"] in {f.id for f in layer_families}
                    }
                ),
                "families_with_structural_hits": sum(f.id in hit_ids for f in layer_families),
                "unique_product_structures": len({canonical(r.material.smiles) for r in hits}),
                "unique_experiments": len({r.record.source.experiment_id for r in hits}),
                "qualified_preparation_experiments": len(
                    {r.record.source.experiment_id for r in hits if r.preparation_hit}
                ),
                "graph_connection_candidates": sum(
                    r.contribution in ("connection_method", "local_method") for r in hits
                ),
                "count_scope": "evaluated_candidates_only_not_full_corpus_total",
            }
        result = ReferencePackage(
            run_id=run_id,
            snapshot_id="pending",
            target_smiles=target_smiles,
            target_input_smiles=request.target.value,
            target_atoms=atom_table(target),
            source_snapshot=source.snapshot_id,
            manifest={
                "created_at": datetime.now(UTC).isoformat(),
                "rdkit_version": rdBase.rdkitVersion,
                "code_version": "0.1.0",
                "implementation_hash": code_fingerprint(),
                "rule_version": rules["version"],
                "rule_hash": rule_hash,
                "request": request.model_dump(),
                "source_record_hashes": source_hashes,
                "target_atom_order": "request_smiles_parse_order",
                "unsupported": unsupported,
                "selection_policy": "exhaustive_fixed_fixture"
                if request.options.exhaustive_fixture
                else getattr(source, "selection_policy", "source_declared_bounded_selection"),
                "selection_policy_status": "uncalibrated_initial_configuration",
            },
            families=list(family_lookup.values()),
            results=ranked,
            proposals=proposals,
            material_relations=relations,
            displayed_reference_ids=display,
            displayed_proposal_ids=[p.id for p in display_proposals],
            coverage_state="complete" if complete else "partial",
            family_states=states,
            stop_reasons=sorted(set(stopped)),
            source_issues=source.issues + source_issues,
            feature_status={
                "single_reactant_transfer": FeatureStatus(
                    state="not_evaluated"
                    if request.budget.max_proposals == 0 and request.options.include_proposals
                    else "not_requested"
                    if not request.options.include_proposals
                    else "partial"
                    if stopped or any(proposal_reasons)
                    else "completed",
                    reason=",".join(sorted(set(proposal_reasons))) or None,
                ),
                "common_intermediate_followups": FeatureStatus(
                    state="not_supported", reason="only_returned_record_relations_are_available"
                ),
                "returned_material_relations": FeatureStatus(
                    state="completed" if relations_complete else "partial",
                    reason="scope_is_returned_records_only_not_route_validation",
                ),
                "advanced_chemical_views": FeatureStatus(
                    state="not_supported", reason=",".join(unsupported)
                ),
                "hazard_and_supplier_enrichment": FeatureStatus(
                    state="not_evaluated", reason="no_material_information_provider_configured"
                ),
                "usage_lookup": FeatureStatus(
                    state="not_requested"
                    if not request.options.include_usage
                    else "partial"
                    if stopped
                    else "completed",
                    reason="evaluated_input_channel_scope_only",
                ),
            },
            statistics={
                "families": len(family_lookup),
                "received_candidates": budget.received,
                "unique_structures": len({canonical(r.material.smiles) for r in ranked}),
                "by_layer": layer_summary,
                "unique_experiments": len({r.record.source.experiment_id for r in ranked}),
                "preparation_hits": len(
                    {
                        (r.record.source.experiment_id, canonical(r.material.smiles))
                        for r in ranked
                        if r.preparation_hit
                    }
                ),
                "usage_hits": len(
                    {
                        (r.record.source.experiment_id, canonical(r.material.smiles))
                        for r in ranked
                        if r.use_hit
                    }
                ),
                "synthetic_references": sum(r.record.source.synthetic for r in ranked),
                "analyzed_reactions": budget.reactions,
                "proposals": len(proposals),
                "display_items": len(display) + len(display_proposals),
                "elapsed_ms": round((time.monotonic() - budget.started) * 1000, 3),
            },
            tasks=budget.events,
            summary=summary,
            summary_status=summary_state,
            summary_omitted_items=omitted,
        )
        return result.model_copy(
            update={"snapshot_id": digest(result.model_dump(exclude={"snapshot_id"}))}
        )

    def publish(force=False):
        """按需向 on_progress 发布当前资料包；force=True 时跳过约 0.5 秒的节流。

        回调通常把阶段结果传到父进程；无回调时不构造进度包，最终结果仍由 search 返回。
        """
        nonlocal last_progress
        if on_progress and (force or time.monotonic() - last_progress > 0.5):
            on_progress(package())
            last_progress = time.monotonic()

    # ② 先发布空的初始包，再按有限预算逐页推进，调用方可持续保存已有结果。
    publish(True)
    try:
        while queue:
            budget.check()
            family, role, cursor, stage = queue.popleft()
            if role == "reactant":
                if use_attempts >= 4:
                    stopped.append("usage_task_budget")
                    continue
                use_attempts += 1
            scope = digest([source.snapshot_id, family.id, role, stage, request.retrieval_profile])
            state_key = f"{family.id}:{role}:{stage}"
            states[state_key] = {
                **states.get(state_key, {}),
                "family_id": family.id,
                "role": role,
                "stage": stage,
                "selection_scope_id": scope,
                "complete": False,
            }
            # 给后面的核验和反应分析预留任务预算，避免召回阶段耗尽全部机会。
            budget.task("source_page", scope, reserve=4)
            try:
                page = source.candidate_page(
                    family, role, cursor, request.budget.page_size, target_smiles, stage
                )
            except Exception as exc:
                source_issues.append(
                    {"scope": scope, "code": "source_query_failed", "type": type(exc).__name__}
                )
                stopped.append("source_query_failed_or_timed_out")
                if (
                    getattr(source, "selection_failure_fallback", False)
                    and role == "product"
                    and family.layer != "fragment"
                    and family.relation != "strict"
                    and stage < getattr(source, "max_selection_stage", 0)
                ):
                    queue.append((family, role, 0, stage + 1))
                publish()
                continue
            states[state_key].update(
                {
                    "stream_exhausted": page.stream_exhausted,
                    "enumeration_kind": page.enumeration_kind,
                }
            )
            budget.task("match_batch", scope, reserve=3)
            matching_complete = True
            # ③ 每个实际材料独立做完整 Markush 核验；记录整侧命中不能替代此步骤。
            for item in page.items:
                budget.candidate()
                # 缓存键保留原始 SMILES：同一身份的不同原子顺序不能复用局部索引。
                cache_key = (family.id, item.structure_id, item.material.smiles)
                molecule = parse(item.material.smiles)
                if family.relation == "strict" and not meets_target(molecule, target):
                    continue
                if cache_key not in match_cache:
                    match_cache[cache_key] = match_family(
                        family,
                        molecule,
                        target,
                        item.structure_id,
                        role,
                        max_mappings=request.budget.max_mappings,
                        max_visits=request.budget.max_atom_visits,
                        checkpoint=budget.check,
                    )
                matched = match_cache[cache_key]
                matching_complete &= matched.enumeration_complete
                if matched.state != "match":
                    continue
                # ④ 只对真正结构命中的记录加载详情，并保持命中的材料实例不变。
                if item.record.id not in hydrated:
                    if getattr(source, "hydration_requires_io", False):
                        budget.task("source_hydration", item.record.id, reserve=3)
                    try:
                        hydrated[item.record.id] = source.hydrate(item.record)
                    except Exception as exc:
                        source_issues.append(
                            {
                                "record_id": item.record.id,
                                "code": "source_hydration_failed",
                                "type": type(exc).__name__,
                            }
                        )
                        hydrated[item.record.id] = item.record
                hydrated_record = hydrated[item.record.id]
                item = replace(
                    item,
                    record=hydrated_record,
                    material=next(
                        m
                        for m in hydrated_record.materials
                        if m.instance_id == item.material.instance_id
                    ),
                )
                item_key = (item.record.id, item.material.instance_id)
                # 见证 ID 再绑定实验材料；结构缓存 ID 则另存，保证引用不会串实验。
                ref_id = digest(item_key)
                matched = matched.model_copy(
                    update={
                        "witnesses": [
                            w.model_copy(
                                update={"id": digest([ref_id, w.id]), "structural_witness_id": w.id}
                            )
                            for w in matched.witnesses
                        ]
                    }
                )
                # 同一材料可能被多个家族发现：合并见证，允许更强的目标位点投影升级贡献。
                if ref_id in references:
                    previous = references[ref_id]
                    witnesses = {w.id: w for w in previous.witnesses + matched.witnesses}
                    coverage = {
                        **previous.coverage,
                        **coverage_summary(
                            list(witnesses.values()),
                            target,
                            previous.coverage.get("enumeration_complete", False)
                            and matched.enumeration_complete,
                        ),
                    }
                    # 优先取目标原子覆盖最高的见证，并用 ID 稳定并列次序。
                    new_best = max(matched.witnesses, key=lambda w: (w.target_atom_coverage, w.id))
                    new_projection = project_changes(
                        item.record, item.material, new_best, previous.analysis
                    )
                    old_projection = previous.coverage.get("projected_changes", {})
                    old_strength = (
                        bool(old_projection.get("formed_target_bonds")),
                        bool(old_projection.get("changed_target_atoms")),
                        previous.coverage.get("method_witness_atom_coverage", 0),
                    )
                    new_strength = (
                        bool(new_projection["formed_target_bonds"]),
                        bool(new_projection["changed_target_atoms"]),
                        new_best.target_atom_coverage,
                    )
                    updates: dict = {}
                    if new_strength > old_strength and item.material.role == "product":
                        coverage.update(
                            projected_changes=new_projection,
                            method_witness_id=new_best.id,
                            method_witness_atom_coverage=new_best.target_atom_coverage,
                        )
                        if previous.contribution != "target_outcome":
                            new_kind = (
                                "connection_method"
                                if new_best.target_atom_coverage == 1
                                else "local_method"
                            )
                            if not new_projection["formed_target_bonds"]:
                                new_kind = (
                                    "modification"
                                    if new_projection["changed_target_atoms"]
                                    else "structure_clue"
                                )
                            updates.update(
                                contribution=new_kind,
                                contribution_support="synthetic_illustration"
                                if item.record.source.synthetic
                                else "source_outcome_and_graph"
                                if previous.obtainment_hit
                                else "graph_only"
                                if new_kind != "structure_clue"
                                else "unknown",
                                reasons=[
                                    reason
                                    for reason in previous.reasons
                                    if not reason.startswith("target_contribution:")
                                ]
                                + ["target_contribution:" + new_kind],
                            )
                    references[ref_id] = previous.model_copy(
                        update={
                            **updates,
                            "family_ids": sorted(set(previous.family_ids + [family.id])),
                            "layers": sorted(set(previous.layers + [family.layer])),
                            "witnesses": list(witnesses.values()),
                            "coverage": coverage,
                        }
                    )
                    continue
                # ⑤ 先分析来源的真实成断键，再通过本次一致见证投影到目标位置。
                if item.record.id not in analyzed:
                    if len(analyzed) % 5 == 0:
                        budget.task("reaction_analysis_batch", scope)
                    budget.reaction()
                    analyzed.add(item.record.id)
                    analysis_cache[item.record.id] = analyze_reaction(item.record)
                analysis = analysis_cache.get(item.record.id, ReactionAnalysis(state="unknown"))
                # 结构/图变化和实验事实分别判断；产物字段存在不自动产生制备命中。
                preparation, obtained, used, claims = evidence_for(item.record, item.material)
                exact = canonical(molecule) == target_smiles
                satisfies = meets_target(molecule, target)
                # 当前贡献先用覆盖最多的见证解释；后续家族仍可提供更强投影。
                best = max(matched.witnesses, key=lambda w: (w.target_atom_coverage, w.id))
                projected = project_changes(item.record, item.material, best, analysis)
                contribution: Literal[
                    "target_outcome",
                    "connection_method",
                    "local_method",
                    "modification",
                    "usage",
                    "structure_clue",
                    "unknown",
                ]
                if role == "reactant":
                    contribution = "usage"
                elif satisfies and obtained:
                    contribution = "target_outcome"
                elif projected["formed_target_bonds"]:
                    contribution = (
                        "connection_method" if best.target_atom_coverage == 1 else "local_method"
                    )
                elif projected["changed_target_atoms"]:
                    contribution = "modification"
                else:
                    contribution = "structure_clue"
                unresolved = list(analysis.reasons)
                if not (preparation or obtained or used):
                    unresolved.append("no_qualified_literature_outcome_or_usage_witness")
                if item.record.source.synthetic:
                    unresolved.append("synthetic_example_not_literature_precedent")
                if not matched.enumeration_complete:
                    unresolved.append("mapping_enumeration_incomplete")
                if not satisfies and any(a.GetChiralTag() != 0 for a in target.GetAtoms()):
                    unresolved.append(
                        "target_stereochemical_outcome_not_established_by_family_match"
                    )
                if item.record.conditions.temperature_max_c is None:
                    unresolved.append("temperature_unknown")
                references[ref_id] = Reference(
                    id=ref_id,
                    record=item.record,
                    material=item.material,
                    family_ids=[family.id],
                    layers=[family.layer],
                    witnesses=matched.witnesses,
                    exact_record_identity=exact,
                    target_requirements_satisfied=satisfies,
                    preparation_hit=preparation,
                    obtainment_hit=obtained,
                    use_hit=used,
                    contribution=contribution,
                    contribution_support="synthetic_illustration"
                    if item.record.source.synthetic
                    else "reported_input"
                    if used
                    else "source_outcome_and_graph"
                    if obtained
                    else "graph_only"
                    if projected["formed_target_bonds"] or projected["changed_target_atoms"]
                    else "unknown",
                    analysis=analysis,
                    claims=claims,
                    similarity=similarity(target, molecule),
                    molecular_weight=descriptors(molecule)["molecular_weight"],
                    coverage={
                        **coverage_summary(matched.witnesses, target, matched.enumeration_complete),
                        "projected_changes": projected,
                        "method_witness_id": best.id,
                        "method_witness_atom_coverage": best.target_atom_coverage,
                    },
                    reasons=[
                        "same_instance_markush_witness",
                        f"event_scope:{item.record.event_scope}",
                        f"target_contribution:{contribution}",
                    ],
                    unresolved=sorted(set(unresolved)),
                )
                seen_candidates.add(item_key)
            states[state_key]["matching_enumeration_complete"] = (
                states[state_key].get("matching_enumeration_complete", True) and matching_complete
            )
            states[state_key]["complete"] = (
                page.scope_complete and states[state_key]["matching_enumeration_complete"]
            )
            # ⑥ 分页后仍有预算才继续；缺少合格获得记录时再放宽候选优先范围。
            if page.next_cursor is not None:
                queue.append((family, role, page.next_cursor, stage))
            elif (
                stage < getattr(source, "max_selection_stage", 2)
                and not request.options.exhaustive_fixture
                and role == "product"
                and family.layer != "fragment"
                and family.relation != "strict"
            ):
                useful = [
                    r for r in references.values() if family.id in r.family_ids and r.obtainment_hit
                ]
                if len(useful) < 4:
                    queue.append((family, role, 0, stage + 1))
            if (
                request.options.directed_followups
                and role == "product"
                and followups < 2
                and len(family_lookup) < request.budget.max_families
            ):
                # 用现有见证暴露的 R 组合缺口补查，不在检索前猜测战略切断键。
                desired = {
                    p
                    for block in outside_blocks(target, family.target_atoms)
                    for p in block["core_positions"]
                }
                found = [
                    w for r in references.values() for w in r.witnesses if w.family_id == family.id
                ]
                if (
                    desired
                    and found
                    and not any(desired <= set(w.matched_r_positions) for w in found)
                ):
                    child = directed_family(family, target, desired)
                    if child and child.id not in family_lookup:
                        family_lookup[child.id] = child
                        followups += 1
                        queue.appendleft((child, "product", 0, 0))
            publish()
    except BudgetExceeded as exc:
        stopped.append(str(exc))
    # ⑦ 在已有命中基础上做有限单反应物替换；每项建议都需来源自回放和目标正向核验。
    if request.options.include_proposals:
        try:
            eligible_pool = [r for r in references.values() if r.material.role == "product"]
            if len(eligible_pool) > 6:
                proposal_reasons.append("transfer_reference_limit_top6")
            if request.budget.max_proposals == 0:
                proposal_reasons.append("proposal_budget_zero")
            # 建议尝试顺序：有获得证据优先，再看结构相似度，最后按 ID 固定次序。
            for ref in sorted(
                eligible_pool, key=lambda r: (not r.obtainment_hit, -r.similarity, r.id)
            )[:6]:
                if len(proposals) >= request.budget.max_proposals:
                    proposal_reasons.append("proposal_count_budget")
                    break
                created, reason = generate_proposals(ref, target, budget)
                if reason:
                    proposal_reasons.append(reason)
                known = {p.id for p in proposals}
                proposals.extend(p for p in created if p.id not in known)
                proposals = proposals[: request.budget.max_proposals]
        except BudgetExceeded as exc:
            proposal_reasons.append(str(exc))
            stopped.append(str(exc))
    # ⑧ 统一排序、证据分账和范围统计；预算截断后的最终包仍保留已完成事实。
    publish(True)
    return package()
