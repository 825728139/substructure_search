from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, strict=True, allow_inf_nan=False
    )


Layer = Literal["whole", "core", "fragment"]
State = Literal["completed", "partial", "not_evaluated", "not_supported", "not_requested"]
Role = Literal["reactant", "product", "reagent", "catalyst", "solvent"]
EventScope = Literal["documented_step", "source_record_net", "unknown"]


class Target(Model):
    format: Literal["smiles"] = "smiles"
    value: Annotated[str, Field(min_length=1, max_length=20000)]


class BudgetConfig(Model):
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
    model_config = ConfigDict(strict=True)
    include_exact_identity: bool = True
    include_proposals: bool = True
    include_usage: bool = True
    exhaustive_fixture: bool = False
    directed_followups: bool = True


class LabContext(Model):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    max_temperature_c: float | None = None
    min_temperature_c: float | None = None
    max_pressure_kpa: Annotated[float | None, Field(gt=0)] = None
    excluded_material_smiles: list[str] = Field(default_factory=list)
    available_equipment: list[str] | None = None

    @model_validator(mode="after")
    def check_range(self):
        if (
            self.min_temperature_c is not None
            and self.max_temperature_c is not None
            and self.min_temperature_c > self.max_temperature_c
        ):
            raise ValueError("Minimum temperature exceeds maximum")
        return self


class SearchRequest(Model):
    schema_version: Literal["1"] = "1"
    target: Target
    retrieval_profile: Literal["reference-v1", "pilot-v0-unmeasured"] = "reference-v1"
    ranking_profile: Literal["reference_first", "lab_fit", "process_reference"] = "reference_first"
    lab_context: LabContext | None = None
    options: SearchOptions = Field(default_factory=SearchOptions)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


class FeatureStatus(Model):
    state: State
    reason: str | None = None


class SourceRef(Model):
    namespace: str
    record_id: str
    experiment_id: str
    document_id: str | None = None
    location: str | None = None
    url: str | None = None
    synthetic: bool = False


class Material(Model):
    instance_id: str
    role: Role
    smiles: str
    name: str | None = None
    actual_input: bool | None = None


class Observation(Model):
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
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    pressure_max_kpa: float | None = None
    duration_seconds: float | None = None
    equipment: list[str] | None = None
    stage_id: str | None = None
    text: str | None = None


class ReactionRecord(Model):
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
    position: Annotated[int, Field(ge=0)]
    requirement: Literal["optional", "required", "hydrogen"] = "optional"
    category: Literal["any", "alkyl", "aryl", "heteroaryl"] = "any"
    exact_fragment: str | None = None
    max_carbons: Annotated[int | None, Field(ge=1)] = None


class QueryFamily(Model):
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
        if not self.target_atoms or len(set(self.target_atoms)) != len(self.target_atoms):
            raise ValueError("A family requires nonempty, unique target atom references")
        if any(c.position >= len(self.target_atoms) for c in self.r_constraints):
            raise ValueError("R constraint references an absent core position")
        return self


class RBlock(Model):
    core_positions: list[int]
    atom_indices: list[int]
    fragment: str
    boundary_bonds: list[str]
    heavy_atoms: int
    category: str


class Witness(Model):
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
    state: Literal["match", "no_match", "unknown", "unsupported"]
    witnesses: list[Witness] = Field(default_factory=list)
    mappings_checked: int = 0
    enumeration_complete: bool = True
    reasons: list[str] = Field(default_factory=list)


class BondChange(Model):
    maps: tuple[int, int]
    before: str | None = None
    after: str | None = None


class ReactionAnalysis(Model):
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
    id: str
    subject_id: str
    predicate: str
    support: Literal["source_reported", "graph_inference", "synthetic_illustration", "unknown"]
    source: SourceRef
    evidence_text: str | None = None
    limitations: list[str] = Field(default_factory=list)


class Reference(Model):
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
    attempt: int
    kind: str
    scope: str
    elapsed_ms: float


class ReferencePackage(Model):
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
    ranking_profile: Literal["reference_first", "lab_fit", "process_reference"] = "reference_first"
    lab_context: LabContext | None = None


class RunState(Model):
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
