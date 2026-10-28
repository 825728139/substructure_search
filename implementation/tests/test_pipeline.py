import json

from reaction_reference.adapters.sources import JsonlSource, import_native
from reaction_reference.application.search import search
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import LabContext
from reaction_reference.ranking.engine import rank_references


def test_end_to_end_package(source, request_factory):
    package = search(
        request_factory(options={"exhaustive_fixture": True}, budget={"max_tasks": 100}), source
    )
    assert package.results and package.proposals
    assert {f.layer for f in package.families} == {"whole", "core", "fragment"}
    assert not package.statistics["preparation_hits"]
    assert all(p.proposal_not_observed for p in package.proposals)
    assert len(package.tasks) <= 100
    assert package.summary_status == "complete"
    summary = json.loads(package.summary)
    assert summary and "reaction_analysis" in summary[0]
    assert package.target_input_smiles == "CCCNC(=O)c1ccccc1"
    assert summary[0]["target_witness"]["atom_order"] == "target_input_smiles_parse_order"


def test_budgets_return_usable_partial_results(source, request_factory):
    package = search(request_factory(budget={"max_tasks": 8, "max_candidates": 4}), source)
    assert package.coverage_state == "partial"
    assert package.stop_reasons
    assert package.statistics["received_candidates"] <= 4
    assert len(package.tasks) <= 8


def test_cached_matches_never_reuse_wrong_atom_indices(tmp_path, amide, request_factory):
    reversed_product = amide.materials[-1].model_copy(
        update={"instance_id": "reordered:p", "smiles": "O=C(NCC)c1ccccc1"}
    )
    other = amide.model_copy(
        update={
            "id": "reordered",
            "materials": [*amide.materials[:-1], reversed_product],
            "observations": [],
        }
    )
    path = tmp_path / "source.jsonl"
    path.write_text(amide.model_dump_json() + "\n" + other.model_dump_json() + "\n")
    source = JsonlSource(path, exhaustive=True)
    target = parse("CCNC(=O)c1ccccc1")
    package = search(
        request_factory(
            "CCNC(=O)c1ccccc1", options={"exhaustive_fixture": True}, budget={"max_tasks": 100}
        ),
        source,
    )
    for ref in package.results:
        mol = parse(ref.material.smiles)
        for witness in ref.witnesses:
            for t, s in witness.target_to_source:
                assert (
                    target.GetAtomWithIdx(t).GetAtomicNum() == mol.GetAtomWithIdx(s).GetAtomicNum()
                )


def test_bad_record_isolated(tmp_path, amide, request_factory):
    path = tmp_path / "source.jsonl"
    path.write_text("not json\n" + amide.model_dump_json() + "\n")
    source = JsonlSource(path, exhaustive=True)
    package = search(request_factory(), source)
    assert package.results
    assert package.source_issues and package.coverage_state == "partial"


def test_lab_unknown_not_easy_or_safe(source, request_factory):
    package = search(request_factory(budget={"max_tasks": 100}), source)
    ranked, _ = rank_references(package.results, "lab_fit", LabContext(max_temperature_c=30))
    net = next(r for r in ranked if r.record.id == "demo-net-amide")
    assert net.lab_fit == "unknown"
    assert "temperature_max_unknown" in net.lab_reasons


def test_imported_arrays_do_not_claim_preparation():
    record = import_native(
        {
            "id": 1,
            "source_namespace": "epo",
            "document_id": "test",
            "product_smiles": ["CCO"],
            "reactant_smiles": ["CC=O"],
        }
    )
    assert record.observations[0].result == "unknown"
    assert record.materials[1].actual_input is None


def test_atom_properties_and_ring_analysis_do_not_require_method_name(source, request_factory):
    package = search(
        request_factory("CCO", options={"include_usage": False}, budget={"max_tasks": 100}), source
    )
    reduced = next(r for r in package.results if r.record.id == "demo-alcohol")
    assert "C_O_bond_order_decrease" in reduced.analysis.reaction_classes
    assert reduced.analysis.atom_property_changes
    assert reduced.contribution == "modification"
    assert reduced.contribution_support == "synthetic_illustration"
    assert not reduced.preparation_hit


