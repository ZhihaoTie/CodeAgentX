"""Tests for sandbox command execution."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codeagentx.config import Config
from codeagentx.sandbox import (
    DockerSandboxRunner,
    LocalSandboxRunner,
    SandboxCommandStatus,
    SandboxSpec,
    create_sandbox_runner,
    snapshot_workspace,
    write_sandbox_artifacts,
)


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestLocalSandboxRunner(unittest.TestCase):
    def test_runs_command_inside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = LocalSandboxRunner().run(
                python_command("print('sandbox-ok')"),
                spec=SandboxSpec(workspace_root=workspace, cwd=workspace),
            )

        self.assertEqual(result.status, SandboxCommandStatus.PASSED)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("sandbox-ok", result.stdout)
        self.assertEqual(result.sandbox_type, "local")

    def test_rejects_cwd_outside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            result = LocalSandboxRunner().run(
                python_command("print('nope')"),
                spec=SandboxSpec(workspace_root=workspace, cwd=outside),
            )

        self.assertEqual(result.status, SandboxCommandStatus.VIOLATION)
        self.assertIsNone(result.exit_code)
        self.assertIn("outside workspace", result.violation)

    def test_times_out_command(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = LocalSandboxRunner().run(
                python_command("import time; time.sleep(2)"),
                spec=SandboxSpec(
                    workspace_root=workspace,
                    cwd=workspace,
                    timeout_seconds=1,
                ),
            )

        self.assertEqual(result.status, SandboxCommandStatus.TIMED_OUT)
        self.assertTrue(result.timed_out)

    def test_truncates_output(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = LocalSandboxRunner().run(
                python_command("print('x' * 40)"),
                spec=SandboxSpec(
                    workspace_root=workspace,
                    cwd=workspace,
                    max_output_chars=10,
                ),
            )

        self.assertEqual(result.status, SandboxCommandStatus.PASSED)
        self.assertIn("truncated", result.stdout)
        self.assertLess(len(result.stdout), 80)

    def test_create_runner_from_config(self):
        runner = create_sandbox_runner(Config(verification_sandbox="local"))

        self.assertIsInstance(runner, LocalSandboxRunner)

    def test_writes_sandbox_artifacts_and_workspace_snapshot(self):
        with tempfile.TemporaryDirectory() as workspace:
            Path(workspace, "app.py").write_text("print('hello')\n", encoding="utf-8")
            result = LocalSandboxRunner().run(
                python_command("print('artifact-ok')"),
                spec=SandboxSpec(workspace_root=workspace, cwd=workspace),
            )

            manifest = write_sandbox_artifacts(
                result,
                Path(workspace) / "artifacts",
                kind="verification",
                task_id="task-1",
            )

            self.assertEqual(manifest["kind"], "verification")
            self.assertEqual(manifest["task_id"], "task-1")
            self.assertTrue(Path(manifest["stdout_path"]).exists())
            self.assertTrue(Path(manifest["stderr_path"]).exists())
            self.assertTrue(Path(manifest["result_path"]).exists())
            self.assertIn("artifact-ok", Path(manifest["stdout_path"]).read_text(encoding="utf-8"))
            snapshot = manifest["workspace_snapshot"]
            self.assertEqual(snapshot["schema_version"], "codeagentx.workspace_snapshot.v1")
            self.assertEqual(snapshot["fingerprinted_files"], 1)
            self.assertEqual(snapshot["recorded_files"][0]["path"], "app.py")

    def test_workspace_snapshot_ignores_codeagentx_artifact_dir(self):
        with tempfile.TemporaryDirectory() as workspace:
            Path(workspace, "app.py").write_text("value = 1\n", encoding="utf-8")
            artifact_dir = Path(workspace) / ".codeagentx" / "sandbox_artifacts"
            artifact_dir.mkdir(parents=True)
            Path(artifact_dir, "stdout.txt").write_text("ignored\n", encoding="utf-8")

            snapshot = snapshot_workspace(workspace)

        paths = [item["path"] for item in snapshot.recorded_files]
        self.assertEqual(paths, ["app.py"])


class TestDockerSandboxRunner(unittest.TestCase):
    def test_builds_docker_run_command(self):
        with tempfile.TemporaryDirectory() as workspace:
            subdir = Path(workspace) / "pkg"
            subdir.mkdir()
            runner = DockerSandboxRunner(
                docker_binary="dockerx",
                image="python:3.12",
                network="none",
                memory="512m",
                cpus="1.5",
            )

            with patch("codeagentx.sandbox.runner.subprocess.run") as mocked_run:
                mocked_run.return_value = SimpleNamespace(
                    returncode=0,
                    stdout="docker-ok\n",
                    stderr="",
                )
                result = runner.run(
                    "python -V",
                    spec=SandboxSpec(
                        workspace_root=workspace,
                        cwd=str(subdir),
                        env={"FOO": "bar"},
                    ),
                )

            args = mocked_run.call_args.args[0]

        self.assertEqual(result.status, SandboxCommandStatus.PASSED)
        self.assertEqual(result.sandbox_type, "docker")
        self.assertIn("docker-ok", result.stdout)
        self.assertEqual(result.metadata["image"], "python:3.12")
        self.assertEqual(result.metadata["network"], "none")
        self.assertEqual(result.metadata["memory"], "512m")
        self.assertEqual(result.metadata["cpus"], "1.5")
        self.assertEqual(result.metadata["container_workdir"], "/workspace/pkg")
        self.assertEqual(args[0:2], ["dockerx", "run"])
        self.assertIn("--rm", args)
        self.assertIn("--network", args)
        self.assertIn("none", args)
        self.assertIn("--memory", args)
        self.assertIn("512m", args)
        self.assertIn("--cpus", args)
        self.assertIn("1.5", args)
        self.assertIn("-e", args)
        self.assertIn("FOO=bar", args)
        self.assertIn("PYTHONIOENCODING=utf-8", args)
        self.assertEqual(args[-4:], ["python:3.12", "/bin/sh", "-lc", "python -V"])

    def test_rejects_cwd_outside_workspace_without_running_docker(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            with patch("codeagentx.sandbox.runner.subprocess.run") as mocked_run:
                result = DockerSandboxRunner().run(
                    "python -V",
                    spec=SandboxSpec(workspace_root=workspace, cwd=outside),
                )

        mocked_run.assert_not_called()
        self.assertEqual(result.status, SandboxCommandStatus.VIOLATION)
        self.assertIn("outside workspace", result.violation)

    def test_docker_binary_error_is_structured(self):
        with tempfile.TemporaryDirectory() as workspace:
            with patch("codeagentx.sandbox.runner.subprocess.run") as mocked_run:
                mocked_run.side_effect = FileNotFoundError("docker")
                result = DockerSandboxRunner().run(
                    "python -V",
                    spec=SandboxSpec(workspace_root=workspace, cwd=workspace),
                )

        self.assertEqual(result.status, SandboxCommandStatus.ERROR)
        self.assertEqual(result.error_type, "FileNotFoundError")
        self.assertEqual(result.sandbox_type, "docker")

    def test_create_runner_from_config(self):
        runner = create_sandbox_runner(Config(
            verification_sandbox="docker",
            docker_sandbox_image="python:3.12",
            docker_sandbox_network="none",
            docker_sandbox_memory="1g",
            docker_sandbox_cpus="2",
        ))

        self.assertIsInstance(runner, DockerSandboxRunner)
        self.assertEqual(runner.image, "python:3.12")
        self.assertEqual(runner.memory, "1g")
        self.assertEqual(runner.cpus, "2")


if __name__ == "__main__":
    unittest.main()
