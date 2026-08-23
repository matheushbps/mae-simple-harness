"use client";

import { useCallback, useEffect, useState } from "react";

const defaultPrompt =
  "Analyze the Brazilian municipal agricultural production database. Identify the most relevant changes in planted area, production, yield, and production value, then present evidence-backed business insights.";

const promptPresets = [
  {
    id: "benchmark",
    label: "Benchmark Default",
    description: "Standard PAM 2019-2024 analysis across 7 crops",
    prompt: defaultPrompt,
  },
  {
    id: "grains",
    label: "Grains Focus (Soy, Corn, Wheat)",
    description: "Compare yield efficiency vs acreage growth in key grain crops",
    prompt:
      "Focus specifically on grain production dynamics (soybeans, corn, and wheat) between 2019 and 2024. Compare yield efficiency (kg/ha) vs planted area expansion and identify market saturation and land allocation patterns.",
  },
  {
    id: "value",
    label: "Production Value Surge",
    description: "Investigate nominal value growth vs physical output",
    prompt:
      "Analyze the dramatic surge in production value (thousand BRL) across all Brazilian crops from 2019 to 2024. Reconcile whether value gains were driven by volume growth or nominal commodity pricing.",
  },
  {
    id: "productivity",
    label: "Productivity & Yield Gains",
    description: "Analyze agricultural technological efficiency",
    prompt:
      "Evaluate agricultural productivity gains (yield in kg/ha) between 2019 and 2024 across all commodities. Which crops demonstrated real technological/efficiency gains versus pure acreage expansion?",
  },
];

const defaultAgents = [
  {
    id: "business_agent",
    index: "01",
    role: "Business Agent",
    system:
      "You are the Lead Business Strategy Agent. Your mission is to deconstruct research requests into explicit agricultural questions and target metric contracts across Brazilian municipal commodities from 2019 to 2024.",
    tools: ["dataset_catalog"],
  },
  {
    id: "sql_agent",
    index: "02",
    role: "SQL Specialist Agent",
    system:
      "You are a Senior SQL Analytics Specialist. Your objective is to formulate DuckDB SQL aggregation queries across municipal commodities.",
    tools: ["readonly_sql"],
  },
  {
    id: "sql_reviewer",
    index: "03",
    role: "SQL Reviewer",
    system:
      "You are an SQL Quality Auditor. Your role is to inspect executed SQL queries and ensure query syntax and row outputs are valid.",
    tools: ["sql_verifier"],
  },
  {
    id: "python_agent",
    index: "04",
    role: "Python / Pandas Agent",
    system:
      "You are a Quantitative Python Data Scientist. Your mission is to compute crop totals, yield comparisons, and growth rates using Python scripts.",
    tools: ["python_analytics"],
  },
  {
    id: "python_reviewer",
    index: "05",
    role: "Python Reviewer",
    system:
      "You are a Python Quality Auditor. Your role is to inspect executed Python analytics and ensure calculations are ready for merging.",
    tools: ["python_verifier"],
  },
  {
    id: "reconciliation_agent",
    index: "06",
    role: "Results Match Reconciler",
    system:
      "You are an Evidence Integration Specialist. Your goal is to collect and merge SQL and Python analytical evidence into a combined dataset.",
    tools: ["evidence_merger"],
  },
  {
    id: "dashboard_agent",
    index: "07",
    role: "Dashboard Agent",
    system:
      "You are an expert Data Visualization Specialist and Dashboard Creator. Your goal is to create appealing, concise, and well-crafted dashboards with clean mini KPI summaries.",
    tools: ["artifact_writer"],
  },
  {
    id: "business_reviewer",
    index: "08",
    role: "Business Specs Reviewer",
    system:
      "You are a Business Specification Reviewer. Your role is to check whether the dashboard covers the requested business questions.",
    tools: ["contract_auditor"],
  },
  {
    id: "ui_ux_reviewer",
    index: "09",
    role: "UI / UX Agent",
    system:
      "You are a UI/UX Visual Reviewer. Your task is to confirm that the generated dashboard layout, charts, and summary cards are clean and visually appealing.",
    tools: ["artifact_reader"],
  },
  {
    id: "final_editor",
    index: "10",
    role: "Final Editor",
    system:
      "You are a Senior Agricultural Report Editor. Your mission is to synthesize the merged analytical evidence into a clear, compelling, and actionable executive report with limitations.",
    tools: ["evidence_reader"],
  },
];

