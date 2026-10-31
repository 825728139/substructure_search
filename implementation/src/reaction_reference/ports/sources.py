"""检索来源的最小端口：返回具体材料候选、页级范围状态，并允许命中后按需加载记录。"""

from dataclasses import dataclass
from typing import Protocol

from reaction_reference.domain.models import Material, QueryFamily, ReactionRecord


@dataclass(frozen=True)
class Candidate:
    """一个具体材料的结构候选及其来源反应；整侧 SQL 命中不能替代此实例的图核验。"""

    structure_id: str
    material: Material
    record: ReactionRecord


@dataclass(frozen=True)
class CandidatePage:
    """一页候选、会话游标与完整性说明；流读完不等于全库或全部家族已查完。

    priority_continuation 可请求下一页优先，但编排器仍限制连续次数及总预算，不代表化学价值或允许无限续页。
    """

    items: list[Candidate]
    next_cursor: int | None
    stream_exhausted: bool
    scope_complete: bool
    enumeration_kind: str
    priority_continuation: bool = False


class CompoundSource(Protocol):
    """应用层依赖的来源协议；适配器负责连接、选择范围、分页和脏数据报告。"""

    snapshot_id: str
    issues: list[dict]

    def candidate_page(
        self,
        family: QueryFamily,
        role: str,
        cursor: int,
        limit: int,
        target_smiles: str,
        stage: int = 0,
    ) -> CandidatePage:
        """读取家族在指定角色和选择阶段中的一页候选，返回 CandidatePage。

        family 为查询家族，role 区分 product/reactant，cursor 只在同一来源会话与范围内有效；limit 限制页内来源取数，target_smiles 用于参考优先选择，stage 表示适配器声明的放宽阶段。候选仍须在应用层逐材料核验。
        """
        ...

    def close(self) -> None:
        """释放来源连接、游标或缓存；使用方应在 finally 中调用。"""
        ...

    def hydrate(self, record: ReactionRecord) -> ReactionRecord:
        """为已命中的轻量记录补读详情并返回 ReactionRecord。

        不得改变记录或材料实例身份；数据已完整的来源可以直接返回原对象。
        """
        ...
