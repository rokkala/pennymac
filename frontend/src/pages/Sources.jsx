import React, { useEffect, useMemo, useState } from "react";
import { api, takeIntent } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, Conf, Transform, Modal, Loading, Tabs, fmt, Kpis, Bar, useDialog, ActionBar, PageHeader } from "../ui.jsx";
import DeliveryProfile from "./DeliveryProfile.jsx";
import { FeedConfigChip } from "./FeedConfig.jsx";
import { VendorList, VendorWorkspace } from "./Vendors.jsx";
import { Segments } from "../charts.jsx";

const MODULES = ["LOAN", "BORROWER", "PROPERTY", "ESCROW", "INVESTOR"];

const show = (v) => (v === null || v === undefined || v === "" ? <span className="faint">(blank)</span> : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));

/** Visual, no-code transform chain editor. */
function StepBuilder({ steps, onChange, catalog, lookups }) {
  const set = (i, patch) => onChange(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i, d) => { const a = [...steps]; const [x] = a.splice(i, 1); a.splice(i + d, 0, x); onChange(a); };
  const paramsOf = (op) => (catalog.find((c) => c.op === op)?.params || []).filter((p) => p !== "map");
  return (
    <div className="stack" style={{ gap: 6 }}>
      {steps.map((st, i) => (
        <div key={i} className="step-row">
          <span className="step-n num">{i + 1}</span>
          <select className="input" aria-label={`Step ${i + 1} operation`} value={st.op} onChange={(e) => onChange(steps.map((s, j) => (j === i ? { op: e.target.value } : s)))}>
            {["cast", "text", "math", "lookup", "default", "composite"].map((g) => (
              <optgroup key={g} label={g}>{catalog.filter((c) => c.group === g).map((c) => <option key={c.op} value={c.op}>{c.op}</option>)}</optgroup>))}
          </select>
          {paramsOf(st.op).map((p) => p === "table" ? (
            <select key={p} className="input" aria-label="lookup table" value={st.table || ""} onChange={(e) => set(i, { table: e.target.value })}>
              <option value="">table…</option>{lookups.map((t) => <option key={t}>{t}</option>)}</select>
          ) : (
            <input key={p} className="input" style={{ width: 110 }} placeholder={p} aria-label={p} value={st[p] ?? ""}
              onChange={(e) => set(i, { [p]: ["factor", "divisor", "width", "length", "start", "index", "precision", "group"].includes(p) && e.target.value !== "" && !Number.isNaN(+e.target.value) ? +e.target.value : e.target.value })} />
          ))}
          <span className="spacer" />
          <button className="btn sm" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
          <button className="btn sm" aria-label="Move down" disabled={i === steps.length - 1} onClick={() => move(i, 1)}>↓</button>
          <button className="btn sm danger" aria-label="Remove step" onClick={() => onChange(steps.filter((_, j) => j !== i))}>✕</button>
        </div>))}
      <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => onChange([...steps, { op: "trim" }])}>+ Add step</button>
    </div>
  );
}

function CheckRow({ label, sub, failed, evaluated, tag, examples }) {
  const ok = failed === 0;
  return (
    <div className="check">
      {failed === null || failed === undefined ? <span className="pill">after save</span> : <span className={`pill ${ok ? "pass" : "fail"}`}>{ok ? "pass" : `${failed} fail`}</span>}
      <div className="stack" style={{ gap: 2, minWidth: 0 }}>
        <span>{label}{tag && <span className="chip" style={{ marginLeft: 6 }}>{tag}</span>}</span>
        {sub && <span className="faint" style={{ fontSize: ".76rem" }}>{sub}</span>}
        {!ok && examples?.length > 0 && <span className="mono faint" style={{ fontSize: ".74rem", overflowWrap: "anywhere" }}>e.g. {examples.slice(0, 3).map((x) => (x === "" || x === "None" || x === "null" ? "(blank)" : x)).join(" · ")}</span>}
      </div>
      <span className="faint num" style={{ fontSize: ".74rem", whiteSpace: "nowrap" }}>{fmt(evaluated)} rows</span>
    </div>
  );
}

