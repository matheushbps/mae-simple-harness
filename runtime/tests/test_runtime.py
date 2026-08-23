from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mae_runtime.analytics import (
    execute_readonly_sql,
    profile_dataset,
    reconcile_evidence,
    render_dashboard_html,
    run_python_analysis,
    run_sql_analysis,
)
from mae_runtime.contracts import LLMTrace
from mae_runtime.dataset import build_fixture_database, estimate_dataset
from mae_runtime.harness import SimpleHarness


class StubModel:
    model_id = "qwen/qwen3.6-35b-a3b"

    def __init__(self) -> None:
        self.systems: dict[str, str] = {}
        self.users: dict[str, str] = {}

    def health(self) -> dict[str, Any]:
        return {"connected": True, "available": True, "model": self.model_id}

    def complete_json(
        self, role: str, system: str, user: str, max_tokens: int | None = None
    ) -> tuple[dict[str, Any], LLMTrace]:
        del max_tokens
        self.systems[role] = system
        self.users[role] = user
        if role in ("dashboard_agent", "dashboard_engineer"):
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
        del max_tokens
        self.systems[role] = system
        self.users[role] = user
        return LLMTrace(role=role, content="Evidence-backed fixture analysis.", completion_tokens=12)


class GeneratedCodeModel(StubModel):
    def complete_json(
        self, role: str, system: str, user: str, max_tokens: int | None = None
    ) -> tuple[dict[str, Any], LLMTrace]:
        if role == "sql_agent":
            self.systems[role] = system
            self.users[role] = user
            crop_filter = "WHERE crop_code = '40124'" if "only crop 40124" in user else ""
            return {
                "code": f"""
                    SELECT crop_code, crop_name, year,
                           sum(production_tonnes) AS production_tonnes
                    FROM crop_metrics {crop_filter}
                    GROUP BY crop_code, crop_name, year
                    ORDER BY crop_code, year
                """,
                "assumptions": [],
            }, LLMTrace(role=role, content="{}", completion_tokens=10)
        if role == "python_agent":
            self.systems[role] = system
            self.users[role] = user
            condition = "row['crop_code'] == '40124'" if "only crop 40124" in user else "True"
            return {
                "code": f"""
def analyze(rows):
    totals = {{}}
    names = {{}}
    for row in rows:
        if {condition}:
            key = (row["crop_code"], row["year"])
            names[row["crop_code"]] = row["crop_name"]
            totals[key] = totals.get(key, 0.0) + (row["production_tonnes"] or 0.0)
    return [{{"crop_code": key[0], "crop_name": names[key[0]], "year": key[1],
             "production_tonnes": totals[key]}} for key in sorted(totals)]
""",
                "assumptions": [],
            }, LLMTrace(role=role, content="{}", completion_tokens=10)
        return super().complete_json(role, system, user, max_tokens)


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
    model = StubModel()
    harness = SimpleHarness(model, dataset_path, tmp_path / "outputs")
    result = harness.run(
        "simple-test",
        "Analyze agricultural changes in the controlled fixture dataset.",
        lambda node, event_type, _message, _data=None: events.append((node, event_type)),
        agent_prompts={"final_editor": "CUSTOM FINAL EDITOR SYSTEM"},
    )
    assert result["harness"] == "simple"
    assert result["narrative"] == "Evidence-backed fixture analysis."
    assert result["model_usage"]["calls"] == 3
    assert ("business_agent", "started") in events
    assert ("dashboard_agent", "started") in events
    assert ("final_editor", "completed") in events
    assert len(result["inter_agent_messages"]) >= 7
    assert model.systems["final_editor"] == "CUSTOM FINAL EDITOR SYSTEM"
    assert result["applied_prompt_overrides"][0]["agent_id"] == "final_editor"
    assert len(result["applied_prompt_overrides"][0]["sha256"]) == 64

    run_dir = tmp_path / "outputs" / "simple-test"
    json_dashboard = run_dir / "dashboard.json"
    html_dashboard = run_dir / "dashboard.html"
    assert json_dashboard.exists() and json_dashboard.stat().st_size > 0
    assert html_dashboard.exists() and html_dashboard.stat().st_size > 0
    html_text = html_dashboard.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert 'id="kpis"' in html_text
    assert 'id="charts"' in html_text
    assert 'id="evidence-ledger"' in html_text


def test_simple_dashboard_agent_receives_the_original_visual_request(
    dataset_path: Path, tmp_path: Path
) -> None:
    model = StubModel()
    harness = SimpleHarness(model, dataset_path, tmp_path / "outputs")

    harness.run(
        "simple-white-theme",
        "Analyze the controlled fixture. The dashboard should have a white background!",
        lambda *_args: None,
    )

    assert "white background" in model.users["dashboard_agent"]
    html = (tmp_path / "outputs/simple-white-theme/dashboard.html").read_text()
    assert "--bg: #ffffff;" in html


def test_simple_dashboard_renderer_applies_structured_visual_theme() -> None:
    rendered = render_dashboard_html(
        {
            "title": "Theme fixture",
            "source": "Fixture",
            "evidence": [],
            "validation": [],
        },
        dashboard_briefing={
            "title": "Theme fixture",
            "visual_theme": {"background": "#ffffff", "accent": "#2563eb"},
        },
    )

    assert "--bg: #ffffff;" in rendered
    assert "--accent: #2563eb;" in rendered


