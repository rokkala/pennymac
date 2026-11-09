import React, { useState } from "react";
import { api, DEMO } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Loading, Tier, ago, human, Modal, Field, useDialog, PageHeader } from "../ui.jsx";

const EDITABLE = [
  { key: "t1_min_confidence", label: "T1 auto-apply: minimum confidence", type: "number", step: 0.01, min: 0.9, max: 1, hint: "Never below 0.90 (enforced on the server)." },
  { key: "t2_min_confidence", label: "T2 suggest: minimum confidence", type: "number", step: 0.01, min: 0.5, max: 0.99 },
  { key: "qa_sample_pct", label: "QA sample of auto-applied fixes (%)", type: "number", step: 1, min: 0, max: 100 },
  { key: "rollback_window_minutes", label: "Rollback window (minutes)", type: "number", step: 5, min: 0, max: 1440 },
  { key: "t1_max_override_rate_pct", label: "Auto-suspend T1 above override rate (%)", type: "number", step: 0.5, min: 0, max: 50 },
  { key: "t1_min_sample", label: "Minimum T1 fixes before auto-suspend judges", type: "number", step: 10, min: 0, max: 10000 },
  { key: "format_fix_downgrades_medium", label: "Formatting fixes on medium-risk fields count as low risk", type: "bool" },
];

function PolicyModal({ policy, persona, onClose, onDone }) {
  const [v, setV] = useState(() => Object.fromEntries(EDITABLE.map((e) => [e.key, policy[e.key]])));
  const [requester, setRequester] = useState("");
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const changes = Object.fromEntries(EDITABLE.filter((e) => v[e.key] !== policy[e.key]).map((e) => [e.key, v[e.key]]));
  const n = Object.keys(changes).length;
  const allowPolicy = canCap(persona, "editPolicy");
  const go = async () => {
    setBusy(true);
    const r = await act(() => api("/api/policy", { method: "PUT", body: { changes, requested_by: requester } }), "Policy updated. New routing applies to the next exceptions triaged.");
    setBusy(false);
    if (r) onDone();
  };
  return (
    <Modal title="Change routing policy" sub="Two people: the requester proposes, a Compliance approver applies it. Every change is audited." size="md" onClose={onClose} busy={busy}
      footer={<><span className="lead faint">{n ? `${n} change(s)` : "No changes"}</span><button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        {allowPolicy && <button className="btn primary" disabled={!n || !requester.trim() || busy} onClick={go}>Approve and apply</button>}</>}>
      {!allowPolicy && <div className="callout t4" style={{ fontSize: ".84rem" }}>Only Compliance can apply policy changes. You can prepare the values, then hand over to a Compliance approver.</div>}
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {EDITABLE.map((e) => e.type === "bool" ? (
          <label key={e.key} className="row" style={{ gridColumn: "1 / -1", gap: 8, fontSize: ".86rem" }}><input type="checkbox" checked={!!v[e.key]} onChange={(x) => setV({ ...v, [e.key]: x.target.checked })} />{e.label}
            {changes[e.key] !== undefined && <span className="pill warn">changed</span>}</label>
        ) : (
          <Field key={e.key} id={`pol-${e.key}`} label={<>{e.label}{changes[e.key] !== undefined && <span className="pill warn" style={{ marginLeft: 6 }}>was {String(policy[e.key])}</span>}</>} hint={e.hint}>
            <input id={`pol-${e.key}`} className="input num" type="number" step={e.step} min={e.min} max={e.max} value={v[e.key] ?? ""} onChange={(x) => setV({ ...v, [e.key]: x.target.value === "" ? "" : +x.target.value })} /></Field>))}
      </div>
      <Field id="pol-req" label="Requested by (must not be you)" hint={`Approver: ${persona.id}`}><input id="pol-req" className="input" value={requester} onChange={(e) => setRequester(e.target.value)} placeholder="e.g. priya.analyst" /></Field>
    </Modal>
  );
}

