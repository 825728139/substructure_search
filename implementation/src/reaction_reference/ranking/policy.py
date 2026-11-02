"""评分YAML的安全解析与严格校验，拒绝误拼键名、重复键和不合法权重。"""

import hashlib
from typing import Annotated, Literal

import yaml
from pydantic import Field, model_validator

from reaction_reference.domain.models import Model

Nonnegative = Annotated[float, Field(ge=0)]
UnitValue = Annotated[float, Field(ge=0, le=1)]


class _UniqueLoader(yaml.SafeLoader):
    """安全YAML解析器；重复键直接报错，防止审核值被后面的同名配置悄悄覆盖。"""

    def construct_mapping(self, node, deep=False):
        """只接受字符串配置键，并逐项检查当前映射是否有重复键。"""
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("评分配置的键必须是字符串")
            if key in mapping:
                raise ValueError(f"评分配置出现重复键：{key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class ScoringPolicy(Model):
    """评分配置契约；数值必须有限，未知字段和不完整分项一律拒绝。"""

    version: Annotated[str, Field(min_length=1)]
    status: Literal["heuristic_not_expert_calibrated"]
    weights: dict[str, Nonnegative]
    core_definition: dict[str, Nonnegative]
    center_values: dict[str, UnitValue]
    method_values: dict[str, UnitValue]
    evidence_values: dict[str, UnitValue]
    environment_distance_scale: Annotated[float, Field(gt=0)]
    environment_unknown_value: UnitValue
    reported_target_bonus: Nonnegative
    process_preference_weight: Nonnegative
    process_values: dict[str, float]
    lab_fit_weight: Nonnegative
    lab_values: dict[str, UnitValue]

    @model_validator(mode="after")
    def check_dimensions(self):
        """检查分项完整、基础分合计100、尺度正数及操作分占比合计1。"""
        expected = {
            "weights": {
                "core_coverage",
                "target_coverage",
                "center_position",
                "balanced_coverage",
                "environment_match",
                "method_contribution",
                "source_evidence",
                "similarity",
            },
            "core_definition": {"ring_base_weight", "ring_cycle_weight", "acyclic_atom_weight"},
            "center_values": {"core_internal", "core_branch_head", "branch_remote_or_unresolved"},
            "method_values": {"formed_target_bond", "changed_target_atom", "unresolved"},
            "evidence_values": {"reported_obtained", "source_reported_claim", "unknown"},
            "process_values": {
                "reference_temperature_c",
                "temperature_scale_c",
                "duration_scale_seconds",
                "temperature_share",
                "duration_share",
            },
            "lab_values": {"pass", "unknown", "not_applicable", "fail"},
        }
        for field, keys in expected.items():
            if set(getattr(self, field)) != keys:
                raise ValueError(f"{field}的配置项缺失或拼写错误；需要：{sorted(keys)}")
        if abs(sum(self.weights.values()) - 100) > 1e-8:
            raise ValueError("基础评分权重合计必须为100")
        core = self.core_definition
        if (
            core["acyclic_atom_weight"] <= 0
            or core["ring_base_weight"] + core["ring_cycle_weight"] <= 0
        ):
            raise ValueError("母核原子权重必须大于0")
        process = self.process_values
        if process["temperature_scale_c"] <= 0 or process["duration_scale_seconds"] <= 0:
            raise ValueError("温度与时长的归一化尺度必须大于0")
        shares = [process["temperature_share"], process["duration_share"]]
        if any(not 0 <= value <= 1 for value in shares) or abs(sum(shares) - 1) > 1e-8:
            raise ValueError("操作分占比必须在0到1之间且合计为1")
        return self


def validate_scoring_policy(text):
    """安全解析并校验YAML，返回可计算字典及原始配置摘要，异常直接交给调用方报告。"""
    data = yaml.load(text, Loader=_UniqueLoader)
    policy = ScoringPolicy.model_validate(data).model_dump()
    policy["config_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    return policy