const pipeline = [
  {
    id: "01",
    nodeId: "business_agent",
    name: "Business Questions",
    owner: "Business Agent",
    detail: "Interprets request into questions and metrics without schema validation.",
  },
  {
    id: "02",
    nodeId: "sql_agent",
    name: "SQL Extraction",
    owner: "SQL Specialist",
    detail: "Extracts aggregations using DuckDB SQL without process isolation.",
  },
  {
    id: "03",
    nodeId: "sql_reviewer",
    name: "SQL Review",
    owner: "SQL Reviewer",
    detail: "Basic check of SQL rows.",
  },
  {
    id: "04",
    nodeId: "python_agent",
    name: "Python Analytics",
    owner: "Python Agent",
    detail: "Calculates agricultural metrics with Python scripts.",
  },
  {
    id: "05",
    nodeId: "python_reviewer",
    name: "Python Review",
    owner: "Python Reviewer",
    detail: "Basic check of Python metrics.",
  },
  {
    id: "06",
    nodeId: "reconciliation_agent",
    name: "Evidence Merge",
    owner: "Results Reconciler",
    detail: "Merges SQL and Python evidence without tolerance gates.",
  },
  {
    id: "07",
    nodeId: "dashboard_agent",
    name: "Dashboard Creation",
    owner: "Dashboard Agent",
    detail: "Builds HTML and JSON dashboard artifacts.",
  },
  {
    id: "08",
    nodeId: "business_reviewer",
    name: "Business Specs",
    owner: "Business Reviewer",
    detail: "Reviews business spec coverage.",
  },
  {
    id: "09",
    nodeId: "ui_ux_reviewer",
    name: "UI/UX Review",
    owner: "UI / UX Agent",
    detail: "Checks artifact presence.",
  },
  {
    id: "10",
    nodeId: "final_editor",
    name: "Report Synthesis",
    owner: "Final Editor",
    detail: "Writes linear prose from shared memory.",
  },
];

type RunState = "idle" | "submitting" | "accepted" | "running" | "completed" | "failed" | "error";
type ConnectionState = "checking" | "connected" | "offline";

type ModelStatus = {
  connected: boolean;
  model: string | null;
  message: string;
  contextLength?: number | null;
  quantization?: string | null;
};

type InterAgentMessage = {
  timestamp: string;
  sender: string;
  receiver: string;
  summary: string;
  verdict: string;
  payload?: any;
};

type RunEvent = {
  sequence: number;
  node: string;
  event_type: string;
  message: string;
  data?: any;
};

type RunSnapshot = {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  events: RunEvent[];
  error?: string | null;
};

function BrandIcon() {
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true">
      <path d="M10 28V12l10-4 10 4v16l-10 4-10-4Z" />
      <path d="M20 8v24M10 12l10 6 10-6" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 10h11M11 6l4 4-4 4" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M15.2 7A6 6 0 1 0 16 11" />
      <path d="M12 7h3.5V3.5" />
    </svg>
  );
}

