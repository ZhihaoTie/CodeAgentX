"""Metrics extracted from an AgentState trajectory."""

from __future__ import annotations

from dataclasses import dataclass

from codeagentx.agent.state import AgentState, TaskStatus


@dataclass(frozen=True)
class TrajectoryMetrics:
    task_id: str
    status: str
    turns: int
    tool_calls: int
    failed_tool_calls: int
    success: bool
    test_runs: int
    edit_count: int
    read_count: int
    plan_step_count: int = 0
    plan_completed_steps: int = 0
    plan_blocked_steps: int = 0
    plan_progress: float = 0.0
    plan_complete: bool = False
    plan_repair_count: int = 0
    plan_repair_last_strategy: str | None = None
    plan_repair_focused_test_command: str | None = None
    ast_context_queries: int = 0
    verification_status: str | None = None
    verified_success: bool = False
    structured_tests_total: int | None = None
    structured_tests_passed: int | None = None
    structured_tests_failed: int = 0
    structured_test_errors: int = 0
    structured_tests_skipped: int = 0
    task_constraint_status: str | None = None
    task_constraint_failed: bool = False
    task_constraint_violation_count: int = 0
    task_success_criteria_count: int = 0
    patch_policy_status: str | None = None
    patch_policy_failed: bool = False
    patch_policy_violation_count: int = 0
    patch_policy_changed_files: int = 0
    patch_policy_changed_lines: int = 0
    context_ranking_count: int = 0
    context_candidate_count: int = 0
    context_top_score: int | None = None
    context_sources: list[str] | None = None
    rollback_status: str | None = None
    rollback_attempted: int = 0
    rollback_restored: int = 0
    rollback_failed: int = 0
    verification_sandbox_type: str | None = None
    verification_sandbox_status: str | None = None
    verification_sandbox_timed_out: bool = False
    verification_sandbox_violation: str = ""
    verification_artifact_count: int = 0
    verification_artifact_dir: str | None = None
    verification_workspace_sha256: str | None = None
    verification_workspace_file_count: int = 0
    reflection_status: str | None = None
    reflection_retryable: bool | None = None
    reflection_signal_count: int = 0
    reflection_categories: list[str] | None = None
    reflection_retry_count: int = 0
    reflection_retry_last_status: str | None = None
    reflection_retry_exhausted: bool = False
    reflection_retry_strategy: str | None = None
    reflection_retry_actions: list[str] | None = None
    tool_planning_guidance_count: int = 0
    tool_planning_guidance_blocked: int = 0
    tool_planning_guidance_warnings: int = 0
    tool_planning_guidance_last_strategy: str | None = None
    memory_retrieval_count: int = 0
    memory_hit_count: int = 0
    memory_candidate_count: int = 0
    memory_filtered_count: int = 0
    memory_prompt_injected_count: int = 0
    memory_top_score: int | None = None
    memory_extraction_count: int = 0
    memory_stored_count: int = 0
    memory_duplicate_count: int = 0
    budget_max_turns: int | None = None
    budget_max_tool_calls: int | None = None
    budget_max_run_seconds: float | None = None
    budget_turns: int = 0
    budget_tool_calls: int = 0
    budget_input_tokens: int = 0
    budget_output_tokens: int = 0
    budget_total_tokens: int = 0
    budget_elapsed_seconds: float = 0.0
    budget_exhausted: bool = False
    budget_exhausted_reason: str | None = None

    @property
    def tool_error_rate(self) -> float:
        if self.tool_calls == 0:
            return 0.0
        return self.failed_tool_calls / self.tool_calls

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "tool_error_rate": self.tool_error_rate,
            "success": self.success,
            "test_runs": self.test_runs,
            "edit_count": self.edit_count,
            "read_count": self.read_count,
            "plan_step_count": self.plan_step_count,
            "plan_completed_steps": self.plan_completed_steps,
            "plan_blocked_steps": self.plan_blocked_steps,
            "plan_progress": self.plan_progress,
            "plan_complete": self.plan_complete,
            "plan_repair_count": self.plan_repair_count,
            "plan_repair_last_strategy": self.plan_repair_last_strategy,
            "plan_repair_focused_test_command": self.plan_repair_focused_test_command,
            "ast_context_queries": self.ast_context_queries,
            "verification_status": self.verification_status,
            "verified_success": self.verified_success,
            "structured_tests_total": self.structured_tests_total,
            "structured_tests_passed": self.structured_tests_passed,
            "structured_tests_failed": self.structured_tests_failed,
            "structured_test_errors": self.structured_test_errors,
            "structured_tests_skipped": self.structured_tests_skipped,
            "task_constraint_status": self.task_constraint_status,
            "task_constraint_failed": self.task_constraint_failed,
            "task_constraint_violation_count": self.task_constraint_violation_count,
            "task_success_criteria_count": self.task_success_criteria_count,
            "patch_policy_status": self.patch_policy_status,
            "patch_policy_failed": self.patch_policy_failed,
            "patch_policy_violation_count": self.patch_policy_violation_count,
            "patch_policy_changed_files": self.patch_policy_changed_files,
            "patch_policy_changed_lines": self.patch_policy_changed_lines,
            "context_ranking_count": self.context_ranking_count,
            "context_candidate_count": self.context_candidate_count,
            "context_top_score": self.context_top_score,
            "context_sources": list(self.context_sources or []),
            "rollback_status": self.rollback_status,
            "rollback_attempted": self.rollback_attempted,
            "rollback_restored": self.rollback_restored,
            "rollback_failed": self.rollback_failed,
            "verification_sandbox_type": self.verification_sandbox_type,
            "verification_sandbox_status": self.verification_sandbox_status,
            "verification_sandbox_timed_out": self.verification_sandbox_timed_out,
            "verification_sandbox_violation": self.verification_sandbox_violation,
            "verification_artifact_count": self.verification_artifact_count,
            "verification_artifact_dir": self.verification_artifact_dir,
            "verification_workspace_sha256": self.verification_workspace_sha256,
            "verification_workspace_file_count": self.verification_workspace_file_count,
            "reflection_status": self.reflection_status,
            "reflection_retryable": self.reflection_retryable,
            "reflection_signal_count": self.reflection_signal_count,
            "reflection_categories": list(self.reflection_categories or []),
            "reflection_retry_count": self.reflection_retry_count,
            "reflection_retry_last_status": self.reflection_retry_last_status,
            "reflection_retry_exhausted": self.reflection_retry_exhausted,
            "reflection_retry_strategy": self.reflection_retry_strategy,
            "reflection_retry_actions": list(self.reflection_retry_actions or []),
            "tool_planning_guidance_count": self.tool_planning_guidance_count,
            "tool_planning_guidance_blocked": self.tool_planning_guidance_blocked,
            "tool_planning_guidance_warnings": self.tool_planning_guidance_warnings,
            "tool_planning_guidance_last_strategy": self.tool_planning_guidance_last_strategy,
            "memory_retrieval_count": self.memory_retrieval_count,
            "memory_hit_count": self.memory_hit_count,
            "memory_candidate_count": self.memory_candidate_count,
            "memory_filtered_count": self.memory_filtered_count,
            "memory_prompt_injected_count": self.memory_prompt_injected_count,
            "memory_top_score": self.memory_top_score,
            "memory_extraction_count": self.memory_extraction_count,
            "memory_stored_count": self.memory_stored_count,
            "memory_duplicate_count": self.memory_duplicate_count,
            "budget_max_turns": self.budget_max_turns,
            "budget_max_tool_calls": self.budget_max_tool_calls,
            "budget_max_run_seconds": self.budget_max_run_seconds,
            "budget_turns": self.budget_turns,
            "budget_tool_calls": self.budget_tool_calls,
            "budget_input_tokens": self.budget_input_tokens,
            "budget_output_tokens": self.budget_output_tokens,
            "budget_total_tokens": self.budget_total_tokens,
            "budget_elapsed_seconds": self.budget_elapsed_seconds,
            "budget_exhausted": self.budget_exhausted,
            "budget_exhausted_reason": self.budget_exhausted_reason,
        }


