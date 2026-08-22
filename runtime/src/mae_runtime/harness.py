from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analytics import (
    profile_dataset,
    run_python_analysis,
    run_sql_analysis,
    write_dashboard_artifact,
)
from .config import RUNTIME_ROOT
from .contracts import LLMTrace, ValidationCheck
from .model_client import ModelGateway

Emit = Callable[[str, str, str, dict[str, Any] | None], None]


class SimpleHarness:
    def __init__(self, model: ModelGateway, dataset_path: Path, artifacts_dir: Path) -> None:
        self.model = model
        self.dataset_path = dataset_path
        self.artifacts_dir = artifacts_dir
        config = json.loads((RUNTIME_ROOT / "config/agents.json").read_text(encoding="utf-8"))
        self.agents = {agent["id"]: agent for agent in config["agents"]}

    def _json_call(
        self,
        role_id: str,
        user: str,
        emit: Emit,
        traces: list[LLMTrace],
    ) -> dict[str, Any]:
        agent = self.agents[role_id]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                payload, trace = self.model.complete_json(
                    role=role_id,
                    system=agent["system"] + " Return one valid JSON object and no markdown.",
                    user=user,
                )
                traces.append(trace)
                return payload
            except Exception as error:  # noqa: BLE001 - the thin harness has one broad retry.
                last_error = error
                emit(role_id, "retry", f"Broad model step retry {attempt + 1}/1.", {"error": str(error)})
                if attempt == 1:
                    break
        raise RuntimeError(f"{role_id} failed after one retry") from last_error

    def _text_call(
        self,
        role_id: str,
        user: str,
        emit: Emit,
        traces: list[LLMTrace],
        max_tokens: int | None = None,
    ) -> str:
        agent = self.agents[role_id]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                trace = self.model.complete(
                    role_id, agent["system"], user, max_tokens=max_tokens
                )
                traces.append(trace)
                if not trace.content.strip():
                    raise ValueError("Model returned empty visible content.")
                return trace.content.strip()
            except Exception as error:  # noqa: BLE001 - the baseline retries the entire step.
                last_error = error
                emit(role_id, "retry", f"Broad model step retry {attempt + 1}/1.", {"error": str(error)})
                if attempt == 1:
                    break
        raise RuntimeError(f"{role_id} failed after one retry") from last_error

    def run(self, run_id: str, prompt: str, emit: Emit) -> dict[str, Any]:
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {self.dataset_path}")
        traces: list[LLMTrace] = []
        output_dir = self.artifacts_dir / run_id

        emit("planner", "started", "Planning the agricultural analysis.", None)
        profile = profile_dataset(self.dataset_path)
        plan = self._json_call(
            "planner",
            "Create a compact plan for this request. Return keys goals, metrics, and steps.\n"
            f"REQUEST:\n{prompt}\nDATA PROFILE:\n{json.dumps(profile, default=str)}",
            emit,
            traces,
        )
        emit("planner", "completed", "Plan created.", {"keys": sorted(plan)})

        emit("data_analyst", "started", "Selecting analytical priorities.", None)
        analyst_decision = self._json_call(
            "data_analyst",
            "Choose the most important metrics for the prepared plan. Return keys priorities and cautions.\n"
            f"PLAN:\n{json.dumps(plan)}",
            emit,
            traces,
        )
        emit("data_analyst", "completed", "Analysis priorities selected.", None)

        emit("code_runner", "started", "Executing SQL and Python analytics in one shared stage.", None)
        sql_evidence = run_sql_analysis(self.dataset_path)
        python_evidence = run_python_analysis(self.dataset_path)
        evidence = sql_evidence + python_evidence
        basic_validation = [
            ValidationCheck(
                check_id="execution:completed",
                passed=bool(evidence),
                message="The broad analysis stage produced evidence.",
            ),
            ValidationCheck(
                check_id="outputs:required",
                passed=bool(sql_evidence and python_evidence),
                message="SQL and Python outputs are present but are not independently reconciled.",
            ),
        ]
        dashboard_path = write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
        )
        html_dashboard_path = output_dir / "dashboard.html"
        emit(
            "code_runner",
            "completed",
            "Execution artifacts created.",
            {
                "evidence_items": len(evidence),
                "artifact": str(dashboard_path),
                "html_artifact": str(html_dashboard_path),
            },
        )

        top_evidence = sorted(
            evidence,
            key=lambda item: abs(item.change_percent or 0.0),
            reverse=True,
        )[:16]
        emit("final_editor", "started", "Writing the final response from the shared evidence set.", None)
        narrative = self._text_call(
            "final_editor",
            "Write an executive agricultural analysis from this evidence. Include limitations.\n"
            f"REQUEST:\n{prompt}\nEVIDENCE:\n"
            f"{json.dumps([item.model_dump(mode='json') for item in top_evidence])}",
            emit,
            traces,
            max_tokens=getattr(self.model, "max_completion_tokens", None),
        )
        # Update dashboard artifact to embed narrative
        write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            narrative=narrative,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
        )
        emit("final_editor", "completed", "Final response created.", None)

        return {
            "harness": "simple",
            "plan": plan,
            "analyst_decision": analyst_decision,
            "profile": profile,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "validation": [check.model_dump(mode="json") for check in basic_validation],
            "artifacts": [str(dashboard_path), str(html_dashboard_path)],
            "narrative": narrative,
            "model_usage": _summarize_usage(traces),
        }


def _summarize_usage(traces: list[LLMTrace]) -> dict[str, Any]:
    return {
        "calls": len(traces),
        "prompt_tokens": sum(trace.prompt_tokens for trace in traces),
        "completion_tokens": sum(trace.completion_tokens for trace in traces),
        "reasoning_tokens": sum(trace.reasoning_tokens for trace in traces),
        "latency_seconds": round(sum(trace.latency_seconds for trace in traces), 4),
        "traces": [
            trace.model_dump(mode="json", exclude={"content", "reasoning_content"}) for trace in traces
        ],
    }