export default function Home() {
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [agentPrompts, setAgentPrompts] = useState<Record<string, string>>({});
  const [runState, setRunState] = useState<RunState>("idle");
  const [runMessage, setRunMessage] = useState("Awaiting a connected model and linear harness runtime.");
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [runEvents, setRunEvents] = useState<RunEvent[]>([]);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const res = await fetch("/api/agents");
        if (res.ok) {
          const data = (await res.json()) as Array<{ id: string; system: string }>;
          const initialMap: Record<string, string> = {};
          data.forEach((agent) => {
            initialMap[agent.id] = agent.system;
          });
          setAgentPrompts((prev) => (Object.keys(prev).length === 0 ? initialMap : prev));
        }
      } catch {
        // Offline fallback
      }
    }
    void fetchAgents();
  }, []);

  const checkModel = useCallback(async () => {
    setConnection("checking");
    try {
      const response = await fetch("/api/model-status", { cache: "no-store" });
      const payload = (await response.json()) as ModelStatus;
      setModelStatus(payload);
      setConnection(payload.connected ? "connected" : "offline");
    } catch {
      setModelStatus({ connected: false, model: null, message: "Model proxy unreachable." });
      setConnection("offline");
    }
  }, []);

  useEffect(() => {
    void checkModel();
  }, [checkModel]);

  useEffect(() => {
    if (!runId || !["submitting", "accepted", "running"].includes(runState)) return;
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/api/run-status?run_id=${encodeURIComponent(runId)}`, {
          cache: "no-store",
        });
        if (!response.ok) return;
        const payload = (await response.json()) as RunSnapshot;
        setRunEvents(payload.events ?? []);
        if (payload.status === "completed") {
          setRunState("completed");
          setRunMessage("Simple harness completed all stages.");
        } else if (payload.status === "failed") {
          setRunState("failed");
          setRunMessage(payload.error ?? "Simple harness failed.");
        } else {
          setRunState("running");
          const latest = payload.events[payload.events.length - 1];
          if (latest) {
            setRunMessage(`[${latest.node}] ${latest.message}`);
          }
        }
      } catch {
        // Polling retry
      }
    }, 400);
    return () => clearInterval(interval);
  }, [runId, runState]);

  const handleAgentPromptChange = (agentId: string, newPrompt: string) => {
    setAgentPrompts((prev) => ({
      ...prev,
      [agentId]: newPrompt,
    }));
  };

  const handleResetAgentPrompt = (agentId: string) => {
    const defaultAgent = defaultAgents.find((a) => a.id === agentId);
    if (defaultAgent) {
      setAgentPrompts((prev) => ({
        ...prev,
        [agentId]: defaultAgent.system,
      }));
    }
  };

  const handleResetAllAgentPrompts = () => {
    const initialMap: Record<string, string> = {};
    defaultAgents.forEach((a) => {
      initialMap[a.id] = a.system;
    });
    setAgentPrompts(initialMap);
  };

  const getAgentSystemPrompt = (agentId: string) => {
    return agentPrompts[agentId] ?? defaultAgents.find((a) => a.id === agentId)?.system ?? "";
  };

  const customAgentsCount = defaultAgents.filter(
    (agent) => getAgentSystemPrompt(agent.id) !== agent.system
  ).length;

  const runHarness = async () => {
    setRunState("submitting");
    setRunMessage("Dispatching run to simple harness runtime…");
    setRunEvents([]);
    try {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, agent_prompts: agentPrompts }),
      });
      const payload = (await response.json()) as { run_id?: string; error?: string; status?: string };
      if (!response.ok || !payload.run_id) {
        setRunState("error");
        setRunMessage(payload.error ?? "Submission failed.");
        return;
      }
      setRunId(payload.run_id);
      setRunState("accepted");
      setRunMessage(`Run accepted (${payload.run_id}). Awaiting execution…`);
    } catch (error) {
      setRunState("error");
      setRunMessage(error instanceof Error ? error.message : "Submission network error.");
    }
  };

  const canRun = connection === "connected" && !["submitting", "accepted", "running"].includes(runState);
  const latestNode = runEvents[runEvents.length - 1]?.node;
  const isCustomPrompt = prompt !== defaultPrompt;
  const modelLabel = modelStatus?.model ? modelStatus.model.replace(/^qwen\//, "") : "local model";

  const interAgentMessages: InterAgentMessage[] = runEvents
    .filter((ev) => ev.event_type === "message_transfer" && ev.data)
    .map((ev) => ev.data as InterAgentMessage);

  return (
    <main className="app-frame variant-simple">
      <aside className="rail">
        <div className="brand-lockup">
          <span className="brand-icon">
            <BrandIcon />
          </span>
          <span>
            <b>MAE</b>
            <small>Agent benchmark</small>
          </span>
        </div>

        <nav className="rail-nav" aria-label="Workspace sections">
          <a className="active" href="#workspace">
            <span>01</span>Run console
          </a>
          <a href="#pipeline">
            <span>02</span>Pipeline
          </a>
          <a href="#agents">
            <span>03</span>Agent prompts
          </a>
          <a href="#inter-agent-feed">
            <span>04</span>Message stream
          </a>
          <a href="#evidence">
            <span>05</span>Ledger
          </a>
        </nav>

        <div className="rail-note">
          <span className="condition-token">CONDITION A</span>
          <strong>Simplified baseline</strong>
          <p>Sequential orchestration without strict tolerance verification.</p>
        </div>

        <div className="rail-footer">
          <span className={`status-dot ${connection}`} />
          <div>
            <strong>
              {connection === "connected"
                ? "Inference online"
                : connection === "checking"
                  ? "Checking inference"
                  : "Inference offline"}
            </strong>
            <small>OpenAI-compatible endpoint</small>
          </div>
        </div>
      </aside>

      <section className="workspace" id="workspace">
        <header className="topbar">
          <div className="title-group">
            <span className="kicker">AGRICULTURAL INTELLIGENCE / EXPERIMENT 01</span>
            <h1>Municipal crop analysis</h1>
          </div>
          <div className={`model-chip ${connection}`}>
            <span className="status-dot" />
            <div>
              <small>LOCAL INFERENCE</small>
              <strong title={modelLabel}>{modelLabel}</strong>
            </div>
            <button
              type="button"
              onClick={() => void checkModel()}
              aria-label="Check model connection"
              disabled={connection === "checking"}
            >
              <RefreshIcon />
            </button>
          </div>
        </header>

        <section className="hero-band">
          <div>
            <span className="section-label">SIMPLE HARNESS · SEQUENTIAL LOOP</span>
            <h2>
              Trust the model.
              <br />
              Observe the drift.
            </h2>
            <p>
              The baseline runs 10 agent roles sequentially with broad prompts, unstructured memory, and
              direct visual synthesis.
            </p>
          </div>
          <div className="hero-index" aria-label="Experiment condition A">
            <span>A</span>
            <small>OF 2 CONDITIONS</small>
          </div>
        </section>

        <section className="metric-grid" aria-label="Harness summary">
          <article>
            <small>TOPOLOGY</small>
            <strong>Sequential</strong>
            <span>Linear pipeline</span>
          </article>
          <article>
            <small>MODEL ROLES</small>
            <strong>10 specialists</strong>
            <span>Sequential chain</span>
          </article>
          <article>
            <small>VALIDATION</small>
            <strong>Basic checks</strong>
            <span>No tolerance gating</span>
          </article>
          <article>
            <small>RETRY POLICY</small>
            <strong>None</strong>
            <span>Single pass forward</span>
          </article>
        </section>

        <section className="workbench">
          <article className="card prompt-card">
            <div className="card-head">
              <div>
                <span className="card-index">01</span>
                <div>
                  <small>INPUT PROMPT</small>
                  <h3>Business prompt</h3>
                </div>
              </div>
              <span className={`tag ${isCustomPrompt ? "tag-custom" : ""}`}>
                {isCustomPrompt ? "CUSTOM PROMPT" : "DEFAULT BENCHMARK"}
              </span>
            </div>

            <div className="preset-selector">
              <small>PRESET SCENARIOS:</small>
              <div className="preset-chips">
                {promptPresets.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    className={`preset-chip ${prompt === preset.prompt ? "active" : ""}`}
                    onClick={() => setPrompt(preset.prompt)}
                    title={preset.description}
                  >
                    {preset.label}
                  </button>
                ))}
                {isCustomPrompt && (
                  <button
                    type="button"
                    className="preset-chip reset-chip"
                    onClick={() => setPrompt(defaultPrompt)}
                    title="Reset to default benchmark prompt"
                  >
                    Reset
                  </button>
                )}
              </div>
            </div>

            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Enter agricultural analysis prompt..."
              disabled={["submitting", "accepted", "running"].includes(runState)}
            />
            <div className="prompt-footer">
              <small>{prompt.length} characters</small>
            </div>
            <div className="prompt-meta">
              <div>
                <small>SOURCE TABLE</small>
                <strong>SIDRA PAM 5457</strong>
                <span>IBGE municipal records</span>
              </div>
              <div>
                <small>COMPARISON</small>
                <strong>2019 vs 2024</strong>
                <span>Pre vs post baseline</span>
              </div>
              <div>
                <small>MODEL WINDOW</small>
                <strong>
                  {modelStatus?.contextLength
                    ? `${modelStatus.contextLength.toLocaleString("en-US")} tokens`
                    : "65K configured"}
                </strong>
                <span>{modelStatus?.quantization ?? "Pending metadata"}</span>
              </div>
            </div>
            <div className="action-row">
              <p>
                <span className={`status-dot ${connection}`} />
                {connection === "connected"
                  ? "Model endpoint verified. Simple harness run is enabled."
                  : "Connect the model server to enable a benchmark run."}
              </p>
              <button className="primary-action" type="button" disabled={!canRun} onClick={runHarness}>
                {runState === "submitting" ? "Launching run…" : "Start simple run"}
                <ArrowIcon />
              </button>
            </div>
          </article>

          <article className="card pipeline-card" id="pipeline">
            <div className="card-head">
              <div>
                <span className="card-index">02</span>
                <div>
                  <small>EXECUTION PIPELINE</small>
                  <h3>Sequential 10-Stage Pipeline</h3>
                </div>
              </div>
              <span className="tag">LINEAR CHAIN</span>
            </div>
            <div className="simple-pipeline">
              {pipeline.map((step) => {
                const isCurrent = latestNode === step.nodeId;
                const hasRun = runEvents.some((e) => e.node === step.nodeId);
                return (
                  <div
                    key={step.id}
                    className={`pipeline-step ${isCurrent ? "current" : ""} ${hasRun ? "completed" : ""}`}
                  >
                    <span className="step-num">{step.id}</span>
                    <div className="step-body">
                      <div className="step-title-row">
                        <strong>{step.name}</strong>
                        <small className="step-owner">{step.owner}</small>
                      </div>
                      <p>{step.detail}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </article>
        </section>

        {/* 03 · Agent System Messages & Prompts */}
        <section className="agent-config-card" id="agents">
          <div className="card-head">
            <div>
              <span className="card-index">03</span>
              <div>
                <small>ROLE ORCHESTRATION</small>
                <h3>Agent System Messages & Prompts (10 Roles)</h3>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <span className={`tag ${customAgentsCount > 0 ? "tag-custom" : ""}`}>
                {customAgentsCount > 0
                  ? `${customAgentsCount} ROLE${customAgentsCount > 1 ? "S" : ""} MODIFIED`
                  : "ALL DEFAULT PROMPTS"}
              </span>
              {customAgentsCount > 0 && (
                <button
                  type="button"
                  className="preset-chip reset-chip"
                  onClick={handleResetAllAgentPrompts}
                  title="Reset all system messages to defaults"
                  style={{ padding: "3px 8px", fontSize: "8px" }}
                >
                  Reset All
                </button>
              )}
            </div>
          </div>
          <p style={{ fontSize: "11.5px", color: "var(--muted)", marginTop: "6px", marginBottom: "12px" }}>
            Customize the system message for each specialist agent. Custom prompts apply to subsequent runs
            in-memory and are embedded into the resulting HTML dashboard.
          </p>

          <div className="agent-config-grid">
            {defaultAgents.map((agent) => {
              const currentSystem = getAgentSystemPrompt(agent.id);
              const isModified = currentSystem !== agent.system;
              return (
                <div key={agent.id} className={`agent-prompt-box ${isModified ? "customized" : ""}`}>
                  <div className="agent-prompt-header">
                    <div>
                      <strong>
                        {agent.index} · {agent.role}
                      </strong>
                      <small style={{ display: "block" }}>id: {agent.id}</small>
                    </div>
                    <span className={`tag ${isModified ? "tag-custom" : ""}`} style={{ fontSize: "6.5px" }}>
                      {isModified ? "CUSTOMIZED" : "DEFAULT"}
                    </span>
                  </div>
                  <textarea
                    className="agent-prompt-textarea"
                    value={currentSystem}
                    onChange={(e) => handleAgentPromptChange(agent.id, e.target.value)}
                    placeholder={`System message for ${agent.role}...`}
                    disabled={["submitting", "accepted", "running"].includes(runState)}
                  />
                  <div className="agent-prompt-footer">
                    <small style={{ fontSize: "8px", color: "var(--muted)" }}>
                      {currentSystem.length} chars · Tools: {agent.tools.join(", ")}
                    </small>
                    {isModified && (
                      <button
                        type="button"
                        className="reset-btn"
                        onClick={() => handleResetAgentPrompt(agent.id)}
                      >
                        Reset
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* 04 · Real-Time Inter-Agent Message Stream */}
        <section className="card message-stream-card" id="inter-agent-feed">
          <div className="card-head">
            <div>
              <span className="card-index">04</span>
              <div>
                <small>REAL-TIME COMMUNICATION</small>
                <h3>Live Inter-Agent Message Stream ({interAgentMessages.length} Transfers)</h3>
              </div>
            </div>
            <span className="tag tag-custom">LIVE DIALOGUE & TRANSFERS</span>
          </div>

          <div className="message-stream-container">
            {interAgentMessages.length === 0 ? (
              <div className="stream-empty">
                <p>
                  No inter-agent messages yet. Start a benchmark run to watch agents exchange metric contracts,
                  sandbox results, review verdicts, and approvals in real time.
                </p>
              </div>
            ) : (
              <div className="message-list">
                {interAgentMessages.map((msg, index) => (
                  <article className={`message-item verdict-${msg.verdict.toLowerCase()}`} key={index}>
                    <div className="message-meta">
                      <span className="msg-seq">#{index + 1}</span>
                      <span className="msg-route">
                        <strong>{msg.sender.replace("_", " ")}</strong> ➔{" "}
                        <strong>{msg.receiver.replace("_", " ")}</strong>
                      </span>
                      <span className={`badge-verdict verdict-badge-${msg.verdict.toLowerCase()}`}>
                        {msg.verdict}
                      </span>
                      <span className="msg-time">{msg.timestamp?.split("T")[1]?.slice(0, 8) || ""}</span>
                    </div>
                    <p className="msg-summary">{msg.summary}</p>
                    {msg.payload && Object.keys(msg.payload).length > 0 && (
                      <details className="msg-payload-details">
                        <summary>Inspect Transferred Payload</summary>
                        <pre>
                          <code>{JSON.stringify(msg.payload, null, 2)}</code>
                        </pre>
                      </details>
                    )}
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* 05 · Evidence & Validation Ledger */}
        <section className="evidence-grid" id="evidence">
          <article className={`card run-card ${runState}`}>
            <div className="mini-head">
              <div>
                <span className="pulse-mark" />
                <div>
                  <small>RUN CONTROL</small>
                  <h3>Execution ledger</h3>
                </div>
              </div>
              <span>{runState.toUpperCase()}</span>
            </div>
            <p className="run-message" aria-live="polite">
              {runMessage}
            </p>
            <div className="trace-list">
              <div>
                <span>RUN ID</span>
                <strong>{runId ?? "Not started"}</strong>
              </div>
              <div>
                <span>EVENTS</span>
                <strong>{runEvents.length} stage events</strong>
              </div>
            </div>
            {runId && (
              <div
                style={{
                  marginTop: "1.25rem",
                  paddingTop: "1rem",
                  borderTop: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                <a
                  href={`/api/run-artifact?run_id=${runId}&file=dashboard.html`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="primary-action"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    textDecoration: "none",
                    fontSize: "0.85rem",
                    padding: "0.5rem 1rem",
                    borderRadius: "6px",
                    width: "100%",
                    justifyContent: "center",
                  }}
                >
                  Open Interactive HTML Dashboard <ArrowIcon />
                </a>
              </div>
            )}
          </article>

          <article className="card data-card">
            <div className="mini-head">
              <div>
                <span className="dataset-mark">DB</span>
                <div>
                  <small>FIXED EVIDENCE BASE</small>
                  <h3>Dataset contract</h3>
                </div>
              </div>
              <span>PUBLIC DATA</span>
            </div>
            <div className="data-name">
              <strong>IBGE SIDRA · PAM 5457</strong>
              <span>Municipal Agricultural Production</span>
            </div>
            <div className="data-specs">
              <div>
                <small>PERIOD</small>
                <strong>2019–2024</strong>
              </div>
              <div>
                <small>ENGINE</small>
                <strong>DuckDB</strong>
              </div>
              <div>
                <small>CROPS</small>
                <strong>7 selected</strong>
              </div>
            </div>
            <p>Evidence records are merged without strict cryptographic tolerances or sandboxed isolation.</p>
          </article>
        </section>

        <footer className="page-footer">
          <span>MAE / HARNESS ENGINEERING CASE STUDY</span>
          <span>Simple condition · baseline interface</span>
        </footer>
      </section>
    </main>
  );
}
