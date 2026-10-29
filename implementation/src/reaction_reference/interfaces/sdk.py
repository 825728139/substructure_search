"""面向内部 Python 调用方的统一 SDK；检索使用受监督任务，重排仅消费已有冻结证据。"""

import uuid
from datetime import UTC, datetime

from reaction_reference.bootstrap import create_manager
from reaction_reference.chemistry.structures import digest, parse
from reaction_reference.domain.models import RunState
from reaction_reference.evidence.claims import summary_items
from reaction_reference.ranking.engine import rank_references
from reaction_reference.retrieval.planner import initial_families


class Client:
    """管理协调器生命周期的 Python 客户端，推荐在 with 语句和脚本 main 保护内使用。"""

    def __init__(self, settings=None):
        """通过统一装配入口创建 RunManager，读取 Settings 或使用传入配置。

        会获取运行目录锁；创建多个客户端时应使用不同目录或复用同一实例。
        """
        self.manager = create_manager(settings)

    def search(self, request):
        """提交 SearchRequest 并等待执行完成，返回保留的 ReferencePackage。

        可返回包含停止原因的部分结果；只有完全没有阶段包时抛出 RuntimeError。因为启动 spawn，脚本调用应放在 if __name__ == "__main__" 内。
        """
        state = self.manager.submit(request)
        state = self.manager.wait(state.run_id)
        package = self.manager.store.package(state.run_id)
        if package is None:
            raise RuntimeError(state.error or {"code": state.lifecycle})
        return package

    def preview(self, request):
        """仅解析目标并生成与真实检索相同的初始家族列表，不查询来源。

        使用请求中的家族上限和严格目标补查开关，便于检查核心/位点语义。
        """
        target = parse(request.target.value, target=True)
        return initial_families(
            target, request.budget.max_families, request.options.include_exact_identity
        )

    def rerank(self, run_id, request, owner="internal"):
        """在 owner 范围内，从已有资料快照创建一个立即完成的重排派生 run。

        request 为 RerankRequest，仅允许排序偏好和实验限制；保留所有已评估候选、事实、见证与来源快照。先保存运行状态，快照落盘后才标记成功；失败经协调器统一收尾。返回新 RunState，不重查来源、不生成新建议，也不允许更改目标。
        """
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
        # 沿用排序器给出的展示位置，重排不重算来源事实或结构见证。
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
            lifecycle="running",
            request=new_request,
            created_at=now,
            updated_at=now,
            owner=owner,
            parent_run_id=run_id,
        )
        self.manager.store.create(new_state)
        try:
            self.manager.store.save_package(new_package)
        except Exception:
            self.manager._finish(
                new_id,
                "failed",
                {
                    "code": "rerank_snapshot_failed",
                    "message": "Reranked snapshot could not be saved",
                },
            )
            raise
        return self.manager._finish(new_id, "succeeded", snapshot_id=new_package.snapshot_id)

    def close(self):
        """关闭协调器，停止其未完成任务并释放运行目录锁。"""
        self.manager.close()

    def __enter__(self):
        """返回当前客户端，供 with 语句复用同一个协调器。"""
        return self

    def __exit__(self, *_):
        """退出 with 时关闭客户端；不吞掉业务块抛出的异常。"""
        self.close()
