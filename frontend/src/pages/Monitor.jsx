import React, { useMemo, useState } from "react";
import { scoped } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, Panel, Status, fmt, ago, Loading, Kpis, fmtCompact, human, PageHeader, EmptyState, Field } from "../ui.jsx";
import { Segments } from "../charts.jsx";
import { SCREEN } from "../screenCopy.js";
import { buildBatchesPath, splitLiveAndHistory, deskOrder } from "../monitorQuery.js";
import { BatchModal, UploadModal } from "./Imports.jsx";

const STEP_PILL = { succeeded: "pass", failed: "fail", running: "accent" };
const STATUS_OPTS = ["queued", "running", "paused", "blocked", "waiting", "out_of_order", "failed", "completed", "discarded"];
const DAY_OPTS = [
  { value: 1, label: "Today" },
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: "custom", label: "Custom range" },
];

function toDateInput(d) {
  return d.toISOString().slice(0, 10);
}
function startOfDayUtc(ymd) {
  return `${ymd}T00:00:00.000Z`;
}
function endOfDayUtc(ymd) {
  return `${ymd}T23:59:59.999Z`;
}

function ProgressBar({ pct, status }) {
  const tone = status === "failed" ? "fail" : status === "completed" ? "pass" : "";
  return (
    <div className={`bar ${tone}`} title={`${pct}%`} style={{ minWidth: 80 }}>
      <i style={{ width: `${Math.min(100, Math.max(0, pct || 0))}%` }} />
    </div>
  );
}

function PipelinePills({ steps }) {
  if (!steps?.length) return null;
  return (
    <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
      {steps.map((s, i) => (
        <span key={`${s.name}-${i}`} className={`pill ${STEP_PILL[s.state] || ""}`} title={s.summary || s.state}>{s.label}</span>
      ))}
    </span>
  );
}