/** Distinct source values → SSE values, with untranslated codes flagged and editable once for the whole source. */
function ValueMap({ mappingId, target, draft, onSaved }) {
  const { data, reload } = useApi(`/api/mappings/${mappingId}/fields/${target}/values`, [mappingId, target]);
  const [edits, setEdits] = useState({});
  const [preview, setPreview] = useState(null);
  const act = useAction();
  useEffect(() => { setEdits({}); setPreview(null); }, [target]);
  const d = preview || data;
  if (!d) return null;
  const vm = { ...(data?.value_map || {}), ...edits };
  const dirty = Object.keys(edits).length > 0;
  const body = (save) => ({ value_map: Object.fromEntries(Object.entries(vm).filter(([, v]) => v)), save });
  return (
    <section className="stack" style={{ gap: 8 }}>
      <div className="row"><h3>Value translation</h3><span className="spacer" />
        <span className={`pill ${d.invalid_rows ? "fail" : "pass"}`}>{d.coverage_pct}% of rows valid</span>
        <span className="faint" style={{ fontSize: ".76rem" }}>{d.distinct} distinct · {d.invalid_distinct} untranslated</span></div>
      {!d.editable && <span className="faint" style={{ fontSize: ".8rem" }}>Values are masked (PII) or too many to translate one by one.</span>}
      <div className="tbl-wrap" style={{ maxHeight: 280 }}><table className="tbl trace">
        <thead><tr><th>Source value</th><th className="r">Rows</th><th>SSE value</th><th></th></tr></thead>
        <tbody>{d.values.map((v) => {
          const key = String(v.source).trim().toLowerCase();
          return (
            <tr key={v.source}>
              <td className="mono">{show(v.source)}</td><td className="r num">{fmt(v.count)}</td>
              <td>{draft && d.editable && d.codes.length ? (
                <select className="input" aria-label={`SSE value for ${v.source}`} value={vm[key] ?? ""} onChange={(e) => { setEdits({ ...edits, [key]: e.target.value }); setPreview(null); }}>
                  <option value="">{v.output !== null && v.output !== undefined && v.output !== "" ? `${v.output} (current)` : "(no translation)"}</option>
                  {d.codes.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>) : <span className="mono">{show(v.output)}</span>}</td>
              <td>{v.valid ? <span className="pill pass">valid</span> : <span className="pill fail" title={v.problems.join("; ")}>invalid</span>}</td>
            </tr>);
        })}</tbody></table></div>
      {draft && d.editable && (
        <div className="row">
          <button className="btn sm" disabled={!dirty} onClick={async () => setPreview(await act(() => api(`/api/mappings/${mappingId}/fields/${target}/values`, { method: "POST", body: body(false) })))}>Preview</button>
          <button className="btn sm primary" disabled={!dirty} onClick={async () => { const r = await act(() => api(`/api/mappings/${mappingId}/fields/${target}/values`, { method: "POST", body: body(true) }), "Value translations saved to this mapping"); if (r) { setEdits({}); setPreview(null); reload(); onSaved(); } }}>Save translations</button>
          {Object.keys(data?.value_map || {}).length > 0 && <span className="faint" style={{ fontSize: ".76rem" }}>{Object.keys(data.value_map).length} source-specific translation(s) in this mapping</span>}
        </div>)}
    </section>
  );
}

function FieldInspector({ mappingId, field, columns, draft, catalog, lookups, onField, onClose, go, onMap, feedsOf, nav }) {
  const base = useApi(`/api/mappings/${mappingId}/fields/${field.target}/inspect`, [field.target, JSON.stringify(field.transform), (field.sources || []).join()]);
  const [editing, setEditing] = useState(false);
  const [steps, setSteps] = useState(field.transform || []);
  const [srcs, setSrcs] = useState(field.sources?.length ? field.sources : [field.source]);
  const [test, setTest] = useState(null);
  const act = useAction();
  useEffect(() => { setEditing(false); setTest(null); setSteps(field.transform || []); setSrcs(field.sources?.length ? field.sources : [field.source]); }, [field.target]);
  const d = test || base.data;
  const runTest = async () => setTest(await act(() => api(`/api/mappings/${mappingId}/fields/${field.target}/inspect`, { method: "POST", body: { sources: srcs, transform: steps } })));
  const save = async () => { await onField(field.target, { action: "override", sources: srcs, source: srcs[0], transform: steps }); setEditing(false); setTest(null); };
  return (
    <Modal title={<span className="row" style={{ gap: 8 }}><span className="mono">{field.target}</span><Status s={field.status} /></span>} size="xl" onClose={onClose} nav={editing ? null : nav}
      sub={d ? `${d.attribute.module} · ${d.attribute.dtype}${d.attribute.length ? `(${d.attribute.length})` : ""} · ${d.attribute.risk} risk${d.attribute.required ? " · required" : ""}${d.attribute.pii ? " · PII" : ""}` : ""}
      footer={draft && !editing ? <>
        <span className="lead faint">Changes save to draft v{field._version || ""}; nothing reaches Glue until the mapping is approved.</span>
        {field.manual || field.one_to_many || field.retargeted_from
          ? <button className="btn danger" onClick={() => onField(field.target, { action: "remove" })}>Remove mapping</button>
          : <button className="btn danger" disabled={field.status === "rejected"} onClick={() => onField(field.target, { action: "reject" })}>Reject</button>}
        <button className="btn primary" disabled={field.status === "accepted"} onClick={async () => { await onField(field.target, { action: "accept" }); nav?.onNext?.(); }}>{field.status === "accepted" ? "Accepted" : "Accept and next"}</button></> : null}>
      {!d ? <Loading error={base.error} /> : (
        <div className="stack" style={{ gap: 16 }}>
          <div className="row"><span className="eyebrow">Source</span><span className="mono">{(d.sources || []).join(" + ") || "—"}</span><span className="spacer" /><Conf v={field.confidence} /><Status s={field.status} /></div>
          {(d.sources || []).some((c) => feedsOf(c).length > 1) && <div className="row" style={{ fontSize: ".8rem" }}><span className="pill accent">1:N</span>
            {(d.sources || []).map((c) => <span key={c}><span className="mono">{c}</span> feeds {feedsOf(c).map((t) => <span key={t} className="chip" style={{ marginRight: 4 }}>{t}</span>)}</span>)}</div>}
          <span className="faint" style={{ fontSize: ".8rem" }}>{field.signals?.memory && field.signals.memory.approved > field.signals.memory.rejected && <span className="pill accent" style={{ marginRight: 6 }}>learned</span>}{field.rationale}</span>
          {draft && !editing && (
            <div className="row">
              <button className="btn sm" onClick={() => setEditing(true)}>Edit transformation</button>
              <button className="btn sm" onClick={() => onMap({ retargetFrom: field.target, sources: d.sources })}>Change target…</button>
              <button className="btn sm" onClick={() => onMap({ sources: d.sources })}>Also map this column to…</button>
            </div>)}

          <section className="stack" style={{ gap: 8 }}>
            <h3>Transformation rules</h3>
            {editing ? (
              <div className="stack" style={{ gap: 10 }}>
                <label className="stack" style={{ gap: 4 }} htmlFor="tb-src"><span className="eyebrow">Source column{srcs.length > 1 ? "s (N:1)" : ""}</span>
                  {srcs.map((sv, i) => (
                    <div key={i} className="row" style={{ flexWrap: "nowrap" }}>
                      <select id={i === 0 ? "tb-src" : undefined} className="input" style={{ flex: 1 }} value={sv || ""} onChange={(e) => setSrcs(srcs.map((x, j) => (j === i ? e.target.value : x)))}>{columns.map((c) => <option key={c}>{c}</option>)}</select>
                      {srcs.length > 1 && <button className="btn sm danger" onClick={() => setSrcs(srcs.filter((_, j) => j !== i))}>✕</button>}
                    </div>))}
                  <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setSrcs([...srcs, columns[0]])}>+ Add source column</button></label>
                <StepBuilder steps={steps} onChange={(x) => { setSteps(x); setTest(null); }} catalog={catalog} lookups={lookups} />
                <div className="row"><button className="btn" onClick={runTest}>Test on sample</button><button className="btn primary" onClick={save}>Save transformation</button>
                  <button className="btn sm" onClick={() => { setEditing(false); setTest(null); setSteps(field.transform || []); }}>Cancel</button></div>
                {test && <span className="callout" style={{ fontSize: ".8rem" }}>Showing results of the unsaved chain{test.demo_partial ? " on the example rows (demo)" : ` on ${test.stats.rows} sample rows`}.</span>}
              </div>
            ) : (
              <ol className="steps">{d.steps.length ? d.steps.map((st, i) => <li key={i}><span className="chip">{st.op}</span> {st.description}</li>) : <li className="faint">Direct copy, no transformation</li>}
                <li className="faint">Load into SSE column <span className="mono">{field.target}</span></li></ol>
            )}
          </section>

          <section className="stack" style={{ gap: 8 }}>
            <div className="row"><h3>Sample trace</h3><span className="spacer" /><span className="faint" style={{ fontSize: ".76rem" }}>{fmt(d.stats.rows)} rows · {d.stats.transform_errors} errors · {d.stats.blank_outputs} blank · {d.stats.distinct_outputs} distinct</span></div>
            <div className="tbl-wrap"><table className="tbl trace">
              <thead><tr><th>Source value</th>{d.steps.filter((s) => s.op !== "trim").map((s, i) => <th key={i}>{s.op}</th>)}<th>SSE value</th></tr></thead>
              <tbody>{d.examples.map((ex, i) => {
                const vis = d.steps.map((s, j) => ({ s, j })).filter(({ s }) => s.op !== "trim");
                return (
                  <tr key={i}>
                    <td className="mono">{Object.values(ex.inputs).map(show).reduce((a, b, k) => (k ? [...a, " + ", b] : [b]), [])}</td>
                    {vis.map(({ j }) => <td key={j} className="mono">{ex.error && j >= ex.steps.length ? (j === ex.steps.length ? <span style={{ color: "var(--fail)" }}>✕</span> : "") : show(ex.steps[j]?.value)}</td>)}
                    <td className="mono">{ex.error ? <span style={{ color: "var(--fail)" }} title={ex.error.message}>{ex.error.message}</span> : <b>{show(ex.output)}</b>}</td>
                  </tr>);
              })}</tbody>
            </table></div>
          </section>

          {(d.attribute.codes?.length > 0 || (field.transform || []).some((st) => st.op === "lookup")) && !editing &&
            <ValueMap mappingId={mappingId} target={field.target} draft={draft} onSaved={() => onField(null)} />}

          <section className="stack" style={{ gap: 8 }}>
            <h3>Data quality checks</h3>
            <span className="eyebrow">From the SSE schema</span>
            {d.schema_checks.map((c) => <CheckRow key={c.id} label={c.label} failed={c.failed} evaluated={c.evaluated} examples={c.examples} />)}
            <span className="eyebrow" style={{ marginTop: 6 }}>Business rules reading this field ({d.dq_rules.length})</span>
            {d.dq_rules.length === 0 && <span className="faint">No business rule reads this field yet.</span>}
            {d.dq_rules.map((r) => (
              <CheckRow key={`${r.rule_id}v${r.version}`} label={<><span className="mono">{r.rule_id}</span> {r.name}</>}
                sub={`${r.severity} · v${r.version} ${r.status}${r.primary_field !== field.target ? ` · cross-field (${r.reads_fields.join(", ")})` : ""}`}
                tag={r.regulatory_tag} failed={r.failed} evaluated={r.evaluated} examples={r.examples} />))}
            <div className="row"><button className="btn sm" onClick={() => go("rules")}>Add a DQ rule for this field</button>
              {test && <span className="faint" style={{ fontSize: ".76rem" }}>{test.demo_partial ? "Business-rule counts refresh after saving." : "Counts reflect the unsaved chain."}</span>}</div>
          </section>
        </div>)}
    </Modal>
  );
}

