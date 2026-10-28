import time

from reaction_reference.domain.models import TaskEvent


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, config):
        self.config = config
        self.started = time.monotonic()
        self.deadline = self.started + config.time_ms / 1000
        self.events = []
        self.received = 0
        self.reactions = 0

    def check(self):
        if time.monotonic() >= self.deadline:
            raise BudgetExceeded("global_deadline")

    def task(self, kind, scope, *, reserve=0):
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
        self.check()
        if self.received >= self.config.max_candidates:
            raise BudgetExceeded("candidate_budget")
        self.received += 1

    def reaction(self):
        self.check()
        if self.reactions >= self.config.max_reactions:
            raise BudgetExceeded("reaction_budget")
        self.reactions += 1
