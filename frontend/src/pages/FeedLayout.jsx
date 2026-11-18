import React, { useEffect, useMemo, useState } from "react";
import { proposeLayout, decideLayout, previewJoin } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, useDialog, Panel, Loading, ActionBar, fmt, human } from "../ui.jsx";
import {
  emptyLayout, emptyReadiness, addDetail, removeDetail, validateLayoutForm, matchRateBadge, previewTrust, joinCodeText, AGG_OPS, PAIRINGS, filesToSend, ensureColumnIds, stripClientIds,
} from "../layoutModel.js";

const clone = (o) => JSON.parse(JSON.stringify(o));
const hint = (t) => <span className="faint" style={{ fontSize: ".76rem" }}>{t}</span>;
const lab = (id, text, el, h) => <label className="stack" style={{ gap: 4 }} htmlFor={id}><span className="eyebrow">{text}</span>{el}{h && hint(h)}</label>;
const OP_TEXT = { sum: "sum", count: "count rows", min: "smallest", max: "largest", first: "first", last: "last", any: "any (true if one is)", concat_distinct: "join the different values" };
const DELIMS = [["", "Detect it"], [",", "Comma"], ["|", "Pipe"], ["\t", "Tab"], [";", "Semicolon"]];
const NORMALIZERS = [["trim", "trim spaces"], ["strip_leading_zeros", "drop leading zeros"], ["upper", "capital letters"]];
const PAIRING_TEXT = {
  business_date: "Same business date in the file name", sequence: "Same running number in the file name", filename_token: "Same token in the file name",
  window_minutes: "Arrived within a time window",
};
const changed = (a, b) => JSON.stringify(a) !== JSON.stringify(b);
const csv = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);

/** where is a JSON-logic object; keep what the person types so a half-typed value is not lost. */
function WhereInput({ value, onChange }) {
  const [text, setText] = useState(value ? JSON.stringify(value) : "");
  const [bad, setBad] = useState(false);
  return (
    <span className="stack" style={{ gap: 2, flex: 1 }}>
      <input aria-label="Only count rows where (optional)" className="input mono" value={text} placeholder='Only rows where, e.g. {"==":[{"var":"type"},"fee"]}'
        onChange={(e) => {
          const t = e.target.value; setText(t);
          if (!t.trim()) { setBad(false); onChange(undefined); return; }
          try { const v = JSON.parse(t); setBad(false); onChange(v); } catch { setBad(true); }
        }} />
      {bad && <span style={{ color: "var(--fail)", fontSize: ".74rem" }}>Not valid JSON yet; the last valid value is kept.</span>}
    </span>
  );
}

