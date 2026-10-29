"""统一领域契约：仅依赖 Pydantic/标准库；结构对象以字符串、索引和来源引用传递，避免暴露 RDKit 或数据库对象。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    """所有领域对象的严格、冻结、禁止额外字段基类；拒绝 NaN/Infinity 和隐式类型宽松转换。"""

    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, strict=True, allow_inf_nan=False
    )


Layer = Literal["whole", "core", "fragment"]
State = Literal["completed", "partial", "not_evaluated", "not_supported", "not_requested"]
Role = Literal["reactant", "product", "reagent", "catalyst", "solvent"]
EventScope = Literal["documented_step", "source_record_net", "unknown"]


class Target(Model):
    """一个具体合成目标的输入表示，当前只接受 SMILES。"""

    format: Literal["smiles"] = "smiles"
    value: Annotated[str, Field(min_length=1, max_length=20000)]


class BudgetConfig(Model):
    """单次检索的资源上限；time_ms 为毫秒，其他字段为有明确范围的计数/字节限额。"""

    time_ms: Annotated[int, Field(strict=True, ge=50, le=120000)] = 10000
    max_tasks: Annotated[int, Field(strict=True, ge=4, le=1000)] = 40
    max_families: Annotated[int, Field(strict=True, ge=3, le=48)] = 12
    max_candidates: Annotated[int, Field(strict=True, ge=1, le=20000)] = 2000
    page_size: Annotated[int, Field(strict=True, ge=1, le=500)] = 100
    max_mappings: Annotated[int, Field(strict=True, ge=1, le=2048)] = 128
    max_atom_visits: Annotated[int, Field(strict=True, ge=16, le=100000)] = 10000
    max_reactions: Annotated[int, Field(strict=True, ge=1, le=1000)] = 60
    max_proposals: Annotated[int, Field(strict=True, ge=0, le=24)] = 12
    max_replay_sets: Annotated[int, Field(strict=True, ge=1, le=128)] = 16
    max_display: Annotated[int, Field(strict=True, ge=3, le=100)] = 18
    max_summary_bytes: Annotated[int, Field(strict=True, ge=256, le=262144)] = 65536


class SearchOptions(Model):
    """决定是否查完整目标、输入使用、替换建议和定向补查；有限样本穷尽不是全库穷尽。"""

    model_config = ConfigDict(strict=True)
    include_exact_identity: bool = True
    include_proposals: bool = True
    include_usage: bool = True
    exhaustive_fixture: bool = False
    directed_followups: bool = True


class LabContext(Model):
    """内部实验能力和明确排除条件；未提供的字段表示未限制，不表示已通过。"""

    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    max_temperature_c: float | None = None
    min_temperature_c: float | None = None
    max_pressure_kpa: Annotated[float | None, Field(gt=0)] = None
    excluded_material_smiles: list[str] = Field(default_factory=list)
    available_equipment: list[str] | None = None

    @model_validator(mode="after")
    def check_range(self):
        """拒绝下限高于上限的温度范围，校验通过返回当前对象。"""
        if (
            self.min_temperature_c is not None
            and self.max_temperature_c is not None
            and self.min_temperature_c > self.max_temperature_c
        ):
            raise ValueError("Minimum temperature exceeds maximum")
        return self


class SearchRequest(Model):
    """检索请求：目标、版本化选择/排序偏好、实验能力、开关与预算。"""

    schema_version: Literal["1"] = "1"
    target: Target
    retrieval_profile: Literal["reference-v1", "pilot-v0-unmeasured"] = "reference-v1"
    ranking_profile: Literal["reference_first", "lab_fit", "process_reference"] = "reference_first"
    lab_context: LabContext | None = None
    options: SearchOptions = Field(default_factory=SearchOptions)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


class FeatureStatus(Model):
    """某项增强能力在当前运行中的评估状态及原因，区别未请求、未支持、未评估和部分完成。"""

    state: State
    reason: str | None = None


class SourceRef(Model):
    """来源实验定位；record_id 是来源记录身份，experiment_id 用于实验去重，synthetic 标记演示来源。"""

    namespace: str
    record_id: str
    experiment_id: str
    document_id: str | None = None
    location: str | None = None
    url: str | None = None
    synthetic: bool = False


class Material(Model):
    """某个反应中的具体材料实例；同结构在不同角色/实验中仍有不同 instance_id。"""

    instance_id: str
    role: Role
    smiles: str
    name: str | None = None
    actual_input: bool | None = None


class Observation(Model):
    """绑定一个产品实例的报告观察，保留结果类型、引文、位置及产品对应收率类型。"""

    product_instance_id: str
    result: Literal[
        "reported_prepared",
        "analytical_observation",
        "enriched",
        "recovered",
        "failed",
        "unknown",
        "conflict",
    ] = "unknown"
    evidence_text: str | None = None
    source_location: str | None = None
    isolated: bool | None = None
    yield_pct: Annotated[float | None, Field(ge=0, le=105)] = None
    yield_type: Literal["isolated", "analytical", "recovery", "unknown"] = "unknown"


class Conditions(Model):
    """来源报告的条件范围与阶段归属；温度 °C、压力 kPa、时长秒，缺失保持 None。"""

    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    pressure_max_kpa: float | None = None
    duration_seconds: float | None = None
    equipment: list[str] | None = None
    stage_id: str | None = None
    text: str | None = None


class ReactionRecord(Model):
    """同一来源记录的材料、产品观察、映射式和事件范围；净端点与明确操作步骤不混用。"""

    id: str
    source: SourceRef
    materials: list[Material]
    observations: list[Observation] = Field(default_factory=list)
    mapped_reaction_smiles: str | None = None
    reaction_smiles: str | None = None
    event_scope: EventScope = "unknown"
    documented_step_ref: str | None = None
    step_count: Annotated[int | None, Field(ge=1)] = None
    one_pot: bool | None = None
    conditions: Conditions = Field(default_factory=Conditions)
    reaction_class: str | None = None
    retro_template: str | None = None
    raw: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_instances(self):
        """验证材料 ID 唯一、观察确实指向产品、明确步骤有引文且不承载多步计数。

        任一关联不合法抛出 ValueError；返回 self 供 Pydantic 完成构造，不补造缺失证据。
        """
        ids = [m.instance_id for m in self.materials]
        if len(ids) != len(set(ids)):
            raise ValueError("Material instance IDs must be unique within an experiment")
        for observation in self.observations:
            if observation.product_instance_id not in ids:
                raise ValueError("Observation references an absent material instance")
            if (
                next(
                    m for m in self.materials if m.instance_id == observation.product_instance_id
                ).role
                != "product"
            ):
                raise ValueError("An outcome observation must reference a product material")
        if self.event_scope == "documented_step" and not self.documented_step_ref:
            raise ValueError("A documented step requires a source step reference")
        if self.event_scope == "documented_step" and self.step_count not in (None, 1):
            raise ValueError("A documented single-step event cannot represent several steps")
        return self


class RConstraint(Model):
    """查询核心某位置的完整 R 块限制；position 是查询核心索引，不是全目标索引。"""

    position: Annotated[int, Field(ge=0)]
    requirement: Literal["optional", "required", "hydrogen"] = "optional"
    category: Literal["any", "alkyl", "aryl", "heteroaryl"] = "any"
    exact_fragment: str | None = None
    max_carbons: Annotated[int | None, Field(ge=1)] = None


class QueryFamily(Model):
    """可序列化的 Markush 查询中间表示，含核心、目标对应、R 谓词和生成规则依据。"""

    id: str
    parent_id: str | None = None
    layer: Layer
    core_smarts: str
    target_atoms: list[int]
    rule_id: str
    rule_version: str
    r_constraints: list[RConstraint] = Field(default_factory=list)
    equal_r_positions: list[list[int]] = Field(default_factory=list)
    core_topology_policy: Literal["forbid_extra_internal_edges", "record_extra_internal_edges"] = (
        "forbid_extra_internal_edges"
    )
    allow_extra_substitution: bool = True
    use_generic_matchers: bool = True
    relation: Literal["strict", "structural_family"] = "structural_family"
    description: str
    trigger: str | None = None

    @model_validator(mode="after")
    def check_correspondence(self):
        """要求非空且唯一的目标原子对应，校验 R 位置不超出核心长度。

        这里只检查契约关联；SMARTS 编译和具体化学语义由 compile_family 检查。
        """
        if not self.target_atoms or len(set(self.target_atoms)) != len(self.target_atoms):
            raise ValueError("A family requires nonempty, unique target atom references")
        if any(c.position >= len(self.target_atoms) for c in self.r_constraints):
            raise ValueError("R constraint references an absent core position")
        return self


class RBlock(Model):
    """核心外一个完整连通支链块；可以有多个边界连接位点，atom_indices 属于具体材料。"""

    core_positions: list[int]
    atom_indices: list[int]
    fragment: str
    boundary_bonds: list[str]
    heavy_atoms: int
    category: str


class Witness(Model):
    """一次一致的目标到来源原子对应；id 绑定实验实例，structural_witness_id 可用于结构核验复用。"""

    id: str
    structural_witness_id: str | None = None
    family_id: str
    source_structure_id: str
    matched_role: Role
    target_to_source: list[tuple[int, int]]
    core_source_atoms: list[int]
    blocks: list[RBlock]
    matched_r_positions: list[int]
    extra_core_edges: list[tuple[int, int]] = Field(default_factory=list)
    target_atom_coverage: float
    target_bond_coverage: float
    mapping_status: Literal["single_witness", "alternative_witness"] = "single_witness"


class MatchResult(Model):
    """结构核验结果与枚举完整性；已有 match 也可能被截断，unknown 不等于 no_match。"""

    state: Literal["match", "no_match", "unknown", "unsupported"]
    witnesses: list[Witness] = Field(default_factory=list)
    mappings_checked: int = 0
    enumeration_complete: bool = True
    reasons: list[str] = Field(default_factory=list)


class BondChange(Model):
    """按来源正原子映射号记录的一对键变化，before/after 为键型而非目标索引。"""

    maps: tuple[int, int]
    before: str | None = None
    after: str | None = None


class ReactionAnalysis(Model):
    """来源端点上的图变化、原子来源和粗类别，含映射支持与事件范围限制。"""

    state: Literal["analyzed", "partial", "unknown"]
    formed: list[BondChange] = Field(default_factory=list)
    broken: list[BondChange] = Field(default_factory=list)
    order_changed: list[BondChange] = Field(default_factory=list)
    representation_only: list[BondChange] = Field(default_factory=list)
    atom_property_changes: list[dict] = Field(default_factory=list)
    untracked_input_bonds: list[tuple[int, int]] = Field(default_factory=list)
    detached_boundaries: list[tuple[int, int]] = Field(default_factory=list)
    atom_sources: dict[int, int] = Field(default_factory=dict)
    topology: list[str] = Field(default_factory=list)
    reaction_classes: list[str] = Field(default_factory=list)
    mapping_support: str = "single_mapping_inference"
    event_scope: EventScope = "unknown"
    reasons: list[str] = Field(default_factory=list)


class Claim(Model):
    """绑定具体材料主体和来源的证据主张；报告、图推定、合成示例与未知明确分开。"""

    id: str
    subject_id: str
    predicate: str
    support: Literal["source_reported", "graph_inference", "synthetic_illustration", "unknown"]
    source: SourceRef
    evidence_text: str | None = None
    limitations: list[str] = Field(default_factory=list)


class Reference(Model):
    """一个来源材料的检索参考，聚合多个家族见证、实际反应贡献、证据、排序特征与限制。"""

    id: str
    record: ReactionRecord
    material: Material
    family_ids: list[str]
    layers: list[Layer]
    witnesses: list[Witness]
    exact_record_identity: bool = False
    target_requirements_satisfied: bool = False
    preparation_hit: bool = False
    obtainment_hit: bool = False
    use_hit: bool = False
    contribution: Literal[
        "target_outcome",
        "connection_method",
        "local_method",
        "modification",
        "usage",
        "structure_clue",
        "unknown",
    ] = "unknown"
    contribution_support: Literal[
        "source_outcome_and_graph",
        "graph_only",
        "reported_input",
        "synthetic_illustration",
        "unknown",
    ] = "unknown"
    analysis: ReactionAnalysis
    claims: list[Claim] = Field(default_factory=list)
    similarity: float = 0.0
    molecular_weight: float
    coverage: dict = Field(default_factory=dict)
    ranking_features: dict = Field(default_factory=dict)
    lab_fit: Literal["pass", "fail", "unknown", "not_applicable"] = "not_applicable"
    lab_reasons: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    display_position: int | None = None


class Proposal(Model):
    """经来源回放约束的单反应物替换建议，始终标记为未观察且条件尚未验证。"""

    id: str
    source_reference_id: str
    source: SourceRef
    source_step_ref: str
    replaced_slot: int
    original_reactants: list[str]
    proposed_reactants: list[str]
    target_smiles: str
    replay_product_sets: list[list[str]]
    enumeration_complete: bool
    validation_complete: bool
    target_found: bool
    rule_id: str
    proposal_not_observed: Literal[True] = True
    condition_support: Literal["unverified"] = "unverified"
    limitations: list[str]


class TaskEvent(Model):
    """已消耗的一次业务任务尝试；elapsed_ms 为自本次预算开始的单调时钟时间。"""

    attempt: int
    kind: str
    scope: str
    elapsed_ms: float


class ReferencePackage(Model):
    """可导出的完整结果快照：原始目标编号参照、来源/规则、全部候选、建议、统计、状态和模型摘要。"""

    schema_version: Literal["1"] = "1"
    run_id: str
    snapshot_id: str
    target_smiles: str
    target_input_smiles: str | None = None
    target_atoms: list[dict]
    source_snapshot: str
    manifest: dict
    families: list[QueryFamily]
    results: list[Reference]
    proposals: list[Proposal] = Field(default_factory=list)
    material_relations: list[dict] = Field(default_factory=list)
    displayed_reference_ids: list[str] = Field(default_factory=list)
    displayed_proposal_ids: list[str] = Field(default_factory=list)
    coverage_state: Literal["complete", "partial"]
    family_states: dict[str, dict] = Field(default_factory=dict)
    stop_reasons: list[str] = Field(default_factory=list)
    source_issues: list[dict] = Field(default_factory=list)
    feature_status: dict[str, FeatureStatus] = Field(default_factory=dict)
    statistics: dict = Field(default_factory=dict)
    tasks: list[TaskEvent] = Field(default_factory=list)
    summary: str = ""
    summary_status: Literal["complete", "truncated", "unavailable"] = "complete"
    summary_omitted_items: int = 0


class RerankRequest(Model):
    """仅改变排序偏好和实验能力，禁止在冻结快照重排时更换目标或候选选择范围。"""

    ranking_profile: Literal["reference_first", "lab_fit", "process_reference"] = "reference_first"
    lab_context: LabContext | None = None


class RunState(Model):
    """协调器作业状态与修订号；lifecycle 的执行终态不同于资料包的范围完整性。"""

    run_id: str
    revision: int = 0
    lifecycle: Literal["queued", "running", "succeeded", "cancelled", "timed_out", "failed"]
    request: SearchRequest
    created_at: str
    updated_at: str
    owner: str = "internal"
    snapshot_id: str | None = None
    error: dict | None = None
    parent_run_id: str | None = None
