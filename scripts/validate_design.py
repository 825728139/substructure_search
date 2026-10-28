"""Check current design artifacts; this does not test a retrieval engine."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = sorted(ROOT.glob("*.md"))
for directory in ("design", "reviews"):
    files.extend(sorted((ROOT / directory).rglob("*.md")))

for path in files:
    content = path.read_text()
    assert content.count("```") % 2 == 0, f"Unbalanced fences: {path}"
    for ref in re.findall(r"\]\(([^)]+)\)", content):
        if ref.startswith(("https://", "http://", "#")):
            continue
        target = ref.split("#", 1)[0]
        assert (path.parent / target).is_file(), f"Broken link: {path}: {ref}"

spec = (ROOT / "design" / "specification.md").read_text()
sections = re.findall(r"^### (\d+\.\d+) ", spec, re.MULTILINE)
assert len(sections) == len(set(sections)), "Duplicate detailed section number"
for ref in re.findall(r"第 (\d+\.\d+) 节", spec):
    assert ref in sections, f"Missing section {ref}"

json_files = []
for directory in ("design", "reviews"):
    json_files.extend((ROOT / directory).glob("*.json"))
for path in json_files:
    json.loads(path.read_text())

# Keep the executable profile identifiers and documented API examples aligned.
pilot = json.loads((ROOT / "design" / "pilot_profile.json").read_text())
ranking = json.loads((ROOT / "design" / "ranking_profiles.json").read_text())
profile_ids = {profile["id"] for profile in ranking["profiles"]}
assert ranking["default_profile"] in profile_ids
for block in re.findall(
    r"```json\s*\n(.*?)\n```", (ROOT / "implementation_plan.md").read_text(), re.DOTALL
):
    example = json.loads(block)
    if "retrieval_profile" in example:
        assert example["retrieval_profile"] == pilot["profile_id"], (
            "Unknown example retrieval profile"
        )
    if "ranking_profile" in example:
        assert example["ranking_profile"] in profile_ids, "Unknown example ranking profile"

assert pilot["task_budget_unit"] == "dispatched_attempt"
assert pilot["candidate_page_size"] <= pilot["max_candidate_records_received"]
assert pilot["matching_batch_size"] <= pilot["max_candidate_records_received"]
assert pilot["source_execution"]["primary_recall"] == "indexed_substructure"
assert not pilot["source_execution"]["require_morgan_similarity_threshold"]
assert pilot["source_execution"]["similarity_priority"]["merge_with_primary"] == "union"
assert pilot["source_execution"]["similarity_priority"]["activation"] == "whole_core_or_broad_query"
assert pilot["source_execution"]["molecular_size_priority"]["enabled"]
size_policy = pilot["source_execution"]["molecular_size_priority"]
assert not set(size_policy["preselection_features"]) & set(size_policy["post_match_features"])
assert "target_coverage" in size_policy["post_match_features"]
assert (
    pilot["source_execution"]["similarity_priority"]["candidate_unit"]
    == "unique_structure_representation"
)
assert pilot["source_execution"]["source_query_timeout_ms"] <= pilot["global_time_budget_ms"]
assert not pilot["source_execution"]["broad_query"]["exact_count_before_first_page"]
initial_read_and_match_tasks = 2 * 3 * pilot["initial_families_per_applicable_layer"]
assert (
    initial_read_and_match_tasks + pilot["reserved_reaction_analysis_tasks"]
    <= pilot["max_total_tasks"]
)
assert pilot["reaction_analysis_batch_size"] <= pilot["max_reaction_records_analyzed"]
assert 0 < pilot["input_usage"]["max_task_attempts"] <= pilot["max_total_tasks"]
assert pilot["input_usage"]["shares_global_budget"]
assert pilot["procedure_references"]["shares_record_expansion_budget"]
assert not pilot["procedure_references"]["inherit_example_outcomes"]
assert not pilot["markush_queries"]["mapping_enumeration_uniquify"]
assert pilot["markush_queries"]["mapping_overflow_detection_extra"] == 1
assert not ranking["comparison_policy"]["pairwise_missing_field_skipping"]
assert not ranking["comparison_policy"]["display_selection_deletes_evidence"]

case_counts = {}
for name in ("evidence", "ranking"):
    cases = json.loads((ROOT / "reviews" / f"{name}_contract_cases.json").read_text())["cases"]
    assert len({case["id"] for case in cases}) == len(cases), f"Duplicate {name} case ID"
    case_counts[name] = len(cases)
    if name == "evidence":
        for case in cases:
            assert case["expected"]["use_hit"] == (
                case["subject_id"] in case["verified_input_subject_ids"]
            ), f"Use claim lacks subject-specific evidence: {case['id']}"
acceptance = spec.split("### 13.1 ", 1)[1].split("### 13.2 ", 1)[0]
chemical_cases = sum(line.startswith("|") for line in acceptance.splitlines()) - 2
plan = (ROOT / "plan.md").read_text()
assert f"{chemical_cases} 项验收案例" in plan
assert f"{case_counts['evidence']} 个证据状态场景" in plan
assert f"{case_counts['ranking']} 个排序场景" in plan

svgs = list((ROOT / "diagrams").glob("*.svg"))
for svg in svgs:
    ET.parse(svg)

print(
    f"Integrity checked: {len(files)} Markdown files, {len(json_files)} JSON files "
    f"and {len(svgs)} diagram SVGs. No engine claims validated."
)
