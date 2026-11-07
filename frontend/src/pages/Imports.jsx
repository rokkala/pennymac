import React, { useEffect, useState } from "react";
import { api, setIntent, scoped } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, fmt, ago, Loading, Kpis, fmtCompact, human, Modal, ReasonModal, useDialog, Field, PageHeader, EmptyState } from "../ui.jsx";
import { Segments, Sparkline } from "../charts.jsx";

const STEP_PILL = { succeeded: "pass", failed: "fail", running: "accent" };

function PipelineSteps({ steps }) {
  if (!steps?.length) return null;
  return (
    <div className="timeline" aria-label="Pipeline steps">
      {steps.map((s, i) => (
        <div key={`${s.name}-${i}`}>
          <span className={`pill ${STEP_PILL[s.state] || ""}`}>{s.label}</span>{" "}
          <span className="faint">{s.state === "running" ? "in progress" : s.summary || s.state}</span>
        </div>
      ))}
    </div>
  );
}

export function UploadModal({ sources, onClose, onDone }) {
  const vendorsIn = [...new Map(sources.filter((s) => s.active_mapping_id).map((s) => [s.vendor_id, s.vendor_name])).entries()];
  const [ven, setVen] = useState("");
  const [src, setSrc] = useState("");
  const [lt, setLt] = useState("");
  const [file, setFile] = useState(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const curVen = ven || vendorsIn[0]?.[0];
  const live = sources.filter((s) => s.active_mapping_id && s.vendor_id === curVen);
  const feed = live.find((x) => x.source_id === (src || live[0]?.source_id));
  const submit = async () => {
    const f = new FormData();
    f.append("source_id", feed.source_id); f.append("file", file); f.append("auto_start", "true");
    if (lt) f.append("load_type", lt);
    setBusy(true);
    const r = await act(() => api("/api/upload", { method: "POST", form: f }), "File received. Boarding has started on the feed's published configuration.");
    setBusy(false);
    if (r) { onDone(r.batch_id); }
  };
  return (
    <Modal title="Upload a loan file" sub="CSV, pipe / tab TXT or Excel. Files delivered to S3 or pulled from a vendor start on their own." size="md" onClose={onClose} busy={busy}
      footer={<><span className="lead faint">{feed ? `Runs on ${feed.name}'s approved mapping${feed.active_mapping_version ? ` v${feed.active_mapping_version}` : ""}` : ""}</span>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn primary" disabled={!file || !feed || busy} onClick={submit}>{busy ? "Uploading…" : "Start boarding"}</button></>}>
      {!vendorsIn.length ? <div className="empty">No feed is live yet. Approve a feed's mapping first.</div> : <>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field id="up-ven" label="Vendor"><select id="up-ven" className="input" value={curVen || ""} onChange={(e) => { setVen(e.target.value); setSrc(""); }}>
            {vendorsIn.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></Field>
          <Field id="up-src" label="Feed"><select id="up-src" className="input" value={feed?.source_id || ""} onChange={(e) => setSrc(e.target.value)}>
            {live.map((s) => <option key={s.source_id} value={s.source_id}>{s.name} ({s.format})</option>)}</select></Field>
        </div>
        <Field id="up-lt" label="File type"><select id="up-lt" className="input" value={lt} onChange={(e) => setLt(e.target.value)}>
          <option value="">Vendor default ({human(feed?.load_type || "full")})</option>
          <option value="full">Full boarding tape</option><option value="incremental">Incremental changes (add / update / close)</option>
          <option value="snapshot">Full snapshot (compare with SSE)</option></select></Field>
        <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); setFile(e.dataTransfer.files[0]); }}>
          <b>{file ? file.name : "Drop a loan tape here"}</b>
          <span>{file ? `${fmt(file.size / 1024, 0)} KB` : "or choose a file"}</span>
          <input id="up-file" type="file" accept=".csv,.txt,.dat,.psv,.xlsx" onChange={(e) => setFile(e.target.files[0])} />
        </div></>}
    </Modal>
  );
}

