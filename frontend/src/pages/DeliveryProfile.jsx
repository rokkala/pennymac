import React, { useState } from "react";
import { api } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, Loading, human, Modal, ActionBar, EmptyState } from "../ui.jsx";

const LT = {
  full: "Full boarding tape: every file is a complete set of new loans.",
  incremental: "Incremental changes: rows add, update or close loans already in SSE. Sparse rows (loan number plus changed fields) are fine.",
  snapshot: "Full snapshot: each file is the vendor's whole current portfolio. The platform works out adds, updates, unchanged loans, and loans that disappeared.",
};

const clone = (o) => JSON.parse(JSON.stringify(o || {}));

const ACTION_TXT = { column: "an action column", filename: "the file name", upsert: "nothing: update if the loan is in SSE, else add" };

/** Read-only description of a delivery profile. */
function Summary({ p }) {
  return (
    <dl className="kv">
      <dt>Files are</dt><dd><b>{p.load_type === "full" ? "Full boarding tapes" : p.load_type === "incremental" ? "Incremental change files" : "Full portfolio snapshots"}</b></dd>
      {p.load_type === "incremental" && <>
        <dt>Row action from</dt><dd>{ACTION_TXT[p.action?.mode] || "—"}{p.action?.mode === "column" && p.action.column && <> <span className="mono">{p.action.column}</span></>}</dd>
        {p.action?.mode === "column" && <><dt>Codes</dt><dd className="row" style={{ gap: 4 }}>{Object.entries(p.action.values || {}).map(([c, a]) => <span key={c} className="chip">{c} → {a}</span>)}</dd></>}
        {p.action?.mode === "filename" && <><dt>File patterns</dt><dd className="row" style={{ gap: 4 }}>{Object.entries(p.action.filename_patterns || {}).filter(([, v]) => v).map(([k, v]) => <span key={k} className="chip">{k}: {v}</span>)}</dd></>}
        <dt>Blank cell</dt><dd>{p.blank_means === "clear" ? "clears the field" : <>no change{p.clear_token ? <> · <span className="mono">{p.clear_token}</span> clears</> : null}</>}</dd>
      </>}
      {p.load_type === "snapshot" && <><dt>Missing loans</dt><dd>{p.snapshot?.missing_action === "ignore" ? "ignored" : "close review for a person"} · truncated above {p.snapshot?.max_missing_pct ?? 5}% missing</dd></>}
      {p.load_type !== "full" && <><dt>File order</dt><dd>{p.sequence?.source === "none" ? "not sequenced" : <>{p.sequence?.kind === "date" ? "date" : "running number"} from {p.sequence?.source === "column" ? <>column <span className="mono">{p.sequence.column}</span></> : <>file name <span className="mono">{p.sequence?.pattern}</span></>}{p.sequence?.kind === "integer" && p.sequence?.strict !== false ? " · waits for gaps" : ""}</>}</dd>
        <dt>Change control</dt><dd>{(p.protected_fields || []).length} protected fields (maker-checker) · {(p.set_once_fields || []).length} set at boarding only</dd></>}
    </dl>
  );
}

const changedKeys = (a, b) => {
  const flat = (o, pre = "") => Object.entries(o || {}).flatMap(([k, v]) => (v && typeof v === "object" && !Array.isArray(v) ? flat(v, `${pre}${k}.`) : [[`${pre}${k}`, JSON.stringify(v)]]));
  const A = Object.fromEntries(flat(a)), B = Object.fromEntries(flat(b));
  return [...new Set([...Object.keys(A), ...Object.keys(B)])].filter((k) => A[k] !== B[k]);
};

