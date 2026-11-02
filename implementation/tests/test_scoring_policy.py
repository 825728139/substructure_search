"""中文评分YAML的严格校验、参数生效和可追溯摘要。"""

from importlib.resources import files

import pytest
import yaml

from reaction_reference.chemistry.structures import parse
from reaction_reference.ranking import scaffold, scoring
from reaction_reference.ranking.policy import validate_scoring_policy


def policy_text():
    """读取实际随包分发的配置，不用测试专用权重替代交付文件。"""
    return files("reaction_reference").joinpath("resources/ranking_weights.yaml").read_text()


def test_default_policy_has_complete_comments_and_traceable_hash():
    """配置包含化学依据、默认总分100及摘要，注释变化也可区分配置内容。"""
    text = policy_text()
    data = validate_scoring_policy(text)
    assert sum(data["weights"].values()) == 100
    assert len(data["config_sha256"]) == 64
    assert "# 原因" in text and "未知" in text and "尾部" in text
    changed = validate_scoring_policy(text + "\n# 审核说明\n")
    assert changed["weights"] == data["weights"]
    assert changed["config_sha256"] != data["config_sha256"]


@pytest.mark.parametrize(
    "case",
    [
        "sum",
        "typo",
        "missing",
        "negative",
        "nan",
        "infinite",
        "bool",
        "string",
        "center_range",
        "scale",
        "core_zero",
        "share",
    ],
)
def test_invalid_policy_fails_instead_of_silent_fallback(case):
    """拒绝常见调分错误，不能静默用旧值或把错别字当成有效配置。"""
    data = yaml.safe_load(policy_text())
    if case == "sum":
        data["weights"]["core_coverage"] += 1
    elif case == "typo":
        data["weights"]["core_coverge"] = data["weights"].pop("core_coverage")
    elif case == "missing":
        del data["center_values"]["core_internal"]
    elif case in ("negative", "nan", "infinite", "bool", "string"):
        data["weights"]["core_coverage"] = {
            "negative": -1,
            "nan": float("nan"),
            "infinite": float("inf"),
            "bool": True,
            "string": "30",
        }[case]
    elif case == "center_range":
        data["center_values"]["core_internal"] = 2
    elif case == "scale":
        data["environment_distance_scale"] = 0
    elif case == "core_zero":
        data["core_definition"]["acyclic_atom_weight"] = 0
    elif case == "share":
        data["process_values"]["temperature_share"] = 0.8
    with pytest.raises(ValueError):
        validate_scoring_policy(yaml.safe_dump(data))


def test_duplicate_or_executable_yaml_is_rejected():
    """重复键和可执行对象标签必须报错，不能覆盖审核值或执行配置内容。"""
    with pytest.raises(ValueError, match="重复键"):
        validate_scoring_policy(policy_text() + "\nversion: duplicate\n")
    with pytest.raises(yaml.YAMLError):
        validate_scoring_policy('!!python/object/apply:os.system ["false"]')


def test_core_and_center_parameters_are_read_from_yaml(monkeypatch):
    """修改配置能改变母核拓扑权重，参数确实进入计算而非只作为展示文档。"""
    data = yaml.safe_load(policy_text())
    data["core_definition"]["ring_base_weight"] = 2
    data["core_definition"]["ring_cycle_weight"] = 3
    policy = validate_scoring_policy(yaml.safe_dump(data))
    monkeypatch.setattr(scoring, "scoring_policy", lambda: policy)
    monkeypatch.setattr(scaffold, "scoring_policy", lambda: policy)
    regions = scaffold.target_regions(parse("CCOC(=O)c1ccccc1"))
    assert set(regions["core_weights"].values()) == {5}