function BatchRows({ rows, vendor, sel, onSelect, showProgress }) {
  if (!rows.length) return null;
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>File</th>
            <th>{vendor ? "Feed" : "Vendor · feed"}</th>
            <th>Status</th>
            {showProgress && <th style={{ minWidth: 100 }}>Progress</th>}
            <th style={{ minWidth: 120 }}>Outcome</th>
            <th className="r">Rows</th>
            <th className="r">Loans/s</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.batch_id} className={`click ${sel === x.batch_id ? "sel" : ""}`} onClick={() => onSelect(x.batch_id)}>
              <td className="mono">
                {x.filename}
                {x.load_type && x.load_type !== "full" && (
                  <div className="row" style={{ gap: 4, marginTop: 2 }}>
                    <span className="chip">{x.load_type === "snapshot" ? "snapshot" : "changes"}</span>
                    {x.sequence && <span className="chip">#{x.sequence}</span>}
                  </div>
                )}
              </td>
              <td>
                {vendor ? x.source_name : (
                  <>
                    {x.vendor_name || x.source_name}
                    {x.vendor_name && x.vendor_name !== x.source_name && (
                      <div className="faint" style={{ fontSize: ".76rem" }}>{x.source_name}</div>
                    )}
                  </>
                )}
              </td>
              <td>
                <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                  <Status s={x.status} />
                  <PipelinePills steps={x.pipeline?.steps} />
                </span>
              </td>
              {showProgress && (
                <td>
                  <div className="stack" style={{ gap: 2 }}>
                    <ProgressBar pct={x.progress_pct} status={x.status} />
                    <span className="faint num" style={{ fontSize: ".76rem" }}>
                      {fmt(x.processed)} / {fmt(x.total_rows)} ({x.progress_pct}%)
                      {x.eta_seconds != null && x.status === "running" ? ` · ETA ${x.eta_seconds}s` : ""}
                    </span>
                  </div>
                </td>
              )}
              <td>
                <Segments
                  total={x.total_rows || x.processed}
                  parts={[
                    { label: "Pass", value: x.passed, color: "var(--pass)" },
                    { label: "Warn", value: x.warned, color: "var(--warn)" },
                    { label: "Fail", value: x.failed, color: "var(--fail)" },
                  ]}
                />
              </td>
              <td className="r num">{fmt(x.processed)}{x.status === "running" || x.status === "queued" ? ` / ${fmt(x.total_rows)}` : ""}</td>
              <td className="r num">{fmt(x.throughput_lps)}</td>
              <td className="faint">{ago(x.started_at || x.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Monitor({ persona, go, vendor }) {
  const today = toDateInput(new Date());
  const weekAgo = toDateInput(new Date(Date.now() - 6 * 86400000));
  const [range, setRange] = useState(1); // 1 | 7 | 30 | "custom"
  const [sinceDay, setSinceDay] = useState(weekAgo);
  const [untilDay, setUntilDay] = useState(today);
  const [status, setStatus] = useState([]);
  const [q, setQ] = useState("");
  const [qDraft, setQDraft] = useState("");
  const [sel, setSel] = useState(null);
  const [upload, setUpload] = useState(false);

  const path = useMemo(() => {
    const custom = range === "custom";
    return scoped(buildBatchesPath({
      days: custom ? null : range,
      since: custom ? startOfDayUtc(sinceDay) : null,
      until: custom ? endOfDayUtc(untilDay) : null,
      status,
      q,
      limit: 50,
    }));
  }, [range, sinceDay, untilDay, status, q, vendor]);
  const b = useApi(path, [path], { poll: 2000 });
  const s = useApi(scoped("/api/sources"));

  if (!b.data || !s.data) return <Loading error={b.error || s.error} />;

  const batches = b.data.batches || [];
  const { live, history } = splitLiveAndHistory(batches);
  const ordered = deskOrder(batches);
  const done = batches.filter((x) => x.status === "completed");
  const idx = ordered.findIndex((x) => x.batch_id === sel);
  const empty = !live.length && !history.length;
  const rangeLabel = range === "custom"
    ? `${sinceDay} → ${untilDay}`
    : (DAY_OPTS.find((d) => d.value === range)?.label || "Range");

  const toggleStatus = (st) => {
    setStatus((prev) => (prev.includes(st) ? prev.filter((x) => x !== st) : [...prev, st]));
  };

  return (
    <>
      <PageHeader
        eyebrow="Run"
        title={SCREEN.monitor.label}
        sub={SCREEN.monitor.sub}
        guideHref="#guide?path=execution&step=arrive"
        primary={canCap(persona, "upload") ? <button type="button" className="btn primary" onClick={() => setUpload(true)}>Upload file</button> : null}
        secondary={<button type="button" className="btn" onClick={() => go("imports")}>File loads</button>}
      />

      <Kpis items={[
        { label: "Batches running", value: b.data.running },
        { label: "Current throughput", value: `${fmt(b.data.current_throughput_lps)}/s`, detail: `target ${b.data.target_lps}/s` },
        { label: "Needs attention", value: b.data.attention ?? 0, detail: "failed · blocked · waiting · paused" },
        { label: "Completed in range", value: done.length, detail: `${fmt(done.reduce((a, x) => a + (x.processed || 0), 0))} loans` },
      ]} />

      <Panel title="Filters" sub="History and live share the same range and search">
        <div className="toolbar" style={{ flexWrap: "wrap", gap: 12 }}>
          <Field id="mon-days" label="Range">
            <select
              id="mon-days"
              className="input"
              value={range}
              onChange={(e) => {
                const v = e.target.value;
                setRange(v === "custom" ? "custom" : Number(v));
              }}
            >
              {DAY_OPTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          {range === "custom" && (
            <>
              <Field id="mon-since" label="From">
                <input id="mon-since" type="date" className="input" value={sinceDay} max={untilDay}
                  onChange={(e) => setSinceDay(e.target.value)} />
              </Field>
              <Field id="mon-until" label="To">
                <input id="mon-until" type="date" className="input" value={untilDay} min={sinceDay}
                  onChange={(e) => setUntilDay(e.target.value)} />
              </Field>
            </>
          )}
          <Field id="mon-q" label="Search">
            <form className="row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); setQ(qDraft); }}>
              <input id="mon-q" className="input" placeholder="Filename or batch id" value={qDraft}
                onChange={(e) => setQDraft(e.target.value)} style={{ minWidth: 180 }} />
              <button type="submit" className="btn sm">Search</button>
              {q && <button type="button" className="btn sm" onClick={() => { setQ(""); setQDraft(""); }}>Clear</button>}
            </form>
          </Field>
        </div>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          <span className="eyebrow">Status</span>
          {STATUS_OPTS.map((st) => (
            <button key={st} type="button" className={`btn sm ${status.includes(st) ? "primary" : ""}`} onClick={() => toggleStatus(st)}>
              {human(st)}
            </button>
          ))}
          {status.length > 0 && <button type="button" className="btn sm" onClick={() => setStatus([])}>Any status</button>}
        </div>
      </Panel>

      {empty ? (
        <EmptyState
          title="No batches in this range"
          body="Upload a file, wait for a vendor delivery, or widen the date range."
          action={canCap(persona, "upload")
            ? <button type="button" className="btn primary" onClick={() => setUpload(true)}>Upload file</button>
            : <button type="button" className="btn" onClick={() => go("deliveries")}>Delivery schedule</button>}
        />
      ) : (
        <>
          {live.length > 0 && (
            <Panel title="Live" sub="Queued, running, and paused — progress updates every few seconds" pad={false}>
              <BatchRows rows={live} vendor={vendor} sel={sel} onSelect={setSel} showProgress />
            </Panel>
          )}
          {history.length > 0 && (
            <Panel title="History" sub={`${rangeLabel} · click a row to open the batch`} pad={false}>
              <BatchRows rows={history} vendor={vendor} sel={sel} onSelect={setSel} showProgress={false} />
            </Panel>
          )}
        </>
      )}

      {sel && (
        <BatchModal
          id={sel}
          persona={persona}
          go={go}
          onClose={() => setSel(null)}
          nav={{
            label: idx >= 0 ? `${idx + 1} of ${ordered.length}` : "",
            onPrev: idx > 0 ? () => setSel(ordered[idx - 1].batch_id) : null,
            onNext: idx >= 0 && idx < ordered.length - 1 ? () => setSel(ordered[idx + 1].batch_id) : null,
          }}
        />
      )}
      {upload && (
        <UploadModal
          sources={s.data.sources}
          onClose={() => setUpload(false)}
          onDone={(bid) => { setUpload(false); b.reload(); if (bid) setSel(bid); }}
        />
      )}
      <p className="faint" style={{ fontSize: ".78rem", marginTop: 8 }}>
        Throughput peak in this page load: {fmtCompact(Math.max(0, ...batches.map((x) => x.throughput_lps || 0)))}/s
      </p>
    </>
  );
}
