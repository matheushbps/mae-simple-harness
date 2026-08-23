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
        if role == "dashboard_engineer":
            payload = {
                "title": "Municipal Crop Intelligence",
                "subtitle": "Strategic Executive Highlights",
                "insights": ["Planted area increased in grains", "Yield efficiency improved"],
                "visual_theme": "cyber_dark",
            }
        else:
            payload = {
                "business_questions": ["What changed?"],
                "metrics": ["production"],
                "acceptance_criteria": ["All crops analyzed"],
            }
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
    assert ("business_analyst", "started") in events
    assert ("dashboard_engineer", "started") in events
    assert ("final_editor", "completed") in events

    run_dir = tmp_path / "outputs" / "simple-test"
    json_dashboard = run_dir / "dashboard.json"
    html_dashboard = run_dir / "dashboard.html"
    assert json_dashboard.exists() and json_dashboard.stat().st_size > 0
    assert html_dashboard.exists() and html_dashboard.stat().st_size > 0
    html_text = html_dashboard.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert "id=\"kpis\"" in html_text
    assert "id=\"charts\"" in html_text
    assert "id=\"evidence-ledger\"" in html_text


def test_simple_harness_supports_custom_agent_prompts(dataset_path: Path, tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    harness = SimpleHarness(StubModel(), dataset_path, tmp_path / "outputs")
    result = harness.run(
        "custom-agent-test",
        "Analyze agricultural changes in the controlled fixture dataset.",
        lambda node, event_type, _message, _data=None: events.append((node, event_type)),
        agent_prompts={"final_editor": "Custom modified final editor system prompt."},
    )
    assert result["harness"] == "simple"
    assert ("final_editor", "completed") in events
