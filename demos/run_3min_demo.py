"""Run the deterministic 3-minute CodeAgent-X runtime demo.

The demo intentionally applies an incomplete first patch, lets the verifier
fail, then relies on the runtime reflection/retry path to apply the final fix.
It uses MockProvider, so it is stable and does not require network or API keys.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from codeagentx.agent import AgentLoop, AgentState
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation.metrics import analyze_state
from codeagentx.models import MockProvider, ModelResponse


FIXTURE_ROOT = PROJECT_ROOT / "demos" / "three_minute_loop" / "fixture"
OUTPUT_ROOT = PROJECT_ROOT / ".codeagentx" / "demo-3min"

DEMO_GOAL = (
    "Fix calculator.py so add returns the mathematical sum and multiply returns "
    "the mathematical product. Do not edit tests."
)


def main() -> int:
    run_dir = _new_run_dir()
    workspace = run_dir / "workspace"
    shutil.copytree(FIXTURE_ROOT, workspace)

    config = Config(
        model_provider="mock",
        model="mock-demo-3min",
        max_turns=10,
        max_tokens=4096,
        workspace_root=str(workspace),
        permission_mode=PermissionMode.AUTO,
        verification_command=_verification_command(),
        verification_timeout_seconds=30,
        verification_sandbox="local",
        enable_sandbox_artifacts=True,
        sandbox_artifact_dir=str(run_dir / "artifacts"),
        sandbox_artifact_task_id="three-minute-demo",
        enable_runtime_planning=True,
        enable_context_ranking=True,
        context_ranking_limit=4,
        enable_task_constraints=True,
        task_success_criteria=[
            "add returns a sum",
            "multiply returns a product",
            "tests remain unchanged",
        ],
        task_required_changed_paths=["calculator.py"],
        task_forbidden_changed_paths=["tests/*"],
        auto_rollback_on_verification_failure=False,
        enable_patch_policy=True,
        patch_policy_max_changed_files=2,
        patch_policy_max_total_changed_lines=80,
        enable_failure_reflection=True,
        max_reflection_retries=1,
        enable_retry_strategy_matrix=True,
        enable_tool_planning_guidance=True,
        enable_long_term_memory=False,
        trajectory_dir=str(run_dir / "trajectories"),
    )

    print("\nCodeAgent-X 3-minute deterministic demo")
    print("=" * 44)
    print(f"Workspace: {workspace}")
    print(f"Goal: {DEMO_GOAL}\n")

    agent = AgentLoop(config=config, provider=MockProvider(_scripted_responses()))
    final_text = agent.run(DEMO_GOAL)
    state = agent.last_state
    if state is None:
        raise RuntimeError("demo finished without an AgentState")

    state_path = Path(agent.trajectory_store.state_path(state.task_id))
    events_path = Path(agent.trajectory_store.events_path(state.task_id))
    events = _load_events(events_path)
    metrics = analyze_state(state).to_dict()
    report_path = _write_report(
        run_dir=run_dir,
        workspace=workspace,
        state=state,
        final_text=final_text,
        metrics=metrics,
        events=events,
        state_path=state_path,
        events_path=events_path,
    )

    _print_live_summary(
        state=state,
        metrics=metrics,
        events=events,
        final_text=final_text,
        report_path=report_path,
        state_path=state_path,
        events_path=events_path,
    )
    return 0 if state.status.value == "succeeded" else 1


def _scripted_responses() -> list[ModelResponse]:
    return [
        ModelResponse.tool_use(
            tool_use_id="demo-read-1",
            name="read_file",
            tool_input={"path": "calculator.py"},
            text="Plan: inspect the target implementation before editing.",
            model="mock-demo-3min",
        ),
        ModelResponse.tool_use(
            tool_use_id="demo-patch-1",
            name="edit_file",
            tool_input={
                "path": "calculator.py",
                "old_string": "def add(a, b):\n    return a - b\n",
                "new_string": "def add(a, b):\n    return a + b\n",
            },
            text="Patch: fix add first. This is intentionally incomplete.",
            model="mock-demo-3min",
        ),
        ModelResponse.text(
            "Initial patch applied. Run the configured verification.",
            model="mock-demo-3min",
        ),
        ModelResponse.tool_use(
            tool_use_id="demo-read-2",
            name="read_file",
            tool_input={"path": "calculator.py"},
            text=(
                "Retry: reflection shows a remaining test failure, so inspect "
                "the changed file again."
            ),
            model="mock-demo-3min",
        ),
        ModelResponse.tool_use(
            tool_use_id="demo-patch-2",
            name="edit_file",
            tool_input={
                "path": "calculator.py",
                "old_string": "def multiply(a, b):\n    return a + b\n",
                "new_string": "def multiply(a, b):\n    return a * b\n",
            },
            text="Patch: apply the focused retry fix for multiply.",
            model="mock-demo-3min",
        ),
        ModelResponse.text(
            "All requested fixes are complete.",
            model="mock-demo-3min",
        ),
    ]


def _new_run_dir() -> Path:
    run_id = datetime.now(timezone.utc).strftime("demo-%Y%m%dT%H%M%SZ")
    run_dir = OUTPUT_ROOT / run_id
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = OUTPUT_ROOT / f"{run_id}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _verification_command() -> str:
    executable = str(Path(sys.executable))
    return f'"{executable}" -B -m unittest discover -s tests -v'


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _write_report(
    *,
    run_dir: Path,
    workspace: Path,
    state: AgentState,
    final_text: str,
    metrics: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    state_path: Path,
    events_path: Path,
) -> Path:
    report_path = run_dir / "trajectory_report.md"
    report_path.write_text(
        _render_report(
            run_dir=run_dir,
            workspace=workspace,
            state=state,
            final_text=final_text,
            metrics=metrics,
            events=events,
            state_path=state_path,
            events_path=events_path,
        ),
        encoding="utf-8",
    )
    return report_path


def _render_report(
    *,
    run_dir: Path,
    workspace: Path,
    state: AgentState,
    final_text: str,
    metrics: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    state_path: Path,
    events_path: Path,
) -> str:
    verification_events = _events_of(events, "verification_completed")
    reflection_events = _events_of(events, "reflection_completed")
    retry_events = _events_of(events, "reflection_retry_scheduled")
    tool_events = _events_of(events, "tool_observation")
    plan_events = _events_of(events, "plan_created")

    lines = [
        "# CodeAgent-X 3-Minute Demo Trajectory Report",
        "",
        "## Demo Chain",
        "",
        "```text",
        "Task",
        "  -> Plan",
        "  -> Read File",
        "  -> Patch",
        "  -> Run Test",
        "  -> Failure",
        "  -> Reflection",
        "  -> Retry",
        "  -> Success",
        "  -> Trajectory Report",
        "```",
        "",
        "## Paths",
        "",
        f"- Run dir: `{run_dir}`",
        f"- Workspace: `{workspace}`",
        f"- State: `{state_path}`",
        f"- Events: `{events_path}`",
        "",
        "## Result",
        "",
        f"- Final status: `{state.status.value}`",
        f"- Final text: `{final_text}`",
        f"- Tool calls: `{metrics.get('tool_calls')}`",
        f"- Reads: `{metrics.get('read_count')}`",
        f"- Edits: `{metrics.get('edit_count')}`",
        f"- Verification status: `{metrics.get('verification_status')}`",
        f"- Structured tests: `{metrics.get('structured_tests_passed')}/{metrics.get('structured_tests_total')}` passed",
        f"- Reflection retries: `{metrics.get('reflection_retry_count')}`",
        f"- Retry strategy: `{metrics.get('reflection_retry_strategy')}`",
        f"- Patch policy: `{metrics.get('patch_policy_status')}`",
        f"- Task constraints: `{metrics.get('task_constraint_status')}`",
        "",
        "## Timeline",
        "",
        "| Step | Evidence |",
        "| --- | --- |",
        f"| Task | `{_short(DEMO_GOAL, 110)}` |",
        f"| Plan | `{_plan_summary(plan_events, state)}` |",
        f"| Read File | `{_tool_count(tool_events, 'read_file')} read_file call(s)` |",
        f"| Patch | `{_tool_count(tool_events, 'edit_file')} edit_file call(s)` |",
        f"| Run Test | `{len(verification_events)} verifier run(s)` |",
        f"| Failure | `{_verification_summary(verification_events, index=0)}` |",
        f"| Reflection | `{_reflection_summary(reflection_events)}` |",
        f"| Retry | `{_retry_summary(retry_events)}` |",
        f"| Success | `{_verification_summary(verification_events, index=-1)}` |",
        f"| Trajectory Report | `{report_path_name(run_dir)}` |",
        "",
        "## Tool Calls",
        "",
        "| Turn | Tool | Status | Input |",
        "| ---: | --- | --- | --- |",
        *_tool_rows(tool_events),
        "",
        "## Verification Events",
        "",
        "| Run | Status | Summary | Failed Tests |",
        "| ---: | --- | --- | --- |",
        *_verification_rows(verification_events),
        "",
        "## Reflection Evidence",
        "",
        *_reflection_lines(state),
        "",
        "## Final calculator.py",
        "",
        "```python",
        (workspace / "calculator.py").read_text(encoding="utf-8").rstrip(),
        "```",
        "",
        "## Demo Sound Bite",
        "",
        (
            "This run proves the runtime loop: the first patch is incomplete, "
            "the verifier catches it, reflection classifies the failure, retry "
            "planning creates a focused repair strategy, and the second patch "
            "passes all checks while leaving a full trajectory artifact."
        ),
        "",
    ]
    return "\n".join(lines)


def _print_live_summary(
    *,
    state: AgentState,
    metrics: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    final_text: str,
    report_path: Path,
    state_path: Path,
    events_path: Path,
) -> None:
    verification_events = _events_of(events, "verification_completed")
    reflection_events = _events_of(events, "reflection_completed")
    retry_events = _events_of(events, "reflection_retry_scheduled")

    print("\n3-minute demo chain")
    print("-" * 24)
    print(f"Task       : {DEMO_GOAL}")
    print(f"Plan       : {_plan_summary(_events_of(events, 'plan_created'), state)}")
    print(f"Read File  : {metrics.get('read_count')} read operation(s)")
    print(f"Patch      : {metrics.get('edit_count')} edit operation(s)")
    print(f"Run Test   : {len(verification_events)} verifier run(s)")
    print(f"Failure    : {_verification_summary(verification_events, index=0)}")
    print(f"Reflection : {_reflection_summary(reflection_events)}")
    print(f"Retry      : {_retry_summary(retry_events)}")
    print(f"Success    : final status={state.status.value}; final_text={final_text!r}")
    print(f"Report     : {report_path}")
    print(f"State      : {state_path}")
    print(f"Events     : {events_path}")


def _events_of(
    events: Iterable[Mapping[str, Any]],
    event_type: str,
) -> list[Mapping[str, Any]]:
    return [event for event in events if event.get("event_type") == event_type]


def _tool_count(events: Iterable[Mapping[str, Any]], tool_name: str) -> int:
    count = 0
    for event in events:
        payload = _mapping(event.get("payload"))
        action = _mapping(payload.get("action"))
        if action.get("tool_name") == tool_name:
            count += 1
    return count


def _tool_rows(events: Iterable[Mapping[str, Any]]) -> list[str]:
    rows: list[str] = []
    for index, event in enumerate(events, start=1):
        payload = _mapping(event.get("payload"))
        action = _mapping(payload.get("action"))
        observation = _mapping(payload.get("observation"))
        status = "ERROR" if observation.get("is_error") else "OK"
        rows.append(
            "| "
            + " | ".join([
                str(index),
                _cell(action.get("tool_name")),
                status,
                _cell(_compact_json(action.get("tool_input"))),
            ])
            + " |"
        )
    return rows or ["| 0 | none | n/a | n/a |"]


def _verification_rows(events: list[Mapping[str, Any]]) -> list[str]:
    rows: list[str] = []
    for index, event in enumerate(events, start=1):
        payload = _mapping(event.get("payload"))
        failed = _failed_test_names(payload)
        rows.append(
            "| "
            + " | ".join([
                str(index),
                _cell(payload.get("status")),
                _cell(payload.get("summary")),
                _cell(", ".join(failed) if failed else "-"),
            ])
            + " |"
        )
    return rows or ["| 0 | none | n/a | - |"]


def _reflection_lines(state: AgentState) -> list[str]:
    report = _mapping(state.reflection_report)
    if not report:
        return ["No reflection report was generated."]
    lines = [
        f"- Summary: `{report.get('summary')}`",
        f"- Retryable: `{report.get('retryable')}`",
        "- Signals:",
    ]
    for signal in report.get("signals", []):
        item = _mapping(signal)
        lines.append(
            f"  - `{item.get('category')}` / `{item.get('severity')}`: "
            f"{item.get('message')}"
        )
    if state.plan_repair_reports:
        latest = _mapping(state.plan_repair_reports[-1])
        lines.append(f"- Planner repair strategy: `{latest.get('strategy')}`")
        if latest.get("focused_test_command"):
            lines.append(
                f"- Focused test command: `{latest.get('focused_test_command')}`"
            )
    if state.tool_planning_guidance_reports:
        latest = _mapping(state.tool_planning_guidance_reports[-1])
        lines.append(f"- Tool guidance strategy: `{latest.get('strategy')}`")
    return lines


def _plan_summary(events: list[Mapping[str, Any]], state: AgentState) -> str:
    if state.plan is not None:
        payload = state.plan.to_dict()
        return (
            f"{payload.get('completed_steps')}/{len(payload.get('steps', []))} "
            f"steps completed"
        )
    if events:
        payload = _mapping(events[0].get("payload"))
        return _short(payload.get("summary") or "plan created", 80)
    return "plan unavailable"


def _verification_summary(
    events: list[Mapping[str, Any]],
    *,
    index: int,
) -> str:
    if not events:
        return "no verification event"
    payload = _mapping(events[index].get("payload"))
    status = str(payload.get("status", "unknown"))
    summary = str(payload.get("summary", ""))
    failed = _failed_test_names(payload)
    if failed:
        return f"{status}: {', '.join(failed)}"
    return f"{status}: {_short(summary, 100)}"


def _reflection_summary(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return "no reflection event"
    payload = _mapping(events[-1].get("payload"))
    return _short(
        f"{payload.get('summary')} retryable={payload.get('retryable')}",
        120,
    )


def _retry_summary(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return "no retry event"
    payload = _mapping(events[-1].get("payload"))
    strategy = _mapping(payload.get("strategy")).get("strategy")
    return (
        f"status={payload.get('status')}; retry_index={payload.get('retry_index')}; "
        f"strategy={strategy}"
    )


def _failed_test_names(payload: Mapping[str, Any]) -> list[str]:
    for check in payload.get("checks", []):
        check_map = _mapping(check)
        if check_map.get("name") != "verification_command":
            continue
        metadata = _mapping(check_map.get("metadata"))
        test_result = _mapping(metadata.get("test_result"))
        names = test_result.get("failure_names")
        if isinstance(names, list):
            return [str(name) for name in names]
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _compact_json(value: Any) -> str:
    return _short(json.dumps(value, ensure_ascii=False, sort_keys=True), 120)


def _short(value: Any, limit: int = 100) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _cell(value: Any) -> str:
    return _short(value, 140).replace("|", "\\|").replace("\n", "<br>")


def report_path_name(run_dir: Path) -> str:
    return str(run_dir / "trajectory_report.md")


if __name__ == "__main__":
    raise SystemExit(main())