function FileCard({ f, onChange, onRemove, disabled, columnsByRole }) {
  const master = f.role === "master";
  const po = f.parse_options || {};
  const setPo = (k, v) => { const n = { ...po }; if (v === "" || v === undefined || v === null) delete n[k]; else n[k] = v; onChange({ ...f, parse_options: n }); };
  return (
    <div className="callout stack" style={{ gap: 8 }}>
      <div className="row" style={{ gap: 8 }}>
        <b className="mono">{f.role}</b>{master ? <span className="pill accent">main file</span> : <span className="pill">detail file</span>}
        {!master && !disabled && <button type="button" className="btn sm" style={{ marginLeft: "auto" }} onClick={onRemove}>Remove</button>}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)", alignItems: "end" }}>
        {lab(`fl-pat-${f.role}`, "File name pattern (regex)",
          <input id={`fl-pat-${f.role}`} className="input mono" value={f.name_pattern || ""} onChange={(e) => onChange({ ...f, name_pattern: e.target.value })} placeholder="^loans_(?P<date>\d{8})\.csv$" />,
          "A named group such as (?P<date>\\d{8}) gives the value that pairs this file with the others of the same delivery. The group name does not matter, but the values must match across the files.")}
        {!master && <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={f.required !== false} onChange={(e) => onChange({ ...f, required: e.target.checked })} />
          Required <span className="faint" style={{ fontSize: ".76rem" }}>(the set waits for it)</span></label>}
      </div>
      {master && (
        <div className="grid g2">
          {lab("fl-ent", "What one row is (optional)", <input id="fl-ent" className="input" value={f.entity || ""} onChange={(e) => onChange({ ...f, entity: e.target.value })} placeholder="e.g. loan" />)}
          {lab("fl-key", "Key column(s)", <input id="fl-key" className="input mono" list={columnsByRole?.[f.role] ? `cols-${f.role}` : undefined} value={(f.key || []).join(", ")} onChange={(e) => onChange({ ...f, key: csv(e.target.value) })} placeholder="loan_id" />,
            "The column(s) that identify one row. Separate several with commas.")}
        </div>)}
      <details>
        <summary className="eyebrow" style={{ cursor: "pointer" }}>How to read this file (optional)</summary>
        <div className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))", marginTop: 8 }}>
          {lab(`fl-del-${f.role}`, "Separator", <select id={`fl-del-${f.role}`} className="input" value={po.delimiter ?? ""} onChange={(e) => setPo("delimiter", e.target.value)}>
            {DELIMS.map(([v, t]) => <option key={t} value={v}>{t}</option>)}</select>)}
          {lab(`fl-hdr-${f.role}`, "Header row", <input id={`fl-hdr-${f.role}`} className="input" type="number" min={0} value={po.header_row ?? ""} onChange={(e) => setPo("header_row", e.target.value === "" ? "" : Number(e.target.value))} placeholder="0" />, "0 means the first line.")}
          {lab(`fl-enc-${f.role}`, "Text encoding", <input id={`fl-enc-${f.role}`} className="input mono" value={po.encoding ?? ""} onChange={(e) => setPo("encoding", e.target.value)} placeholder="utf-8-sig" />)}
        </div>
      </details>
    </div>
  );
}

function AggColumns({ cols, onChange, disabled }) {
  const set = (i, patch) => onChange(cols.map((c, j) => {
    if (j !== i) return c;
    const n = { ...c, ...patch };
    Object.keys(n).forEach((k) => { if (n[k] === undefined) delete n[k]; });
    return n;
  }));
  return (
    <div className="stack" style={{ gap: 8 }}>
      <span className="eyebrow">Summary columns (one value per main-file row)</span>
      {cols.map((c, i) => (
        <div key={c._id || i} className="callout stack" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <input aria-label="Output column name" className="input mono" style={{ width: 150 }} value={c.as || ""} onChange={(e) => set(i, { as: e.target.value })} placeholder="total_fees" />
            <span>=</span>
            <select aria-label="Operation" className="input" value={c.op || "sum"} onChange={(e) => set(i, { op: e.target.value })}>{AGG_OPS.map((o) => <option key={o} value={o}>{OP_TEXT[o]}</option>)}</select>
            {c.op !== "count" && <><span>of</span><input aria-label="Detail column" className="input mono" style={{ width: 150 }} value={c.col || ""} onChange={(e) => set(i, { col: e.target.value })} placeholder="detail column" /></>}
            {!disabled && <button type="button" className="btn sm" style={{ marginLeft: "auto" }} onClick={() => onChange(cols.filter((_, j) => j !== i))}>Remove</button>}
          </div>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}><WhereInput value={c.where} onChange={(v) => set(i, { where: v })} /></div>
          {["first", "last", "concat_distinct"].includes(c.op) && (
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <span className="faint" style={{ fontSize: ".78rem" }}>Order by (optional)</span>
              <input aria-label="Order by column" className="input mono" style={{ width: 130 }} value={c.order_by?.[0]?.col || ""} placeholder="column"
                onChange={(e) => set(i, { order_by: e.target.value ? [{ ...(c.order_by?.[0] || { type: "text" }), col: e.target.value }] : undefined })} />
              {c.order_by?.[0] && <>
                <select aria-label="Order type" className="input" value={c.order_by[0].type || "text"} onChange={(e) => set(i, { order_by: [{ ...c.order_by[0], type: e.target.value }] })}>
                  <option value="text">as text</option><option value="number">as number</option><option value="date">as date</option></select>
                <label className="row" style={{ gap: 4 }}><input type="checkbox" checked={!!c.order_by[0].desc} onChange={(e) => set(i, { order_by: [{ ...c.order_by[0], desc: e.target.checked }] })} />newest or largest first</label></>}
              {!c.order_by?.[0] && <span className="faint" style={{ fontSize: ".74rem" }}>Without it the file order decides.</span>}
            </div>)}
        </div>))}
      <div><button type="button" className="btn sm" onClick={() => onChange([...cols, { as: "", op: "sum", col: "" }])} disabled={disabled}>+ Summary column</button></div>
    </div>
  );
}