def analyze_state(state: AgentState) -> TrajectoryMetrics:
    test_runs = 0
    for step in state.trajectory:
        if step.action.tool_name != "bash":
            continue
        command = str(step.action.tool_input.get("command", "")).lower()
        if any(token in command for token in ("pytest", "unittest", "npm test", "mvn test", "go test")):
            test_runs += 1

    verification_status = None
    structured = {}
    sandbox = {}
    if state.verification_report:
        verification_status = str(state.verification_report.get("status", ""))
        structured = _extract_structured_test_result(state.verification_report)
        sandbox = _extract_sandbox_result(state.verification_report)
        artifacts = _extract_verification_artifacts(state.verification_report)
        task_constraints = _extract_task_constraints(state.verification_report)
    else:
        artifacts = {}
        task_constraints = {}
    rollback = _extract_rollback_report(state)
    patch_policy = _extract_patch_policy_report(state)
    plan = _extract_plan_report(state)
    plan_repair = _extract_plan_repair_reports(state)
    context_ranking = _extract_context_ranking_reports(state)
    reflection = _extract_reflection_report(state)
    reflection_retry = _extract_reflection_retry_reports(state)
    tool_guidance = _extract_tool_planning_guidance(state)
    memory_retrieval = _extract_memory_retrieval_reports(state)
    memory_extraction = _extract_memory_extraction_reports(state)
    budget = _extract_run_budget_report(state)

    return TrajectoryMetrics(
        task_id=state.task_id,
        status=state.status.value,
        turns=state.turn_index,
        tool_calls=state.tool_call_count(),
        failed_tool_calls=state.error_count(),
        success=state.status == TaskStatus.SUCCEEDED,
        test_runs=test_runs,
        edit_count=state.tool_call_count("edit_file") + state.tool_call_count("write_file"),
        read_count=(
            state.tool_call_count("read_file")
            + state.tool_call_count("grep")
            + state.tool_call_count("glob")
            + state.tool_call_count("ast_context")
        ),
        plan_step_count=int(plan.get("step_count", 0) or 0),
        plan_completed_steps=int(plan.get("completed_steps", 0) or 0),
        plan_blocked_steps=int(plan.get("blocked_steps", 0) or 0),
        plan_progress=float(plan.get("progress", 0.0) or 0.0),
        plan_complete=bool(plan.get("complete", False)),
        plan_repair_count=int(plan_repair.get("count", 0) or 0),
        plan_repair_last_strategy=_optional_str(plan_repair.get("last_strategy")),
        plan_repair_focused_test_command=_optional_str(
            plan_repair.get("focused_test_command")
        ),
        ast_context_queries=state.tool_call_count("ast_context"),
        verification_status=verification_status,
        verified_success=verification_status == "passed",
        structured_tests_total=structured.get("total"),
        structured_tests_passed=structured.get("passed"),
        structured_tests_failed=int(structured.get("failed", 0) or 0),
        structured_test_errors=int(structured.get("errors", 0) or 0),
        structured_tests_skipped=int(structured.get("skipped", 0) or 0),
        task_constraint_status=task_constraints.get("status"),
        task_constraint_failed=task_constraints.get("status") == "failed",
        task_constraint_violation_count=int(task_constraints.get("violation_count", 0) or 0),
        task_success_criteria_count=int(task_constraints.get("success_criteria_count", 0) or 0),
        patch_policy_status=patch_policy.get("status"),
        patch_policy_failed=patch_policy.get("status") == "failed",
        patch_policy_violation_count=int(patch_policy.get("violation_count", 0) or 0),
        patch_policy_changed_files=int(patch_policy.get("changed_files", 0) or 0),
        patch_policy_changed_lines=int(patch_policy.get("changed_lines", 0) or 0),
        context_ranking_count=int(context_ranking.get("count", 0) or 0),
        context_candidate_count=int(context_ranking.get("candidate_count", 0) or 0),
        context_top_score=context_ranking.get("top_score"),
        context_sources=context_ranking.get("sources", []),
        rollback_status=rollback.get("status"),
        rollback_attempted=int(rollback.get("attempted", 0) or 0),
        rollback_restored=int(rollback.get("restored", 0) or 0),
        rollback_failed=int(rollback.get("failed", 0) or 0),
        verification_sandbox_type=sandbox.get("sandbox_type"),
        verification_sandbox_status=sandbox.get("status"),
        verification_sandbox_timed_out=bool(sandbox.get("timed_out", False)),
        verification_sandbox_violation=str(sandbox.get("violation", "") or ""),
        verification_artifact_count=int(artifacts.get("count", 0) or 0),
        verification_artifact_dir=artifacts.get("artifact_dir"),
        verification_workspace_sha256=artifacts.get("workspace_sha256"),
        verification_workspace_file_count=int(artifacts.get("workspace_file_count", 0) or 0),
        reflection_status=reflection.get("status"),
        reflection_retryable=reflection.get("retryable"),
        reflection_signal_count=int(reflection.get("signal_count", 0) or 0),
        reflection_categories=reflection.get("categories", []),
        reflection_retry_count=int(reflection_retry.get("retry_count", 0) or 0),
        reflection_retry_last_status=reflection_retry.get("last_status"),
        reflection_retry_exhausted=bool(reflection_retry.get("exhausted", False)),
        reflection_retry_strategy=reflection_retry.get("strategy"),
        reflection_retry_actions=reflection_retry.get("actions", []),
        tool_planning_guidance_count=int(tool_guidance.get("count", 0) or 0),
        tool_planning_guidance_blocked=int(tool_guidance.get("blocked", 0) or 0),
        tool_planning_guidance_warnings=int(tool_guidance.get("warnings", 0) or 0),
        tool_planning_guidance_last_strategy=tool_guidance.get("last_strategy"),
        memory_retrieval_count=int(memory_retrieval.get("count", 0) or 0),
        memory_hit_count=int(memory_retrieval.get("hit_count", 0) or 0),
        memory_candidate_count=int(memory_retrieval.get("candidate_count", 0) or 0),
        memory_filtered_count=int(memory_retrieval.get("filtered_count", 0) or 0),
        memory_prompt_injected_count=int(
            memory_retrieval.get("prompt_injected_count", 0) or 0
        ),
        memory_top_score=memory_retrieval.get("top_score"),
        memory_extraction_count=int(memory_extraction.get("count", 0) or 0),
        memory_stored_count=int(memory_extraction.get("stored", 0) or 0),
        memory_duplicate_count=int(memory_extraction.get("duplicate", 0) or 0),
        budget_max_turns=_optional_int(budget.get("max_turns")),
        budget_max_tool_calls=_optional_int(budget.get("max_tool_calls")),
        budget_max_run_seconds=_optional_float(budget.get("max_run_seconds")),
        budget_turns=int(budget.get("turns", 0) or 0),
        budget_tool_calls=int(budget.get("tool_calls", 0) or 0),
        budget_input_tokens=int(budget.get("input_tokens", 0) or 0),
        budget_output_tokens=int(budget.get("output_tokens", 0) or 0),
        budget_total_tokens=int(budget.get("total_tokens", 0) or 0),
        budget_elapsed_seconds=float(budget.get("elapsed_seconds", 0.0) or 0.0),
        budget_exhausted=bool(budget.get("exhausted", False)),
        budget_exhausted_reason=_optional_str(budget.get("exhausted_reason")),
    )


