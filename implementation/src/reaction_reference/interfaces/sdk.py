import uuid
from datetime import UTC, datetime

from reaction_reference.bootstrap import create_manager
from reaction_reference.chemistry.structures import digest, parse
from reaction_reference.domain.models import RunState
from reaction_reference.evidence.claims import summary_items
from reaction_reference.ranking.engine import rank_references
from reaction_reference.retrieval.planner import initial_families


class Client:
    def __init__(self, settings=None):
        self.manager = create_manager(settings)

    def search(self, request):
        state = self.manager.submit(request)
        state = self.manager.wait(state.run_id)
        package = self.manager.store.package(state.run_id)
        if package is None:
            raise RuntimeError(state.error or {"code": state.lifecycle})
        return package

    def preview(self, request):
        target = parse(request.target.value, target=True)
        return initial_families(
            target, request.budget.max_families, request.options.include_exact_identity
        )

    def rerank(self, run_id, request, owner="internal"):
        state = self.manager.store.load(run_id, owner)
        package = self.manager.store.package(run_id)
        if package is None:
            raise ValueError("A retained evidence snapshot is required")
        new_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        new_request = state.request.model_copy(
            update={"ranking_profile": request.ranking_profile, "lab_context": request.lab_context}
        )
        ranked, displayed = rank_references(
            package.results,
            request.ranking_profile,
            request.lab_context,
            max(3, state.request.budget.max_display - min(3, len(package.proposals))),
        )
        chosen = sorted(
            (r for r in ranked if r.id in displayed), key=lambda r: r.display_position or 0
        )
        shown_proposals = package.proposals[
            : max(0, state.request.budget.max_display - len(displayed))
        ]
        summary, summary_state, omitted = summary_items(
            chosen, shown_proposals, state.request.budget.max_summary_bytes
        )
        new_package = package.model_copy(
            update={
                "run_id": new_id,
                "snapshot_id": digest([new_id, package.snapshot_id, request.model_dump()]),
                "results": ranked,
                "displayed_reference_ids": displayed,
                "displayed_proposal_ids": [p.id for p in shown_proposals],
                "summary": summary,
                "summary_status": summary_state,
                "summary_omitted_items": omitted,
                "manifest": {
                    **package.manifest,
                    "reranked_from_snapshot": package.snapshot_id,
                    "request": new_request.model_dump(),
                },
            }
        )
        new_state = RunState(
            run_id=new_id,
            lifecycle="succeeded",
            request=new_request,
            created_at=now,
            updated_at=now,
            owner=owner,
            snapshot_id=new_package.snapshot_id,
            parent_run_id=run_id,
        )
        self.manager.store.create(new_state)
        self.manager.store.save_package(new_package)
        return new_state

    def close(self):
        self.manager.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
