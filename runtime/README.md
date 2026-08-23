# Simple Runtime

This FastAPI service is the deliberately thin benchmark condition. It executes four broad stages in a linear Python flow and calls the fixed local Qwen model through LM Studio.

## Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export MODEL_BASE_URL=http://127.0.0.1:1234/v1
export MODEL_ID=qwen/qwen3.6-35b-a3b
export RUNTIME_HOST=127.0.0.1
export RUNTIME_PORT=8787
# When binding beyond loopback, use a high-entropy token and set the same value
# as AGENT_RUNTIME_TOKEN in the web app process.
# export MAE_RUNTIME_TOKEN='generate-a-secret-outside-the-repository'
.venv/bin/python -m mae_runtime.dataset --fixture --output ../data/agriculture.duckdb
.venv/bin/uvicorn mae_runtime.app:app --host 127.0.0.1 --port 8787
```

Keep credentials and machine-specific settings in the shell or a local secret manager. No `.env` files are committed.
Non-loopback listeners refuse to start without `MAE_RUNTIME_TOKEN`; the runtime also caps concurrent runs, request rate, retained runs, and generated prompt overrides.

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
