# Simple Agricultural Agent Harness

This repository is the thin-context baseline for the MAE harness engineering experiment. Its frontend submits the frozen business prompt and selected inference provider to a local agent runtime. API credentials remain in the runtime and are never exposed to the browser.

## Local interface

```bash
cp .env.example .env.local
npm install
npm run dev
```

The agent runtime must implement `POST /runs` at `AGENT_RUNTIME_URL`. The request contains `harness`, `prompt`, and `provider`; the `X-Harness-Variant` header is set to `simple`.

## Experiment rule

The business prompt, dataset, Codex authoring model, generated harness hash, and inference settings must be frozen before measured runs.