function RelationCard({ r, onChange, disabled, columnsByRole }) {
  const set = (patch) => onChange({ ...r, ...patch });
  const on = r.on || [];
  const norm = Array.isArray(r.normalize) ? r.normalize : [r.normalize].filter(Boolean);
  const sel = (id, text, key, opts, h) => lab(id, text, <select id={id} className="input" value={r[key]} onChange={(e) => set({ [key]: e.target.value })}>{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>, h);
  return (
    <div className="callout stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8 }}><b className="mono">{r.detail}</b><span className="faint">joins to</span><b className="mono">{r.to}</b></div>
      <div className="grid g2">
        {lab(`rl-mode-${r.detail}`, "How the detail rows are used", <select id={`rl-mode-${r.detail}`} className="input" value={r.mode} onChange={(e) => {
          const mode = e.target.value;
          set({ mode, cardinality: mode === "merge" ? "one" : "many", ...(mode === "aggregate" ? { aggregate: r.aggregate || { columns: [{ as: "", op: "sum", col: "" }] } } : {}) });
        }}>
          <option value="merge">Add its columns (one detail row per main row)</option>
          <option value="aggregate">Summarise several detail rows into columns</option></select>,
        "Other ways to combine files are not available yet.")}
        {sel(`rl-join-${r.detail}`, "Main rows with no detail row", "join", [["left", "Keep them (left join)"], ["inner", "Drop them (inner join)"]])}
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <span className="eyebrow">Matching columns</span>
        {on.map((p, i) => (
          <div key={i} className="row" style={{ gap: 6 }}>
            <input aria-label={`Column in ${r.to}`} className="input mono" list={columnsByRole?.[r.to] ? `cols-${r.to}` : undefined} value={p.parent || ""} onChange={(e) => set({ on: on.map((q, j) => (j === i ? { ...q, parent: e.target.value } : q)) })} placeholder={`column in ${r.to}`} />
            <span>=</span>
            <input aria-label={`Column in ${r.detail}`} className="input mono" list={columnsByRole?.[r.detail] ? `cols-${r.detail}` : undefined} value={p.detail || ""} onChange={(e) => set({ on: on.map((q, j) => (j === i ? { ...q, detail: e.target.value } : q)) })} placeholder={`column in ${r.detail}`} />
            {on.length > 1 && !disabled && <button type="button" className="btn sm" onClick={() => set({ on: on.filter((_, j) => j !== i) })}>Remove</button>}
          </div>))}
        <div><button type="button" className="btn sm" disabled={disabled} onClick={() => set({ on: [...on, { parent: "", detail: "" }] })}>+ Matching column</button></div>
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}><span className="faint" style={{ fontSize: ".78rem" }}>Tidy values before matching:</span>
          {NORMALIZERS.map(([v, t]) => <label key={v} className="row" style={{ gap: 4 }}><input type="checkbox" checked={norm.includes(v)} onChange={(e) => set({ normalize: e.target.checked ? [...norm, v] : norm.filter((x) => x !== v) })} />{t}</label>)}
          <span className="faint" style={{ fontSize: ".74rem" }}>Only used for matching; stored values keep their original form.</span></div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        {sel(`rl-orph-${r.detail}`, "A detail row has no main row", "on_orphan_detail", [["exception", "Raise a loan to fix (orphan)"], ["drop", "Drop it quietly"]])}
        {sel(`rl-miss-${r.detail}`, "A main row has no detail row", "on_missing_detail", [["allow", "Allow it"], ["exception", "Raise a loan to fix and leave it out"]])}
        {sel(`rl-dup-${r.detail}`, "The same main key appears twice", "on_duplicate_master", [["reject_all", "Reject every copy"], ["first", "Keep the first"], ["last", "Keep the last"]])}
        {lab(`rl-rate-${r.detail}`, "Smallest acceptable match rate (%)", <input id={`rl-rate-${r.detail}`} className="input" type="number" min={0} max={100} step="1" value={Math.round((Number(r.min_match_rate) || 0) * 1000) / 10}
          onChange={(e) => set({ min_match_rate: e.target.value === "" ? 0 : Number(e.target.value) / 100 })} />,
        "If fewer main rows match than this, the file is stopped before anything loads. 0 turns the check off.")}
      </div>
      {r.mode === "aggregate" && <AggColumns cols={r.aggregate?.columns || []} disabled={disabled} onChange={(columns) => set({ aggregate: { ...(r.aggregate || {}), columns } })} />}
    </div>
  );
}

