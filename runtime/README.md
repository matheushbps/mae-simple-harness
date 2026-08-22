# Simple Runtime

This FastAPI service is the deliberately thin benchmark condition. It executes four broad stages in a linear Python flow and calls the fixed local Qwen model through LM Studio.

## Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python -m mae_runtime.dataset --fixture --output ../data/agriculture.duckdb
.venv/bin/uvicorn mae_runtime.app:app --host 127.0.0.1 --port 8787
```

Use `--estimate` to inspect the approved dataset scope without downloading it. The full 42-chunk download requires the explicit `--full` flag.

## API

- `GET /health`: runtime, model, and dataset readiness.
- `POST /runs`: accept the frozen prompt and return a run ID.
- `GET /runs/{run_id}`: return state, events, metrics, and results.
- `GET /runs/{run_id}/events?after=N`: return incremental stage events.

Structured calls use LM Studio's native chat endpoint with reasoning disabled so JSON is emitted within a bounded output budget. Narrative generation leaves model reasoning enabled. This is an inference adapter policy, shared by both conditions, not an extra validation gate.

## Verify

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```