function Preflight({ data, onChanged, persona, go }) {
  const pf = data.preflight;
  const [ren, setRen] = useState(() => Object.fromEntries((pf?.missing_columns || []).filter((m) => m.rename_to).map((m) => [m.column, m.rename_to.column])));
  const [fmts, setFmts] = useState(() => Object.fromEntries((pf?.type_drift || []).filter((t) => t.breaks?.length && t.suggested_date_format).map((t) => [t.column, t.suggested_date_format])));
  const [dialog, ask] = useDialog();
  const act = useAction();
  if (!pf) return null;
  const blocked = data.status === "blocked";
  const newCols = (pf.new_columns || []).map((c) => c.column);
  const canOverride = canCap(persona, "overridePreflight");
  const canResume = canCap(persona, "resumeBatch");
  const renames = Object.entries(ren).filter(([, v]) => v);
  const dateFixes = Object.entries(fmts).filter(([, v]) => v);
  const makeFix = () => ask({ kind: "confirm", title: "Create a mapping fix", confirmLabel: "Create draft version", size: "md",
    body: <>
      <span>A new <b>draft</b> mapping version is created from the approved one with these changes. Nothing boards until an SME approves it and you resume this batch.</span>
      {renames.length + dateFixes.length === 0 ? <div className="callout t4">No fix selected. The draft will be an unchanged copy you can edit in the workbench.</div> :
        <div className="tbl-wrap"><table className="tbl trace"><thead><tr><th>Column</th><th>Change</th></tr></thead><tbody>
          {renames.map(([c, v]) => <tr key={c}><td className="mono">{c}</td><td>read from <span className="mono">{v}</span></td></tr>)}
          {dateFixes.map(([c, v]) => <tr key={c}><td className="mono">{c}</td><td>parse dates as <span className="mono">{v}</span></td></tr>)}</tbody></table></div>}
    </>,
    onConfirm: async () => {
      const m = await act(() => api(`/api/batches/${data.batch_id}/remap`, { method: "POST", body: { renames: ren, date_formats: fmts } }),
        (r) => `Draft mapping v${r.version} created with the fixes. An SME must approve it, then resume this batch.`);
      if (m) { setIntent({ page: "sources", mappingId: m.mapping_id }); go("sources"); }
      return m;
    } });
  const override = () => ask({ kind: "reason", title: "Run anyway on the current mapping", danger: true, confirmLabel: "Override and run", minLength: 10,
    help: "The pre-flight found schema drift that would break rows. Overriding runs the file on the approved mapping as-is: affected rows will fail validation and be held as exceptions. SME or Compliance; audited.",
    placeholder: "e.g. Vendor confirmed the column is intentionally blank this cycle (ticket #…)",
    onSubmit: (reason) => act(() => api(`/api/batches/${data.batch_id}/override-preflight`, { method: "POST", body: { reason } }), "Override recorded. Batch is running on the current mapping.").then((r) => { onChanged(); return r; }) });
  return (
    <div className={`callout ${pf.decision === "block" ? "t5" : pf.decision === "warn" ? "t4" : ""}`}>
      <div className="row"><b>Schema pre-flight</b><Status s={pf.decision} /><span className="faint" style={{ fontSize: ".78rem" }}>mapping v{pf.mapping_version} · {pf.rows_sampled} rows checked</span></div>
      <p style={{ fontSize: ".86rem", marginTop: 4 }}>{pf.summary}</p>
      {pf.override && <p className="faint" style={{ fontSize: ".8rem" }}>Overridden by {pf.override.actor}: {pf.override.reason}</p>}
      {pf.missing_columns?.some((m) => m.sparse_ok) && <p className="faint" style={{ fontSize: ".8rem" }}>Sparse change file: {pf.missing_columns.filter((m) => m.sparse_ok).length} mapped column(s) not sent; their SSE values stay as they are.</p>}
      {pf.missing_columns?.some((m) => !m.sparse_ok) && (
        <div className="stack" style={{ gap: 4, marginTop: 8 }}><span className="eyebrow">Mapped columns missing from the file</span>
          {pf.missing_columns.filter((m) => !m.sparse_ok).map((m) => (
            <div key={m.column} className="row" style={{ fontSize: ".84rem" }}>
              <span className="mono">{m.column}</span><span className="faint">feeds {m.feeds.join(", ")}</span>{m.blocking && <span className="pill fail">blocks</span>}
              {blocked && <><span className="spacer" /><label className="faint" htmlFor={`rn-${m.column}`}>renamed to</label>
                <select id={`rn-${m.column}`} className="input" value={ren[m.column] || ""} onChange={(e) => setRen({ ...ren, [m.column]: e.target.value })}>
                  <option value="">(not in file)</option>{newCols.map((c) => <option key={c}>{c}</option>)}</select>
                {m.rename_to && <span className="faint" style={{ fontSize: ".74rem" }}>suggested · {m.rename_to.score}</span>}</>}
            </div>))}
        </div>)}
      {pf.type_drift?.length > 0 && (
        <div className="stack" style={{ gap: 4, marginTop: 8 }}><span className="eyebrow">Format changes</span>
          {pf.type_drift.map((t) => (
            <div key={t.column} className="row" style={{ fontSize: ".84rem" }}>
              <span className="mono">{t.column}</span>
              <span className="mono faint">{t.was.type}{t.was.date_format ? ` ${t.was.date_format}` : ""} → {t.now.type}{t.now.date_format ? ` ${t.now.date_format}` : ""}</span>
              {t.breaks?.length > 0 ? <span className="pill fail">{t.error_rate_pct}% of rows fail {t.breaks.join(", ")}</span> : <span className="pill">still parses</span>}
              {blocked && t.suggested_date_format && t.breaks?.length > 0 && <label className="row" style={{ gap: 4 }}><input type="checkbox" checked={!!fmts[t.column]} onChange={(e) => setFmts({ ...fmts, [t.column]: e.target.checked ? t.suggested_date_format : undefined })} />use {t.suggested_date_format}</label>}
            </div>))}
        </div>)}
      {pf.null_spikes?.length > 0 && <div style={{ fontSize: ".84rem", marginTop: 6 }}><span className="eyebrow">Suddenly blank</span> {pf.null_spikes.map((n) => <span key={n.column} className="chip" style={{ marginLeft: 6 }}>{n.column} {n.was_pct}% → {n.now_pct}%</span>)}</div>}
      {newCols.length > 0 && <div style={{ fontSize: ".84rem", marginTop: 6 }}><span className="eyebrow">New columns</span> {newCols.map((c) => <span key={c} className="chip" style={{ marginLeft: 6 }}>{c}</span>)}</div>}
      {blocked && (
        <div className="stack" style={{ gap: 8, marginTop: 10 }}>
          <div className="row">
            {canCap(persona, "editMapping") && <button className="btn primary" onClick={makeFix}>Create mapping fix (new version)</button>}
            {canResume && <button className="btn" onClick={() => act(() => api(`/api/batches/${data.batch_id}/resume`, { method: "POST" }), "Re-checking on the latest approved mapping").then(onChanged)}>Resume on approved mapping</button>}
          </div>
          {canOverride && <div className="row"><button className="btn danger" onClick={override}>Override and run…</button></div>}
        </div>)}
      {dialog}
    </div>
  );
}

