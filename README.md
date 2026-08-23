# Simple Agricultural Agent Harness

This repository is the thin-context baseline for the MAE harness engineering experiment. Its frontend submits the frozen business prompt and selected inference provider to a local agent runtime. API credentials remain in the runtime and are never exposed to the browser.

## Local interface

```bash
# Set these in your shell or local secret manager; no environment files are committed.
export AGENT_RUNTIME_URL=http://127.0.0.1:8787
export MODEL_BASE_URL=http://127.0.0.1:1234/v1
export MODEL_ID=qwen/qwen3.6-35b-a3b
npm install
npm run dev
```

The agent runtime must implement `POST /runs` at `AGENT_RUNTIME_URL`. The request contains `harness`, `prompt`, and `provider`; the `X-Harness-Variant` header is set to `simple`.

## Experiment rule

The business prompt, dataset, Codex authoring model, generated harness hash, and inference settings must be frozen before measured runs.
