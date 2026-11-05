import React, { useState } from "react";
import { api, scoped } from "../api.js";
import { useApi, useAction, Panel, Tabs, Loading, fmt, Kpis, Conf, Status, PageHeader } from "../ui.jsx";
import { HBars, VBars, heatColor } from "../charts.jsx";

function Ask() {
  const [q, setQ] = useState("Which vendor has the worst success rate?");
  const [ans, setAns] = useState(null);
  const act = useAction();
  const run = async (question = q) => setAns(await act(() => api("/api/analytics/ask", { method: "POST", body: { question } })));
  const render = (a) => {
    if (a === null || a === undefined) return null;
    if (Array.isArray(a)) return (
      <div className="tbl-wrap"><table className="tbl"><thead><tr>{Object.keys(a[0] || {}).map((k) => <th key={k}>{k.replace(/_/g, " ")}</th>)}</tr></thead>
        <tbody>{a.map((r, i) => <tr key={i}>{Object.values(r).map((v, j) => <td key={j} className="num">{typeof v === "number" ? fmt(v, 1) : String(v)}</td>)}</tr>)}</tbody></table></div>);
    if (typeof a === "object") return <dl className="kv">{Object.entries(a).map(([k, v]) => <React.Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="num">{typeof v === "number" ? fmt(v, 1) : String(v)}</dd></React.Fragment>)}</dl>;
    return <span className="kpi"><span className="v">{typeof a === "number" ? fmt(a, 1) : a}</span></span>;
  };
  return (
    <Panel title="Ask the data" sub="Natural-language questions over boarding metrics (QuickSight Q in AWS)">
      <form className="row" onSubmit={(e) => { e.preventDefault(); run(); }}>
        <input id="ask-q" className="input" style={{ flex: 1, minWidth: 220 }} value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn primary" type="submit">Ask</button>
      </form>
      {ans && <div className="stack" style={{ marginTop: 12 }}>
        {ans.answer_title ? <><span className="eyebrow">{ans.answer_title}</span>{render(ans.answer)}</> :
          <div className="row"><span className="muted">Try one of these:</span>{(ans.suggestions || []).map((s) => <button key={s} className="btn sm" onClick={() => { setQ(s); run(s); }}>{s}</button>)}</div>}
      </div>}
    </Panel>
  );
}

function ExceptionsDash() {
  const { data } = useApi(scoped("/api/analytics/exceptions"));
  if (!data) return <Loading />;
  return (
    <>
      <Kpis items={[{ label: "Exceptions (30 d)", value: fmt(data.total) }, { label: "Open", value: fmt(data.open) },
        { label: "Auto-applied", value: fmt(data.auto_applied), detail: `${data.auto_apply_rate}% of all` },
        ...Object.entries(data.avg_resolution_minutes).slice(0, 2).map(([t, m]) => ({ label: `Avg time to resolve ${t}`, value: `${fmt(m, 1)} min` }))]} />
      <div className="grid g2">
        <Panel title="By category"><HBars items={Object.entries(data.by_category).map(([k, v]) => ({ label: k, value: v }))} /></Panel>
        <Panel title="By vendor · feed"><HBars items={Object.entries(data.by_source).map(([k, v]) => ({ label: k, value: v }))} color="var(--chart-3)" /></Panel>
        <Panel title="Open exception age"><VBars items={Object.entries(data.aging).map(([k, v]) => ({ label: k, value: v, color: "var(--chart-2)" }))} /></Panel>
        <Panel title="Bulk-resolution candidates" sub="Same rule and same bad value, many loans" pad={false}>
          <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Rule</th><th>Value</th><th className="r">Open</th></tr></thead>
            <tbody>{data.bulk_candidates.map((b, i) => <tr key={i}><td className="mono">{b.rule_id}</td><td className="mono">{b.original_value ?? "(blank)"}</td><td className="r num">{b.count}</td></tr>)}</tbody></table></div>
        </Panel>
      </div>
    </>
  );
}

