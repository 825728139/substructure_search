"""请求隔离与结果接收竞态：持久化请求必须与实际执行一致。"""

import threading
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from reaction_reference.adapters import execution
from reaction_reference.domain.models import LabContext, ReferencePackage, RerankRequest, RunState
from reaction_reference.interfaces.api import create_app
from reaction_reference.interfaces.sdk import Client


@pytest.mark.parametrize("mutate_returned", [False, True])
def test_submitted_request_is_detached_from_caller(
    settings, request_factory, monkeypatch, mutate_returned
):
    """修改原请求或返回状态中的嵌套列表，都不能改变已经接纳的后台请求。"""
    entered, release = threading.Event(), threading.Event()
    observed = []
    with Client(settings) as client:

        def hold(state, cancellation):
            """暂停工作线程，捕获外部修改之后实际执行所见的请求。"""
            entered.set()
            assert release.wait(3)
            observed.append(state.request.model_dump())
            client.manager._finish(state.run_id, "cancelled")

        monkeypatch.setattr(client.manager, "_supervise", hold)
        request = request_factory(lab_context=LabContext(excluded_material_smiles=["CCN"]))
        state = client.manager.submit(request)
        try:
            assert entered.wait(1)
            persisted = client.manager.store.load(state.run_id).request.model_dump()
            mutable = state.request if mutate_returned else request
            mutable.lab_context.excluded_material_smiles.append("invalid(")
        finally:
            release.set()
        client.manager.wait(state.run_id)
        assert observed == [persisted]


def test_client_settings_are_detached_from_caller(settings):
    """调用方修改传入 Settings 不能悄悄改变已有客户端的来源和执行配置。"""
    with Client(settings) as client:
        original = client.manager.settings.worker_config()
        settings.source_kind = "postgres"
        settings.source_timeout_ms = 100
        assert client.manager.settings.worker_config() == original


def test_api_auth_configuration_is_detached_from_caller(settings):
    """外部复用配置对象并清空令牌时，已创建应用仍必须拒绝未认证请求。"""
    settings.api_token = "initial-token"
    with TestClient(create_app(settings)) as client:
        settings.api_token = None
        assert client.get("/v1/capabilities").status_code == 401
        assert (
            client.get(
                "/v1/capabilities", headers={"Authorization": "Bearer initial-token"}
            ).status_code
            == 200
        )


def test_api_readiness_uses_the_same_source_as_worker(settings, tmp_path):
    """外部修改来源路径时，就绪探测仍须检查应用实际执行任务所用的原配置。"""
    app = create_app(settings)
    with TestClient(app) as client:
        settings.source_path = tmp_path / "missing.jsonl"
        response = client.get("/health/ready")
        assert response.status_code == 200, response.text
        assert app.state.client.manager.settings.source_path != settings.source_path


def test_rerank_freezes_request_before_computation(settings, request_factory, monkeypatch):
    """重排正在计算时外部改变请求列表，不能改变派生任务保存的实验要求。"""
    import reaction_reference.interfaces.sdk as sdk

    request = RerankRequest(lab_context=LabContext(excluded_material_smiles=["CCN"]))
    with Client(settings) as client:
        now = datetime.now(UTC).isoformat()
        state = RunState(
            run_id=uuid.uuid4().hex,
            lifecycle="succeeded",
            request=request_factory(),
            created_at=now,
            updated_at=now,
        )
        client.manager.store.create(state)
        package = ReferencePackage(
            run_id=state.run_id,
            snapshot_id="a" * 24,
            target_smiles="CCO",
            target_atoms=[],
            source_snapshot="fixture",
            manifest={},
            families=[],
            results=[],
            coverage_state="partial",
        )
        client.manager.store.save_package(package)
        original = sdk.rank_references

        def mutate_during_rank(*args, **kwargs):
            """模拟另一调用方在排序过程中修改原请求，仍执行真实排序函数。"""
            request.lab_context.excluded_material_smiles.append("invalid(")
            return original(*args, **kwargs)

        monkeypatch.setattr(sdk, "rank_references", mutate_during_rank)
        derived = client.rerank(state.run_id, request)
        assert derived.request.lab_context.excluded_material_smiles == ["CCN"]
        saved = client.manager.store.package(derived.run_id)
        assert saved.manifest["request"]["lab_context"]["excluded_material_smiles"] == ["CCN"]


@pytest.mark.parametrize("interrupt", ["deadline", "cancel"])
def test_final_message_cannot_override_interrupt_during_receive(
    settings, request_factory, monkeypatch, interrupt
):
    """结果在等待消息期间触及截止或收到取消时，不得绕过二次检查标记成功。"""
    clock = [0.0]
    cancellation = threading.Event()
    with Client(settings) as client:
        now = datetime.now(UTC).isoformat()
        request = request_factory(budget={"time_ms": 50})
        state = RunState(
            run_id=uuid.uuid4().hex,
            lifecycle="queued",
            request=request,
            created_at=now,
            updated_at=now,
        )
        client.manager.store.create(state)
        package = ReferencePackage(
            run_id=state.run_id,
            snapshot_id="b" * 24,
            target_smiles="CCO",
            target_atoms=[],
            source_snapshot="fixture",
            manifest={},
            families=[],
            results=[],
            coverage_state="partial",
        )

        class Channel:
            """无需系统通信的管道端点替身。"""

            def close(self):
                """端点关闭不影响本例的接收时序。"""
                pass

        class Process:
            """立即结束的进程替身，避免实际启动干扰时钟。"""

            def start(self):
                """模拟已启动。"""
                pass

            def is_alive(self):
                """结果已就绪，没有仍在运行的进程。"""
                return False

            def close(self):
                """模拟句柄清理。"""
                pass

        class Context:
            """返回确定性进程和管道替身。"""

            def Pipe(self, duplex=False):
                """构造独立收发端。"""
                return Channel(), Channel()

            def Process(self, **kwargs):
                """提供不消耗真实时间的进程。"""
                return Process()

        class Messages:
            """模拟结果在 get 等待期间才到达，并同时触发中断。"""

            def __init__(self, **kwargs):
                """兼容有界队列初始化。"""
                pass

            def get(self, timeout=None):
                """返回结果之前推进时钟或设置取消事件。"""
                if interrupt == "deadline":
                    clock[0] = 0.1
                else:
                    cancellation.set()
                return "result", package.model_dump_json()

        def no_receiver(*args):
            """本地队列已控制接收结果，不需要独立读取。"""
            return None

        monkeypatch.setattr(execution.multiprocessing, "get_context", lambda _: Context())
        monkeypatch.setattr(execution.queue, "Queue", Messages)
        monkeypatch.setattr(execution, "_receive_packages", no_receiver)
        monkeypatch.setattr(execution.time, "monotonic", lambda: clock[0])
        client.manager._execute(state, cancellation)
        terminal = client.manager.store.load(state.run_id)
        assert terminal.lifecycle == ("timed_out" if interrupt == "deadline" else "cancelled")