function DqTab({ mappingId, go }) {
  const { data, error } = useApi(`/api/mappings/${mappingId}/dq`);
  if (!data) return <Loading error={error} />;
  return (
    <Panel title="DQ rules on this source" sub={`Every rule in the registry run against ${data.rows} sample rows mapped with this configuration`} pad={false}
      actions={<button className="btn sm" onClick={() => go("rules")}>Manage rules</button>}>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Rule</th><th>Primary field</th><th>Reads</th><th>Severity</th><th>Tag</th><th>Status</th><th className="r">Failing rows</th><th style={{ minWidth: 110 }}>Fail rate</th></tr></thead>
        <tbody>{data.rules.map((r) => (
          <tr key={`${r.rule_id}v${r.version}`}>
            <td><span className="mono">{r.rule_id}</span> {r.name}</td><td className="mono">{r.primary_field}</td>
            <td>{r.unmapped_fields.length ? <span className="pill warn" title={`Not mapped: ${r.unmapped_fields.join(", ")}`}>{r.unmapped_fields.length} field(s) unmapped</span> : <span className="faint">{r.reads_fields.length} mapped</span>}</td>
            <td><span className={`pill ${r.severity === "FAIL" ? "fail" : "warn"}`}>{r.severity}</span></td><td>{r.regulatory_tag || <span className="faint">—</span>}</td>
            <td><Status s={r.status} /></td><td className="r num">{fmt(r.failed)}</td>
            <td><span className="row" style={{ gap: 6, flexWrap: "nowrap" }}><Bar pct={Math.min(100, r.fail_rate_pct * 10)} kind={r.failed ? "fail" : "pass"} /><span className="num" style={{ fontSize: ".78rem" }}>{r.fail_rate_pct}%</span></span></td>
          </tr>))}</tbody>
      </table></div>
    </Panel>
  );
}