function ReadinessCard({ ready, onChange, layout }) {
  const set = (patch) => onChange({ ...ready, ...patch });
  const hasRequired = layout.files.some((f) => f.role !== "master" && f.required);
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
      {lab("rd-req", "The delivery is complete when", <select id="rd-req" className="input" value={ready.require} onChange={(e) => set({ require: e.target.value })}>
        <option value="all_required">Every required file has arrived</option><option value="master_only">The main file has arrived</option></select>)}
      {lab("rd-pair", "Files belong together when", <select id="rd-pair" className="input" value={ready.pairing} onChange={(e) => set({ pairing: e.target.value })}>
        {PAIRINGS.map((p) => <option key={p} value={p}>{PAIRING_TEXT[p]}</option>)}</select>)}
      {ready.pairing === "window_minutes" && lab("rd-win", "Window (minutes)", <input id="rd-win" className="input" type="number" min={1} value={ready.window_minutes ?? ""} onChange={(e) => set({ window_minutes: e.target.value === "" ? undefined : Number(e.target.value) })} />)}
      {lab("rd-wait", "Wait for missing files (minutes)", <input id="rd-wait" className="input" type="number" min={0} value={ready.wait_timeout_minutes ?? 0} onChange={(e) => set({ wait_timeout_minutes: Number(e.target.value) })} />)}
      {lab("rd-to", "When the wait runs out", <select id="rd-to" className="input" value={ready.on_timeout} onChange={(e) => set({ on_timeout: e.target.value })}>
        <option value="alert_only">Keep waiting and alert someone</option><option value="fail">Mark the set expired</option>
        <option value="load_master_only" disabled={hasRequired}>Load the main file alone{hasRequired ? " (needs every detail file optional)" : ""}</option></select>)}
    </div>
  );
}

function CountsTable({ per }) {
  return (
    <div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>File</th><th className="r">Rows read</th><th className="r">Matched</th><th className="r">No match (orphans)</th><th className="r">Rejected</th></tr></thead>
      <tbody>{Object.entries(per || {}).map(([role, s]) => <tr key={role}><td className="mono">{role}</td><td className="r num">{fmt(s.rows_in)}</td><td className="r num">{fmt(s.matched)}</td><td className="r num">{fmt(s.orphaned)}</td><td className="r num">{fmt(s.rejected)}</td></tr>)}</tbody>
    </table></div>
  );
}

const BADGE = { ok: ["pass", "Matches well"], warn: ["warn", "Check the match"], block: ["fail", "Below the minimum"] };