def test_dirty_string_field_is_not_split_into_atom_materials():
    import pytest

    with pytest.raises(ValueError, match="arrays"):
        import_native({"id": 1, "product_smiles": "CCO"})


def test_later_fragment_witness_can_upgrade_reaction_contribution(
    source, request_factory, monkeypatch
):
    import reaction_reference.application.search as module
    from reaction_reference.domain.models import QueryFamily
    from reaction_reference.retrieval.planner import _core_smarts

    target = parse("CCCNC(=O)c1ccccc1")
    families = []
    for layer, atoms in [("core", target.GetRingInfo().AtomRings()[0]), ("fragment", [3, 4, 5, 6])]:
        smarts, ids = _core_smarts(target, atoms, [])
        families.append(
            QueryFamily(
                id=layer,
                layer=layer,
                core_smarts=smarts,
                target_atoms=ids,
                rule_id="test",
                rule_version="1",
                description="regression",
            )
        )
    monkeypatch.setattr(module, "initial_families", lambda *_: families)
    package = module.search(
        request_factory(
            options={
                "include_usage": False,
                "include_proposals": False,
                "directed_followups": False,
                "exhaustive_fixture": True,
            }
        ),
        source,
    )
    ref = next(r for r in package.results if r.record.id == "demo-amide-ethyl")
    assert set(ref.layers) == {"core", "fragment"}
    assert ref.contribution == "local_method"
    assert ref.coverage["projected_changes"]["formed_target_bonds"]
    assert ref.coverage["method_witness_id"]


def test_mapping_incompleteness_is_accumulated_across_source_pages(
    amide, request_factory, monkeypatch
):
    import reaction_reference.application.search as module
    from reaction_reference.domain.models import Material, QueryFamily
    from reaction_reference.ports.sources import Candidate, CandidatePage

    f = QueryFamily(
        id="one",
        layer="whole",
        core_smarts="[C]",
        target_atoms=[0],
        rule_id="test",
        rule_version="1",
        description="regression",
    )
    monkeypatch.setattr(module, "initial_families", lambda *_: [f])

    class Source:
        snapshot_id = "test-fixed-pages"
        issues = []
        max_selection_stage = 0

        def candidate_page(self, family, role, cursor, *args):
            m = Material(
                instance_id=f"p{cursor}", role="product", smiles="CC" if cursor == 0 else "C"
            )
            r = amide.model_copy(
                update={"id": f"record{cursor}", "materials": [m], "observations": []}
            )
            return CandidatePage(
                [Candidate(f"s{cursor}", m, r)],
                1 if cursor == 0 else None,
                cursor == 1,
                cursor == 1,
                "test",
            )

        def hydrate(self, record):
            return record

    package = module.search(
        request_factory(
            "C",
            options={
                "include_usage": False,
                "include_proposals": False,
                "directed_followups": False,
                "exhaustive_fixture": True,
            },
            budget={"max_tasks": 100, "max_mappings": 1},
        ),
        Source(),
    )
    state = next(iter(package.family_states.values()))
    assert state["stream_exhausted"]
    assert not state["matching_enumeration_complete"]
    assert not state["complete"] and package.coverage_state == "partial"


def test_small_summary_budget_does_not_hide_full_evidence_or_claim_complete(
    source, request_factory
):
    package = search(request_factory(budget={"max_summary_bytes": 256}), source)
    assert package.results and package.summary_status == "unavailable"
    assert not package.summary
    assert package.summary_omitted_items > 0
    assert len(package.summary.encode()) <= 256


def test_detail_names_are_bound_by_structure_not_array_position():
    record = import_native(
        {
            "id": 1,
            "product_smiles": ["CCO", "CCN"],
            "details": {
                "products": [
                    {"smiles": "CCN", "name": "amine"},
                    {"smiles": "OCC", "name": "alcohol"},
                ]
            },
        }
    )
    assert [m.name for m in record.materials] == ["alcohol", "amine"]