function ProfileTab({ sourceId, feedsOf, draft, onMap, onPick }) {
  const prof = useApi(`/api/sources/${sourceId}`);
  if (!prof.data) return <Loading error={prof.error} />;
  const p = prof.data.profile;
  return (
    <Panel title="Source profile" sub={`${p.row_count_sampled} rows sampled · completeness ${p.completeness}% · validity ${p.validity}%`} pad={false}>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Column</th><th>Feeds SSE fields</th><th>Type</th><th className="r">Null %</th><th className="r">Distinct</th><th>Top patterns</th><th>Range / samples</th><th>Notes</th></tr></thead>
        <tbody>{p.columns.map((c) => (
          <tr key={c.name}><td className="mono">{c.name}</td>
            <td><span className="row" style={{ gap: 4 }}>{feedsOf(c.name).map((t) => <button key={t} className="chip" style={{ border: 0, cursor: "pointer" }} onClick={() => onPick(t)}>{t}</button>)}
              {!feedsOf(c.name).length && <span className="pill warn">unmapped</span>}
              {draft && <button className="btn sm" onClick={() => onMap(c.name)}>Map…</button>}</span></td>
            <td>{c.inferred_type}{c.date_format && <span className="faint"> {c.date_format}</span>}</td>
            <td className="r num">{c.null_pct}</td><td className="r num">{fmt(c.distinct)}</td>
            <td className="mono faint">{(c.top_patterns || []).map((x) => x[0]).join("  ")}</td>
            <td className="mono faint">{c.min_value !== null && c.min_value !== undefined ? `${fmt(c.min_value, 2)} – ${fmt(c.max_value, 2)}` : c.pii_type ? "masked" : (c.samples || []).join(", ")}</td>
            <td>{c.pii_type && <span className="pill fail" title="Values masked in UI and logs">PII · {c.pii_type}</span>} {c.notes.map((n) => <span key={n} className="pill warn">{n}</span>)}</td></tr>))}</tbody>
      </table></div>
    </Panel>
  );
}

/** Map any source column(s) to any SSE attribute (incl. 1:N), or re-point an existing mapping. */
function MapTargetModal({ mappingId, fields, columns, catalog, lookups, preset, onClose, onSaved }) {
  const schema = useApi("/api/schema/target");
  const retarget = preset?.retargetFrom;
  const [target, setTarget] = useState(preset?.target || "");
  const [q, setQ] = useState("");
  const [srcs, setSrcs] = useState(preset?.sources || [columns[0]]);
  const [steps, setSteps] = useState([]);
  const [sug, setSug] = useState(null);
  const [test, setTest] = useState(null);
  const act = useAction();
  const mappedBy = useMemo(() => Object.fromEntries(fields.filter((f) => f.status !== "rejected").map((f) => [f.target, (f.sources?.length ? f.sources : [f.source]).join(" + ")])), [fields]);
  useEffect(() => {
    if (!target || retarget || !srcs.length || srcs.some((x) => !x)) return;
    let live = true;
    api(`/api/mappings/${mappingId}/suggest`, { method: "POST", body: { sources: srcs, target } }).then((r) => { if (live) { setSug(r); setSteps(r.transform); setTest(null); } }).catch(() => {});
    return () => { live = false; };
  }, [target, srcs.join("|")]);
  const attrs = (schema.data?.attributes || []).filter((a) => !q || a.name.includes(q.toLowerCase().replace(/\s+/g, "_")) || (a.synonyms || []).some((x) => x.includes(q.toLowerCase())));
  const runTest = async () => setTest(await act(() => api(`/api/mappings/${mappingId}/fields/${target}/inspect`, { method: "POST", body: { sources: srcs, transform: steps } })));
  const save = async () => {
    const r = retarget
      ? await act(() => api(`/api/mappings/${mappingId}/fields/${retarget}/retarget`, { method: "POST", body: { new_target: target } }), `Re-pointed ${retarget} → ${target}`)
      : await act(() => api(`/api/mappings/${mappingId}/fields`, { method: "POST", body: { target, sources: srcs, transform: steps } }), `Mapped ${srcs.join(" + ")} → ${target}`);
    if (r) onSaved(target);
  };
  const feeds = sug ? Object.entries(sug.already_feeds || {}) : [];
  return (
    <Modal title={retarget ? `Change target of ${retarget}` : "Map a source column to an SSE field"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!target || (!retarget && !srcs.length)} onClick={save}>{retarget ? "Re-point mapping" : "Save mapping"}</button></>}>
      {retarget && <p className="muted">The source column and transformation steps move to the new SSE attribute. The final type cast is re-derived for the new attribute's type.</p>}
      <div className="stack" style={{ gap: 4 }}>
        <span className="eyebrow">SSE target attribute</span>
        <input id="tgt-q" className="input" placeholder="Search 109 SSE attributes (name or synonym)" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="tbl-wrap" style={{ maxHeight: 220, border: "1px solid var(--line)", borderRadius: "var(--r)" }}>
          <table className="tbl"><tbody>{attrs.map((a) => (
            <tr key={a.name} className={`click ${target === a.name ? "sel" : ""}`} onClick={() => setTarget(a.name)}>
              <td className="mono">{a.name}{a.required && <span style={{ color: "var(--fail)" }}> *</span>}</td><td className="faint">{a.module}</td><td className="faint">{a.dtype}</td>
              <td>{mappedBy[a.name] ? <span className="pill warn" title="Saving replaces this mapping">from {mappedBy[a.name]}</span> : <span className="faint" style={{ fontSize: ".78rem" }}>unmapped</span>}</td>
            </tr>))}</tbody></table>
        </div>
      </div>
      {!retarget && (
        <div className="stack" style={{ gap: 4 }}>
          <span className="eyebrow">Source column{srcs.length > 1 ? "s (N:1, joined in order)" : ""}</span>
          {srcs.map((sv, i) => (
            <div key={i} className="row" style={{ flexWrap: "nowrap" }}>
              <select className="input" style={{ flex: 1 }} aria-label={`Source column ${i + 1}`} value={sv} onChange={(e) => setSrcs(srcs.map((x, j) => (j === i ? e.target.value : x)))}>{columns.map((c) => <option key={c}>{c}</option>)}</select>
              {srcs.length > 1 && <button className="btn sm danger" onClick={() => setSrcs(srcs.filter((_, j) => j !== i))}>✕</button>}
            </div>))}
          <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setSrcs([...srcs, columns[0]])}>+ Add source column</button>
          {feeds.length > 0 && <div className="callout" style={{ fontSize: ".84rem" }}>One-to-many: {feeds.map(([c, ts]) => <span key={c}><span className="mono">{c}</span> already feeds <span className="mono">{ts.join(", ")}</span>. </span>)}Saving adds another target; the existing mapping stays.</div>}
          {sug?.replaces && <div className="callout t4" style={{ fontSize: ".84rem" }}><span className="mono">{target}</span> is currently mapped from <span className="mono">{(sug.replaces.sources || []).join(" + ")}</span>. Saving replaces it.</div>}
        </div>)}
      {!retarget && target && (
        <div className="stack" style={{ gap: 6 }}>
          <div className="row"><span className="eyebrow">Transformation steps</span><span className="spacer" />{sug?.confidence != null && <><span className="faint" style={{ fontSize: ".78rem" }}>match confidence</span><Conf v={sug.confidence} /></>}</div>
          <StepBuilder steps={steps} onChange={(x) => { setSteps(x); setTest(null); }} catalog={catalog} lookups={lookups} />
          <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={runTest}>Test on sample</button>
          {test && (
            <div className="stack" style={{ gap: 6 }}>
              <div className="tbl-wrap"><table className="tbl trace"><thead><tr><th>Source value</th><th>SSE value</th></tr></thead>
                <tbody>{test.examples.slice(0, 5).map((ex, i) => <tr key={i}><td className="mono">{Object.values(ex.inputs).map((v) => String(v ?? "")).join(" + ")}</td>
                  <td className="mono">{ex.error ? <span style={{ color: "var(--fail)" }}>{ex.error.message}</span> : <b>{show(ex.output)}</b>}</td></tr>)}</tbody></table></div>
              <div className="row">{test.schema_checks.map((c) => <span key={c.id} className={`pill ${c.failed ? "fail" : "pass"}`} title={c.label}>{c.id}{c.failed ? ` · ${c.failed} fail` : " ✓"}</span>)}</div>
            </div>)}
        </div>)}
    </Modal>
  );
}