def test_simple_dashboard_renderer_uses_temporal_rows_when_evidence_is_empty() -> None:
    rendered = render_dashboard_html(
        {
            "title": "Temporal fixture",
            "source": "Fixture",
            "evidence": [],
            "validation": [],
            "temporal_rows": [
                {
                    "crop_code": "40124",
                    "crop_name": "Upland cotton (seed)",
                    "year": 2019,
                    "production_tonnes": 10.0,
                    "weighted_yield_kg_ha": 100.0,
                    "yoy_production_pct": None,
                    "production_rank": 2,
                    "trailing_3y_yield_kg_ha": 100.0,
                    "yield_vs_trailing_pct": 0.0,
                },
                {
                    "crop_code": "40124",
                    "crop_name": "Upland cotton (seed)",
                    "year": 2024,
                    "production_tonnes": 20.0,
                    "weighted_yield_kg_ha": 140.0,
                    "yoy_production_pct": 100.0,
                    "production_rank": 1,
                    "trailing_3y_yield_kg_ha": 120.0,
                    "yield_vs_trailing_pct": 16.6666666667,
                },
                {
                    "crop_code": "00001",
                    "crop_name": "Paddy rice",
                    "year": 2019,
                    "production_tonnes": 30.0,
                    "weighted_yield_kg_ha": 200.0,
                    "yoy_production_pct": None,
                    "production_rank": 1,
                    "trailing_3y_yield_kg_ha": 200.0,
                    "yield_vs_trailing_pct": 0.0,
                },
                {
                    "crop_code": "00001",
                    "crop_name": "Paddy rice",
                    "year": 2024,
                    "production_tonnes": 15.0,
                    "weighted_yield_kg_ha": 180.0,
                    "yoy_production_pct": -50.0,
                    "production_rank": 2,
                    "trailing_3y_yield_kg_ha": 190.0,
                    "yield_vs_trailing_pct": -5.2631578947,
                },
            ],
            "generated_analysis": {
                "sql": {"status": "completed"},
                "python": {"status": "completed"},
            },
            "temporal_label": "4 reconciled crop-year rows",
        },
        dashboard_briefing={
            "title": "Temporal fixture",
            "visual_theme": {"background": "#ffffff", "accent": "#2563eb"},
        },
    )

    assert "Reconciled Crop-Year Rows" in rendered
    assert "4" in rendered
    assert "Total Production" in rendered
    assert "Paddy rice" in rendered
    assert "0 ha" not in rendered


def test_simple_dashboard_renderer_shows_placeholder_when_no_data_is_released() -> None:
    rendered = render_dashboard_html(
        {
            "title": "Empty fixture",
            "source": "Fixture",
            "evidence": [],
            "validation": [],
        }
    )

    assert "No released data available" in rendered
    assert "0 ha" not in rendered


def test_simple_temporal_task_executes_one_generated_attempt_per_branch(
    dataset_path: Path, tmp_path: Path
) -> None:
    model = GeneratedCodeModel()
    events: list[tuple[str, str]] = []
    result = SimpleHarness(model, dataset_path, tmp_path / "outputs").run(
        "simple-generated",
        "[TASK:mae-temporal-window-analysis-v3] Analyze every crop-year.",
        lambda node, event_type, *_args: events.append((node, event_type)),
    )

    generated = result["generated_analysis"]
    assert generated["sql"]["status"] == "completed"
    assert generated["python"]["status"] == "completed"
    assert len(generated["sql"]["rows"]) == 4
    assert len(generated["python"]["rows"]) == 4
    assert result["model_usage"]["calls"] == 4
    assert result["terminal_status"] == "failed"
    assert result["evidence"] == []
    assert "No analytical conclusions were published" in result["narrative"]
    assert not [event for event in events if event[1] == "branch_repair"]
    html = (tmp_path / "outputs" / "simple-generated" / "dashboard.html").read_text()
    assert 'id="temporal-analysis"' in html


def test_simple_analytical_prompt_changes_generated_results(
    dataset_path: Path, tmp_path: Path
) -> None:
    harness = SimpleHarness(GeneratedCodeModel(), dataset_path, tmp_path / "outputs")
    all_crops = harness.run(
        "simple-all-crops",
        "[TASK:mae-temporal-window-analysis-v3] Analyze every crop-year.",
        lambda *_args: None,
    )
    one_crop = harness.run(
        "simple-one-crop",
        "[TASK:mae-temporal-window-analysis-v3] Analyze only crop 40124.",
        lambda *_args: None,
    )

    assert len(all_crops["generated_analysis"]["sql"]["rows"]) == 4
    assert len(one_crop["generated_analysis"]["sql"]["rows"]) == 2
    assert (
        all_crops["generated_analysis"]["sql"]["code_sha256"]
        != one_crop["generated_analysis"]["sql"]["code_sha256"]
    )


def test_simple_rejects_prompt_override_for_deterministic_role(
    dataset_path: Path, tmp_path: Path
) -> None:
    harness = SimpleHarness(StubModel(), dataset_path, tmp_path / "outputs")
    with pytest.raises(ValueError, match="not inference-backed"):
        harness.run(
            "invalid-prompt-role",
            "Analyze agricultural changes in the controlled fixture dataset.",
            lambda *_args: None,
            agent_prompts={"sql_reviewer": "This cannot affect a deterministic reviewer."},
        )
