"""内部 HTTP 与页面入口；协议、认证和展示留在接口层，化学检索由 SDK/协调器执行。"""

import base64
import hashlib
import hmac
import json
import secrets
from contextlib import asynccontextmanager
from importlib.resources import files

from anyio import CancelScope
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
    """装配 FastAPI 应用、共享 Client、内部认证和快照分页接口，返回 app。

    settings 可注入测试配置；构造时建立运行目录协调锁。服务应使用单 worker；lifespan 结束时统一关闭任务和锁。
    """
    settings = settings or Settings()
    client = Client(settings)
    secret = (settings.cursor_secret or secrets.token_hex(32)).encode()

    @asynccontextmanager
    async def lifespan(_):
        """应用启动后接管共享客户端的生命周期，关闭时在线程池中等待清理。

        清理可能停止计算进程，不能阻塞事件循环；启动资源已在 create_app 中创建。
        """
        try:
            yield
        finally:
            # 生命周期异常或取消时仍完成资源清理，不将目录锁留给失效客户端。
            with CancelScope(shield=True):
                await run_in_threadpool(client.close)

    app = FastAPI(title="Reaction Reference", version="0.1.0", lifespan=lifespan)
    app.state.client = client

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        """返回随包分发的内部查看页面 HTML；页面本身不包含业务证据或访问令牌。"""
        return files("reaction_reference").joinpath("interfaces/static/index.html").read_text()

    def owner(authorization: str | None = Header(default=None)):
        """验证可选内部 Bearer 令牌，返回固定 internal 访问范围。

        配置令牌时使用常量时间比较，缺失/错误返回 401；这是内部单范围服务，不是多用户账户系统。
        """
        if settings.api_token:
            supplied = authorization or ""
            if not secrets.compare_digest(
                supplied.encode(), f"Bearer {settings.api_token}".encode()
            ):
                raise HTTPException(401, "Authentication required")
        return "internal"

    def encode_cursor(data):
        """将运行、owner、snapshot 和 offset 编码并附加 HMAC 签名，返回分页令牌。

        令牌绑定不可变展示快照；签名保证完整性，不对内容加密。
        """
        payload = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode()
        signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def decode_cursor(cursor):
        """校验分页令牌长度和 HMAC 后恢复游标字段，非法内容返回 422。

        实际 run/owner 绑定还由 results 核验；签名密钥改变后旧令牌无法继续使用。
        """
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
        """把不存在或不可见的运行/快照 KeyError 转为 404 JSON。"""
        return JSONResponse(status_code=404, content={"code": "not_found", "message": str(exc)})

    @app.exception_handler(RevisionConflict)
    async def conflict(_, exc):
        """把 revision、幂等或快照冲突转为 409 JSON。"""
        return JSONResponse(status_code=409, content={"code": "conflict", "message": str(exc)})

    @app.exception_handler(CapacityExceeded)
    async def capacity(_, exc):
        """把协调器容量不足转换为 429 JSON，不在 HTTP 层继续排无限任务。"""
        return JSONResponse(status_code=429, content={"code": "capacity", "message": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        """把业务输入 ValueError 转为 422，截断消息长度，不返回原生堆栈。"""
        return JSONResponse(
            status_code=422, content={"code": "invalid_request", "message": str(exc)[:400]}
        )

    @app.get("/health/live")
    def live():
        """返回进程存活标志，不检查来源连接，因此不代表检索已就绪。"""
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(_=Depends(owner)):
        """校验规则并尝试打开/关闭来源，返回 ready 或 503。

        来源缺索引、连接不可用等返回受限异常类型；不执行完整目标检索或修改源数据。
        """
        try:
            load_rules()
            source = open_source(settings)
            source.close()
        except Exception as exc:
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "reason": type(exc).__name__}
            )
        return {
            "status": "ready",
            "source": settings.source_kind,
            "recovery_issues": client.manager.store.recovery_issues,
        }

    @app.get("/v1/capabilities")
    def get_capabilities(_=Depends(owner)):
        """返回当前规则版本、支持查询/分析能力及未支持范围，受内部认证保护。"""
        return capabilities()

    @app.post("/v1/query-families/preview")
    def preview(request: SearchRequest, _=Depends(owner)):
        """调用 SDK 生成初始查询家族并序列化返回，不读取来源反应。"""
        return {"families": [f.model_dump() for f in client.preview(request)]}

    @app.post("/v1/search-runs", status_code=202)
    def submit(
        request: SearchRequest,
        idempotency_key: str | None = Header(default=None),
        scope=Depends(owner),
    ):
        """校验幂等键长度后提交检索，返回 202 和初始 RunState。

        SearchRequest 由 FastAPI/Pydantic 先校验，化学计算在独立进程中进行；同键异请求按 409 处理。
        """
        if idempotency_key and len(idempotency_key) > 256:
            raise HTTPException(422, "Idempotency key too long")
        return client.manager.submit(request, owner=scope, idempotency_key=idempotency_key)

    @app.get("/v1/search-runs/{run_id}")
    def status(run_id: str, scope=Depends(owner)):
        """读取访问范围内的运行状态，并附上最新已保存快照的统计与完整性。

        queued/running 也可能已有阶段包；latest_snapshot_id 供客户端判断是否切换显示。
        """
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
        """按已发布的展示 ID 顺序返回参考卡片和建议卡片及下页游标。

        首次请求读取 latest，后续 cursor 固定 snapshot/owner/run；limit 只分页该快照的展示集合，不重新做来源检索。没有阶段结果时返回空的部分范围响应。
        """
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
        """在指定 run 的最新资料包中查找 Claim 或实验绑定 Witness。

        只返回当前运行内的证据及来源/反应分析；无法找到时返回 404，不跨运行借用同结构的其他实验。
        """
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
        """返回访问范围内的完整 JSON 资料包，可指定固定 snapshot。

        未产生任何资料快照时返回 409；返回包括未入选展示的全部已评估候选。
        """
        client.manager.store.load(run_id, scope)
        package = client.manager.store.package(run_id, snapshot)
        if package is None:
            raise HTTPException(409, "No evidence snapshot is available yet")
        return Response(package.model_dump_json(), media_type="application/json")

    @app.get("/v1/search-runs/{run_id}/structures/{reference_id}.svg")
    def structure(
        run_id: str, reference_id: str, snapshot: str | None = None, scope=Depends(owner)
    ):
        """为运行内的指定参考生成带原子高亮的 SVG，可指定固定 snapshot。

        只绘制已保存材料和见证，不接收任意来源路径；找不到参考返回 404，并对 SVG 使用限制性响应策略。
        """
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
        """请求协调器停止运行并返回其真实终态或当前状态，不在接口层伪造取消成功。"""
        return client.manager.cancel(run_id, scope)

    @app.post("/v1/search-runs/{run_id}/rerank", status_code=202)
    def rerank(run_id: str, request: RerankRequest, scope=Depends(owner)):
        """在当前访问范围内创建冻结证据重排 run，返回 202 和派生状态。

        请求仅有排序偏好与实验限制，目标或来源条件变化必须另开新检索。
        """
        return client.rerank(run_id, request, scope)

    return app