/** `preview(layout, ready, files)` runs the dry run; it defaults to the feed's own preview route. `onResult(res | null)` reports every run and every reset. */
export function PreviewPanel({ sourceId, layout, ready, canEdit, preview, onResult }) {
  const roles = layout.files.map((f) => f.role).filter(Boolean);
  const [files, setFiles] = useState({});
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const toSend = filesToSend(layout, files);
  const all = roles.length > 0 && roles.every((r) => toSend[r]);
  const sig = JSON.stringify([stripClientIds(layout), ready]);
  useEffect(() => { setRes(null); onResult?.(null); }, [sig]);
  useEffect(() => { setFiles((f) => { const keep = Object.fromEntries(Object.entries(f).filter(([r]) => roles.includes(r))); return Object.keys(keep).length === Object.keys(f).length ? f : keep; }); }, [roles.join("|")]);
  const minRate = Math.max(0, ...layout.relations.map((r) => Number(r.min_match_rate) || 0));
  const run = async () => {
    setBusy(true);
    const r = await act(() => (preview || ((l, rd, f) => previewJoin(sourceId, l, rd, f)))(stripClientIds(layout), ready, toSend));
    setBusy(false);
    if (r) { setRes(r); onResult?.(r); }
  };
  return (
    <Panel title="Try it on sample files" sub="Pick one small file per role. Nothing is stored or loaded; this only shows how the rows would join.">
      <div className="stack">
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {roles.map((r) => lab(`pv-${r}`, `${r} sample file`, <input id={`pv-${r}`} type="file" className="input" disabled={!canEdit} onChange={(e) => { setFiles({ ...files, [r]: e.target.files[0] || null }); setRes(null); onResult?.(null); }} />))}
        </div>
        <div className="row"><button type="button" className="btn primary" disabled={!all || busy || !canEdit} onClick={run}>{busy ? "Joining…" : "Preview the join"}</button>
          {!all && <span className="faint" style={{ fontSize: ".8rem" }}>Choose a file for every role first.</span>}</div>
        <PreviewResult res={res} minRate={minRate} />
      </div>
    </Panel>
  );
}

