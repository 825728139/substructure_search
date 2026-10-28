import base64
import hashlib
import hmac
import json
import secrets
from contextlib import asynccontextmanager
from importlib.resources import files

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from reaction_reference.adapters.execution import CapacityExceeded
from reaction_reference.adapters.run_store import RevisionConflict
from reaction_reference.bootstrap import open_source
from reaction_reference.domain.models import RerankRequest, SearchRequest
from reaction_reference.interfaces.sdk import Client
from reaction_reference.rules import capabilities, load_rules
from reaction_reference.settings import Settings


def create_app(settings=None):
    settings = settings or Settings()
    client = Client(settings)
    secret = (settings.cursor_secret or secrets.token_hex(32)).encode()

    @asynccontextmanager
    async def lifespan(_):
        yield
        await run_in_threadpool(client.close)

    app = FastAPI(title="Reaction Reference", version="0.1.0", lifespan=lifespan)
    app.state.client = client

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        return files("reaction_reference").joinpath("interfaces/static/index.html").read_text()

    def owner(authorization: str | None = Header(default=None)):
        if settings.api_token:
            supplied = authorization or ""
            if not secrets.compare_digest(supplied, f"Bearer {settings.api_token}"):
                raise HTTPException(401, "Authentication required")
        return "internal"

    def encode_cursor(data):
        payload = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode()
        signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def decode_cursor(cursor):
        try:
            if len(cursor) > 2048:
                raise ValueError()
            payload, signature = cursor.rsplit(".", 1)
            expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            return json.loads(base64.urlsafe_b64decode(payload))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise HTTPException(422, "Invalid or expired result cursor") from None

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse(status_code=404, content={"code": "not_found", "message": str(exc)})

    @app.exception_handler(RevisionConflict)
    async def conflict(_, exc):
        return JSONResponse(status_code=409, content={"code": "conflict", "message": str(exc)})

    @app.exception_handler(CapacityExceeded)
    async def capacity(_, exc):
        return JSONResponse(status_code=429, content={"code": "capacity", "message": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse(
            status_code=422, content={"code": "invalid_request", "message": str(exc)[:400]}
        )

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(_=Depends(owner)):
        try:
            load_rules()
            source = open_source(settings)
            source.close()
        except Exception as exc:
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "reason": type(exc).__name__}
            )
        return {"status": "ready", "source": settings.source_kind}

    @app.get("/v1/capabilities")
    def get_capabilities(_=Depends(owner)):
        return capabilities()

    @app.post("/v1/query-families/preview")
    def preview(request: SearchRequest, _=Depends(owner)):
        return {"families": [f.model_dump() for f in client.preview(request)]}

    @app.post("/v1/search-runs", status_code=202)
    def submit(
        request: SearchRequest,
        idempotency_key: str | None = Header(default=None),
        scope=Depends(owner),
    ):
        if idempotency_key and len(idempotency_key) > 256:
            raise HTTPException(422, "Idempotency key too long")
        return client.manager.submit(request, owner=scope, idempotency_key=idempotency_key)

    @app.get("/v1/search-runs/{run_id}")
    def status(run_id: str, scope=Depends(owner)):
        state = client.manager.store.load(run_id, scope)
        package = client.manager.store.package(run_id)
        return {
            **state.model_dump(),
            "coverage_state": package.coverage_state if package else None,
            "statistics": package.statistics if package else {},
            "latest_snapshot_id": package.snapshot_id if package else None,
        }

    @app.get("/v1/search-runs/{run_id}/results")
    def results(
        run_id: str,
        cursor: str | None = None,
        limit: int = Query(18, ge=1, le=100),
        scope=Depends(owner),
    ):
        client.manager.store.load(run_id, scope)
        offset, snapshot = 0, None
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded.get("run_id") != run_id or decoded.get("owner") != scope:
                raise HTTPException(422, "Cursor belongs to another run")
            offset, snapshot = decoded["offset"], decoded["snapshot"]
        package = client.manager.store.package(run_id, snapshot)
        if package is None:
            return {
                "results": [],
                "snapshot_id": None,
                "coverage_state": "partial",
                "next_cursor": None,
            }
        by_id = {r.id: r for r in package.results}
        by_proposal = {p.id: p for p in package.proposals}
        cards = [
            {"kind": "source_reference", "item": by_id[i].model_dump()}
            for i in package.displayed_reference_ids
        ] + [
            {"kind": "proposal_not_observed", "item": by_proposal[i].model_dump()}
            for i in package.displayed_proposal_ids
        ]
        end = offset + limit
        next_cursor = (
            encode_cursor(
                {"owner": scope, "run_id": run_id, "snapshot": package.snapshot_id, "offset": end}
            )
            if end < len(cards)
            else None
        )
        return {
            "results": cards[offset:end],
            "snapshot_id": package.snapshot_id,
            "coverage_state": package.coverage_state,
            "stop_reasons": package.stop_reasons,
            "feature_status": package.feature_status,
            "statistics": package.statistics,
            "next_cursor": next_cursor,
            "summary_status": package.summary_status,
        }

    @app.get("/v1/search-runs/{run_id}/evidence/{claim_id}")
    def evidence(run_id: str, claim_id: str, scope=Depends(owner)):
        client.manager.store.load(run_id, scope)
        package = client.manager.store.package(run_id)
        if package:
            for ref in package.results:
                for claim in ref.claims:
                    if claim.id == claim_id:
                        return claim
                for witness in ref.witnesses:
                    if witness.id == claim_id:
                        return {
                            "witness": witness,
                            "source": ref.record.source,
                            "analysis": ref.analysis,
                        }
        raise HTTPException(404, "Evidence not found in this run")

    @app.get("/v1/search-runs/{run_id}/package")
    def export_package(run_id: str, snapshot: str | None = None, scope=Depends(owner)):
        client.manager.store.load(run_id, scope)
        package = client.manager.store.package(run_id, snapshot)
        if package is None:
            raise HTTPException(409, "No evidence snapshot is available yet")
        return Response(package.model_dump_json(), media_type="application/json")

    @app.get("/v1/search-runs/{run_id}/structures/{reference_id}.svg")
    def structure(
        run_id: str, reference_id: str, snapshot: str | None = None, scope=Depends(owner)
    ):
        from reaction_reference.interfaces.depiction import reference_svg

        client.manager.store.load(run_id, scope)
        package = client.manager.store.package(run_id, snapshot)
        if package:
            reference = next((r for r in package.results if r.id == reference_id), None)
            if reference:
                return Response(
                    reference_svg(reference),
                    media_type="image/svg+xml",
                    headers={
                        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"
                    },
                )
        raise HTTPException(404, "Reference structure not found in this run")

    @app.post("/v1/search-runs/{run_id}/cancel")
    def cancel(run_id: str, scope=Depends(owner)):
        return client.manager.cancel(run_id, scope)

    @app.post("/v1/search-runs/{run_id}/rerank", status_code=202)
    def rerank(run_id: str, request: RerankRequest, scope=Depends(owner)):
        return client.rerank(run_id, request, scope)

    return app
