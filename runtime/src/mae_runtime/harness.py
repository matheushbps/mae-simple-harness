from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analytics import (
    profile_dataset,
    run_python_analysis,
    run_sql_analysis,
    validate_dashboard,
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
        agents: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        agent_dict = agents or self.agents
        agent = agent_dict[role_id]
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
        agents: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        agent_dict = agents or self.agents
        agent = agent_dict[role_id]
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

    def run(
        self,
        run_id: str,
        prompt: str,
        emit: Emit,
        agent_prompts: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {self.dataset_path}")
        
        active_agents = {
            k: {**v, "system": agent_prompts[k]} if (agent_prompts and k in agent_prompts) else dict(v)
            for k, v in self.agents.items()
        }
        traces: list[LLMTrace] = []
        output_dir = self.artifacts_dir / run_id

        # 1. Business Analyst
        emit("business_analyst", "started", "Interpreting business questions and metrics.", None)
        contract = self._json_call(
            "business_analyst",
            "Produce business questions and target metrics for this request. "
            "Return keys business_questions, metrics, and acceptance_criteria.\n"
            f"REQUEST:\n{prompt}",
            emit,
            traces,
            agents=active_agents,
        )
        emit("business_analyst", "completed", "Business contract prepared.", {"keys": sorted(contract)})

        # 2. Data Profiler
        emit("data_profiler", "started", "Profiling dataset structure.", None)
        profile = profile_dataset(self.dataset_path)
        emit("data_profiler", "completed", "Dataset profiled.", {"rows": profile["rows"]})

        # 3. SQL Analyst
        emit("sql_analyst", "started", "Executing SQL aggregations.", None)
        sql_evidence = run_sql_analysis(self.dataset_path)
        emit("sql_analyst", "completed", "SQL evidence generated.", {"items": len(sql_evidence)})

        # 4. Python Analyst
        emit("python_analyst", "started", "Executing Python calculations.", None)
        python_evidence = run_python_analysis(self.dataset_path)
        emit("python_analyst", "completed", "Python evidence generated.", {"items": len(python_evidence)})

        # 5. Evidence Reconciler (Simple merge without strict tolerance gate)
        emit("evidence_reconciler", "started", "Combining evidence sets without tolerance gating.", None)
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
        emit("evidence_reconciler", "completed", "Evidence sets merged.", {"evidence_items": len(evidence)})

        # 6. Dashboard Engineer
        emit("dashboard_engineer", "started", "Generating dashboard artifacts.", None)
        dashboard_path = write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
        )
        html_dashboard_path = output_dir / "dashboard.html"
        emit(
            "dashboard_engineer",
            "completed",
            "Dashboard artifacts written.",
            {
                "evidence_items": len(evidence),
                "artifact": str(dashboard_path),
                "html_artifact": str(html_dashboard_path),
            },
        )

        # 7. Visual Reviewer
        emit("visual_reviewer", "started", "Reviewing rendered artifacts.", None)
        checks = validate_dashboard(dashboard_path)
        emit("visual_reviewer", "completed", "Visual artifacts reviewed.", {"checks": len(checks)})

        # 8. Final Editor
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
            agents=active_agents,
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
            "contract": contract,
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
        "traces": [trace.model_dump(mode="json") for trace in traces],
    }