function ReplayModal({ data, persona: _persona, onClose, onChanged }) {
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  useEffect(() => {
    let live = true;
    setRes(null);
    setErr(null);
    api(`/api/batches/${data.batch_id}/replay?dry_run=true`, { method: "POST" })
      .then((r) => { if (live) setRes(r); })
      .catch((e) => { if (live) setErr(e.message || String(e)); });
    return () => { live = false; };
  }, [data.batch_id]);
  const run = async () => {
    setBusy(true);
    const r = await act(() => api(`/api/batches/${data.batch_id}/replay?dry_run=false`, { method: "POST" }),
      (x) => (x.submitted ? "Replay started on Glue" : `Replayed: ${x.now_boarded} loans boarded, ${x.still_held} still held`));
    setBusy(false);
    if (r) { setRes(r); onChanged(); }
  };
  return (
    <Modal title="Replay held loans" sub={`${data.filename} · re-runs held loans on the feed's current published mapping and rules`} size="md" onClose={onClose} busy={busy}
      footer={<><button className="btn" onClick={onClose} disabled={busy}>{res && !res.dry_run ? "Done" : "Cancel"}</button>
        {res?.dry_run && <button className="btn primary" disabled={busy || !res.now_boarded} onClick={run}>
          {busy ? "Replaying…" : `Replay now: board ${fmt(res.now_boarded)}`}</button>}</>}>
      {err ? (
        <div className="callout t5" role="alert"><b>Preview failed.</b> {err}</div>
      ) : !res ? <Loading /> : res.submitted ? <div className="callout">Replay is running as a Glue job. Results appear on the batch when it finishes.</div> : (
        <div className="stack">
          <div className="kpis" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <div className="kpi"><span className="eyebrow">Replayed</span><span className="v">{fmt(res.replayed)}</span></div>
            <div className="kpi"><span className="eyebrow">{res.dry_run ? "Would board" : "Boarded"}</span><span className="v" style={{ color: "var(--pass)" }}>{fmt(res.now_boarded)}</span></div>
            <div className="kpi"><span className="eyebrow">Still held</span><span className="v">{fmt(res.still_held)}</span></div>
          </div>
          <span className="muted" style={{ fontSize: ".86rem" }}>{res.dry_run ? "Preview" : "Done"} on mapping v{res.mapping_version}. Exceptions {fmt(res.exceptions_before)} → {fmt(res.exceptions_after)}.</span>
          {Object.keys(res.by_rule_before || {}).length > 0 && <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Rule</th><th className="r">Before</th><th className="r">After</th></tr></thead>
            <tbody>{Object.entries(res.by_rule_before).map(([r, n]) => <tr key={r}><td className="mono">{r}</td><td className="r num">{fmt(n)}</td><td className="r num">{fmt(res.by_rule_after[r] || 0)}</td></tr>)}</tbody></table></div>}
        </div>)}
    </Modal>
  );
}