def _extract_structured_test_result(report: dict[str, object]) -> dict[str, object]:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return {}

    for check in checks:
        if not isinstance(check, dict):
            continue
        metadata = check.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        test_result = metadata.get("test_result", {})
        if isinstance(test_result, dict) and test_result.get("recognized"):
            return test_result
    return {}


def _extract_task_constraints(report: dict[str, object]) -> dict[str, object]:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return {}

    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("name") != "task_constraints":
            continue
        metadata = check.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        success_criteria = metadata.get("success_criteria", [])
        return {
            "status": check.get("status"),
            "violation_count": metadata.get("violation_count", 0),
            "success_criteria_count": (
                len(success_criteria)
                if isinstance(success_criteria, list)
                else 0
            ),
        }
    return {}


def _extract_rollback_report(state: AgentState) -> dict[str, object]:
    report = getattr(state, "rollback_report", None)
    if isinstance(report, dict):
        return report
    return {}


def _extract_patch_policy_report(state: AgentState) -> dict[str, object]:
    report = getattr(state, "patch_policy_report", None)
    if not isinstance(report, dict):
        return {}

    violations = report.get("violations", [])
    violation_count = len(violations) if isinstance(violations, list) else 0
    return {
        "status": report.get("status"),
        "violation_count": violation_count,
        "changed_files": report.get("changed_files"),
        "changed_lines": report.get("total_changed_lines"),
    }