function AuditModal({ a, onClose, nav }) {
  return (
    <Modal title={<span className="mono">{a.action}</span>} sub={`${a.actor} · ${new Date(a.ts.endsWith("Z") ? a.ts : a.ts + "Z").toLocaleString()} · ${human(a.entity_type)} ${a.entity_id}`} size="md" onClose={onClose} nav={nav}>
      <dl className="kv"><dt>Actor</dt><dd>{a.actor}</dd><dt>Action</dt><dd className="mono">{a.action}</dd><dt>Entity</dt><dd className="mono">{human(a.entity_type)} {a.entity_id}</dd><dt>When</dt><dd>{ago(a.ts)}</dd>
        {a.hash && <><dt>Chain hash</dt><dd className="mono faint" style={{ fontSize: ".74rem", overflowWrap: "anywhere" }}>{a.hash}</dd></>}</dl>
      <pre className="code" style={{ maxHeight: 360, overflow: "auto" }}>{JSON.stringify(a.detail, null, 2)}</pre>
    </Modal>
  );
}

const ROWS = [
  { t: "T1", conf: (p) => `≥ ${p.t1_min_confidence}`, risk: "Low (typos, codes, formatting)", route: "AI applies, audited, sampled QA", control: (p) => `Override rate < ${p.t1_max_override_rate_pct}%; rollback window ${p.rollback_window_minutes} min; ${p.qa_sample_pct}% QA sample` },
  { t: "T2", conf: (p) => `${p.t2_min_confidence} – ${p.t1_min_confidence}`, risk: "Medium (addresses, non-regulated)", route: "Single reviewer; AI pre-fills", control: () => "Rationale and top-3 precedents shown" },
  { t: "T3", conf: (p) => `< ${p.t2_min_confidence}`, risk: "Any", route: "Standard review queue; hints only", control: () => "Full manual edit, AI optional" },
  { t: "T4", conf: () => "Any", risk: "High (rate, term, FICO, DTI, HMDA, identity)", route: "Maker-checker, two distinct users", control: () => "No AI auto-apply, ever" },
  { t: "T5", conf: () => "Any", risk: "Critical (fraud, OFAC hit)", route: "Halt loan; alert Compliance", control: () => "Investigation stays with Compliance" },
];

function DemoSetupModal({ onClose }) {
  const [scale, setScale] = useState("compact");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const act = useAction();
  const [wipe, setWipe] = useState(false);
  const run = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api("/api/demo/setup", { method: "POST", body: { force: wipe, scale } });
      await act(async () => r, `Demo loaded (${r.scale}, ${r.vendors} vendors, ${r.batches} batches in ${r.seconds}s)`);
      window.location.reload();
    } catch (e) {
      const msg = String(e.message || e);
      if (/already exists|demo_data_exists/i.test(msg)) {
        setErr("Data already exists. Check “Wipe existing data…” then load again.");
      } else {
        setErr(msg);
      }
      setBusy(false);
    }
  };
  return (
    <Modal title="Load demo scenario" sub="Builds the demo-kit vendors, feeds, exceptions and schedules into this environment. Local / demo mode only."
      size="md" onClose={onClose} busy={busy}
      footer={<>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className={`btn ${wipe ? "danger" : "primary"}`} disabled={busy} onClick={run}>
          {wipe ? "Wipe and load" : `Load ${scale}`}
        </button>
      </>}>
      <p className="muted" style={{ fontSize: ".86rem" }}>Compact is for daily practice (~200 rows/feed). Full matches the sales talk track (~3k rows/feed, slower).</p>
      <Field id="demo-scale" label="Scale">
        <select id="demo-scale" className="input" value={scale} onChange={(e) => setScale(e.target.value)} disabled={busy}>
          <option value="compact">Compact (default)</option>
          <option value="full">Full (sales demo)</option>
        </select>
      </Field>
      <label className="row" style={{ gap: 8, fontSize: ".86rem", marginTop: 12 }}>
        <input type="checkbox" checked={wipe} onChange={(e) => setWipe(e.target.checked)} disabled={busy} />
        Wipe existing data and rebuild (required if this environment already has sources)
      </label>
      {err && <div className="callout t4" style={{ marginTop: 12, fontSize: ".84rem" }}>{err}</div>}
    </Modal>
  );
}

