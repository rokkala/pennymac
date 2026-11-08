import React, { useMemo, useState } from "react";
import { scoped } from "../api.js";
import { useApi, Panel, Tabs, Loading, fmt, ago, Kpis, Status, PageHeader, EmptyState } from "../ui.jsx";
import { HBars } from "../charts.jsx";

function pct(v) {
  return v === null || v === undefined ? "—" : `${fmt(v, 1)}%`;
}

function rollupVendors(byVendor, sources, loads) {
  const byVid = new Map();
  for (const s of sources || []) {
    const id = s.vendor_id || s.source_id;
    const cur = byVid.get(id) || {
      vendor_id: id,
      name: s.vendor_name || s.name,
      processed: 0,
      boarded: 0,
      exceptions: 0,
      auto_fixed: 0,
      feeds: 0,
      feed_rows: [],
    };
    cur.processed += s.loans_processed || 0;
    cur.boarded += s.loans_boarded || 0;
    cur.exceptions += s.exceptions || 0;
    cur.auto_fixed += s.auto_fixed || 0;
    cur.feeds += 1;
    cur.feed_rows.push(s);
    byVid.set(id, cur);
  }
  const loadsByVendor = new Map();
  for (const b of loads || []) {
    if (!b.vendor_id) continue;
    const list = loadsByVendor.get(b.vendor_id) || [];
    list.push(b);
    loadsByVendor.set(b.vendor_id, list);
  }
  const base = (byVendor || []).length
    ? byVendor
    : [...byVid.values()].map((v) => ({ vendor_id: v.vendor_id, name: v.name, status: "active", open_exceptions: 0, on_time_pct: null, last_file: null, feeds: v.feeds }));
  return base.map((v) => {
    const perf = byVid.get(v.vendor_id) || { processed: 0, boarded: 0, exceptions: 0, auto_fixed: 0, feeds: v.feeds || 0, feed_rows: [] };
    const success = perf.processed ? round(perf.boarded / perf.processed * 100, 1) : null;
    const ex100 = perf.processed ? round(perf.exceptions / perf.processed * 100, 1) : null;
    return {
      ...v,
      processed: perf.processed,
      boarded: perf.boarded,
      success_rate: success,
      exceptions: perf.exceptions,
      exceptions_per_100: ex100,
      auto_fixed: perf.auto_fixed,
      feed_rows: perf.feed_rows,
      loads: loadsByVendor.get(v.vendor_id) || [],
    };
  }).sort((a, b) => (b.processed || 0) - (a.processed || 0));
}

function round(n, d) {
  const p = 10 ** d;
  return Math.round(n * p) / p;
}

function SummaryStrip() {
  const { data } = useApi(scoped("/api/analytics/executive"));
  if (!data) return <Loading />;
  return (
    <Kpis items={[
      { label: "Boarded (24 h)", value: fmt(data.loans_boarded_24h), detail: `${fmt(data.loans_boarded_total)} total` },
      { label: "Straight-through", value: pct(data.straight_through_rate), detail: `${fmt(data.loans_processed)} processed` },
      { label: "Open blocking", value: fmt(data.open_blocking_exceptions), detail: data.compliance_blocks ? `${fmt(data.compliance_blocks)} compliance` : undefined },
      { label: "Auto-apply rate", value: pct(data.auto_apply_rate) },
    ]} />
  );
}

