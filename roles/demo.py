"""Deterministic fixture provider; not an AI model or general code agent."""

from core.models import FileEdit, Implementation, Plan, Review, TaskRequest, TestResult


class DemoProvider:
    """Handles only the bundled calculator fixture scenario."""

    old_expression = "def add(left: int, right: int) -> int:\n    # Deliberate bug for the isolated demo scenario.\n    return left - right"
    new_expression = "def add(left: int, right: int) -> int:\n    # Deliberate bug for the isolated demo scenario.\n    return left + right"

    def plan(self, request: TaskRequest) -> Plan:
        objective = request.objective.lower()
        if "calculator" not in objective and "جمع" not in objective and "add" not in objective:
            raise ValueError("Demo provider only supports the bundled calculator regression scenario")
        return Plan(
            summary="Fix calculator addition and run its focused regression test.",
            steps=("inspect fixture", "apply one-line fix", "run focused regression test", "review diff"),
            test_profile="demo_regression",
            expected_files=("calculator.py",),
        )

    def implement(self, request: TaskRequest, plan: Plan) -> Implementation:
        return Implementation(
            edits=(FileEdit("calculator.py", self.old_expression, self.new_expression),),
            explanation="The add function used subtraction; replace the operator and check regression cases.",
        )

    def review(
        self, request: TaskRequest, plan: Plan, implementation: Implementation,
        diff: str, tests: TestResult,
    ) -> Review:
        findings: list[str] = []
        if not tests.passed:
            findings.append("Regression test did not pass")
        if "return left + right" not in diff:
            findings.append("Expected addition fix is absent from the diff")
        if "calculator.py" not in diff:
            findings.append("Diff does not include the expected fixture file")
        return Review(approved=not findings, findings=tuple(findings))