def _extract_plan_report(state: AgentState) -> dict[str, object]:
    plan = getattr(state, "plan", None)
    if plan is None:
        return {}
    steps = getattr(plan, "steps", [])
    if not isinstance(steps, list):
        return {}
    statuses = [
        getattr(getattr(step, "status", None), "value", "")
        for step in steps
    ]
    step_count = len(statuses)
    completed = statuses.count("done")
    blocked = statuses.count("blocked")
    return {
        "step_count": step_count,
        "completed_steps": completed,
        "blocked_steps": blocked,
        "progress": plan.progress() if hasattr(plan, "progress") else 0.0,
        "complete": step_count > 0 and completed == step_count,
    }


def _extract_plan_repair_reports(state: AgentState) -> dict[str, object]:
    reports = getattr(state, "plan_repair_reports", [])
    if not isinstance(reports, list) or not reports:
        return {}

    last_strategy = None
    focused_test_command = None
    for report in reports:
        if not isinstance(report, dict):
            continue
        strategy = report.get("strategy")
        if strategy is not None:
            last_strategy = str(strategy)
        command = report.get("focused_test_command")
        if command:
            focused_test_command = str(command)

    return {
        "count": len(reports),
        "last_strategy": last_strategy,
        "focused_test_command": focused_test_command,
    }