function Replay({ data, persona, onChanged }) {
  const [open, setOpen] = useState(false);
  const held = (data.processed || 0) - (data.loaded || 0) - (data.reconciliation?.rejected || 0);
  const eligible = data.status === "completed" && held > 0;
  const allowReplay = canCap(persona, "replay");
  if (!eligible && !(data.replays || []).length) return null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {eligible && (
        <div className="row">
          <span className="eyebrow">Held loans</span>
          <span className="faint" style={{ fontSize: ".8rem" }}>{fmt(held)} held · fixed the mapping or a rule? Re-run them without re-sending the file.</span>
          <span className="spacer" />
          {allowReplay
            ? <button className="btn sm" onClick={() => setOpen(true)}>Preview replay…</button>
            : <span className="faint" style={{ fontSize: ".78rem" }}>Ops or SME can replay</span>}
        </div>
      )}
      {(data.replays || []).length > 0 && <ReplayHistory items={data.replays} />}
      {open && allowReplay && <ReplayModal data={data} persona={persona} onClose={() => setOpen(false)} onChanged={onChanged} />}
    </div>
  );
}

const ReplayHistory = ({ items }) => (
  <div className="timeline">{items.map((r, i) => <div key={i}><b>Replay on v{r.mapping_version}</b> · {r.actor} · {fmt(r.replayed)} replayed, {fmt(r.now_boarded)} boarded · <span className="faint">{ago(r.ts)}</span></div>)}</div>
);

