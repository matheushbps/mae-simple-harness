# Simple Harness Repository Guide

## Purpose

This repository is the intentionally thin baseline in the MAE controlled experiment. The comparison changes the harness, not the business prompt, dataset, model, or hardware.

Codex or another coding agent authors this repository. Qwen is only the runtime inference provider for the fixed agents; Qwen must not create, rename, or redesign agents.

## Experimental invariants

- Keep all code, prompts, documentation, logs, and UI copy in English.
- Use the frozen business prompt in `runtime/config/business_prompt.txt`.
- Use `qwen/qwen3.6-35b-a3b` with the frozen run settings.
- Use the same IBGE SIDRA PAM 5457 snapshot and checksum as the robust condition.
- Keep the runtime API compatible with the robust repository.
- Never commit private endpoint addresses, credentials, generated databases, or run artifacts.

## Deliberate baseline limits

- Keep four broad stages: Plan, Analyze, Execute, Report.
- Use one shared, loosely structured run context.
- Allow at most one whole-step retry.
- Validate successful execution and required output presence only.
- Do not add independent SQL/Python reconciliation, typed graph state, persistent checkpoints, specialist repair routes, or reusable runtime skills.
- Do not make the simple condition fail artificially. It must still run, log errors, and execute its documented checks.

## Repository map

- `app/`: experiment console and server-side proxy.
- `runtime/`: FastAPI service, Qwen client, linear flow, data tools, and tests.
- `data/`: generated local data only; full datasets are ignored by Git.
- `tests/`: frontend rendering and credential-boundary tests.

## Tool policy

- The analysis stage may use read-only DuckDB SQL and the bounded Python analytics tool.
- The execution stage may write only under `outputs/`.
- Runtime agents have no shell or network access. Dataset acquisition is a separate developer command.
- Reject mutating SQL and paths outside the repository output directory.

## First run

```bash
npm install
cd runtime && python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export AGENT_RUNTIME_URL=http://127.0.0.1:8787
export MODEL_BASE_URL=http://127.0.0.1:1234/v1
export MODEL_ID=qwen/qwen3.6-35b-a3b
```

## Verification

```bash
npm run lint
npm test
cd runtime && .venv/bin/ruff check src tests
cd runtime && .venv/bin/pytest -q
```

## Definition of done

- The requested change is within the thin-baseline limits.
- Frontend lint and production build pass.
- Runtime tests pass.
- The runtime contract remains compatible with the robust condition.
- No private configuration or generated data is tracked.

This file is intentionally short. The baseline omits the richer state, feedback, recovery, and skill subsystems present in the robust condition.