function DiffModal({ mappingId, onClose }) {
  const { data, error } = useApi(`/api/mappings/${mappingId}/diff`);
  const label = { added: "pass", removed: "fail", changed: "warn" };
  const steps = (t) => (t || []).filter((x) => x.op !== "trim").map((x) => x.op + (x.map ? `{${Object.keys(x.map).length}}` : "") + (x.format ? `:${x.format}` : "") + (x.part ? `:${x.part}` : "")).join(" → ") || "copy";
  return (
    <Modal title={data?.against ? `Changes vs v${data.against_version}` : "Changes"} size="lg" onClose={onClose}
      sub={data?.summary ? `${data.summary.added} added · ${data.summary.changed} changed · ${data.summary.removed} removed` : ""}>
      {!data ? <Loading error={error} /> : !data.against ? <div className="empty">This is the first version of the mapping.</div> :
        data.changes.length ? <div className="tbl-wrap"><table className="tbl trace"><thead><tr><th>SSE attribute</th><th>Change</th><th>Before</th><th>After</th></tr></thead>
          <tbody>{data.changes.map((c) => <tr key={c.target}><td className="mono">{c.target}</td><td><span className={`pill ${label[c.change]}`}>{c.change}{c.what ? `: ${c.what.join(", ")}` : ""}</span></td>
            <td className="mono faint">{c.before ? `${c.before.sources.join(" + ")} · ${steps(c.before.transform)}` : "—"}</td>
            <td className="mono">{c.after ? `${c.after.sources.join(" + ")} · ${steps(c.after.transform)}` : "—"}</td></tr>)}</tbody></table></div>
          : <div className="empty">No field changes yet.</div>}
    </Modal>
  );
}

function PreviewModal({ mappingId, onClose }) {
  const { data: preview, error } = useApi(`/api/mappings/${mappingId}/preview`);
  return (
    <Modal title="Validation preview" size="md" onClose={onClose} sub={preview ? `${preview.rows} sample rows through this mapping and the live rule set. Nothing is loaded.` : ""}>
      {!preview ? <Loading error={error} /> : <div className="stack">
        <div className="kpis" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
          <div className="kpi"><span className="eyebrow">Would board</span><span className="v">{preview.pass_rate}%</span></div>
          <div className="kpi"><span className="eyebrow">Warn</span><span className="v">{fmt(preview.counts.WARN)}</span></div>
          <div className="kpi"><span className="eyebrow">Fail</span><span className="v" style={{ color: "var(--fail)" }}>{fmt(preview.counts.FAIL)}</span></div>
        </div>
        <Segments parts={[{ label: "Pass", value: preview.counts.PASS, color: "var(--pass)" }, { label: "Warn", value: preview.counts.WARN, color: "var(--warn)" }, { label: "Fail", value: preview.counts.FAIL, color: "var(--fail)" }]} />
        <div className="legend"><span><i style={{ background: "var(--pass)" }} />Pass {preview.counts.PASS}</span><span><i style={{ background: "var(--warn)" }} />Warn {preview.counts.WARN}</span><span><i style={{ background: "var(--fail)" }} />Fail {preview.counts.FAIL}</span></div>
        {(Object.keys(preview.failures_by_rule).length > 0 || Object.keys(preview.transform_errors).length > 0) && <div className="stack" style={{ gap: 6 }}><span className="eyebrow">What fails</span>
          <div className="row">{Object.entries(preview.failures_by_rule).map(([r, n]) => <span key={r} className="chip">{r} × {n}</span>)}
            {Object.entries(preview.transform_errors).map(([f, n]) => <span key={f} className="chip" style={{ color: "var(--fail)" }}>cast {f} × {n}</span>)}</div></div>}
      </div>}
    </Modal>
  );
}

