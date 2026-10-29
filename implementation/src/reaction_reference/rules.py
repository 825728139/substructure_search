"""版本化有限规则的严格校验、资源内容摘要与能力说明；规则和业务代码均参与可复现记录。"""

import hashlib
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from pydantic import Field
from rdkit import Chem
from rdkit.Chem import rdChemReactions

from reaction_reference.domain.models import Model


class FunctionalRule(Model):
    """官能团识别规则：稳定 ID、有限 SMARTS 和处理优先级。"""

    id: str
    smarts: str = Field(min_length=1, max_length=2000)
    priority: int = Field(ge=0, le=1000)


class TransferRule(Model):
    """有限注册回放规则：正向/逆向 SMARTS 与适用范围说明。"""

    id: str
    forward: str = Field(min_length=1, max_length=20000)
    retro: str = Field(min_length=1, max_length=20000)
    scope: str


class RuleSet(Model):
    """随包发布的规则集合契约，拒绝未知字段并声明未支持范围。"""

    schema_version: str
    version: str
    status: str
    functional_groups: list[FunctionalRule]
    query_rules: list[str]
    transfer_rules: list[TransferRule]
    unsupported: list[str]


@lru_cache(maxsize=1)
def code_fingerprint():
    """对包内 Python、规则/示例 JSON 和 HTML 的路径与原始内容计算 SHA-256。

    结果按进程缓存；注释和 docstring 也会改变摘要，因此注释交接后需重新生成当前验证记录，不能沿用旧代码哈希。
    """
    root = Path(str(files("reaction_reference")))
    checksum = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".jsonl", ".html"):
            checksum.update(str(path.relative_to(root)).encode())
            checksum.update(hashlib.sha256(path.read_bytes()).digest())
    return checksum.hexdigest()


def load_rules():
    """读取随包 rules.json，严格校验契约并编译官能团及双向回放规则。

    返回（普通规则字典、文件 SHA-256）；版本、重复官能团 ID 或编译错误抛出 ValueError，不静默忽略失效规则。
    """
    payload = files("reaction_reference").joinpath("resources/rules.json").read_bytes()
    rules = RuleSet.model_validate_json(payload).model_dump()
    if rules.get("schema_version") != "1":
        raise ValueError("Unsupported rule schema")
    seen = set()
    for rule in rules["functional_groups"]:
        if rule["id"] in seen or Chem.MolFromSmarts(rule["smarts"]) is None:
            raise ValueError("Invalid or duplicate functional-group rule")
        seen.add(rule["id"])
    for rule in rules["transfer_rules"]:
        for direction in ("forward", "retro"):
            reaction = rdChemReactions.ReactionFromSmarts(rule[direction])
            if reaction is None or reaction.Validate(silent=True)[1]:
                raise ValueError("Invalid transfer rule")
    return rules, hashlib.sha256(payload).hexdigest()


def capabilities():
    """返回与当前规则版本绑定的查询形式、来源、分析能力和未支持清单。

    这是静态实现能力，不代表某次 run 已完整评估或某个外部来源已连接成功。
    """
    rules, rule_hash = load_rules()
    return {
        "schema_version": "1",
        "rule_version": rules["version"],
        "rule_hash": rule_hash,
        "query_forms": [
            "connected_core",
            "multi_R",
            "optional_H",
            "whole_R_predicates",
            "generic_groups",
            "multi_attachment_blocks",
            "R_equality",
        ],
        "sources": ["bounded_jsonl", "postgresql_indexed_readonly"],
        "analysis": [
            "mapping_validation",
            "reported_scope_bond_changes",
            "local_resonance",
            "observed_ring_changes",
            "target_connection_projection",
            "stage_scope",
        ],
        "transfer_rules": [r["id"] for r in rules["transfer_rules"]],
        "unsupported": rules["unsupported"],
    }
