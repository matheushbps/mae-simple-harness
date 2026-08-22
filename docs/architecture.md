# Simple Harness Architecture

```text
frozen prompt
    ↓
planner → data analyst → code runner → final editor
                ↓              ↓
         broad priorities   SQL + Python + dashboard
```

The baseline is intentionally limited by `AGENTS.md`: four broad roles, shared context, one whole-step retry, and checks for execution and required output presence. It has no typed graph state, checkpoint recovery, reusable runtime skills, cross-method reconciliation, or specialist repair route.

This is a credible thin harness, not a deliberately broken implementation. It still enforces read-only analytics, bounded output paths, fixed configuration, and observable stage events.