function DQ() {
  const { data } = useApi(scoped("/api/analytics/dq-scorecard"));
  if (!data) return <Loading />;
  return (
    <>
      <Kpis items={[{ label: "Overall DQ score", value: fmt(data.overall_score, 1) }, { label: "Required-field completeness", value: `${fmt(data.required_completeness, 1)}%` }, { label: "Loans sampled", value: fmt(data.sampled_loans) }]} />
      <Panel title="Quality heatmap" sub="Score by vendor feed and SSE module (100 = no exceptions)" pad={false}>
        <div className="tbl-wrap"><table className="tbl heat"><thead><tr><th>Source</th>{data.modules.map((m) => <th key={m} style={{ textAlign: "center" }}>{m}</th>)}</tr></thead>
          <tbody>{data.heatmap.map((r) => <tr key={r.source}><td>{r.source}</td>{data.modules.map((m) => <td key={m} className="h" style={{ background: heatColor(r[m]) }} title={`${r.source} · ${m}: ${r[m]}`}>{fmt(r[m], 1)}</td>)}</tr>)}</tbody></table></div>
      </Panel>
      <Panel title="Lowest-scoring fields" pad={false}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Field</th><th>Module</th><th className="r">Completeness</th><th className="r">Exception rate</th><th className="r">Score</th></tr></thead>
          <tbody>{data.fields.slice(0, 15).map((f) => <tr key={f.field}><td className="mono">{f.field}{f.required && <span style={{ color: "var(--fail)" }}> *</span>}</td><td>{f.module}</td>
            <td className="r num">{fmt(f.completeness, 1)}%</td><td className="r num">{fmt(f.exception_rate, 2)}%</td><td className="r num"><b>{fmt(f.score, 1)}</b></td></tr>)}</tbody></table></div>
      </Panel>
    </>
  );
}

function SourcesDash() {
  const { data } = useApi(scoped("/api/analytics/source-performance"));
  if (!data) return <Loading />;
  return (
    <Panel title="Vendor and feed performance" pad={false}>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Vendor · feed</th><th>Format</th><th>Status</th><th className="r">Batches</th><th className="r">Processed</th><th className="r">Boarded</th>
        <th className="r">Success</th><th className="r">Exceptions / 100</th><th className="r">Auto-fixed</th><th className="r">Avg loans/s</th></tr></thead>
        <tbody>{data.sources.map((s) => <tr key={s.source_id}><td>{s.name}</td><td className="mono">{s.format}</td><td><Status s={s.status} /></td><td className="r num">{s.batches}</td>
          <td className="r num">{fmt(s.loans_processed)}</td><td className="r num">{fmt(s.loans_boarded)}</td><td className="r num">{s.success_rate ?? "—"}%</td>
          <td className="r num">{s.exceptions_per_100 ?? "—"}</td><td className="r num">{fmt(s.auto_fixed)}</td><td className="r num">{fmt(s.avg_throughput_lps)}</td></tr>)}</tbody></table></div>
    </Panel>
  );
}

function AIDash() {
  const { data } = useApi(scoped("/api/analytics/ai-mapping"));
  const mem = useApi("/api/mapping-memory");
  if (!data) return <Loading />;
  const e = data.exception_ai;
  return (
    <>
      <Kpis items={[{ label: "T1 auto-applied", value: fmt(e.t1_auto_applied) }, { label: "T1 override rate", value: `${e.t1_override_rate_pct}%`, detail: "control limit < 2%" },
        { label: "QA samples pending", value: fmt(e.qa_samples_pending) }, { label: "AI proposal acceptance", value: e.ai_proposal_acceptance_pct === null ? "—" : `${e.ai_proposal_acceptance_pct}%`, detail: `${fmt(e.human_resolutions)} human resolutions` }]} />
      {mem.data && <Panel title="Mapping memory" sub={`${mem.data.approved_pairs} column → field pairs learned from SME approvals · ${mem.data.rejected_pairs} rejected pairs suppressed. New sources with familiar columns start pre-mapped.`} pad={false}>
        <div className="tbl-wrap" style={{ maxHeight: 260 }}><table className="tbl"><thead><tr><th>Source column</th><th>SSE field</th><th className="r">Approved</th><th className="r">Rejected</th><th>Learned from</th></tr></thead>
          <tbody>{mem.data.items.slice(0, 60).map((x, i) => <tr key={i}><td className="mono">{x.source_column}</td><td className="mono">{x.target}</td><td className="r num">{x.approved}</td><td className="r num">{x.rejected}</td><td className="faint">{(x.sources || []).join(", ")}</td></tr>)}</tbody></table></div>
      </Panel>}
      <Panel title="Mapping quality by vendor feed" pad={false}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Source</th><th>Version</th><th>Status</th><th className="r">Fields</th><th className="r">Auto-mapped</th><th>Avg confidence</th><th className="r">Override rate</th><th className="r">Review time</th></tr></thead>
          <tbody>{data.mappings.map((m) => <tr key={m.mapping_id}><td>{m.source}</td><td>v{m.version}</td><td><Status s={m.status} /></td><td className="r num">{m.fields}</td><td className="r num">{m.auto_mapped_pct}%</td>
            <td><Conf v={m.avg_confidence} /></td><td className="r num">{m.override_rate}%</td><td className="r num">{m.review_minutes === null ? "—" : `${fmt(m.review_minutes, 1)} min`}</td></tr>)}</tbody></table></div>
      </Panel>
    </>
  );
}