/** The outcome of a join dry run: errors, match rates, counts, exception examples, joined rows. */
export function PreviewResult({ res, minRate }) {
  const trust = previewTrust(res);
  const [kind, badgeText] = res && !res.errors?.length && res.master_match_rate != null ? BADGE[matchRateBadge(res.master_match_rate, minRate)] : ["", ""];
  if (!res) return null;
  return (
    <div className="stack">
        {res?.errors?.length > 0 && <div className="callout t5"><b>The preview could not run</b><ul style={{ margin: "6px 0 0 18px" }}>{res.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
        {res && !res.errors?.length && <>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <span className={`pill ${trust.reliable ? kind : ""}`} title="Share of main-file rows that found their detail rows">{res.master_match_rate == null ? "No match rate" : `${trust.reliable ? badgeText : "Not a verdict"} · ${fmt(res.master_match_rate * 100, 1)}% of main rows matched`}</span>
            {Object.entries(res.detail_match_rate || {}).map(([r, v]) => <span key={r} className="chip">{r}: {fmt(v * 100, 1)}% of its rows matched</span>)}
            {trust.reliable && res.blocked && <span className="pill fail" title={String(res.blocked)}>This file would be stopped before loading{typeof res.blocked === "string" ? `: ${res.blocked}` : ""}</span>}
            <span className="faint" style={{ fontSize: ".78rem" }}>{fmt(res.rows_read)} rows read</span>
          </div>
          {!trust.reliable && <div className="callout t4" style={{ fontSize: ".86rem" }}>{trust.note}</div>}
          <CountsTable per={res.per_role} />
          {Object.keys(res.exception_counts || {}).length > 0 && (
            <div className="stack" style={{ gap: 4 }}><span className="eyebrow">What would become a loan to fix</span>
              {Object.entries(res.exception_counts).map(([code, n]) => <div key={code} className="row" style={{ gap: 8, fontSize: ".86rem" }}><span className="mono">{code}</span><b className="num">{fmt(n)}</b><span className="muted">{joinCodeText(code)}</span></div>)}</div>)}
          <div className="stack" style={{ gap: 4 }}><span className="eyebrow">First {Math.min(10, (res.rows || []).length)} joined rows</span>
            {(res.rows || []).length === 0 ? <div className="empty">No rows joined.</div> : (
              <div className="tbl-wrap" style={{ maxHeight: 320 }}><table className="tbl">
                <thead><tr>{res.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{res.rows.slice(0, 10).map((row, i) => <tr key={i}>{res.columns.map((c) => <td key={c} className="mono">{row[c] ?? ""}</td>)}</tr>)}</tbody></table></div>)}</div>
          {(res.exceptions || []).length > 0 && (
            <div className="stack" style={{ gap: 4 }}><span className="eyebrow">Examples of rows that would need a fix</span>
              {res.exceptions.map((x, i) => (
                <div key={i} className="callout" style={{ fontSize: ".84rem" }}>
                  <div className="row" style={{ gap: 8, flexWrap: "wrap" }}><span className="mono">{x.code}</span><span className="chip">{x.role}</span>{x.row_number != null && <span className="faint">row {fmt(x.row_number)}</span>}</div>
                  <div className="muted">{joinCodeText(x.code) || x.message}</div>
                  {x.message && joinCodeText(x.code) && <div className="faint" style={{ fontSize: ".78rem" }}>{x.message}</div>}
                </div>))}</div>)}
        </>}
    </div>
  );
}

/** Files, how the files join, and readiness. Controlled: the caller owns `layout` and `ready`. columnsByRole ({role: [column]}) feeds column suggestions. */
export function LayoutEditor({ layout, setLayout, ready, setReady, disabled, columnsByRole }) {
  const [newRole, setNewRole] = useState("");
  const [errs, setErrs] = useState([]);
  const dis = !!disabled;
  const setFile = (role, f) => setLayout((l) => ({ ...l, files: l.files.map((x) => (x.role === role ? f : x)) }));
  const setRel = (detail, r) => setLayout((l) => ensureColumnIds({ ...l, relations: l.relations.map((x) => (x.detail === detail ? r : x)) }));
  const add = () => { try { setLayout(addDetail(layout, newRole)); setNewRole(""); setErrs([]); } catch (e) { setErrs([e.message]); } };
  return (
    <>
      {Object.entries(columnsByRole || {}).map(([role, cols]) => <datalist key={role} id={`cols-${role}`}>{cols.map((c) => <option key={c} value={c} />)}</datalist>)}
      {errs.length > 0 && <div className="callout t5" style={{ fontSize: ".84rem" }}><b>Fix before adding</b><ul style={{ margin: "6px 0 0 18px" }}>{errs.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
      <Panel title="Files" sub="Each file is told apart by its name.">
        <fieldset disabled={dis} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}><div className="stack">
          {layout.files.map((f) => <FileCard key={f.role} f={f} disabled={dis} columnsByRole={columnsByRole} onChange={(n) => setFile(f.role, n)} onRemove={() => setLayout(removeDetail(layout, f.role))} />)}
          <div className="row" style={{ gap: 6 }}>
            <input aria-label="New detail file role" className="input mono" value={newRole} onChange={(e) => setNewRole(e.target.value.trim())} placeholder="role name, e.g. details" />
            <button type="button" className="btn" disabled={!newRole} onClick={add}>+ Add a detail file</button>
          </div>
        </div></fieldset>
      </Panel>
      {layout.relations.length > 0 && (
        <Panel title="How the files join" sub="Rows are matched on the columns you pick. The joined file keeps the main file's order.">
          <fieldset disabled={dis} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}><div className="stack">
            {layout.relations.map((r) => <RelationCard key={r.detail} r={r} disabled={dis} columnsByRole={columnsByRole} onChange={(n) => setRel(r.detail, n)} />)}
          </div></fieldset>
        </Panel>)}
      <Panel title="When a delivery is complete" sub="What the platform waits for before it starts the join.">
        <fieldset disabled={dis} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}><ReadinessCard ready={ready} onChange={setReady} layout={layout} /></fieldset>
      </Panel>
    </>
  );
}

function Editor({ sourceId, data, persona, reload }) {
  const baseLayout = data.draft || data.layout || emptyLayout();
  const baseReady = data.draft ? data.readiness_draft || emptyReadiness() : data.readiness || emptyReadiness();
  const [layout, setLayout] = useState(() => ensureColumnIds(baseLayout));
  const [ready, setReady] = useState(() => ({ ...emptyReadiness(), ...clone(baseReady) }));
  const [errs, setErrs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [dialog, ask] = useDialog();
  const act = useAction();
  const pending = !!data.draft;
  const canEdit = canCap(persona, "editDelivery");
  const canDecide = canCap(persona, "approveDelivery") && persona.id !== data.proposed_by;
  const dirty = changed(stripClientIds(layout), baseLayout) || changed(ready, { ...emptyReadiness(), ...baseReady });
  const problems = useMemo(() => validateLayoutForm(layout, ready), [layout, ready]);
  const propose = async () => {
    const e = validateLayoutForm(layout, ready);
    setErrs(e);
    if (e.length) return;
    setBusy(true);
    const r = await act(() => proposeLayout(sourceId, stripClientIds(layout), ready), "Proposed. A different SME must approve it before files use it.");
    setBusy(false);
    if (r) reload();
  };
  const decide = (approve) => ask({ kind: "reason", title: approve ? "Approve this layout" : "Send this layout back", confirmLabel: approve ? "Approve and publish" : "Send back",
    required: !approve, minLength: approve ? 0 : 5, label: approve ? "Note (optional)" : "What needs to change",
    help: approve ? "Approval publishes the layout. Files already running finish on the layout they started with." : "The proposal is rejected with your comment.",
    onSubmit: (comment) => act(() => decideLayout(sourceId, approve, comment), approve ? "Approved and published. New file sets use this layout." : "Proposal rejected").then((r) => { if (r) reload(); return r; }) });
  const dis = !canEdit;
  const live = !!data.configured;
  return (
    <div className="stack">
      <Panel title="How this feed's files fit together" sub="One main file plus detail files, joined into one table before anything loads. Changes need a second approver (maker-checker)."
        actions={<ActionBar
          primary={pending && canDecide ? <button type="button" className="btn sm primary" onClick={() => decide(true)}>Approve…</button>
            : canEdit ? <button type="button" className="btn sm primary" disabled={busy || !dirty} onClick={propose}>{busy ? "Proposing…" : "Propose for approval"}</button> : null}>
          {pending ? <span className="pill warn">change proposed by {data.proposed_by}</span> : <span className={`pill ${live ? "pass" : ""}`}>{live ? "approved" : "not set up"}</span>}
          {pending && canDecide && <button type="button" className="btn sm" onClick={() => decide(false)}>Reject…</button>}
        </ActionBar>}>
        <div className="stack">
          {!live && !pending && <div className="callout" style={{ fontSize: ".86rem" }}>This feed delivers one file today. Describe a main file and its detail files here, try it on small samples, then propose it. Nothing changes for the feed until a second person approves.</div>}
          {pending && <div className="callout t4" style={{ fontSize: ".86rem" }}><b>{data.proposed_by}</b> proposed this layout.{" "}
            {canDecide ? "Read it below, then approve or reject." : persona.id === data.proposed_by ? "You proposed it; a different SME must decide." : "An SME can approve it."}</div>}
          {!canEdit && <span className="faint" style={{ fontSize: ".8rem" }}>You can read this layout. Onboarding can edit it; an SME approves.</span>}
          {(errs.length > 0 || (dirty && problems.length > 0)) && <div className="callout t5" style={{ fontSize: ".84rem" }}><b>Fix before proposing</b>
            <ul style={{ margin: "6px 0 0 18px" }}>{(errs.length ? errs : problems).map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
        </div>
      </Panel>
      <LayoutEditor layout={layout} setLayout={setLayout} ready={ready} setReady={setReady} disabled={dis} />
      <PreviewPanel sourceId={sourceId} layout={layout} ready={ready} canEdit={canEdit} />
      <span className="faint" style={{ fontSize: ".78rem" }}>Mode: {human(layout.relations.map((r) => r.mode).join(", ") || "none")}. Names in the joined table: main-file columns keep their names, detail columns appear as role.column, summaries use the name you give them.</span>
      {dialog}
    </div>
  );
}

export default function FeedLayout({ sourceId, persona }) {
  const d = useApi(`/api/sources/${sourceId}/layout`, [sourceId]);
  if (!d.data) return <Loading error={d.error} />;
  return <Editor key={`${!!d.data.draft}-${d.data.proposed_by || ""}-${!!d.data.configured}`} sourceId={sourceId} data={d.data} persona={persona} reload={d.reload} />;
}
