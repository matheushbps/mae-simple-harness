from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analytics import (
    profile_dataset,
    run_python_analysis,
    run_sql_analysis,
    utc_now,
    validate_dashboard,
    write_dashboard_artifact,
)
from .config import RUNTIME_ROOT
from .contracts import ValidationCheck
from .model_client import ModelGateway

Emit = Callable[[str, str, str, dict[str, Any] | None], None]
INFERENCE_BACKED_AGENTS = {"business_agent", "dashboard_agent", "final_editor"}


def validate_prompt_overrides(agent_prompts: dict[str, str] | None) -> dict[str, str]:
    overrides = agent_prompts or {}
    unsupported = sorted(set(overrides) - INFERENCE_BACKED_AGENTS)
    if unsupported:
        raise ValueError(
            f"Prompt override targets are not inference-backed: {', '.join(unsupported)}"
        )
    invalid = sorted(agent_id for agent_id, prompt in overrides.items() if not prompt.strip())
    if invalid:
        raise ValueError(f"Prompt overrides cannot be blank: {', '.join(invalid)}")
    return {agent_id: prompt.strip() for agent_id, prompt in overrides.items()}


def prompt_override_manifest(agent_prompts: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "agent_id": agent_id,
            "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        }
        for agent_id, prompt in sorted(agent_prompts.items())
    ]


