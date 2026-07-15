"use client";

import { useMemo, useState } from "react";
import type { ActionDefinition } from "../lib/types";

function samplePayload(action: ActionDefinition) {
  const samples: Record<string, unknown> = {
    candidate_id: "candidate_demo_001",
    job_id: "job_001",
    source_id: "src_001",
    jobs: [],
    match_ids: ["match_demo_001"],
    action: "send_digest",
    target_id: "notification_demo_001",
    notification_id: "notification_demo_001",
  };
  return Object.fromEntries((action.input_schema.required ?? []).map((field) => [field, samples[field] ?? ""]));
}

export function ActionConsole({ agentId, actions }: { agentId: string; actions: ActionDefinition[] }) {
  const [actionName, setActionName] = useState(actions[0]?.name ?? "");
  const selected = useMemo(() => actions.find((action) => action.name === actionName) ?? actions[0], [actionName, actions]);
  const [payload, setPayload] = useState(() => JSON.stringify(actions[0] ? samplePayload(actions[0]) : {}, null, 2));
  const [result, setResult] = useState("选择动作并运行，结果会显示在这里。");
  const [running, setRunning] = useState(false);

  function changeAction(name: string) {
    setActionName(name);
    const next = actions.find((action) => action.name === name);
    setPayload(JSON.stringify(next ? samplePayload(next) : {}, null, 2));
    setResult("等待运行…");
  }

  async function invoke() {
    setRunning(true);
    try {
      const parsed = JSON.parse(payload) as Record<string, unknown>;
      const response = await fetch("/api/invoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agentId, action: actionName, payload: parsed }),
      });
      const data = await response.json();
      setResult(JSON.stringify(data, null, 2));
    } catch (error) {
      setResult(JSON.stringify({ error: error instanceof Error ? error.message : "Invalid request" }, null, 2));
    } finally {
      setRunning(false);
    }
  }

  if (!selected) return null;

  return (
    <div className="form-stack">
      <label className="field-label">
        动作
        <select className="select" value={actionName} onChange={(event) => changeAction(event.target.value)}>
          {actions.map((action) => <option key={action.name} value={action.name}>{action.name}</option>)}
        </select>
      </label>
      <div className="action-meta">
        <span className={`risk-badge ${selected.risk_level}`}>{selected.risk_level} risk</span>
        <span className={`status-badge ${selected.mode === "write" ? "pending" : "approved"}`}>{selected.mode}</span>
      </div>
      <label className="field-label">
        Payload JSON
        <textarea className="textarea" value={payload} onChange={(event) => setPayload(event.target.value)} spellCheck={false} />
      </label>
      <button className="button" onClick={invoke} disabled={running}>{running ? "运行中…" : "运行测试"}</button>
      <div className="result-box" aria-live="polite">{result}</div>
    </div>
  );
}