function ApproveModal({ mp, dqFails, onClose, onDone }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const diff = useApi(mp.version > 1 ? `/api/mappings/${mp.mapping_id}/diff` : null);
  const go = async () => {
    setBusy(true);
    const r = await act(() => api(`/api/mappings/${mp.mapping_id}/approve`, { method: "POST", body: { approve: true, comment: comment || undefined } }), "Approved. The configuration is published and the next file runs on it.");
    setBusy(false);
    if (r) onDone();
  };
  const fields = mp.fields.filter((f) => f.status !== "rejected");
  return (
    <Modal title={`Approve mapping v${mp.version}`} sub={`${mp.source.name}${mp.source.vendor_name ? ` · ${mp.source.vendor_name}` : ""} · prepared by ${mp.created_by}`} size="md" onClose={onClose} busy={busy}
      footer={<><button className="btn" onClick={onClose} disabled={busy}>Cancel</button><button className="btn primary" disabled={busy} onClick={go}>{busy ? "Approving…" : "Approve and publish"}</button></>}>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div className="kpi"><span className="eyebrow">Fields mapped</span><span className="v">{fields.length}</span></div>
        <div className="kpi"><span className="eyebrow">Changed vs live</span><span className="v">{diff.data?.summary ? diff.data.summary.added + diff.data.summary.changed + diff.data.summary.removed : mp.version > 1 ? "…" : "new"}</span></div>
        <div className="kpi"><span className="eyebrow">DQ rules failing</span><span className="v" style={{ color: dqFails ? "var(--warn)" : undefined }}>{dqFails}</span><span className="d">on the sample</span></div>
      </div>
      <div className="callout" style={{ fontSize: ".84rem" }}>Approving makes this the feed's live mapping and <b>publishes a signed configuration</b> for the Glue data plane. Files already running finish on the version they started with.</div>
      <label className="stack" style={{ gap: 4 }} htmlFor="ap-c"><span className="eyebrow">Approval note (optional, audited)</span>
        <textarea id="ap-c" className="input" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Verified value translations with the vendor's code list" /></label>
    </Modal>
  );
}

