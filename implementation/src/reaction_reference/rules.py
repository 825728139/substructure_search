import hashlib
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from pydantic import Field
from rdkit import Chem
from rdkit.Chem import rdChemReactions

from reaction_reference.domain.models import Model


class FunctionalRule(Model):
    id: str
    smarts: str = Field(min_length=1, max_length=2000)
    priority: int = Field(ge=0, le=1000)


class TransferRule(Model):
    id: str
    forward: str = Field(min_length=1, max_length=20000)
    retro: str = Field(min_length=1, max_length=20000)
    scope: str


class RuleSet(Model):
    schema_version: str
    version: str
    status: str
    functional_groups: list[FunctionalRule]
    query_rules: list[str]
    transfer_rules: list[TransferRule]
    unsupported: list[str]


@lru_cache(maxsize=1)
def code_fingerprint():
    root = Path(str(files("reaction_reference")))
    checksum = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".jsonl", ".html"):
            checksum.update(str(path.relative_to(root)).encode())
            checksum.update(hashlib.sha256(path.read_bytes()).digest())
    return checksum.hexdigest()


def load_rules():
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
