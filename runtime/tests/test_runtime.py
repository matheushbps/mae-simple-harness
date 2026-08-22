from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mae_runtime.analytics import (
    execute_readonly_sql,
    profile_dataset,
    reconcile_evidence,
    run_python_analysis,
    run_sql_analysis,
)
from mae_runtime.contracts import LLMTrace
from mae_runtime.dataset import build_fixture_database, estimate_dataset
from mae_runtime.harness import SimpleHarness


class StubModel:
    model_id = "qwen/qwen3.6-35b-a3b"

    def health(self) -> dict[str, Any]:
        return {"connected": True, "available": True, "model": self.model_id}

    def complete_json(
        self, role: str, system: str, user: str, max_tokens: int | None = None
    ) -> tuple[dict[str, Any], LLMTrace]:
        del system, user, max_tokens
        payload = (
            {"goals": ["compare"], "metrics": ["production"], "steps": ["analyze"]}
            if role == "planner"
            else {"priorities": ["production"], "cautions": ["fixture data"]}
        )
        return payload, LLMTrace(role=role, content="{}", completion_tokens=10)

    def complete(self, role: str, system: str, user: str, max_tokens: int | None = None) -> LLMTrace:
        del system, user, max_tokens
        return LLMTrace(role=role, content="Evidence-backed fixture analysis.", completion_tokens=12)


@pytest.fixture
def dataset_path(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.duckdb"
    build_fixture_database(path)
    return path


def test_dataset_estimate_is_bounded() -> None:
    estimate = estimate_dataset()
    assert estimate["maximum_wide_rows"] == 233_940
    assert estimate["estimated_duckdb_mb"][1] <= 25


def test_fixture_profile_and_independent_agreement(dataset_path: Path) -> None:
    profile = profile_dataset(dataset_path)
    assert profile["rows"] == 12
    assert profile["duplicate_keys"] == 0
    assert profile["manifest_present"]
    assert len(profile["dataset_sha256"]) == 64
    sql_evidence = run_sql_analysis(dataset_path)
    python_evidence = run_python_analysis(dataset_path)
    checks, approved = reconcile_evidence(sql_evidence, python_evidence, tolerance=1e-9)
    assert checks
    assert all(check.passed for check in checks)
    assert len(approved) == 8
    assert all(len(item.provenance["dataset_sha256"]) == 64 for item in approved)


def test_readonly_sql_rejects_mutation(dataset_path: Path) -> None:
    result = execute_readonly_sql(dataset_path, "SELECT crop_code FROM crop_metrics")
    assert result["rows"]
    with pytest.raises(ValueError, match="Only SELECT"):
        execute_readonly_sql(dataset_path, "DROP TABLE crop_metrics")


def test_simple_harness_runs_linear_flow(dataset_path: Path, tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    harness = SimpleHarness(StubModel(), dataset_path, tmp_path / "outputs")
    result = harness.run(
        "simple-test",
        "Analyze agricultural changes in the controlled fixture dataset.",
        lambda node, event_type, _message, _data=None: events.append((node, event_type)),
    )
    assert result["harness"] == "simple"
    assert result["narrative"] == "Evidence-backed fixture analysis."
    assert result["model_usage"]["calls"] == 3
    assert ("planner", "started") in events
    assert ("final_editor", "completed") in events
