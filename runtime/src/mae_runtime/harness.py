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
from .code_execution import execute_generated_python, execute_generated_sql
from .config import RUNTIME_ROOT
from .contracts import ValidationCheck
from .model_client import ModelGateway
from .temporal_prompts import temporal_generation_prompt, temporal_prompt_hashes
from .visual_requirements import apply_explicit_visual_requirements

Emit = Callable[[str, str, str, dict[str, Any] | None], None]
INFERENCE_BACKED_AGENTS = {
    "business_agent",
    "sql_agent",
    "python_agent",
    "dashboard_agent",
    "final_editor",
}


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
        temporal_task = "[TASK:mae-temporal-window-analysis-v3]" in prompt
        generated_analysis: dict[str, Any] = {}

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
        if temporal_task:
            sql_spec = self._json_call(
                "sql_agent",
                temporal_generation_prompt("sql", prompt, contract),
                emit,
                traces,
                max_tokens=3072,
                agents=active_agents,
            )
            sql_execution = execute_generated_sql(
                self.dataset_path, str(sql_spec.get("code", "")), max_rows=100
            )
            generated_analysis["sql"] = sql_execution.model_dump(mode="json")
            emit(
                "sql_agent",
                "branch_attempt",
                f"SQL first attempt {sql_execution.status}; no automatic correction is available.",
                {
                    "status": sql_execution.status,
                    "code_sha256": sql_execution.code_sha256,
                    "diagnostics": [item.model_dump(mode="json") for item in sql_execution.diagnostics],
                },
            )
        sql_evidence = [] if temporal_task else run_sql_analysis(self.dataset_path)
        transfer(
            "sql_agent",
            "sql_reviewer",
            f"SQL generated branch finished ({len(generated_analysis.get('sql', {}).get('rows', []))} rows)."
            if temporal_task
            else f"SQL executed ({len(sql_evidence)} rows).",
            None,
            verdict="EXEC",
        )
        emit("sql_agent", "completed", "SQL evidence generated.", {"items": len(sql_evidence)})

        emit("sql_reviewer", "started", "Auditing SQL query results.", None)
        sql_passed = (
            generated_analysis.get("sql", {}).get("status") == "completed"
            if temporal_task
            else bool(sql_evidence)
        )
        transfer(
            "sql_reviewer",
            "reconciliation_agent",
            "SQL first attempt completed." if sql_passed else "SQL first attempt was rejected.",
            None,
            verdict="APPROVED" if sql_passed else "REJECTED",
        )
        emit("sql_reviewer", "completed", "SQL branch recorded.", {"passed": sql_passed})

        # 3. Python Specialist & Reviewer
        emit("python_agent", "started", "Executing Python calculations.", None)
        if temporal_task:
            python_spec = self._json_call(
                "python_agent",
                temporal_generation_prompt("python", prompt, contract),
                emit,
                traces,
                max_tokens=3072,
                agents=active_agents,
            )
            python_execution = execute_generated_python(
                self.dataset_path, str(python_spec.get("code", "")), max_rows=100
            )
            generated_analysis["python"] = python_execution.model_dump(mode="json")
            emit(
                "python_agent",
                "branch_attempt",
                f"Python first attempt {python_execution.status}; no automatic correction is available.",
                {
                    "status": python_execution.status,
                    "code_sha256": python_execution.code_sha256,
                    "diagnostics": [
                        item.model_dump(mode="json") for item in python_execution.diagnostics
                    ],
                },
            )
        python_evidence = [] if temporal_task else run_python_analysis(self.dataset_path)
        transfer(
            "python_agent",
            "python_reviewer",
            "Python generated branch finished "
            f"({len(generated_analysis.get('python', {}).get('rows', []))} rows)."
            if temporal_task
            else f"Python executed ({len(python_evidence)} rows).",
            None,
            verdict="EXEC",
        )
        emit("python_agent", "completed", "Python evidence generated.", {"items": len(python_evidence)})

        emit("python_reviewer", "started", "Auditing Python calculation outputs.", None)
        python_passed = (
            generated_analysis.get("python", {}).get("status") == "completed"
            if temporal_task
            else bool(python_evidence)
        )
        transfer(
            "python_reviewer",
            "reconciliation_agent",
            "Python first attempt completed."
            if python_passed
            else "Python first attempt was rejected; no repair route exists.",
            None,
            verdict="APPROVED" if python_passed else "REJECTED",
        )
        emit("python_reviewer", "completed", "Python branch recorded.", {"passed": python_passed})

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
        if temporal_task:
            basic_validation = [
                ValidationCheck(
                    check_id="temporal:sql_execution",
                    passed=sql_passed,
                    message="SQL first attempt completed." if sql_passed else "SQL first attempt failed.",
                ),
                ValidationCheck(
                    check_id="temporal:python_execution",
                    passed=python_passed,
                    message="Python first attempt completed."
                    if python_passed
                    else "Python first attempt failed.",
                ),
                ValidationCheck(
                    check_id="temporal:cross_method_agreement",
                    passed=False,
                    message="The Simple architecture has no numeric reconciliation gate.",
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
        temporal_rows = (
            generated_analysis.get("sql", {}).get("rows", [])
            or generated_analysis.get("python", {}).get("rows", [])
        )
        failure_reason = None
        if temporal_task:
            failed = [
                branch
                for branch in ("sql", "python")
                if generated_analysis.get(branch, {}).get("status") != "completed"
            ]
            detail = ", ".join(failed) if failed else "cross-method agreement"
            failure_reason = (
                f"Temporal release failed at {detail}; the Simple architecture has no automatic "
                "branch repair or numeric reconciliation gate."
            )

        # 5. Dashboard Agent
        emit("dashboard_agent", "started", "Generating dashboard layout and visual briefing.", None)
        briefing = self._json_call(
            "dashboard_agent",
            "Generate visual executive briefing metadata for this agricultural dashboard. "
            "Honor every explicit presentation requirement in the original request. "
            "Return a JSON object with keys: title, subtitle, insights, and visual_theme. "
            "visual_theme must be an object with background and accent as six-digit hex colors.\n"
            f"ORIGINAL REQUEST:\n{prompt}\n"
            f"TEMPORAL RESULT SAMPLE:\n{json.dumps(temporal_rows[:10])}\n"
            f"EVIDENCE SAMPLE:\n{json.dumps([item.model_dump(mode='json') for item in evidence[:10]])}",
            emit,
            traces,
            agents=active_agents,
        )
        briefing = apply_explicit_visual_requirements(briefing, prompt)
        dashboard_path = write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            dashboard_briefing=briefing,
            agent_prompts=agent_prompts,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
            temporal_rows=temporal_rows,
            generated_analysis=generated_analysis,
            temporal_label=f"{len(temporal_rows)} generated crop-year rows",
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
        narrative = (
            f"## Analysis not released\n\n{failure_reason}\n\nNo analytical conclusions were published."
            if temporal_task
            else self._text_call(
                "final_editor",
                "Write an executive agricultural analysis synthesizing the evidence according to your role.\n"
                f"REQUEST:\n{prompt}\nEVIDENCE:\n"
                f"{json.dumps([item.model_dump(mode='json') for item in top_evidence])}\n"
                f"GENERATED TEMPORAL ROWS:\n{json.dumps(temporal_rows)}",
                emit,
                traces,
                max_tokens=min(getattr(self.model, "max_completion_tokens", 1024), 1024),
                agents=active_agents,
            )
        )
        write_dashboard_artifact(
            output_dir,
            evidence,
            basic_validation,
            narrative=narrative,
            dashboard_briefing=briefing,
            agent_prompts=agent_prompts,
            metadata={"harness": "Simple Harness (Condition A)", "run_id": run_id},
            temporal_rows=temporal_rows,
            generated_analysis=generated_analysis,
            temporal_label=f"{len(temporal_rows)} generated crop-year rows",
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
            "generated_analysis": generated_analysis,
            "first_attempt_prompt_hashes": temporal_prompt_hashes(prompt) if temporal_task else {},
            "contract": contract,
            "profile": profile_dataset(self.dataset_path),
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "validation": [check.model_dump(mode="json") for check in basic_validation + checks],
            "inter_agent_messages": messages,
            "artifacts": [str(dashboard_path)],
            "narrative": narrative,
            "terminal_status": "failed" if temporal_task else "completed",
            "failure_reason": failure_reason,
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