function VendorsDash() {
  const { data } = useApi(scoped("/api/analytics/vendors"));
  if (!data) return <Loading />;
  const v = data.vendors;
  const bv = data.by_vendor || [];
  const tot = (k) => v.reduce((a, x) => a + (x.changes_30d?.[k] || 0), 0);
  return (
    <>
      <Kpis items={[{ label: "Vendors", value: bv.length, detail: `${v.length} feeds · ${v.filter((x) => x.load_type !== "full").length} send change files or snapshots` },
        { label: "Changes applied (30 d)", value: fmt(tot("updates") + tot("closes") + tot("adds")), detail: `${fmt(tot("updates"))} updates · ${fmt(tot("closes"))} closes · ${fmt(tot("adds"))} adds` },
        { label: "Unchanged rows skipped", value: fmt(tot("unchanged")), detail: "snapshot rows identical to SSE" },
        { label: "Concurrent-change conflicts", value: fmt(tot("conflicts")), detail: "held for a person, never overwritten" }]} />
      <Panel title="By vendor" pad={false}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Vendor</th><th>Status</th><th className="r">Feeds</th><th className="r">Active loans</th><th className="r">Open exceptions</th>
          <th className="r">On time (30 d)</th><th className="r">Late / missed</th><th className="r">Files held</th></tr></thead>
          <tbody>{bv.map((x) => <tr key={x.vendor_id}><td>{x.name}</td><td><Status s={x.status} /></td><td className="r num">{x.feeds}</td><td className="r num">{fmt(x.active_loans)}</td>
            <td className="r num">{fmt(x.open_exceptions)}</td><td className="r num">{x.on_time_pct === null ? "—" : `${x.on_time_pct}%`}</td><td className="r num">{x.late_or_missed}</td><td className="r num">{x.attention_files}</td></tr>)}</tbody></table></div>
      </Panel>
      <Panel title="Feeds: freshness and change volume" sub="Last 30 days" pad={false}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Vendor · feed</th><th>Delivers</th><th className="r">Active loans</th><th className="r">Last file</th><th className="r">Applied #</th>
          <th className="r">On time</th><th className="r">Late / missed (open)</th><th className="r">Files</th><th className="r">Updates</th><th className="r">Closes</th><th className="r">Adds</th></tr></thead>
          <tbody>{v.map((x) => <tr key={x.source_id}><td>{x.vendor_name || x.name}{x.vendor_name && x.vendor_name !== x.name && <div className="faint" style={{ fontSize: ".74rem" }}>{x.name}</div>}{x.waiting_files > 0 && <span className="pill warn" style={{ marginLeft: 6 }}>{x.waiting_files} waiting</span>}</td>
            <td><span className="chip">{x.load_type}</span></td><td className="r num">{fmt(x.active_loans)}</td>
            <td className="r num">{x.hours_since_arrival === null ? "—" : `${fmt(x.hours_since_arrival, 1)} h ago`}</td><td className="r num">{x.last_sequence ?? "—"}</td>
            <td className="r num">{x.on_time_pct === null ? "—" : `${x.on_time_pct}%`}</td><td className="r num">{x.open_late_or_missed || 0}</td>
            <td className="r num">{fmt(x.changes_30d?.files || 0)}</td><td className="r num">{fmt(x.changes_30d?.updates || 0)}</td><td className="r num">{fmt(x.changes_30d?.closes || 0)}</td><td className="r num">{fmt(x.changes_30d?.adds || 0)}</td></tr>)}</tbody></table></div>
      </Panel>
    </>
  );
}

export default function Analytics() {
  const [tab, setTab] = useState("exceptions");
  return (
    <>
      <PageHeader
        eyebrow="Run"
        title="Analytics"
        sub="Batch KPIs, exception trends, data-quality scoring, and AI performance. In AWS these are Redshift views served through QuickSight."
        guideHref="#guide?path=execution&step=board"
      />
      <Ask />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "exceptions", label: "Exception analytics" }, { id: "dq", label: "DQ scorecard" }, { id: "sources", label: "Vendor & feed performance" }, { id: "vendors", label: "Vendor deliveries" }, { id: "ai", label: "AI mapping insights" }]} />
      {tab === "exceptions" && <ExceptionsDash />}{tab === "dq" && <DQ />}{tab === "sources" && <SourcesDash />}{tab === "vendors" && <VendorsDash />}{tab === "ai" && <AIDash />}
    </>
  );
}
