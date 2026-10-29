"""每次检索的单调时钟预算与任务/候选/反应计数；原生计算的强制终止由外层进程监督负责。"""

import time

from reaction_reference.domain.models import TaskEvent


class BudgetExceeded(Exception):
    """任一全局资源上限达到时抛出的停止信号；编排器捕获后保留部分结果。"""

    pass


class Budget:
    """单次业务执行的共享预算对象，保存 deadline、计数器与 TaskEvent 轨迹。"""

    def __init__(self, config):
        """接收 BudgetConfig，以当前单调时钟建立执行截止时间并将计数归零。

        时间不包含排队等待；协调器另有覆盖子进程启动和运行的硬截止时间。
        """
        self.config = config
        self.started = time.monotonic()
        self.deadline = self.started + config.time_ms / 1000
        self.events = []
        self.received = 0
        self.reactions = 0

    def check(self):
        """检查当前时间是否达到 deadline；超时抛出 BudgetExceeded，无返回值。"""
        if time.monotonic() >= self.deadline:
            raise BudgetExceeded("global_deadline")

    def task(self, kind, scope, *, reserve=0):
        """检查时间和任务额度后记入一条 TaskEvent。

        kind/scope 标明任务类别和范围，reserve 为后续阶段预留任务数；失败调用不会增加计数。已失败的来源调用因调用前计数，仍消耗一次真实尝试。
        """
        self.check()
        if len(self.events) >= self.config.max_tasks - reserve:
            raise BudgetExceeded("task_budget")
        self.events.append(
            TaskEvent(
                attempt=len(self.events) + 1,
                kind=kind,
                scope=scope,
                elapsed_ms=round((time.monotonic() - self.started) * 1000, 3),
            )
        )

    def candidate(self):
        """在逐候选处理前检查时间和候选上限，然后增加接收计数。

        计数的是本次处理次数，跨家族重复出现的结构也会消耗预算。
        """
        self.check()
        if self.received >= self.config.max_candidates:
            raise BudgetExceeded("candidate_budget")
        self.received += 1

    def reaction(self):
        """在首次分析一个反应前检查时间和反应上限，然后增加分析计数。

        按来源记录复用分析结果的去重由编排器负责。
        """
        self.check()
        if self.reactions >= self.config.max_reactions:
            raise BudgetExceeded("reaction_budget")
        self.reactions += 1