function EditModal({ sourceId, initial, approved, cols, seenAll, onClose, onSaved }) {
  const [p, setP] = useState(() => clone(initial));
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const set = (path, v) => setP((x) => { const y = clone(x); const k = path.split("."); let o = y; k.slice(0, -1).forEach((q) => { o[q] = o[q] || {}; o = o[q]; }); o[k[k.length - 1]] = v; return y; });
  const values = Object.entries(p.action?.values || {});
  const seen = (seenAll || {})[p.action?.column] || [];
  const lab = (id, text, el, hint) => <label className="stack" style={{ gap: 4 }} htmlFor={id}><span className="eyebrow">{text}</span>{el}{hint && <span className="faint" style={{ fontSize: ".76rem" }}>{hint}</span>}</label>;
  const diff = changedKeys(approved, p);
  const save = async () => {
    setBusy(true);
    const r = await act(() => api(`/api/sources/${sourceId}/delivery`, { method: "PUT", body: p }), "Proposed. A different SME must approve it before files use it.");
    setBusy(false);
    if (r) onSaved();
  };
  return (
    <Modal title="Edit delivery profile" sub="Applies to every new file from this feed once a second person approves it (maker-checker)." size="lg" onClose={onClose} busy={busy}
      footer={<><span className="lead faint">{diff.length ? `${diff.length} setting(s) differ from the approved profile` : "No change from the approved profile"}</span>
        <button className="btn" onClick={() => setP(clone(approved))} disabled={busy}>Reset to approved</button>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn primary" disabled={busy || !diff.length} onClick={save}>{busy ? "Proposing…" : "Propose for approval"}</button></>}>
      <div className="stack">
          <div className="row" style={{ gap: 8 }}>{["full", "incremental", "snapshot"].map((k) => (
            <button key={k} className={`btn ${p.load_type === k ? "primary" : ""}`} onClick={() => set("load_type", k)}>{k === "full" ? "Full tapes" : k === "incremental" ? "Incremental changes" : "Full snapshots"}</button>))}</div>
          <span className="muted" style={{ fontSize: ".86rem" }}>{LT[p.load_type]}</span>
          {p.load_type === "incremental" && (
            <div className="stack callout">
              <b>How a row says what it is</b>
              <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                {lab("dp-mode", "Action comes from", <select id="dp-mode" className="input" value={p.action.mode} onChange={(e) => set("action.mode", e.target.value)}>
                  <option value="column">A column (action code)</option><option value="filename">The file name</option><option value="upsert">Nothing: update if in SSE, else add</option></select>)}
                {p.action.mode === "column" && lab("dp-col", "Action column", <input id="dp-col" className="input mono" list="dp-cols" value={p.action.column || ""} onChange={(e) => set("action.column", e.target.value)} />, cols.length ? "Pick from the profiled columns or type the vendor's header" : null)}
                <datalist id="dp-cols">{cols.map((c) => <option key={c} value={c} />)}</datalist>
              </div>
              {p.action.mode === "column" && (
                <div className="stack" style={{ gap: 6 }}>
                  <span className="eyebrow">Vendor code → action</span>
                  {values.map(([code, a], i) => (
                    <div key={i} className="row" style={{ gap: 6 }}>
                      <input aria-label="Vendor code" className="input mono" style={{ width: 110 }} value={code} onChange={(e) => { const v = { ...p.action.values }; delete v[code]; v[e.target.value] = a; set("action.values", v); }} />
                      <span>→</span>
                      <select aria-label="Action" className="input" value={a} onChange={(e) => set("action.values", { ...p.action.values, [code]: e.target.value })}>
                        <option value="add">add (new loan)</option><option value="update">update</option><option value="close">close (payoff / transfer out)</option></select>
                      <button className="btn sm" onClick={() => { const v = { ...p.action.values }; delete v[code]; set("action.values", v); }}>Remove</button>
                    </div>))}
                  <div className="row"><button className="btn sm" onClick={() => set("action.values", { ...p.action.values, [`CODE${values.length + 1}`]: "update" })}>+ Code</button>
                    {seen.length > 0 && <span className="faint" style={{ fontSize: ".78rem" }}>seen in sample: {seen.slice(0, 8).map((x) => <span key={String(x.value ?? x)} className="chip" style={{ marginLeft: 4 }}>{String(x.value ?? x)}</span>)}</span>}</div>
                </div>)}
              {p.action.mode === "filename" && (
                <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                  {["add", "update", "close"].map((k) => lab(`dp-fp-${k}`, `${k} files match (regex)`, <input id={`dp-fp-${k}`} className="input mono" value={p.action.filename_patterns?.[k] || ""} onChange={(e) => set(`action.filename_patterns.${k}`, e.target.value)} placeholder={k === "add" ? "_NEW_" : k === "update" ? "_CHG_" : "_PIF_"} />))}
                </div>)}
              <div className="grid" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                {lab("dp-blank", "A blank cell means", <select id="dp-blank" className="input" value={p.blank_means} onChange={(e) => set("blank_means", e.target.value)}>
                  <option value="no_change">No change (sparse rows)</option><option value="clear">Clear the field</option></select>)}
                {p.blank_means === "no_change" && lab("dp-clear", "Token that clears a field (optional)", <input id="dp-clear" className="input mono" value={p.clear_token || ""} onChange={(e) => set("clear_token", e.target.value || null)} placeholder="#CLEAR" />)}
              </div>
            </div>)}
          {p.load_type === "snapshot" && (
            <div className="stack callout">
              <b>Loans missing from a snapshot</b>
              <div className="grid" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                {lab("dp-miss", "When a boarded loan is absent", <select id="dp-miss" className="input" value={p.snapshot?.missing_action || "review"} onChange={(e) => set("snapshot.missing_action", e.target.value)}>
                  <option value="review">Raise a close review for a person</option><option value="ignore">Ignore (vendor sends partial portfolios)</option></select>)}
                {lab("dp-max", "Treat the file as truncated above (% missing)", <input id="dp-max" className="input" type="number" min={0} max={100} step="0.5" value={p.snapshot?.max_missing_pct ?? 5} onChange={(e) => set("snapshot.max_missing_pct", +e.target.value)} />,
                  "Above this, no close reviews are raised and an alert is sent, so a half-delivered file can't close half a portfolio.")}
              </div>
            </div>)}
          {p.load_type !== "full" && (
            <div className="stack callout">
              <b>File order</b>
              <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                {lab("dp-seq", "Sequence comes from", <select id="dp-seq" className="input" value={p.sequence.source} onChange={(e) => set("sequence.source", e.target.value)}>
                  <option value="filename">The file name</option><option value="column">A column (as-of date)</option><option value="none">Not sequenced</option></select>)}
                {p.sequence.source === "filename" && lab("dp-pat", "Pattern (one capture group)", <input id="dp-pat" className="input mono" value={p.sequence.pattern || ""} onChange={(e) => set("sequence.pattern", e.target.value)} placeholder="_(\d+)\.csv$" />)}
                {p.sequence.source === "column" && lab("dp-scol", "Column", <input id="dp-scol" className="input mono" list="dp-cols" value={p.sequence.column || ""} onChange={(e) => set("sequence.column", e.target.value)} />)}
                {p.sequence.source !== "none" && lab("dp-kind", "Kind", <select id="dp-kind" className="input" value={p.sequence.kind} onChange={(e) => set("sequence.kind", e.target.value)}>
                  <option value="integer">Running number</option><option value="date">Date</option></select>)}
              </div>
              {p.sequence.source !== "none" && p.sequence.kind === "integer" && <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={p.sequence.strict !== false} onChange={(e) => set("sequence.strict", e.target.checked)} />
                Wait for missing numbers before applying later files <span className="faint" style={{ fontSize: ".78rem" }}>(Ops can skip a gap with a reason)</span></label>}
              <span className="faint" style={{ fontSize: ".78rem" }}>Older files than the last applied are held as out of order, never applied silently.</span>
            </div>)}
          {p.load_type !== "full" && (
            <details>
              <summary className="eyebrow" style={{ cursor: "pointer" }}>Change control · {p.protected_fields.length} protected fields · {(p.set_once_fields || []).length} set at boarding only</summary>
              <div className="stack" style={{ gap: 6, marginTop: 8, fontSize: ".84rem" }}>
                <span>A change to a <b>protected field</b> is held for a maker and a checker (T4). Rate changes on ARM loans are routine.</span>
                <div className="row" style={{ gap: 4 }}>{p.protected_fields.map((f) => <span key={f} className="chip">{f}</span>)}</div>
                <span><b>Set at boarding only</b>: change files never overwrite these original terms.</span>
                <div className="row" style={{ gap: 4 }}>{(p.set_once_fields || []).map((f) => <span key={f} className="chip">{f}</span>)}</div>
              </div>
            </details>)}
        </div>
    </Modal>
  );
}

function ReviewModal({ d, persona, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const canDecide = canCap(persona, "approveDelivery") && persona.id !== d.proposed_by;
  const diff = changedKeys(d.delivery, d.draft);
  const decide = async (approve) => {
    setBusy(true);
    const r = await act(() => api(`/api/sources/${d.source_id}/delivery/approve`, { method: "POST", body: { approve } }), approve ? "Approved and published. New files from this feed use this profile." : "Proposal rejected");
    setBusy(false);
    if (r) onDone();
  };
  return (
    <Modal title="Review delivery profile change" sub={`Proposed by ${d.proposed_by}`} size="lg" onClose={onClose} busy={busy}
      footer={<><span className="lead faint">{canDecide ? "" : persona.id === d.proposed_by ? "You proposed this; a different SME must decide." : "SME can approve"}</span>
        {canDecide && <><button className="btn" disabled={busy} onClick={() => decide(false)}>Reject</button>
        <button className="btn primary" disabled={busy} onClick={() => decide(true)}>Approve and publish</button></>}</>}>
      <div className="row" style={{ gap: 4 }}><span className="eyebrow">Changed</span>{diff.map((k) => <span key={k} className="chip">{k}</span>)}</div>
      <div className="grid g2" style={{ alignItems: "start" }}>
        <div className="stack" style={{ gap: 6 }}><span className="eyebrow">Approved now</span><Summary p={d.delivery} /></div>
        <div className="stack" style={{ gap: 6 }}><span className="eyebrow">Proposed</span><Summary p={d.draft} /></div>
      </div>
      <div className="callout" style={{ fontSize: ".84rem" }}>Approval publishes a new signed configuration for the Glue data plane. Files already running finish on the profile they started with.</div>
    </Modal>
  );
}

export default function DeliveryProfile({ sourceId, persona, go }) {
  const d = useApi(`/api/sources/${sourceId}/delivery`, [sourceId]);
  const sch = useApi(`/api/schedules?source_id=${sourceId}`, [sourceId]);
  const [fname, setFname] = useState("");
  const [test, setTest] = useState(null);
  const [modal, setModal] = useState(null);
  const act = useAction();
  if (!d.data) return <Loading error={d.error} />;
  const pending = d.data.draft;
  const runTest = async () => setTest(await act(() => api(`/api/sources/${sourceId}/delivery/test?filename=${encodeURIComponent(fname)}&draft=${pending ? "true" : "false"}`)));
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 380px)", alignItems: "start" }}>
      <Panel title="How this vendor delivers" sub="Applies to every new file from this feed. Changes need a second approver (maker-checker)."
        actions={<ActionBar
          primary={pending && (canCap(persona, "approveDelivery") || canCap(persona, "editDelivery"))
            ? <button type="button" className="btn sm primary" onClick={() => setModal("review")}>Review proposal…</button>
            : canCap(persona, "editDelivery") ? <button type="button" className="btn sm primary" onClick={() => setModal("edit")}>Edit…</button> : null}
        >
          {pending ? <span className="pill warn">change proposed by {d.data.proposed_by}</span> : <span className="pill pass">{d.data.configured ? "approved" : "default (full tapes)"}</span>}
          {pending && canCap(persona, "editDelivery") && <button type="button" className="btn sm" onClick={() => setModal("edit")}>Edit proposal…</button>}
        </ActionBar>}>
        <div className="stack">
          <span className="muted" style={{ fontSize: ".86rem" }}>{LT[d.data.delivery.load_type]}</span>
          <Summary p={d.data.delivery} />
          {pending && <div className="callout t4" style={{ fontSize: ".86rem" }}><b>{d.data.proposed_by}</b> proposed a change ({changedKeys(d.data.delivery, pending).length} setting(s)). Use Review proposal to approve or reject.</div>}
          {d.data.last_sequence && <span className="faint" style={{ fontSize: ".8rem" }}>last applied file #{d.data.last_sequence}</span>}
        </div>
      </Panel>
      {modal === "edit" && <EditModal sourceId={sourceId} initial={pending || d.data.delivery} approved={d.data.delivery} cols={d.data.columns || []} seenAll={d.data.action_values_seen}
        onClose={() => setModal(null)} onSaved={() => { setModal(null); d.reload(); }} />}
      {modal === "review" && <ReviewModal d={{ ...d.data, source_id: sourceId }} persona={persona} onClose={() => setModal(null)} onDone={() => { setModal(null); d.reload(); }} />}
      <div className="stack">
        <Panel title="Test a file name">
          <div className="stack">
            <div className="row"><input aria-label="File name" className="input mono" style={{ flex: 1 }} value={fname} onChange={(e) => setFname(e.target.value)} placeholder="PCG_DELTA_000042.csv" />
              <button className="btn" disabled={!fname} onClick={runTest}>Test</button></div>
            {test && <div className={`callout ${test.ok ? "" : "t5"}`} style={{ fontSize: ".84rem" }}>
              {test.ok ? <>Loads as <b>{human(test.load_type)}</b>{test.file_action && <> · every row <b>{test.file_action}</b></>}{test.sequence && <> · sequence <b>#{test.sequence}</b></>}</> : test.error}
              {pending && <div className="faint" style={{ fontSize: ".76rem" }}>tested against the proposed profile</div>}</div>}
          </div>
        </Panel>
        <Panel title="Delivery schedules" actions={<button className="btn sm" onClick={() => go("deliveries")}>Open delivery schedule</button>}>
          {!sch.data ? <Loading /> : sch.data.schedules.length === 0 ? <EmptyState title="No schedule" body="Files still process on arrival, but nobody is alerted if one doesn’t show up." action={<button type="button" className="btn sm primary" onClick={() => go("deliveries")}>Open delivery schedule</button>} /> : (
            <div className="stack" style={{ gap: 6 }}>{sch.data.schedules.map((x) => (
              <div key={x.schedule_id} className="row" style={{ fontSize: ".86rem" }}><b>{x.name}</b><Status s={x.status} /><span className="faint">{x.describe} · {(x.config || x.proposed || {}).timezone}</span>
                {x.next_due_local && <span className="chip">next {x.next_due_local}</span>}</div>))}</div>)}
        </Panel>
      </div>
    </div>
  );
}
