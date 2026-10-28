import time
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.adapters.run_store import FileRunStore, RevisionConflict
from reaction_reference.domain.models import RerankRequest, RunState
from reaction_reference.interfaces.api import create_app
from reaction_reference.interfaces.sdk import Client


def test_sdk_process_and_frozen_rerank(settings, request_factory, monkeypatch):
    with Client(settings) as client:
        package = client.search(request_factory())
        state = client.manager.store.load(package.run_id)
        assert state.lifecycle == "succeeded"
        assert package.results and package.proposals
        monkeypatch.setattr(
            type(client.manager.settings),
            "worker_config",
            lambda _: (_ for _ in ()).throw(AssertionError("rerank must not read source")),
        )
        reranked = client.rerank(package.run_id, RerankRequest(ranking_profile="process_reference"))
        frozen = client.manager.store.package(reranked.run_id)
        assert frozen.source_snapshot == package.source_snapshot
        assert {r.id for r in frozen.results} == {r.id for r in package.results}
        assert reranked.parent_run_id == package.run_id


def test_single_coordinator_lock(settings):
    with Client(settings), pytest.raises(RuntimeError, match="coordinator"):
        Client(settings)
    with Client(settings):
        pass


def test_api_lifecycle_auth_idempotency_and_cursor(settings, request_factory):
    settings = settings.model_copy(update={"api_token": "test-token"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/capabilities").status_code == 401
        headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "fixed"}
        assert client.get("/health/ready", headers=headers).status_code == 200
        request = request_factory().model_dump(mode="json")
        response = client.post("/v1/search-runs", json=request, headers=headers)
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        assert (
            client.post("/v1/search-runs", json=request, headers=headers).json()["run_id"] == run_id
        )
        request["target"]["value"] = "CCO"
        assert client.post("/v1/search-runs", json=request, headers=headers).status_code == 409
        for _ in range(200):
            state = client.get("/v1/search-runs/" + run_id, headers=headers).json()
            if state["lifecycle"] in ("succeeded", "failed", "timed_out"):
                break
            time.sleep(0.02)
        assert state["lifecycle"] == "succeeded", state
        url = "/v1/search-runs/" + run_id + "/results"
        first = client.get(url, params={"limit": 1}, headers=headers).json()
        assert first["results"] and first["next_cursor"]
        ref_id = first["results"][0]["item"]["id"]
        picture = client.get(
            "/v1/search-runs/" + run_id + "/structures/" + ref_id + ".svg", headers=headers
        )
        assert picture.status_code == 200 and "<svg" in picture.text
        exported = client.get("/v1/search-runs/" + run_id + "/package", headers=headers)
        assert exported.status_code == 200 and exported.json()["target_atoms"]
        assert client.get("/").status_code == 200
        second = client.get(
            url, params={"limit": 1, "cursor": first["next_cursor"]}, headers=headers
        ).json()
        assert first["snapshot_id"] == second["snapshot_id"]
        assert first["results"][0]["item"]["id"] != second["results"][0]["item"]["id"]
        assert (
            client.get(
                url, params={"cursor": first["next_cursor"] + "bad"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/search-runs/" + run_id + "/rerank",
                json={"ranking_profile": "lab_fit", "target": {"value": "CCO"}},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/search-runs",
                json={"target": {"value": "invalid("}},
                headers={"Authorization": "Bearer test-token"},
            ).status_code
            == 422
        )


def test_cancel_stops_job_and_is_terminal(settings, request_factory):
    with Client(settings) as client:
        state = client.manager.submit(request_factory())
        terminal = client.manager.cancel(state.run_id)
        assert terminal.lifecycle in ("cancelled", "succeeded")
        assert client.manager.wait(state.run_id).lifecycle == terminal.lifecycle


def test_supervisor_start_failure_does_not_leave_running(settings, request_factory, monkeypatch):
    with Client(settings) as client:
        monkeypatch.setattr(
            type(client.manager.settings),
            "worker_config",
            lambda _: (_ for _ in ()).throw(RuntimeError("start failed")),
        )
        state = client.manager.submit(request_factory())
        terminal = client.manager.wait(state.run_id)
        assert terminal.lifecycle == "failed" and terminal.error["code"] == "supervisor_failed"


def test_restart_preserves_snapshot_and_fails_interrupted(settings, request_factory):
    store = FileRunStore(settings.store_path)
    now = datetime.now(UTC).isoformat()
    state = RunState(
        run_id=uuid.uuid4().hex,
        lifecycle="running",
        request=request_factory(),
        created_at=now,
        updated_at=now,
    )
    store.create(state)
    with Client(settings) as client:
        recovered = client.manager.store.load(state.run_id)
        assert recovered.lifecycle == "failed"
        assert recovered.error["code"] == "coordinator_restarted"
        with pytest.raises(RevisionConflict):
            client.manager.store.update(recovered, recovered.revision)


def test_hard_timeout_is_terminal_and_subprocess_stops(settings, request_factory):
    with Client(settings) as client:
        state = client.manager.submit(request_factory(budget={"time_ms": 50}))
        terminal = client.manager.wait(state.run_id)
        assert terminal.lifecycle == "timed_out"
        assert client.manager.wait(state.run_id).lifecycle == "timed_out"