def _extract_context_ranking_reports(state: AgentState) -> dict[str, object]:
    reports = getattr(state, "context_ranking_reports", [])
    if not isinstance(reports, list) or not reports:
        return {}

    candidate_count = 0
    top_score = None
    sources: set[str] = set()
    for report in reports:
        if not isinstance(report, dict):
            continue
        candidates = report.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        candidate_count += len(candidates)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            score = candidate.get("score")
            if isinstance(score, int) and (top_score is None or score > top_score):
                top_score = score
            for source in candidate.get("sources", []) or []:
                sources.add(str(source))

    return {
        "count": len(reports),
        "candidate_count": candidate_count,
        "top_score": top_score,
        "sources": sorted(sources),
    }


def _extract_sandbox_result(report: dict[str, object]) -> dict[str, object]:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return {}

    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("name") != "verification_command":
            continue
        metadata = check.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        sandbox = metadata.get("sandbox", {})
        if isinstance(sandbox, dict):
            return sandbox
    return {}


def _extract_verification_artifacts(report: dict[str, object]) -> dict[str, object]:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return {}

    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("name") != "verification_command":
            continue
        metadata = check.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        artifact = metadata.get("artifacts", {})
        if not isinstance(artifact, dict) or not artifact:
            return {}
        snapshot = artifact.get("workspace_snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}
        return {
            "count": 1,
            "artifact_dir": artifact.get("artifact_dir"),
            "workspace_sha256": snapshot.get("sha256"),
            "workspace_file_count": snapshot.get("fingerprinted_files", 0),
        }
    return {}


def _extract_reflection_report(state: AgentState) -> dict[str, object]:
    report = getattr(state, "reflection_report", None)
    if not isinstance(report, dict):
        return {}

    signals = report.get("signals", [])
    categories: list[str] = []
    if isinstance(signals, list):
        for signal in signals:
            if isinstance(signal, dict):
                category = signal.get("category")
                if category is not None:
                    categories.append(str(category))

    return {
        "status": report.get("status"),
        "retryable": report.get("retryable"),
        "signal_count": len(categories),
        "categories": categories,
    }


def _extract_reflection_retry_reports(state: AgentState) -> dict[str, object]:
    reports = getattr(state, "reflection_retry_reports", [])
    if not isinstance(reports, list) or not reports:
        return {}

    statuses: list[str] = []
    retry_count = 0
    last_strategy = None
    last_actions: list[str] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        status = str(report.get("status", "") or "")
        if not status:
            continue
        statuses.append(status)
        if status == "retry":
            retry_count += 1
        strategy = report.get("strategy")
        if isinstance(strategy, dict):
            value = strategy.get("strategy")
            if value is not None:
                last_strategy = str(value)
            actions = strategy.get("actions", [])
            if isinstance(actions, list):
                last_actions = [str(action) for action in actions]

    return {
        "retry_count": retry_count,
        "last_status": statuses[-1] if statuses else None,
        "exhausted": "exhausted" in statuses,
        "strategy": last_strategy,
        "actions": last_actions,
    }


def _extract_tool_planning_guidance(state: AgentState) -> dict[str, object]:
    reports = getattr(state, "tool_planning_guidance_reports", [])
    report_count = len(reports) if isinstance(reports, list) else 0
    last_strategy = None
    if isinstance(reports, list) and reports:
        last_report = reports[-1]
        if isinstance(last_report, dict):
            strategy = last_report.get("strategy")
            if strategy is not None:
                last_strategy = str(strategy)

    blocked = 0
    warnings = 0
    for step in state.trajectory:
        guidance = step.observation.metadata.get("tool_planning_guidance")
        if not isinstance(guidance, dict):
            continue
        status = str(guidance.get("status", "") or "")
        if status == "blocked":
            blocked += 1
        elif status == "warning":
            warnings += 1

    return {
        "count": report_count,
        "blocked": blocked,
        "warnings": warnings,
        "last_strategy": last_strategy,
    }


def _extract_memory_retrieval_reports(state: AgentState) -> dict[str, object]:
    reports = getattr(state, "memory_retrieval_reports", [])
    if not isinstance(reports, list) or not reports:
        return {}

    hit_count = 0
    candidate_count = 0
    filtered_count = 0
    prompt_injected_count = 0
    top_score = None
    for report in reports:
        if not isinstance(report, dict):
            continue
        if report.get("prompt_injected"):
            prompt_injected_count += 1
        hits = report.get("hits", [])
        if not isinstance(hits, list):
            continue
        candidate_value = report.get("candidate_count")
        candidate_count += (
            int(candidate_value)
            if candidate_value is not None
            else len(hits)
        )
        filtered_count += int(report.get("filtered_hit_count", 0) or 0)
        hit_count += len(hits)
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            score = hit.get("score")
            if isinstance(score, int) and (top_score is None or score > top_score):
                top_score = score

    return {
        "count": len(reports),
        "hit_count": hit_count,
        "candidate_count": candidate_count,
        "filtered_count": filtered_count,
        "prompt_injected_count": prompt_injected_count,
        "top_score": top_score,
    }


def _extract_memory_extraction_reports(state: AgentState) -> dict[str, object]:
    reports = getattr(state, "memory_extraction_reports", [])
    if not isinstance(reports, list) or not reports:
        return {}

    stored = 0
    duplicate = 0
    for report in reports:
        if not isinstance(report, dict):
            continue
        status = str(report.get("status", "") or "")
        if status == "stored":
            stored += 1
        elif status == "duplicate":
            duplicate += 1

    return {
        "count": len(reports),
        "stored": stored,
        "duplicate": duplicate,
    }


def _extract_run_budget_report(state: AgentState) -> dict[str, object]:
    report = getattr(state, "run_budget_report", None)
    return report if isinstance(report, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
