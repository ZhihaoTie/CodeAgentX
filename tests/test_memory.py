"""Tests for verified long-term memory."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from codeagentx.agent import AgentAction, AgentLoop, AgentObservation, AgentState
from codeagentx.config import Config, PermissionMode
from codeagentx.evaluation import analyze_state
from codeagentx.memory import (
    MemoryExtractor,
    MemoryRecord,
    MemoryRetriever,
    MemoryStore,
    format_memory_prompt,
)
from codeagentx.models import MockProvider, ModelResponse


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class MemoryStoreTests(unittest.TestCase):
    def test_append_if_new_deduplicates_by_memory_id(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = MemoryStore(Path(tempdir) / "memory.jsonl")
            record = _record("mem-1", source_goal="fix slugify punctuation")

            first_added, first_path = store.append_if_new(record)
            second_added, second_path = store.append_if_new(record)
            records = store.list_records()

        self.assertTrue(first_added)
        self.assertFalse(second_added)
        self.assertIsNotNone(first_path)
        self.assertIsNotNone(second_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].memory_id, "mem-1")

    def test_list_records_skips_corrupt_jsonl_lines(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "memory.jsonl"
            path.write_text(
                "{not json}\n" + json.dumps(_record("mem-1", source_goal="fix slugify").to_dict()),
                encoding="utf-8",
            )

            records = MemoryStore(path).list_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].memory_id, "mem-1")


class MemoryExtractorTests(unittest.TestCase):
    def test_extracts_only_verified_successful_trajectory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            absolute_path = str(Path(tempdir) / "src" / "text_utils.py")
            state = AgentState(goal="Fix slugify punctuation handling")
            state.add_step(
                AgentAction(
                    tool_name="edit_file",
                    tool_input={"path": absolute_path},
                ),
                AgentObservation(
                    tool_name="edit_file",
                    output="patched",
                    metadata={"patch": {"path": absolute_path}},
                ),
            )
            state.set_verification_report({
                "status": "passed",
                "summary": "All configured verification checks passed.",
                "checks": [{
                    "name": "verification_command",
                    "metadata": {
                        "command": "python -B -m unittest discover -s tests -v",
                        "test_result": {"recognized": True, "failure_names": []},
                    },
                }],
            })
            state.finish()

            record = MemoryExtractor().extract(
                state,
                evidence_path="events.jsonl",
                workspace_root=tempdir,
            )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.language, "python")
        self.assertEqual(record.changed_files, ["src/text_utils.py"])
        self.assertEqual(record.tests, ["python -B -m unittest discover -s tests -v"])
        self.assertEqual(record.evidence_path, "events.jsonl")
        self.assertTrue(any(item.startswith("task goal:") for item in record.symptoms))
        self.assertIn("targeted implementation change", record.root_cause)
        self.assertTrue(record.verified)

    def test_extracts_relative_patch_paths_without_workspace_root(self):
        state = AgentState(goal="Fix slugify punctuation handling")
        state.add_step(
            AgentAction(
                tool_name="edit_file",
                tool_input={"path": "src/text_utils.py"},
            ),
            AgentObservation(
                tool_name="edit_file",
                output="patched",
                metadata={"patch": {"path": "src/text_utils.py"}},
            ),
        )
        state.set_verification_report({
            "status": "passed",
            "summary": "All configured verification checks passed.",
            "checks": [{
                "name": "verification_command",
                "metadata": {
                    "command": "python -B -m unittest discover -s tests -v",
                    "test_result": {"recognized": True, "failure_names": []},
                },
            }],
        })
        state.finish()

        record = MemoryExtractor().extract(state, evidence_path="events.jsonl")

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.language, "python")
        self.assertEqual(record.changed_files, ["src/text_utils.py"])
        self.assertEqual(record.tests, ["python -B -m unittest discover -s tests -v"])
        self.assertEqual(record.evidence_path, "events.jsonl")
        self.assertTrue(record.verified)

    def test_skips_failed_or_unverified_state(self):
        failed = AgentState(goal="fix")
        failed.fail("verification failed")
        unverified = AgentState(goal="fix")
        unverified.finish()
        unverified.set_verification_report({"status": "skipped"})

        extractor = MemoryExtractor()

        self.assertIsNone(extractor.extract(failed))
        self.assertIsNone(extractor.extract(unverified))


class MemoryRetrieverTests(unittest.TestCase):
    def test_ranks_verified_memory_by_goal_and_patch_terms(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = MemoryStore(Path(tempdir) / "memory.jsonl")
            store.append(_record(
                "slug",
                source_goal="fix slugify punctuation normalization",
                changed_files=["src/text_utils.py"],
                symptoms=["punctuation leaves duplicate hyphens"],
                strategy="collapse symbol runs and trim hyphens",
            ))
            store.append(_record(
                "cart",
                source_goal="fix cart discount total",
                changed_files=["shop/cart.py"],
                symptoms=["quantity ignored"],
                strategy="multiply unit price by quantity",
            ))

            report = MemoryRetriever(store, default_limit=1).retrieve(
                goal="Implement slugify so punctuation becomes one hyphen",
                patches=[{"path": "src/text_utils.py"}],
            )

        self.assertEqual(report.status, "generated")
        self.assertEqual(len(report.hits), 1)
        self.assertEqual(report.hits[0].record.memory_id, "slug")
        self.assertIn("slugify", report.query_terms)
        self.assertIn("Relevant verified memories", format_memory_prompt(report.to_dict()))

    def test_filters_low_scoring_memory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = MemoryStore(Path(tempdir) / "memory.jsonl")
            store.append(_record(
                "cart",
                source_goal="fix cart discount total",
                changed_files=["shop/cart.py"],
                symptoms=["quantity ignored"],
                strategy="multiply unit price by quantity",
            ))

            report = MemoryRetriever(store, default_min_score=999).retrieve(
                goal="Fix cart total",
            )

        self.assertEqual(report.status, "filtered")
        self.assertEqual(report.candidate_count, 1)
        self.assertEqual(report.filtered_hit_count, 1)
        self.assertEqual(report.min_score, 999)
        self.assertEqual(report.hits, [])
        self.assertEqual(format_memory_prompt(report.to_dict()), "")


class AgentLoopMemoryTests(unittest.TestCase):
    def test_injects_retrieved_memory_and_extracts_success_memory(self):
        provider = MockProvider([
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            memory_path = Path(tempdir) / "memories.jsonl"
            MemoryStore(memory_path).append(_record(
                "prior-slug",
                source_goal="fix slugify punctuation normalization",
                changed_files=["src/text_utils.py"],
                symptoms=["punctuation normalization"],
                strategy="collapse punctuation into a single hyphen",
            ))
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                trajectory_dir=str(Path(tempdir) / "trajectories"),
                verification_command=python_command("print('ok')"),
                enable_long_term_memory=True,
                memory_store_path=str(memory_path),
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("Fix slugify punctuation handling")

            state = agent.last_state
            assert state is not None
            messages = provider.requests[0]["messages"]
            events = agent.trajectory_store.read_events(state.task_id)
            records = MemoryStore(memory_path).list_records()
            metrics = analyze_state(state)

        event_types = [event["event_type"] for event in events]
        self.assertIn("Long-term memory context", str(messages))
        self.assertIn("prior-slug", str(messages))
        self.assertIn("memory_retrieved", event_types)
        self.assertIn("memory_extracted", event_types)
        self.assertEqual(metrics.memory_retrieval_count, 1)
        self.assertEqual(metrics.memory_hit_count, 1)
        self.assertEqual(metrics.memory_prompt_injected_count, 1)
        self.assertEqual(metrics.memory_extraction_count, 1)
        self.assertEqual(metrics.memory_stored_count, 1)
        self.assertEqual(len(records), 2)

    def test_skips_low_scoring_memory_prompt_injection(self):
        provider = MockProvider([
            ModelResponse.text("Done.", model="mock-model"),
        ])

        with tempfile.TemporaryDirectory() as tempdir:
            memory_path = Path(tempdir) / "memories.jsonl"
            MemoryStore(memory_path).append(_record(
                "prior-slug",
                source_goal="fix slugify punctuation normalization",
                changed_files=["src/text_utils.py"],
                symptoms=["punctuation normalization"],
                strategy="collapse punctuation into a single hyphen",
            ))
            config = Config(
                model_provider="mock",
                model="mock-model",
                permission_mode=PermissionMode.AUTO,
                workspace_root=tempdir,
                trajectory_dir=str(Path(tempdir) / "trajectories"),
                verification_command=python_command("print('ok')"),
                enable_long_term_memory=True,
                memory_store_path=str(memory_path),
                memory_min_score=999,
            )
            agent = AgentLoop(config=config, provider=provider)

            with redirect_stdout(StringIO()):
                agent.run("Fix slugify punctuation handling")

            state = agent.last_state
            assert state is not None
            messages = provider.requests[0]["messages"]
            events = agent.trajectory_store.read_events(state.task_id)
            metrics = analyze_state(state)

        retrieval_events = [
            event for event in events if event["event_type"] == "memory_retrieved"
        ]
        self.assertNotIn("Long-term memory context", str(messages))
        self.assertEqual(len(retrieval_events), 1)
        self.assertEqual(retrieval_events[0]["payload"]["status"], "filtered")
        self.assertFalse(retrieval_events[0]["payload"]["prompt_injected"])
        self.assertEqual(metrics.memory_retrieval_count, 1)
        self.assertEqual(metrics.memory_candidate_count, 1)
        self.assertEqual(metrics.memory_filtered_count, 1)
        self.assertEqual(metrics.memory_hit_count, 0)
        self.assertEqual(metrics.memory_prompt_injected_count, 0)


def _record(
    memory_id: str,
    *,
    source_goal: str,
    changed_files: list[str] | None = None,
    symptoms: list[str] | None = None,
    strategy: str = "apply targeted fix",
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        task_id="task-" + memory_id,
        task_type="test_driven_repair",
        language="python",
        source_goal=source_goal,
        symptoms=list(symptoms or []),
        root_cause="tests exposed a localized implementation bug",
        strategy=strategy,
        changed_files=list(changed_files or []),
        tests=["python -B -m unittest discover -s tests -v"],
        evidence_path=f"trajectories/{memory_id}.jsonl",
        applicability="Use only when task and failing tests are similar.",
        verified=True,
    )


if __name__ == "__main__":
    unittest.main()