function SequenceGate({ data, persona, onChanged }) {
  const [mode, setMode] = useState(null);
  const act = useAction();
  const g = data.sequence_detail?.gate;
  const ov = data.sequence_detail?.override;
  if (!["waiting", "out_of_order"].includes(data.status) && !ov) return null;
  const ACTIONS = {
    skip: { label: "Skip the gap", path: "skip-gap", msg: "Gap skipped. The file is processing.",
      help: "Apply this file even though the earlier sequence number(s) never arrived. Use only when the vendor confirms they were never produced." },
    apply: { label: "Apply with dual control", path: "apply-out-of-order", msg: "Applying. Every change is held for a maker and a checker.",
      help: "This file is older than what is already applied. Every change in it is held for dual control, so nothing newer is overwritten without a person deciding." },
    discard: { label: "Discard file", path: "discard", msg: "Discarded. Files waiting behind it were released.",
      help: "Drop this file without loading anything (bad resend, superseded). Files waiting behind it are released." },
  };
  const a = mode && ACTIONS[mode];
  return (
    <div className={`callout ${data.status === "out_of_order" ? "t5" : "t4"}`}>
      <div className="row"><b>Vendor sequence</b>{data.sequence && <span className="chip">file #{data.sequence}</span>}{g?.last_applied && <span className="faint" style={{ fontSize: ".78rem" }}>last applied #{g.last_applied}</span>}</div>
      {g && ["waiting", "out_of_order"].includes(data.status) && <p style={{ fontSize: ".86rem", marginTop: 4 }}>{g.reason}</p>}
      {g?.missing && <div className="row" style={{ gap: 4, marginTop: 4 }}><span className="eyebrow">Missing</span>{g.missing.map((m) => <span key={m} className="chip">#{m}</span>)}</div>}
      {ov && <p className="faint" style={{ fontSize: ".8rem", marginTop: 4 }}>{ov.type === "skip_gap" ? "Gap skipped" : "Applied out of order"} by {ov.actor}: {ov.reason}</p>}
      {["waiting", "out_of_order"].includes(data.status) && (
        <div className="row" style={{ marginTop: 8 }}>
          {data.status === "waiting" && canCap(persona, "resumeBatch") && <button className="btn sm" onClick={() => act(() => api(`/api/batches/${data.batch_id}/resume`, { method: "POST" }), "Re-checked the sequence").then(onChanged)}>Re-check</button>}
          {data.status === "waiting" && !g?.waiting_for_batch && canCap(persona, "skipGap") && <button className="btn sm" onClick={() => setMode("skip")}>Skip gap…</button>}
          {data.status === "out_of_order" && canCap(persona, "applyOutOfOrder") && <button className="btn sm" onClick={() => setMode("apply")}>Apply with dual control…</button>}
          {canCap(persona, "discardBatch") && <button className="btn sm danger" onClick={() => setMode("discard")}>Discard…</button>}
        </div>)}
      {a && <ReasonModal title={a.label} help={a.help} confirmLabel={a.label} danger={mode === "discard"} onClose={() => setMode(null)}
        onSubmit={(reason) => act(() => api(`/api/batches/${data.batch_id}/${a.path}`, { method: "POST", body: { reason } }), a.msg).then((r) => { if (r) onChanged(); return r; })} />}
    </div>
  );
}

function ChangeSummary({ data, persona, onChanged }) {
  const cs = data.change_summary;
  const act = useAction();
  const [dialog, ask] = useDialog();
  if (!cs || data.load_type === "full") return null;
  const snap = cs.snapshot;
  const cells = [["Adds", cs.adds_applied, cs.add_rows], ["Updates", cs.updates_applied, cs.update_rows], ["Closes", cs.closes_applied, cs.close_rows], ["Unchanged", cs.unchanged_rows]];
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="eyebrow">{data.load_type === "snapshot" ? "Snapshot compared with SSE" : "Changes in this file"}</span>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        {cells.map(([l, v, rows]) => <div key={l} className="kpi"><span className="eyebrow">{l}</span><span className="v">{fmt(v || 0)}</span>{rows !== undefined && rows !== v && <span className="d">{fmt(rows || 0)} rows · {fmt((rows || 0) - (v || 0))} held</span>}</div>)}
      </div>
      <div className="row" style={{ gap: 6, fontSize: ".8rem" }}>
        {cs.conflicts > 0 && <span className="pill fail">{cs.conflicts} conflict(s) with newer SSE data</span>}
        {cs.preexisting_issues > 0 && <span className="pill" title="Rule failures already on the boarded loan, not caused by this change">{cs.preexisting_issues} pre-existing DQ issue(s) not blocking</span>}
        {cs.corrections_kept > 0 && <span className="pill pass" title="The vendor re-sent a value that a reviewer or an approved auto-fix had already corrected; the corrected SSE value was kept">{cs.corrections_kept} earlier correction(s) kept</span>}
        {cs.set_once_ignored > 0 && <span className="pill" title="Original terms are set at boarding and never changed by change files">{cs.set_once_ignored} original-term value(s) ignored</span>}
      </div>
      {cs.fields_changed && Object.keys(cs.fields_changed).length > 0 && (
        <div className="row" style={{ gap: 4, fontSize: ".8rem" }}><span className="eyebrow">Fields changed</span>
          {Object.entries(cs.fields_changed).map(([f, n]) => <span key={f} className="chip">{f} ×{fmt(n)}</span>)}</div>)}
      {snap && (
        <div className={`callout ${snap.truncation_suspected ? "t5" : ""}`} style={{ fontSize: ".84rem" }}>
          <b>{fmt(snap.missing)} of {fmt(snap.portfolio_active)} active loans are not in this snapshot ({snap.missing_pct}%).</b>{" "}
          {snap.truncation_suspected ? <>That is above the {snap.max_missing_pct}% limit, so the file looks truncated. No close reviews were raised.
            {canCap(persona, "snapshotReviews") && <div className="row" style={{ marginTop: 6 }}><button className="btn sm" onClick={() => ask({ kind: "confirm", title: "Raise close reviews", confirmLabel: `Raise ${fmt(snap.missing)} close reviews`, danger: true,
              body: <span>Only do this when the vendor has confirmed the snapshot is complete. Each of the <b>{fmt(snap.missing)}</b> missing loans becomes a close review (CHG04): a person still confirms every payoff before SSE changes.</span>,
              onConfirm: () => act(() => api(`/api/batches/${data.batch_id}/snapshot-reviews`, { method: "POST" }), (r) => `${r.reviews_raised} close reviews raised`).then((r) => { onChanged(); return r; }) })}>Vendor confirmed: raise close reviews…</button></div>}</>
            : snap.reviews_raised ? <>Each is a close review (CHG04) in Loans to fix: confirm the payoff or keep the loan active.</> : null}
        </div>)}
      {dialog}
    </div>
  );
}

function ChangeLogModal({ id, filename, onClose }) {
  const { data, error } = useApi(`/api/batches/${id}/changes?limit=100`, [id]);
  const rows = data ? [...data.held.map((h) => ({ ...h, held: true })), ...data.applied] : [];
  return (
    <Modal title="Loan changes" sub={`${filename}${data ? ` · ${fmt(data.total_applied)} applied${data.held.length ? ` · ${data.held.length} held` : ""}` : ""} · NPI masked`} size="lg" onClose={onClose}>
      {!data ? <Loading error={error} /> : !rows.length ? <div className="empty">No loan changes recorded for this file.</div> : (
        <div className="tbl-wrap"><table className="tbl trace">
          <thead><tr><th>Loan</th><th>Action</th><th>Field</th><th>Was</th><th>Now</th></tr></thead>
          <tbody>{rows.slice(0, 150).flatMap((r, i) => {
            const ch = Object.entries(r.changes || {}).filter(([, v]) => v && typeof v === "object");
            return (ch.length ? ch : [["", {}]]).map(([f, v], j) => (
              <tr key={`${i}-${j}`}>{j === 0 && <><td rowSpan={ch.length || 1} className="mono">{r.loan_number}</td>
                <td rowSpan={ch.length || 1}><span className={`pill ${r.held ? "warn" : r.action === "close" ? "fail" : "pass"}`}>{r.held ? `${human(r.action)} · held` : human(r.action)}</span></td></>}
                <td className="mono">{f}</td><td className="mono faint">{v.old ?? "—"}</td><td className="mono"><b>{v.new ?? "—"}</b></td></tr>));
          })}</tbody></table></div>)}
    </Modal>
  );
}

export function BatchModal({ id, onClose, persona, go, nav }) {
  const { data, reload } = useApi(`/api/batches/${id}`, [], { poll: 1500 });
  const act = useAction();
  const [changes, setChanges] = useState(false);
  if (!data) return <Modal title="Loading…" size="xl" onClose={onClose} nav={nav}><Loading /></Modal>;
  const r = data.reconciliation;
  const incr = data.load_type && data.load_type !== "full";
  return (
    <Modal title={<span className="row" style={{ gap: 8 }}><span className="mono">{data.filename}</span><Status s={data.status} /></span>} size="xl" onClose={onClose} nav={nav}
      sub={`${data.vendor_name && data.vendor_name !== data.source_name ? `${data.vendor_name} · ` : ""}${data.source_name} · ${data.batch_id}`} actions={<>
      {data.status === "running" && canCap(persona, "pauseBatch") && <button className="btn sm" onClick={() => act(() => api(`/api/batches/${id}/pause`, { method: "POST" }), "Pausing at the next checkpoint")}>Pause</button>}
      {data.status === "paused" && canCap(persona, "resumeBatch") && <button className="btn sm primary" onClick={() => act(() => api(`/api/batches/${id}/resume`, { method: "POST" }), "Resumed from checkpoint")}>Resume</button>}</>}>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.25fr) minmax(0, 1fr)", alignItems: "start", gap: 16 }}>
      <div className="stack">
        <PipelineSteps steps={data.pipeline?.steps} />
        <dl className="kv">
          <dt>Status</dt><dd><Status s={data.status} /></dd>
          <dt>File type</dt><dd>{human(data.load_type || "full")}{data.sequence && <span className="chip" style={{ marginLeft: 6 }}>#{data.sequence}</span>}{data.delivery_id && <span className="faint" style={{ marginLeft: 6, fontSize: ".78rem" }}>scheduled delivery</span>}</dd>
          <dt>Progress</dt><dd className="num">{fmt(data.processed)} / {fmt(data.total_rows)} rows ({data.progress_pct}%)</dd>
          <dt>Throughput</dt><dd className="num">{fmt(data.throughput_lps)} loans/s · {fmtCompact(data.projected_24h)} per 24h</dd>
          <dt>Micro-batches</dt><dd className="num">{data.micro_batches} committed (each a resumable checkpoint)</dd>
          {data.eta_seconds !== null && data.eta_seconds !== undefined && <><dt>ETA</dt><dd className="num">{data.eta_seconds}s</dd></>}
          {data.sequence_detail?.config && <><dt>Configuration</dt><dd><span className="chip">published v{data.sequence_detail.config.version}</span> <span className="mono faint" style={{ fontSize: ".74rem" }}>{data.sequence_detail.config.sha256}</span></dd></>}
          {data.error && <><dt>Error</dt><dd style={{ color: "var(--fail)" }}>{data.error}</dd></>}
        </dl>
        <ChangeSummary data={data} persona={persona} onChanged={reload} />
        <Segments total={data.total_rows} parts={[
          { label: "Passed", value: data.passed, color: "var(--pass)" }, { label: "Warn", value: data.warned, color: "var(--warn)" },
          { label: "Failed", value: data.failed, color: "var(--fail)" }]} />
        <div className="legend"><span><i style={{ background: "var(--pass)" }} />Pass {fmt(data.passed)}</span><span><i style={{ background: "var(--warn)" }} />Warn {fmt(data.warned)}</span><span><i style={{ background: "var(--fail)" }} />Fail {fmt(data.failed)}</span></div>
        {r && (
          <div className={`callout ${r.balanced ? "" : "t5"}`}>
            <b>{r.balanced ? "Reconciled" : "Reconciliation mismatch"}</b>
            <div className="num muted" style={{ fontSize: ".85rem" }}>
              Source {fmt(r.source_rows)} = {data.load_type && data.load_type !== "full" ? "applied" : "boarded"} {fmt(r.boarded)} + held in exceptions {fmt(r.held_in_exceptions)} + rejected {fmt(r.rejected)}{r.unchanged ? ` + unchanged ${fmt(r.unchanged)}` : ""} · {data.load_type && data.load_type !== "full" ? `new loans in SSE ${fmt(r.in_sse)}${r.changes_logged !== undefined ? ` · change log ${fmt(r.changes_logged)}` : ""}` : `in SSE ${fmt(r.in_sse)}`}
            </div>
          </div>
        )}
        {!incr && <Replay data={data} persona={persona} onChanged={reload} />}
        {incr && <div className="row"><button className="btn sm" onClick={() => setChanges(true)}>View loan changes{data.change_summary ? ` (${fmt((data.change_summary.adds_applied || 0) + (data.change_summary.updates_applied || 0) + (data.change_summary.closes_applied || 0))})` : ""}…</button></div>}
      </div>
      <div className="stack">
        <SequenceGate data={data} persona={persona} onChanged={reload} />
        <Preflight key={`${data.batch_id}-${data.preflight?.checked_at}`} data={data} persona={persona} go={go} onChanged={reload} />
        <div className="stack" style={{ gap: 6 }}><span className="eyebrow">Micro-batches (checkpoints)</span>
          <div className="tbl-wrap" style={{ maxHeight: 280 }}>
            <table className="tbl"><thead><tr><th>#</th><th className="r">Rows</th><th className="r">Seconds</th><th className="r">Failed</th></tr></thead>
              <tbody>{(data.micro_batch_log || data.last_micro_batches || []).slice(-30).map((m) => <tr key={m.index}><td className="num">{m.index}</td><td className="r num">{fmt(m.rows)}</td><td className="r num">{m.seconds}</td><td className="r num">{fmt(m.failed)}</td></tr>)}</tbody></table>
          </div></div>
      </div>
      </div>
      {changes && <ChangeLogModal id={id} filename={data.filename} onClose={() => setChanges(false)} />}
    </Modal>
  );
}

export default function Imports({ persona, go, vendor }) {
  const b = useApi(scoped("/api/batches"), [], { poll: 2000 });
  const s = useApi(scoped("/api/sources"));
  const [sel, setSel] = useState(null);
  const [upload, setUpload] = useState(false);
  if (!b.data || !s.data) return <Loading error={b.error || s.error} />;
  const rank = (s) => (s === "queued" || s === "running" ? 0 : s === "paused" || s === "waiting" || s === "blocked" ? 1 : s === "failed" ? 2 : 3);
  const batches = [...b.data.batches].sort((a, c) => rank(a.status) - rank(c.status));
  const idx = batches.findIndex((x) => x.batch_id === sel);
  const done = batches.filter((x) => x.status === "completed");
  const peak = Math.max(0, ...batches.map((x) => x.throughput_lps || 0));
  return (
    <>
      <PageHeader
        eyebrow="Run"
        title="File loads"
        sub="See whether today's files boarded, and open the ones that stopped."
        guideHref="#guide?path=execution&step=arrive"
        primary={canCap(persona, "upload") ? <button type="button" className="btn primary" onClick={() => setUpload(true)}>Upload file</button> : null}
      />
      <Kpis items={[
        { label: "Batches running", value: b.data.running },
        { label: "Current throughput", value: `${fmt(b.data.current_throughput_lps)}/s`, detail: `target ${b.data.target_lps}/s for 1M/24h` },
        { label: "Peak throughput", value: `${fmt(peak)}/s` },
        { label: "Completed batches", value: done.length, detail: `${fmt(done.reduce((a, x) => a + x.processed, 0))} loans` },
      ]} />
      <Panel title="Batches" sub="Select a file to see its progress, checks and actions" pad={false}>
          {!batches.length ? (
            <EmptyState
              title="No batches yet"
              body="Upload a file or wait for a vendor delivery to arrive."
              action={canCap(persona, "upload")
                ? <button type="button" className="btn primary" onClick={() => setUpload(true)}>Upload file</button>
                : <a className="btn primary" href="#guide?path=execution&step=arrive">How arrival works</a>}
            />
          ) : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>File</th><th>{vendor ? "Feed" : "Vendor · feed"}</th><th>Status</th><th style={{ minWidth: 140 }}>Outcome</th><th className="r">Rows</th><th className="r">Loans/s</th><th>Micro-batch time</th><th>Started</th></tr></thead>
            <tbody>{batches.map((x) => (
              <tr key={x.batch_id} className={`click ${sel === x.batch_id ? "sel" : ""}`} onClick={() => setSel(x.batch_id)}>
                <td className="mono">{x.filename}{x.load_type && x.load_type !== "full" && <div className="row" style={{ gap: 4, marginTop: 2 }}><span className="chip">{x.load_type === "snapshot" ? "snapshot" : "changes"}</span>{x.sequence && <span className="chip">#{x.sequence}</span>}</div>}</td><td>{vendor ? x.source_name : <>{x.vendor_name || x.source_name}{x.vendor_name && x.vendor_name !== x.source_name && <div className="faint" style={{ fontSize: ".76rem" }}>{x.source_name}</div>}</>}</td><td><span className="row" style={{ gap: 4, flexWrap: "wrap" }}><Status s={x.status} />{x.preflight?.decision === "warn" && <span className="pill warn" title={x.preflight.summary}>drift</span>}{(x.replays || []).length > 0 && <span className="pill accent">replayed</span>}{(x.pipeline?.steps || []).map((s, i) => <span key={`${s.name}-${i}`} className={`pill ${STEP_PILL[s.state] || ""}`} title={s.summary || s.state}>{s.label}</span>)}</span></td>
                <td><Segments total={x.total_rows || x.processed} parts={[{ label: "Pass", value: x.passed, color: "var(--pass)" }, { label: "Warn", value: x.warned, color: "var(--warn)" }, { label: "Fail", value: x.failed, color: "var(--fail)" }]} /></td>
                <td className="r num">{fmt(x.processed)}{x.status === "running" || x.status === "queued" ? ` / ${fmt(x.total_rows)}` : ""}</td>
                <td className="r num">{fmt(x.throughput_lps)}</td>
                <td><Sparkline values={(x.last_micro_batches || []).map((m) => m.seconds)} /></td>
                <td className="faint">{ago(x.started_at)}</td>
              </tr>))}</tbody>
          </table></div>)}
      </Panel>
      {sel && <BatchModal id={sel} persona={persona} go={go} onClose={() => setSel(null)}
        nav={{ label: idx >= 0 ? `${idx + 1} of ${batches.length}` : "", onPrev: idx > 0 ? () => setSel(batches[idx - 1].batch_id) : null, onNext: idx >= 0 && idx < batches.length - 1 ? () => setSel(batches[idx + 1].batch_id) : null }} />}
      {upload && <UploadModal sources={s.data.sources} onClose={() => setUpload(false)} onDone={(bid) => { setUpload(false); b.reload(); if (bid) setSel(bid); }} />}
    </>
  );
}
