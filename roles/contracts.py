"""Independent input/output contracts for each workflow role."""

from typing import Protocol

from core.models import Implementation, Plan, Review, TaskRequest, TestResult


class Planner(Protocol):
    def plan(self, request: TaskRequest) -> Plan: ...


class Executor(Protocol):
    def implement(self, request: TaskRequest, plan: Plan) -> Implementation: ...


class Reviewer(Protocol):
    def review(
        self,
        request: TaskRequest,
        plan: Plan,
        implementation: Implementation,
        diff: str,
        tests: TestResult,
    ) -> Review: ...