function VendorDetail({ vendor, exceptions }) {
  const cats = Object.entries(exceptions?.by_category || {}).map(([label, value]) => ({ label, value }));
  const recent = (vendor.loads || []).slice(0, 8);
  return (
    <div className="grid g2" style={{ marginTop: 12 }}>
      <Panel title="Feeds" pad={false}>
        {!vendor.feed_rows?.length ? <EmptyState title="No feeds" body="This vendor has no performance history yet." /> : (
          <div className="tbl-wrap"><table className="tbl"><thead><tr>
            <th>Feed</th><th className="r">Batches</th><th className="r">Processed</th><th className="r">Boarded</th><th className="r">Success</th><th className="r">Ex / 100</th>
          </tr></thead><tbody>
            {vendor.feed_rows.map((s) => (
              <tr key={s.source_id}>
                <td>{s.feed_name || s.name}<div className="faint" style={{ fontSize: ".74rem" }}>{s.format}</div></td>
                <td className="r num">{fmt(s.batches)}</td>
                <td className="r num">{fmt(s.loans_processed)}</td>
                <td className="r num">{fmt(s.loans_boarded)}</td>
                <td className="r num">{pct(s.success_rate)}</td>
                <td className="r num">{s.exceptions_per_100 ?? "—"}</td>
              </tr>
            ))}
          </tbody></table></div>
        )}
      </Panel>
      <Panel title="Exceptions by category" sub="Last 30 days for this vendor">
        {cats.length ? <HBars items={cats} /> : <span className="faint">No exceptions in range.</span>}
      </Panel>
      <div style={{ gridColumn: "1 / -1" }}>
        <Panel title="Recent file loads" pad={false}>
          {!recent.length ? <EmptyState title="No loads" body="No file loads recorded for this vendor." /> : (
            <div className="tbl-wrap"><table className="tbl"><thead><tr>
              <th>File</th><th>Type</th><th>Status</th><th className="r">Rows</th><th className="r">Boarded</th><th className="r">Exceptions</th><th className="r">Finished</th>
            </tr></thead><tbody>
              {recent.map((b) => (
                <tr key={b.batch_id}>
                  <td className="mono">{b.filename}</td>
                  <td><span className="chip">{b.load_type || "full"}</span></td>
                  <td><Status s={b.status} /></td>
                  <td className="r num">{fmt(b.processed)} / {fmt(b.total_rows)}</td>
                  <td className="r num">{fmt(b.loaded)}</td>
                  <td className="r num">{fmt(b.exceptions || 0)}{b.open_exceptions ? <span className="faint"> · {fmt(b.open_exceptions)} open</span> : null}</td>
                  <td className="r num">{ago(b.finished_at || b.created_at)}</td>
                </tr>
              ))}
            </tbody></table></div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function ByVendor() {
  const vend = useApi(scoped("/api/analytics/vendors"));
  const perf = useApi(scoped("/api/analytics/source-performance"));
  const loads = useApi(scoped("/api/analytics/import-status?limit=200"));
  const [sel, setSel] = useState(null);
  const rows = useMemo(
    () => rollupVendors(vend.data?.by_vendor, perf.data?.sources, loads.data?.batches),
    [vend.data, perf.data, loads.data],
  );
  const selected = rows.find((r) => r.vendor_id === sel) || null;
  const ex = useApi(selected ? `/api/analytics/exceptions?vendor_id=${encodeURIComponent(selected.vendor_id)}` : null, [selected?.vendor_id]);
  if (!vend.data || !perf.data || !loads.data) return <Loading />;
  if (!rows.length) return <EmptyState title="No vendors" body="Onboard a vendor and run a file load to see analytics." />;
  return (
    <>
      <Panel title="By vendor" sub="Boarding outcomes rolled up to the vendor. Select a row for feeds, exceptions, and recent loads." pad={false}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr>
          <th>Vendor</th><th>Status</th><th className="r">Feeds</th><th className="r">Processed</th><th className="r">Boarded</th>
          <th className="r">Success</th><th className="r">Open ex.</th><th className="r">Ex / 100</th><th className="r">Auto-fixed</th>
          <th className="r">On time</th><th className="r">Last file</th>
        </tr></thead><tbody>
          {rows.map((v) => (
            <tr key={v.vendor_id} className={`click${sel === v.vendor_id ? " selected" : ""}`} onClick={() => setSel(sel === v.vendor_id ? null : v.vendor_id)}>
              <td>{v.name}</td>
              <td><Status s={v.status} /></td>
              <td className="r num">{fmt(v.feeds ?? v.feed_rows?.length ?? 0)}</td>
              <td className="r num">{fmt(v.processed)}</td>
              <td className="r num">{fmt(v.boarded)}</td>
              <td className="r num">{pct(v.success_rate)}</td>
              <td className="r num">{fmt(v.open_exceptions)}</td>
              <td className="r num">{v.exceptions_per_100 ?? "—"}</td>
              <td className="r num">{fmt(v.auto_fixed)}</td>
              <td className="r num">{v.on_time_pct === null || v.on_time_pct === undefined ? "—" : `${v.on_time_pct}%`}</td>
              <td className="r num">{ago(v.last_file)}</td>
            </tr>
          ))}
        </tbody></table></div>
      </Panel>
      {selected && <VendorDetail vendor={selected} exceptions={ex.data} />}
    </>
  );
}

function LoadDetail({ batch }) {
  const rec = batch.reconciliation || {};
  const ch = batch.change_summary || {};
  const pf = batch.preflight;
  return (
    <div className="grid g2" style={{ marginTop: 12 }}>
      <Panel title="Load outcome">
        <dl className="kv">
          <dt>Vendor</dt><dd>{batch.vendor_name || "—"}</dd>
          <dt>Feed</dt><dd>{batch.source_name || "—"}</dd>
          <dt>File</dt><dd className="mono">{batch.filename}</dd>
          <dt>Type</dt><dd><span className="chip">{batch.load_type || "full"}</span></dd>
          <dt>Status</dt><dd><Status s={batch.status} /></dd>
          <dt>Submitted by</dt><dd>{batch.submitted_by || "—"}</dd>
          <dt>Throughput</dt><dd className="num">{batch.throughput_lps ? `${fmt(batch.throughput_lps, 1)} loans/s` : "—"}</dd>
        </dl>
      </Panel>
      <Panel title="Counts">
        <Kpis items={[
          { label: "Processed", value: fmt(batch.processed) },
          { label: "Boarded", value: fmt(batch.loaded) },
          { label: "Failed / warned", value: `${fmt(batch.failed)} / ${fmt(batch.warned)}` },
          { label: "Exceptions", value: fmt(batch.exceptions || 0), detail: batch.open_exceptions ? `${fmt(batch.open_exceptions)} still open` : undefined },
        ]} />
      </Panel>
      {(rec.balanced !== undefined || Object.keys(ch).length > 0) && (
        <div style={{ gridColumn: "1 / -1" }}>
          <Panel title="Reconciliation / changes">
            <dl className="kv">
              {rec.balanced !== undefined && <><dt>Balanced</dt><dd>{rec.balanced ? "Yes" : "No"}</dd></>}
              {rec.expected != null && <><dt>Expected</dt><dd className="num">{fmt(rec.expected)}</dd></>}
              {rec.actual != null && <><dt>Actual</dt><dd className="num">{fmt(rec.actual)}</dd></>}
              {["adds", "updates", "closes", "unchanged", "conflicts"].filter((k) => ch[k] != null).map((k) => (
                <React.Fragment key={k}><dt>{k}</dt><dd className="num">{fmt(ch[k])}</dd></React.Fragment>
              ))}
            </dl>
          </Panel>
        </div>
      )}
      {pf && (
        <div style={{ gridColumn: "1 / -1" }}>
          <Panel title="Pre-flight">
            <div className="row"><Status s={pf.decision} /><span className="faint">{pf.summary}</span></div>
          </Panel>
        </div>
      )}
      {batch.error && (
        <div style={{ gridColumn: "1 / -1" }}>
          <Panel title="Error"><span className="fail">{batch.error}</span></Panel>
        </div>
      )}
    </div>
  );
}

function ByFileLoad() {
  const { data } = useApi(scoped("/api/analytics/import-status?limit=100"), [], { poll: 5000 });
  const [sel, setSel] = useState(null);
  if (!data) return <Loading />;
  const batches = data.batches || [];
  const selected = batches.find((b) => b.batch_id === sel) || null;
  if (!batches.length) return <EmptyState title="No file loads" body="Upload or schedule a file to see per-load analytics." />;
  return (
    <>
      <Kpis items={[
        { label: "Loads shown", value: fmt(batches.length) },
        { label: "Running now", value: fmt(data.running) },
        { label: "Current throughput", value: data.current_throughput_lps ? `${fmt(data.current_throughput_lps, 1)} /s` : "—" },
      ]} />
      <Panel title="By file load" sub="Each boarded file. Select a row for reconciliation, pre-flight, and exception counts." pad={false}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr>
          <th>Vendor</th><th>File</th><th>Type</th><th>Status</th>
          <th className="r">Rows</th><th className="r">Boarded</th><th className="r">Failed</th>
          <th className="r">Exceptions</th><th className="r">Open</th><th className="r">Loans/s</th><th className="r">When</th>
        </tr></thead><tbody>
          {batches.map((b) => (
            <tr key={b.batch_id} className={`click${sel === b.batch_id ? " selected" : ""}`} onClick={() => setSel(sel === b.batch_id ? null : b.batch_id)}>
              <td>{b.vendor_name || b.source_name || "—"}</td>
              <td className="mono">{b.filename}</td>
              <td><span className="chip">{b.load_type || "full"}</span></td>
              <td><Status s={b.status} /></td>
              <td className="r num">{fmt(b.processed)}{b.total_rows ? <span className="faint"> / {fmt(b.total_rows)}</span> : null}</td>
              <td className="r num">{fmt(b.loaded)}</td>
              <td className="r num">{fmt(b.failed)}</td>
              <td className="r num">{fmt(b.exceptions || 0)}</td>
              <td className="r num">{fmt(b.open_exceptions || 0)}</td>
              <td className="r num">{b.throughput_lps ? fmt(b.throughput_lps, 1) : "—"}</td>
              <td className="r num">{ago(b.finished_at || b.started_at || b.created_at)}</td>
            </tr>
          ))}
        </tbody></table></div>
      </Panel>
      {selected && <LoadDetail batch={selected} />}
    </>
  );
}

export default function Analytics() {
  const [tab, setTab] = useState("vendors");
  return (
    <>
      <PageHeader
        eyebrow="Run"
        title="Analytics"
        sub="What boarded, what is still held, and which seller is driving it."
        guideHref="#guide?path=execution&step=board"
      />
      <SummaryStrip />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "vendors", label: "By vendor" },
          { id: "loads", label: "By file load" },
        ]}
      />
      {tab === "vendors" && <ByVendor />}
      {tab === "loads" && <ByFileLoad />}
    </>
  );
}