def test_failed_similarity_selection_keeps_independent_substructure_opportunity(
    amide, request_factory, monkeypatch
):
    import reaction_reference.application.search as module
    from reaction_reference.domain.models import QueryFamily
    from reaction_reference.ports.sources import Candidate, CandidatePage

    f = QueryFamily(
        id="core",
        layer="core",
        core_smarts="[C]",
        target_atoms=[0],
        rule_id="test",
        rule_version="1",
        description="regression",
    )
    monkeypatch.setattr(module, "initial_families", lambda *_: [f])

    class Source:
        snapshot_id = "test-independent-fallback"
        issues = []
        max_selection_stage = 1
        selection_failure_fallback = True

        def candidate_page(self, family, role, cursor, limit, target, stage):
            if stage == 0:
                raise TimeoutError("bounded nearest-neighbor query timed out")
            return CandidatePage(
                [Candidate("amide", amide.materials[-1], amide)],
                None,
                True,
                True,
                "test_core_index",
            )

        def hydrate(self, record):
            return record

    package = module.search(
        request_factory(
            "C",
            options={
                "include_usage": False,
                "include_proposals": False,
                "directed_followups": False,
            },
            budget={"max_tasks": 100},
        ),
        Source(),
    )
    assert package.results and package.source_issues
    assert package.coverage_state == "partial"


def test_duplicate_record_ids_cannot_mix_materials_and_reaction_analysis(tmp_path):
    path = tmp_path / "conflict.jsonl"
    path.write_text(
        json.dumps({"id": 1, "product_smiles": ["CCO"]})
        + "\n"
        + json.dumps({"id": 1, "product_smiles": ["CCN"]})
        + "\n"
    )
    source = JsonlSource(path)
    assert not source.records and not source.candidates
    assert source.issues[0]["code"] == "conflicting_record_identity"
    row = json.dumps({"id": 1, "product_smiles": ["CCO"]}) + "\n"
    path.write_text(row + row)
    duplicate = JsonlSource(path)
    assert len(duplicate.records) == 1 and not duplicate.issues


def test_shared_structure_witness_is_bound_to_each_actual_experiment(
    tmp_path, amide, request_factory
):
    other = amide.model_copy(
        update={
            "id": "other-experiment",
            "source": amide.source.model_copy(
                update={"record_id": "other", "experiment_id": "other-experiment"}
            ),
        }
    )
    path = tmp_path / "two-experiments.jsonl"
    path.write_text(amide.model_dump_json() + "\n" + other.model_dump_json() + "\n")
    source = JsonlSource(path, exhaustive=True)
    package = search(
        request_factory(
            "CCNC(=O)c1ccccc1",
            options={
                "exhaustive_fixture": True,
                "include_usage": False,
                "include_proposals": False,
            },
            budget={"max_tasks": 100},
        ),
        source,
    )
    first = next(r for r in package.results if r.record.id == amide.id)
    second = next(r for r in package.results if r.record.id == other.id)
    assert {w.structural_witness_id for w in first.witnesses} == {
        w.structural_witness_id for w in second.witnesses
    }
    assert not ({w.id for w in first.witnesses} & {w.id for w in second.witnesses})
    assert first.coverage["method_witness_id"] in {w.id for w in first.witnesses}


def test_missing_operation_fields_do_not_rank_as_easy_conditions(source, request_factory):
    package = search(request_factory(budget={"max_tasks": 100}), source)
    known = next(r for r in package.results if r.record.id == "demo-amide-ethyl")
    unknown = known.model_copy(
        update={
            "id": "unknown-conditions",
            "record": known.record.model_copy(
                update={
                    "conditions": known.record.conditions.model_copy(
                        update={
                            "temperature_min_c": None,
                            "temperature_max_c": None,
                            "duration_seconds": None,
                        }
                    )
                }
            ),
            "ranking_features": {},
        }
    )
    ordered, _ = rank_references([unknown, known], "process_reference")
    assert ordered[0].id == known.id


def test_operation_preference_does_not_assume_zero_celsius_is_room_temperature(
    source, request_factory
):
    package = search(request_factory(budget={"max_tasks": 100}), source)
    ambient = next(r for r in package.results if r.record.id == "demo-amide-ethyl")
    chilled = ambient.model_copy(
        update={
            "id": "requires-cooling",
            "record": ambient.record.model_copy(
                update={
                    "conditions": ambient.record.conditions.model_copy(
                        update={"temperature_min_c": 0, "temperature_max_c": 0}
                    )
                }
            ),
            "ranking_features": {},
        }
    )
    ordered, _ = rank_references([chilled, ambient], "process_reference")
    assert ordered[0].id == ambient.id