function Workbench({ mappingId, persona, onBack, go, initialTarget, onOpen, initialView, onVendors, onVendor }) {
  const m = useApi(`/api/mappings/${mappingId}`);
  const dq = useApi(`/api/mappings/${mappingId}/dq`);
  const meta = useApi("/api/meta/transforms");
  const [filter, setFilter] = useState("all");
  const [view, setView] = useState(initialView || "fields");
  const [sel, setSel] = useState(initialTarget || null);
  const [modal, setModal] = useState(null); // "preview" | "diff" | "approve"
  const [mapModal, setMapModal] = useState(null);
  const [dialog, ask] = useDialog();
  const act = useAction();
  const fields = m.data?.fields || [];
  const feeds = useMemo(() => {
    const out = {};
    fields.filter((f) => f.status !== "rejected").forEach((f) => (f.sources?.length ? f.sources : [f.source]).forEach((c) => { (out[c] = out[c] || []).push(f.target); }));
    return out;
  }, [fields]);
  const feedsOf = (c) => feeds[c] || [];
  const isOneToMany = (f) => (f.sources?.length ? f.sources : [f.source]).some((c) => feedsOf(c).length > 1);
  const dqByField = useMemo(() => {
    const out = {};
    (dq.data?.rules || []).forEach((r) => { const f = r.primary_field; (out[f] = out[f] || { n: 0, failed: 0 }); out[f].n++; out[f].failed += r.failed; });
    return out;
  }, [dq.data]);
  const shown = useMemo(() => fields.filter((f) => filter === "all" ? true : filter === "review" ? ["suggested", "needs_review"].includes(f.status) : filter === "low" ? f.confidence < 0.8 : filter === "dq" ? dqByField[f.target]?.failed > 0 : filter === "1n" ? isOneToMany(f) : f.composite || f.derived_from), [fields, filter, dqByField, feeds]);
  if (!m.data) return <Loading error={m.error} />;
  const mp = m.data;
  const draft = mp.status === "draft";
  const pending = fields.filter((f) => ["suggested", "needs_review"].includes(f.status)).length;
  const doField = async (target, body) => { if (!target) { m.reload(); dq.reload(); return; } const r = await act(() => api(`/api/mappings/${mappingId}/fields/${target}`, { method: "POST", body }), body.action === "override" ? "Transformation saved" : body.action === "remove" ? `Removed mapping to ${target}` : body.action === "accept" ? `${target} accepted` : undefined); if (r) { if (body.action === "remove") setSel(null); m.reload(); dq.reload(); } return r; };
  const canApprove = canCap(persona, "approveMapping");
  const canEdit = canCap(persona, "editMapping");
  const selField = fields.find((f) => f.target === sel);
  const order = MODULES.flatMap((mod) => shown.filter((f) => f.module === mod));
  const selIdx = order.findIndex((f) => f.target === sel);
  const dqFails = (dq.data?.rules || []).filter((r) => r.failed > 0).length;
  return (
    <>
      <PageHeader
        eyebrow={<span className="crumbs"><a onClick={onVendors}>All vendors</a><span className="faint">›</span>
          <a onClick={() => (mp.source.vendor_id ? onVendor(mp.source.vendor_id) : onBack())}>{mp.source.vendor_name || "Vendor"}</a><span className="faint">›</span>
          <span>{mp.source.name}</span><span className="faint">›</span><span>Mapping v{mp.version}</span></span>}
        title={<>{mp.source.name}{mp.source.vendor_name && mp.source.vendor_name !== mp.source.name && <span className="faint" style={{ fontWeight: 400 }}> · {mp.source.vendor_name}</span>}</>}
        sub={<>Mapping v{mp.version} · <Status s={mp.status} /> · prepared by {mp.created_by}{mp.approved_by ? ` · approved by ${mp.approved_by}` : ""}</>}
        guideHref="#guide?path=setup&step=mapping"
        primary={
          mp.status === "in_review" && canApprove ? <button type="button" className="btn primary" onClick={() => setModal("approve")}>Approve…</button>
            : draft && canEdit ? <button type="button" className="btn primary" onClick={() => ask({ kind: "reason", title: "Submit for SME approval", confirmLabel: "Submit", required: false, label: "Note for the approver",
              help: pending ? `${pending} field(s) are still awaiting review; the server will refuse the submission until each is accepted, changed or rejected.` : "An SME other than you reviews and approves. On approval the configuration is published to the Glue data plane.",
              placeholder: "e.g. New value translations for LoanType; please check FHA codes",
              onSubmit: () => act(() => api(`/api/mappings/${mappingId}/submit`, { method: "POST" }), "Sent to SME for approval").then((r) => { if (r) m.reload(); return r; }) })}>Submit for approval…</button>
            : mp.status === "approved" && canEdit ? <button type="button" className="btn primary" onClick={() => ask({ kind: "confirm", title: `Edit ${mp.source.name} as a new version`, confirmLabel: `Create draft v${mp.version + 1}`,
              body: <span>A draft copy of the live mapping v{mp.version} is created for editing. The live version keeps running until the draft is approved.</span>,
              onConfirm: async () => { const r = await act(() => api(`/api/sources/${mp.source_id}/mappings/new-version`, { method: "POST" }), (x) => `Draft v${x.version} created from the live mapping`); if (r) onOpen(r.mapping_id); return r; } })}>Edit as new version…</button>
            : null
        }
        secondary={(
          <ActionBar>
            <button type="button" className="btn" onClick={() => setModal("preview")}>Validation preview</button>
            {mp.version > 1 && <button type="button" className="btn" onClick={() => setModal("diff")}>Changes vs v{mp.version - 1}</button>}
            {draft && canEdit && <button type="button" className="btn" disabled={!pending} onClick={() => ask({ kind: "confirm", title: "Accept high-confidence suggestions", confirmLabel: "Accept all ≥ 0.80",
              body: <span>Accepts every suggested mapping with confidence 0.80 or higher ({fields.filter((f) => ["suggested", "needs_review"].includes(f.status) && f.confidence >= 0.8).length} fields). Lower-confidence fields stay for review. You can still change any field before submitting.</span>,
              onConfirm: () => act(() => api(`/api/mappings/${mappingId}/accept-all?min_confidence=0.8`, { method: "POST" }), (r) => `Accepted ${r.accepted} high-confidence mappings`).then((r) => { if (r) m.reload(); return r; }) })}>Accept all ≥ 0.80…</button>}
            {mp.status === "in_review" && canApprove && <button type="button" className="btn" onClick={() => ask({ kind: "reason", title: "Send back to the analyst", confirmLabel: "Send back", minLength: 5,
              help: "The mapping returns to draft with your comment. Say what needs to change.", presets: ["Please revisit the low-confidence fields", "Value translations incomplete"],
              onSubmit: (comment) => act(() => api(`/api/mappings/${mappingId}/approve`, { method: "POST", body: { approve: false, comment } }), "Sent back to analyst").then((r) => { if (r) m.reload(); return r; }) })}>Send back…</button>}
            {mp.status === "in_review" && !canApprove && <span className="faint" style={{ fontSize: ".82rem" }}>SME can approve</span>}
            {mp.source_id && mp.source.status === "live" && <FeedConfigChip sourceId={mp.source_id} persona={persona} />}
          </ActionBar>
        )}
      />
      <Kpis items={[
        { label: "Auto-mapped", value: `${mp.stats?.auto_mapped_pct}%`, detail: "confidence ≥ 0.80 (PoC target 70%)" },
        { label: "Avg confidence", value: (mp.stats?.avg_confidence ?? 0).toFixed(2) },
        { label: "Fields mapped", value: fields.filter((f) => f.status !== "rejected").length, detail: `${mp.stats?.source_columns} source columns` },
        { label: "Awaiting review", value: pending, detail: `${fields.filter((f) => f.signals?.memory && f.signals.memory.approved > f.signals.memory.rejected).length} learned from earlier approvals` },
        { label: "DQ rules failing on sample", value: dq.data ? `${dqFails} / ${dq.data.rules.length}` : "…", detail: "business rules run on the sample" },
      ]} />
      {modal === "preview" && <PreviewModal mappingId={mappingId} onClose={() => setModal(null)} />}
      {modal === "diff" && <DiffModal mappingId={mappingId} onClose={() => setModal(null)} />}
      {modal === "approve" && <ApproveModal mp={mp} dqFails={dqFails} onClose={() => setModal(null)} onDone={() => { setModal(null); m.reload(); }} />}
      {dialog}
      <Tabs value={view} onChange={setView} tabs={[{ id: "fields", label: "Field mappings & transformations", count: fields.length }, { id: "dq", label: "DQ rules", count: dq.data?.rules.length }, { id: "profile", label: "Source profile", count: mp.source.columns.length }, { id: "delivery", label: "Delivery & schedule" }]} />
      {view === "dq" && <DqTab mappingId={mappingId} go={go} />}
      {view === "delivery" && <DeliveryProfile sourceId={mp.source_id} persona={persona} go={go} />}
      {view === "profile" && <ProfileTab sourceId={mp.source_id} feedsOf={feedsOf} draft={draft} onMap={(c) => setMapModal({ sources: [c] })} onPick={(t) => { setView("fields"); setSel(t); }} />}
      {mapModal && <MapTargetModal mappingId={mappingId} fields={fields} columns={mp.source.columns} catalog={meta.data?.ops || []} lookups={Object.keys(meta.data?.lookup_tables || {})}
        preset={mapModal} onClose={() => setMapModal(null)} onSaved={(t) => { setMapModal(null); m.reload(); dq.reload(); setView("fields"); setSel(t); }} />}
      {view === "fields" && draft && <div className="row"><button className="btn primary" onClick={() => setMapModal({})}>+ Map a source column to an SSE field</button>
        <span className="faint" style={{ fontSize: ".8rem" }}>Any column can feed several SSE fields (1:N). Select a row to change its target or transformation.</span></div>}
      {view === "fields" && (
        <div>
          <Panel title="Source → SSE mapping" sub="Open a field to see its transformation steps, a sample trace and its DQ checks" pad={false} actions={<Tabs value={filter} onChange={setFilter} tabs={[
            { id: "all", label: "All", count: fields.length }, { id: "review", label: "To review", count: pending },
            { id: "low", label: "Low confidence", count: fields.filter((f) => f.confidence < 0.8).length },
            { id: "dq", label: "DQ failing", count: fields.filter((f) => dqByField[f.target]?.failed > 0).length },
            { id: "1n", label: "1:N", count: fields.filter(isOneToMany).length },
            { id: "composite", label: "Composite", count: fields.filter((f) => f.composite || f.derived_from).length }]} />}>
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>SSE attribute</th><th>Source column</th><th>Transformation</th><th>DQ rules</th><th>Confidence</th><th>Status</th>{draft && <th></th>}</tr></thead>
              <tbody>{MODULES.map((mod) => {
                const rows = shown.filter((f) => f.module === mod);
                if (!rows.length) return null;
                return (
                  <React.Fragment key={mod}>
                    <tr className="group"><td colSpan={7}>{mod}</td></tr>
                    {rows.map((f) => {
                      const q = dqByField[f.target];
                      return (
                        <tr key={f.target} className={`click ${sel === f.target ? "sel" : ""}`} onClick={() => setSel(f.target)}>
                          <td><span className="mono">{f.target}</span>{f.required && <span title="required" style={{ color: "var(--fail)" }}> *</span>}<div className="faint" style={{ fontSize: ".74rem" }}>{f.risk} risk</div></td>
                          <td><span className="mono">{(f.sources?.length ? f.sources : [f.source]).join(" + ")}</span>
                            {isOneToMany(f) && <span className="pill accent" style={{ marginLeft: 6 }} title={`${(f.sources?.length ? f.sources : [f.source]).map((c) => `${c} → ${feedsOf(c).join(", ")}`).join("; ")}`}>1:N</span>}
                            {f.retargeted_from && <div className="faint" style={{ fontSize: ".72rem" }}>was {f.retargeted_from}</div>}</td>
                          <td><Transform steps={f.transform} /></td>
                          <td>{q ? <span className="stack" style={{ gap: 2 }} title={`${q.n} business rule(s) on this field`}><span className={`pill ${q.failed ? "fail" : "pass"}`} style={{ alignSelf: "flex-start" }}>{q.failed ? `${q.failed} fail` : "pass"}</span><span className="faint" style={{ fontSize: ".72rem" }}>{q.n} rule{q.n > 1 ? "s" : ""}</span></span> : <span className="faint" style={{ fontSize: ".78rem" }}>schema only</span>}</td>
                          <td><Conf v={f.confidence} /></td>
                          <td><Status s={f.status} /></td>
                          {draft && <td className="r" onClick={(e) => e.stopPropagation()}><span className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
                            <button className="btn sm" onClick={() => doField(f.target, { action: "accept" })} disabled={f.status === "accepted"}>Accept</button>
                            <button className="btn sm" onClick={() => setSel(f.target)}>Inspect</button></span></td>}
                        </tr>);
                    })}
                  </React.Fragment>);
              })}</tbody>
            </table></div>
          </Panel>
          {selField && <FieldInspector key={selField.target} mappingId={mappingId} field={{ ...selField, _version: mp.version }} columns={mp.source.columns} draft={draft}
            catalog={meta.data?.ops || []} lookups={Object.keys(meta.data?.lookup_tables || {})} onField={doField} onClose={() => setSel(null)} go={go}
            onMap={setMapModal} feedsOf={feedsOf}
            nav={{ label: selIdx >= 0 ? `${selIdx + 1} of ${order.length}` : "", onPrev: selIdx > 0 ? () => setSel(order[selIdx - 1].target) : null,
              onNext: selIdx >= 0 && selIdx < order.length - 1 ? () => setSel(order[selIdx + 1].target) : null }} />}
        </div>)}
    </>
  );
}