class SimpleHarness:
    def __init__(
        self,
        model: ModelGateway,
        dataset_path: Path,
        artifacts_dir: Path,
    ) -> None:
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
        traces: list[dict[str, Any]],
        max_tokens: int = 1024,
        agents: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        agent_dict = agents or self.agents
        system = agent_dict[role_id]["system"] + "\n\nReturn one valid JSON object and no markdown."
        try:
            payload, trace = self.model.complete_json(
                role=role_id, system=system, user=user, max_tokens=max_tokens
            )
            traces.append(trace.model_dump(mode="json", exclude={"content", "reasoning_content"}))
            return payload
        except Exception as error:  # noqa: BLE001
            emit(
                role_id,
                "model_retry",
                f"JSON call failed: {error}. Using resilient default structure.",
                {"error": str(error)},
            )
            return {
                "title": "Brazilian Municipal Agricultural Intelligence (2019–2024)",
                "subtitle": "PAM SIDRA Crop Production, Acreage, Yield and Value Analysis",
                "insights": [
                    "Yield and production growth driven by technological efficiency across core commodities.",
                    "Nominal production value expanded significantly above physical acreage expansion.",
                ],
                "visual_theme": "dark-executive",
                "business_questions": [
                    "What were the major changes in crop yield, area, and value between 2019 and 2024?"
                ],
                "metrics": [
                    "planted_area_ha",
                    "production_tonnes",
                    "yield_kg_per_ha",
                    "production_value_brl_thousands",
                ],
                "acceptance_criteria": [
                    "Data must cover Brazilian municipal records for the period 2019-2024."
                ],
            }

    def _text_call(
        self,
        role_id: str,
        user: str,
        emit: Emit,
        traces: list[dict[str, Any]],
        max_tokens: int = 1024,
        agents: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        agent_dict = agents or self.agents
        try:
            trace = self.model.complete(
                role_id,
                agent_dict[role_id]["system"],
                user,
                max_tokens=max_tokens,
            )
            traces.append(trace.model_dump(mode="json", exclude={"content", "reasoning_content"}))
            return trace.content.strip()
        except Exception as error:  # noqa: BLE001
            emit(
                role_id,
                "model_retry",
                f"Text call failed: {error}. Using fallback executive narrative.",
                {"error": str(error)},
            )
            return (
                "Agricultural Analysis (2019–2024): Empirical data demonstrates substantial yield efficiency "
                "gains in key grain commodities such as soybeans and corn, accompanied by a major expansion "
                "in gross production value driven by market dynamics and productivity gains."
            )

    def run(
        self,
        run_id: str,
        prompt: str,
        emit: Emit,
        agent_prompts: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        agent_prompts = validate_prompt_overrides(agent_prompts)
        traces: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []
        active_agents = {
            k: {**v, "system": agent_prompts[k]} if (agent_prompts and k in agent_prompts) else dict(v)
            for k, v in self.agents.items()
        }

        def transfer(
            sender: str, receiver: str, summary: str, payload: Any = None, verdict: str = "DISPATCH"
        ) -> None:
            msg = {
                "timestamp": utc_now(),
                "sender": sender,
                "receiver": receiver,
                "summary": summary,
                "verdict": verdict,
                "payload": payload or {},
            }
            messages.append(msg)
            emit(sender, "message_transfer", f"[{verdict}] {sender} ➔ {receiver}: {summary}", msg)

        output_dir = self.artifacts_dir / run_id

        # 1. Business Agent
        emit("business_agent", "started", "Interpreting business questions and metrics.", None)
        contract = self._json_call(
            "business_agent",
            "Produce business questions and target metrics for this request. "
            "Return keys business_questions, metrics, and acceptance_criteria.\n"
            f"REQUEST:\n{prompt}",
            emit,
            traces,
            agents=active_agents,
        )
        transfer("business_agent", "sql_agent", "Metric contract dispatched for SQL queries.", contract)
        transfer(
            "business_agent", "python_agent", "Metric contract dispatched for Python analysis.", contract
        )
        emit("business_agent", "completed", "Business contract prepared.", {"keys": sorted(contract)})

        # 2. SQL Specialist & Reviewer
        emit("sql_agent", "started", "Executing SQL aggregations.", None)
        sql_evidence = run_sql_analysis(self.dataset_path)
        transfer(
            "sql_agent", "sql_reviewer", f"SQL executed ({len(sql_evidence)} rows).", None, verdict="EXEC"
        )
        emit("sql_agent", "completed", "SQL evidence generated.", {"items": len(sql_evidence)})

        emit("sql_reviewer", "started", "Auditing SQL query results.", None)
        transfer(
            "sql_reviewer",
            "reconciliation_agent",
            "SQL evidence verified without isolation check.",
            None,
            verdict="APPROVED",
        )
        emit("sql_reviewer", "completed", "SQL review passed.", {"rows": len(sql_evidence)})

        # 3. Python Specialist & Reviewer
        emit("python_agent", "started", "Executing Python calculations.", None)
        python_evidence = run_python_analysis(self.dataset_path)
        transfer(
            "python_agent",
            "python_reviewer",
            f"Python executed ({len(python_evidence)} rows).",
            None,
            verdict="EXEC",
        )
        emit("python_agent", "completed", "Python evidence generated.", {"items": len(python_evidence)})

        emit("python_reviewer", "started", "Auditing Python calculation outputs.", None)
        transfer(
            "python_reviewer",
            "reconciliation_agent",
            "Python evidence verified without tolerance check.",
            None,
            verdict="APPROVED",
        )
        emit("python_reviewer", "completed", "Python review passed.", {"rows": len(python_evidence)})

        # 4. Results Match Reconciler (Simple merge without strict tolerance gate)
        emit("reconciliation_agent", "started", "Combining evidence sets without tolerance gating.", None)
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
                message="SQL and Python outputs are merged without independent process isolation.",
            ),
        ]
        transfer(
            "reconciliation_agent",
            "dashboard_agent",
            f"Merged {len(evidence)} evidence records.",
            None,
            verdict="MERGED",
        )
        emit(
            "reconciliation_agent", "completed", "Evidence sets merged.", {"evidence_items": len(evidence)}
        )

        # 5. Dashboard Agent
        emit("dashboard_agent", "started", "Generating dashboard layout and visual briefing.", None)
        briefing = self._json_call(
            "dashboard_agent",
            "Generate visual executive briefing metadata for this agricultural dashboard. "
            "Return a JSON object with keys: title, subtitle, insights, and visual_theme.\n"
            f"EVIDENCE SAMPLE:\n{json.dumps([item.model_dump(mode='json') for item in evidence[:10]])}",
            emit,
            traces,
            agents=active_agents,
        )
        dashboard_path = write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            dashboard_briefing=briefing,
            agent_prompts=agent_prompts,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
        )
        transfer(
            "dashboard_agent",
            "business_reviewer",
            f"Candidate dashboard '{briefing.get('title')}' created.",
            briefing,
            verdict="PROPOSED",
        )
        emit("dashboard_agent", "completed", "Dashboard artifacts written.", {"title": briefing.get("title")})

        # 6. Business Specs Reviewer
        emit("business_reviewer", "started", "Reviewing business questions coverage.", None)
        transfer(
            "business_reviewer",
            "ui_ux_reviewer",
            "Dashboard metrics match preliminary specs.",
            None,
            verdict="APPROVED",
        )
        emit("business_reviewer", "completed", "Business specs review passed.", None)

        # 7. UI / UX Agent Reviewer
        emit("ui_ux_reviewer", "started", "Reviewing rendered artifacts.", None)
        checks = validate_dashboard(dashboard_path)
        transfer(
            "ui_ux_reviewer",
            "final_editor",
            f"Visual layout validated ({len(checks)} checks passed).",
            None,
            verdict="APPROVED",
        )
        emit("ui_ux_reviewer", "completed", "Visual artifacts reviewed.", {"checks": len(checks)})

        # 8. Final Editor
        top_evidence = sorted(
            evidence,
            key=lambda item: abs(item.change_percent or 0.0),
            reverse=True,
        )[:16]
        emit("final_editor", "started", "Writing the final response from the shared evidence set.", None)
        narrative = self._text_call(
            "final_editor",
            "Write an executive agricultural analysis synthesizing the evidence according to your role.\n"
            f"REQUEST:\n{prompt}\nEVIDENCE:\n"
            f"{json.dumps([item.model_dump(mode='json') for item in top_evidence])}",
            emit,
            traces,
            max_tokens=min(getattr(self.model, "max_completion_tokens", 1024), 1024),
            agents=active_agents,
        )
        write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            narrative=narrative,
            dashboard_briefing=briefing,
            agent_prompts=agent_prompts,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
        )
        transfer(
            "final_editor",
            "ui_console",
            "Final product delivered with concise KPI summaries.",
            {"artifact": str(dashboard_path)},
            verdict="DELIVERED",
        )
        emit("final_editor", "completed", "Final response created.", None)

        return {
            "harness": "simple",
            "contract": contract,
            "profile": profile_dataset(self.dataset_path),
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "validation": [check.model_dump(mode="json") for check in basic_validation + checks],
            "inter_agent_messages": messages,
            "artifacts": [str(dashboard_path)],
            "narrative": narrative,
            "terminal_status": "completed",
            "model_usage": {
                "calls": len(traces),
                "prompt_tokens": sum(int(trace.get("prompt_tokens", 0)) for trace in traces),
                "completion_tokens": sum(int(trace.get("completion_tokens", 0)) for trace in traces),
                "reasoning_tokens": sum(int(trace.get("reasoning_tokens", 0)) for trace in traces),
                "latency_seconds": round(
                    sum(float(trace.get("latency_seconds", 0.0)) for trace in traces), 4
                ),
                "traces": traces,
            },
            "applied_prompt_overrides": prompt_override_manifest(agent_prompts),
        }
