from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from codeagentx.evaluation import (
    SWEBENCH_PREFLIGHT_SCHEMA_VERSION,
    SWEbenchTaskSpec,
    build_swebench_preflight_report,
    write_swebench_preflight_report,
)


class SWEbenchPreflightTests(unittest.TestCase):
    def test_builds_passing_report_with_non_required_warnings(self):
        report = build_swebench_preflight_report(
            [_task()],
            provider="mock",
            model="mock-model",
            memory_policy="shared",
            evaluate_requested=False,
            executable_resolver=lambda name: f"/bin/{name}",
            import_checker=lambda name: False,
            command_runner=_ok_command,
            env={},
        )

        checks = {check.name: check for check in report.checks}

        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.warning_count, 1)
        self.assertEqual(checks["git_available"].status, "pass")
        self.assertEqual(checks["model_provider_config"].status, "pass")
        self.assertEqual(checks["swebench_harness_available"].status, "warn")
        self.assertEqual(checks["benchmark_memory_policy"].status, "warn")

    def test_official_evaluation_requires_disabled_memory_policy(self):
        report = build_swebench_preflight_report(
            [_task()],
            provider="mock",
            model="mock-model",
            memory_policy="shared",
            evaluate_requested=True,
            executable_resolver=lambda name: f"/bin/{name}",
            import_checker=lambda name: True,
            command_runner=_ok_command,
            env={},
        )

        checks = {check.name: check for check in report.checks}

        self.assertFalse(report.passed)
        self.assertEqual(checks["benchmark_memory_policy"].status, "fail")
        self.assertIn("disabled", checks["benchmark_memory_policy"].message)

    def test_official_evaluator_can_be_checked_through_command_prefix(self):
        commands: list[list[str]] = []

        def runner(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            commands.append(argv)
            return _ok_command(argv, timeout_seconds)

        report = build_swebench_preflight_report(
            [_task()],
            provider="mock",
            model="mock-model",
            memory_policy="disabled",
            evaluate_requested=True,
            python_executable="python",
            evaluator_command_prefix=["docker", "run", "--rm", "evaluator-image"],
            executable_resolver=lambda name: f"/bin/{name}",
            import_checker=lambda name: False,
            command_runner=runner,
            env={},
        )

        checks = {check.name: check for check in report.checks}

        self.assertTrue(report.passed)
        self.assertEqual(checks["docker_container_lifecycle"].status, "pass")
        self.assertEqual(
            checks["docker_container_lifecycle"].command[:5],
            ["docker", "run", "--rm", "evaluator-image", "python"],
        )
        self.assertEqual(
            checks["docker_container_lifecycle"].details["probe_image"],
            "python:3.12-slim",
        )
        self.assertEqual(checks["swebench_harness_available"].status, "pass")
        self.assertEqual(
            checks["swebench_harness_available"].command[:5],
            ["docker", "run", "--rm", "evaluator-image", "python"],
        )
        self.assertIn("swebench.harness.run_evaluation", " ".join(commands[-2]))
        self.assertEqual(
            checks["python_available"].command,
            ["docker", "run", "--rm", "evaluator-image", "python", "--version"],
        )

    def test_official_evaluator_fails_when_docker_lifecycle_fails(self):
        def runner(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            if "codeagentx_docker_lifecycle" in " ".join(argv):
                return subprocess.CompletedProcess(
                    argv,
                    125,
                    stdout="",
                    stderr="metadata.db: read-only file system",
                )
            return _ok_command(argv, timeout_seconds)

        report = build_swebench_preflight_report(
            [_task()],
            provider="mock",
            model="mock-model",
            memory_policy="disabled",
            evaluate_requested=True,
            python_executable="python",
            evaluator_command_prefix=["docker", "run", "--rm", "evaluator-image"],
            executable_resolver=lambda name: f"/bin/{name}",
            import_checker=lambda name: False,
            command_runner=runner,
            env={},
        )

        checks = {check.name: check for check in report.checks}

        self.assertFalse(report.passed)
        self.assertEqual(checks["docker_container_lifecycle"].status, "fail")
        self.assertIn("lifecycle", checks["docker_container_lifecycle"].message)
        self.assertIn("read-only file system", checks["docker_container_lifecycle"].stderr)

    def test_host_docker_lifecycle_uses_configured_probe_image(self):
        report = build_swebench_preflight_report(
            [_task()],
            provider="mock",
            model="mock-model",
            memory_policy="disabled",
            evaluate_requested=True,
            docker_lifecycle_image="python:3.11-slim",
            executable_resolver=lambda name: f"/bin/{name}",
            import_checker=lambda name: True,
            command_runner=_ok_command,
            env={},
        )

        check = {check.name: check for check in report.checks}["docker_container_lifecycle"]

        self.assertEqual(check.status, "pass")
        self.assertEqual(
            check.command[:4],
            ["/bin/docker", "run", "--rm", "python:3.11-slim"],
        )
        self.assertFalse(check.details["uses_python_docker_sdk"])

    def test_missing_provider_key_fails(self):
        report = build_swebench_preflight_report(
            [_task()],
            provider="deepseek",
            model="deepseek-v4-pro",
            memory_policy="disabled",
            executable_resolver=lambda name: f"/bin/{name}",
            import_checker=lambda name: True,
            command_runner=_ok_command,
            env={},
        )

        checks = {check.name: check for check in report.checks}

        self.assertFalse(report.passed)
        self.assertEqual(checks["model_provider_config"].status, "fail")
        self.assertEqual(checks["model_provider_config"].details["required_env"], "DEEPSEEK_API_KEY")

    def test_writes_preflight_report_json(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "preflight.json"

            report = write_swebench_preflight_report(
                [_task()],
                path,
                provider="mock",
                model="mock-model",
                memory_policy="disabled",
                executable_resolver=lambda name: f"/bin/{name}",
                import_checker=lambda name: True,
                command_runner=_ok_command,
                env={},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(report.report_path, str(path))
        self.assertEqual(payload["schema_version"], SWEBENCH_PREFLIGHT_SCHEMA_VERSION)
        self.assertEqual(payload["summary"]["failure_count"], 0)
        self.assertEqual(payload["task_manifest"]["task_ids"], ["owner__repo-1"])


def _task() -> SWEbenchTaskSpec:
    return SWEbenchTaskSpec(
        instance_id="owner__repo-1",
        repo="owner/repo",
        base_commit="abc123",
        problem_statement="Fix the parser.",
        fail_to_pass=["hidden::test_bug"],
        pass_to_pass=["hidden::test_existing"],
    )


def _ok_command(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        argv,
        0,
        stdout="version 1.0\n",
        stderr="",
    )


if __name__ == "__main__":
    unittest.main()