export default function Governance({ persona }) {
  const pol = useApi("/api/policy");
  const aud = useApi("/api/audit?limit=200");
  const cfg = useApi("/api/config");
  const [edit, setEdit] = useState(false);
  const [sel, setSel] = useState(null);
  const [demoModal, setDemoModal] = useState(false);
  const [dialog, ask] = useDialog();
  const act = useAction();
  if (!pol.data) return <Loading error={pol.error} />;
  const p = pol.data.policy;
  const items = aud.data?.items || [];
  const showDemo = !DEMO && cfg.data?.demo && cfg.data?.demo_setup?.available && canCap(persona, "demoSetup");
  const canPolicy = canCap(persona, "editPolicy");
  const verify = async () => {
    const r = await act(() => api("/api/audit/verify"));
    if (r) ask({ kind: "confirm", title: r.valid ? "Audit chain verified" : "Audit chain BROKEN", confirmLabel: "OK", danger: !r.valid, onConfirm: () => true,
      body: r.valid ? <span>All {r.entries} entries hash-chain correctly: nothing has been altered or removed.</span> : <span>{r.broken_at_id ? `Entry ${r.broken_at_id} (${r.action}) does not match its hash.` : r.reason} Escalate to Compliance and Security.</span> });
  };
  const t1 = pol.data.effective;
  return (
    <>
      <PageHeader
        eyebrow="Govern"
        title="Policy"
        sub="Who may auto-apply a fix, and the audit of every change."
        primary={showDemo ? <button type="button" className="btn" onClick={() => setDemoModal(true)}>Load demo scenario…</button> : null}
      />
      <Panel title="Confidence × risk routing" sub="The hard gate. Risk tier wins over confidence." pad={false}
        actions={<>{t1 && <span className={`pill ${t1.t1_effective ? "pass" : "fail"}`}>{t1.t1_effective ? "T1 auto-apply on" : t1.t1_auto_suspended ? "T1 auto-suspended" : "T1 off"}</span>}
          {canPolicy && p.t1_enabled !== false && <button className="btn sm danger" onClick={() => ask({ kind: "reason", title: "Turn off AI auto-apply (T1)", danger: true, confirmLabel: "Turn off T1",
            help: "Kill switch. Every fix that would have been auto-applied goes to a reviewer instead. Takes effect immediately for running batches. Compliance; one person may switch it off (the safe direction).",
            presets: ["Override rate rising; pausing pending model review"], onSubmit: (reason) => act(() => api("/api/policy", { method: "PUT", body: { changes: { t1_enabled: false }, requested_by: persona.id, reason } }), "T1 auto-apply is off").then((r) => { if (r) pol.reload(); return r; }) })}>Kill switch…</button>}
          <button className="btn sm" onClick={() => setEdit(true)}>Change thresholds…</button></>}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Tier</th><th>Confidence</th><th>Loan / field risk</th><th>Routing</th><th>BFSI control</th></tr></thead>
          <tbody>{ROWS.map((r) => <tr key={r.t}><td><Tier t={r.t} /></td><td className="mono">{r.conf(p)}</td><td>{r.risk}</td><td>{r.route}</td><td className="muted">{r.control(p)}</td></tr>)}</tbody></table></div>
        <div className="panel-b faint" style={{ fontSize: ".8rem", borderTop: "1px solid var(--line)" }}>Regulatory references: SR 11-7 (model risk) · ECOA / Reg B · SOX audit trail · GLBA (PII) · HMDA reporting accuracy. Pure formatting or code-lookup fixes on medium-risk fields count as low risk: {String(p.format_fix_downgrades_medium)}.</div>
      </Panel>
      <Panel title="Audit trail" sub="Most recent first · hash-chained · open an entry for the full record" pad={false} actions={canCap(persona, "readAudit") ? <button className="btn sm" onClick={verify}>Verify chain</button> : null}>
        {!aud.data ? <Loading /> : <div className="tbl-wrap" style={{ maxHeight: 560 }}><table className="tbl"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
          <tbody>{items.map((a, i) => <tr key={a.id + a.ts} className="click" onClick={() => setSel(i)}><td className="faint">{ago(a.ts)}</td><td>{a.actor}</td><td className="mono">{a.action}</td><td className="mono">{human(a.entity_type)} {a.entity_id}</td>
            <td className="mono faint" style={{ maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{JSON.stringify(a.detail)}</td></tr>)}</tbody></table></div>}
      </Panel>
      {edit && <PolicyModal policy={p} persona={persona} onClose={() => setEdit(false)} onDone={() => { setEdit(false); pol.reload(); aud.reload(); }} />}
      {sel !== null && items[sel] && <AuditModal a={items[sel]} onClose={() => setSel(null)}
        nav={{ label: `${sel + 1} of ${items.length}`, onPrev: sel > 0 ? () => setSel(sel - 1) : null, onNext: sel < items.length - 1 ? () => setSel(sel + 1) : null }} />}
      {demoModal && <DemoSetupModal onClose={() => setDemoModal(false)} />}
      {dialog}
    </>
  );
}