export default function Sources({ persona, go, vendor, pickVendor, reloadVendors }) {
  const [intent] = useState(() => takeIntent("sources"));
  const [mapping, setMapping] = useState(intent?.mappingId ? { id: intent.mappingId, view: intent.view || "fields" } : null);
  const [openVendor, setOpenVendor] = useState(vendor || null);
  const toVendors = () => { setMapping(null); setOpenVendor(null); if (vendor) pickVendor(null); };
  if (mapping) return <Workbench key={`${mapping.id}-${mapping.view}`} mappingId={mapping.id} initialView={mapping.view} persona={persona} go={go}
    initialTarget={intent?.mappingId === mapping.id ? intent?.target : null} onOpen={(id) => setMapping({ id, view: "fields" })}
    onBack={() => setMapping(null)} onVendors={toVendors} onVendor={(vid) => { setMapping(null); setOpenVendor(vid); }} />;
  if (openVendor) return <VendorWorkspace vendorId={openVendor} persona={persona} go={go} pickVendor={pickVendor} reloadVendors={reloadVendors}
    onBack={vendor ? null : () => setOpenVendor(null)} onOpenMapping={(id, view) => setMapping({ id, view })} />;
  return <VendorList persona={persona} onOpen={setOpenVendor} onCreated={(vid) => { reloadVendors && reloadVendors(); setOpenVendor(vid); }} />;
}
