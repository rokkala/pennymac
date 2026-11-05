import React, { useEffect, useMemo, useState } from "react";
import { DEMO, api, getPersona, scoped } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Kpis, fmt, fmtCompact, fmtMoney, Loading, Tier, TIER_NAMES, PageHeader, QueueCard, EmptyState, Status, Modal, ago, useDialog } from "../ui.jsx";
import { Lines, HBars, VBars } from "../charts.jsx";
import { buildWorkCards } from "../workToday.js";
import { buildAttentionRows, buildLoadHealth } from "../loadDesk.js";
import { BatchModal } from "./Imports.jsx";

function DeliveryWatch({ delivery, persona, onClose, onOpenBatch, go, onChanged }) {
  const act = useAction();
  const [dialog, ask] = useDialog();
  const d = delivery;
  const canSched = canCap(persona, "schedules");
  const batchId = (d.batch_ids || [])[0] || d.batches?.[0]?.batch_id;
  const pull = () => ask({
    kind: "confirm", title: `Pull now · ${d.schedule_name || d.source_name}`, confirmLabel: "Pull now",
    body: <span>Fetch the vendor file for this window if a pull channel is configured.</span>,
    onConfirm: () => act(
      () => api(`/api/schedules/${d.schedule_id}/pull-now`, { method: "POST" }),
      (r) => (r.glue_run_id || r.submitted ? "Pull started" : r.error ? `Pull failed: ${r.error}` : `${(r.fetched || []).length} file(s) fetched`),
    ).then((r) => { onChanged?.(); return r; }),
  });
  const waive = () => ask({
    kind: "reason", title: `Waive · ${d.schedule_name || d.source_name}`, confirmLabel: "Waive",
    help: "Marks this expected window as waived. Audited.",
    placeholder: "e.g. Vendor holiday confirmed, ticket OPS-1234",
    onSubmit: (reason) => act(
      () => api(`/api/deliveries/${d.delivery_id}/waive`, { method: "POST", body: { reason } }),
      "Delivery waived",
    ).then((r) => { onChanged?.(); onClose(); return r; }),
  });
  return (
    <>
      <Modal
        title={<span className="row" style={{ gap: 8 }}><span>{d.schedule_name || d.source_name}</span><Status s={d.status} /></span>}
        sub={[d.vendor_name, d.source_name, d.local_label].filter(Boolean).join(" · ")}
        size="md"
        onClose={onClose}
        footer={(
          <>
            <button type="button" className="btn" onClick={onClose}>Close</button>
            <button type="button" className="btn" onClick={() => go("deliveries")}>Open Vendor Deliveries</button>
            {batchId && <button type="button" className="btn primary" onClick={() => onOpenBatch(batchId)}>Watch batch</button>}
          </>
        )}
      >
        <dl className="kv">
          <dt>Status</dt><dd><Status s={d.status} /></dd>
          <dt>Due</dt><dd>{d.local_label || d.due_at}{d.due_at && <span className="faint"> · {ago(d.due_at)}</span>}</dd>
          <dt>Schedule</dt><dd>{d.schedule_name || "—"}</dd>
          <dt>Feed</dt><dd>{d.vendor_name && d.vendor_name !== d.source_name ? `${d.vendor_name} · ${d.source_name}` : (d.source_name || "—")}</dd>
          {d.last_pull_error && <><dt>Last pull</dt><dd style={{ color: "var(--fail)" }}>{d.last_pull_error}{d.pull_attempts ? ` · ×${d.pull_attempts}` : ""}</dd></>}
          {d.waive_reason && <><dt>Waived</dt><dd className="faint">{d.waived_by}: {d.waive_reason}</dd></>}
        </dl>
        {canSched && ["expected", "late", "missed"].includes(d.status) && (
          <div className="row" style={{ marginTop: 12, gap: 8 }}>
            <button type="button" className="btn sm primary" onClick={pull}>Pull now…</button>
            <button type="button" className="btn sm" onClick={waive}>Waive…</button>
          </div>
        )}
        {!batchId && <p className="faint" style={{ fontSize: ".84rem", marginTop: 12 }}>No file registered for this window yet. Pull if the vendor uses SFTP, or wait for S3 drop / upload.</p>}
      </Modal>
      {dialog}
    </>
  );
}

export default function Overview({ go, persona }) {
  const who = persona || getPersona();
  const batchesApi = useApi(scoped("/api/batches"), [], { poll: 2000 });
  const delivApi = useApi(scoped("/api/deliveries?days_back=2&days_ahead=2"), [], { poll: 15000 });
  const ex = useApi(scoped("/api/analytics/executive"));
  const ea = useApi(scoped("/api/analytics/exceptions"));
  const cfg = useApi("/api/config");
  const { data: summary } = useApi(scoped("/api/exceptions/summary"), [], { poll: 15000 });
  const { data: ntf } = useApi("/api/notifications", [who?.id], { poll: 20000 });
  const [batchId, setBatchId] = useState(null);
  const [watch, setWatch] = useState(null);

  const batches = batchesApi.data?.batches || [];
  const deliveries = delivApi.data?.deliveries || [];
  const openExceptions = summary
    ? Object.values(summary.tiers).reduce((acc, t) => acc + (t.open || 0) + (t.pending_checker || 0) + (t.escalated || 0), 0)
    : (ex.data?.open_blocking_exceptions || 0);
  const health = useMemo(
    () => buildLoadHealth({ batches, deliveries, openExceptions }),
    [batches, deliveries, openExceptions],
  );
  const attention = useMemo(() => buildAttentionRows({ batches, deliveries }), [batches, deliveries]);

  useEffect(() => {
    const q = new URLSearchParams((window.location.hash.split("?")[1] || ""));
    if (q.get("focus") === "attention") {
      document.getElementById("desk-attention")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [attention.length]);

  const showDemo = !DEMO && cfg.data?.demo && cfg.data?.demo_setup?.available && canCap(who, "demoSetup");
  const ntfUnread = ntf?.unread ?? (ntf?.notifications || []).filter((x) => !x.read_at).length;
  const cards = buildWorkCards({
    canWorkExceptions: canCap(who, "workExceptions"),
    openExceptions,
    canReviewRules: canCap(who, "authorRules") || canCap(who, "editRules"),
    ntfUnread,
    canDemoSetup: showDemo,
    showMappingLink: canCap(who, "editMapping") || canCap(who, "approveMapping") || canCap(who, "editVendors") || canCap(who, "publishConfig"),
    showPolicyLink: canCap(who, "editPolicy") || canCap(who, "readAudit"),
    lateDeliveries: health.late + health.missed,
    runningBatches: health.running,
    stuckBatches: health.stuck,
  });

  let primary = <button type="button" className="btn primary" onClick={() => go("deliveries")}>Vendor deliveries</button>;
  if (canCap(who, "upload")) {
    primary = <button type="button" className="btn primary" onClick={() => go("imports")}>Upload a file</button>;
  } else if (canCap(who, "workExceptions") && openExceptions > 0) {
    primary = <button type="button" className="btn primary" onClick={() => go("exceptions")}>Work exceptions</button>;
  }

  const openRow = (row) => {
    if (row.kind === "batch" || (row.batchId && row.kind === "delivery" && ["running", "paused", "blocked", "waiting", "out_of_order", "failed"].includes(
      batches.find((b) => b.batch_id === row.batchId)?.status,
    ))) {
      setWatch(null);
      setBatchId(row.batchId || row.id.replace(/^batch:/, ""));
      return;
    }
    if (row.kind === "delivery") {
      const d = row.delivery || deliveries.find((x) => x.delivery_id === row.deliveryId);
      if (d) setWatch(d);
      return;
    }
  };

  const deskReady = batchesApi.data && delivApi.data;
  const e = ex.data;
  const a = ea.data;

  return (
    <>
      <PageHeader
        eyebrow="Home"
        title="Boarding desk"
        sub="Scheduled loads and in-flight batches for this vendor scope. Open a row to watch progress or act on a late window."
        primary={primary}
        secondary={(
          <>
            <button type="button" className="btn" onClick={() => go("imports")}>Import Monitor</button>
            <button type="button" className="btn" onClick={() => go("deliveries")}>Deliveries</button>
            <button type="button" className="btn" onClick={() => go("guide")}>How it works</button>
          </>
        )}
      />

      {!deskReady ? <Loading error={batchesApi.error || delivApi.error} /> : (
        <>
          <div role="status" aria-atomic="true" aria-live="polite">
            <Kpis items={[
              { label: "Running", value: health.running, detail: "batches in flight" },
              { label: "Late", value: health.late, detail: "delivery windows" },
              { label: "Missed", value: health.missed, detail: "past miss threshold" },
              { label: "Stuck", value: health.stuck, detail: "blocked · waiting · paused" },
              { label: "Exceptions", value: fmt(health.openExceptions), detail: "open / checker / escalated" },
            ]} />
          </div>

          <div id="desk-attention">
            <Panel
              title="Needs attention"
              sub="Late and missed schedules, then stuck and running batches — click a row to monitor"
              pad={false}
              actions={attention.length > 0 ? <span className="faint" style={{ fontSize: ".8rem" }}>{attention.length} item{attention.length === 1 ? "" : "s"}</span> : null}
            >
              {attention.length === 0 ? (
                <EmptyState
                  title="All clear on the desk"
                  body="No late deliveries or active batches in this scope. Upload a file or check the full delivery board."
                  action={(
                    <span className="row" style={{ gap: 8 }}>
                      {canCap(who, "upload") && <button type="button" className="btn primary" onClick={() => go("imports")}>Upload a file</button>}
                      <button type="button" className="btn" onClick={() => go("deliveries")}>Vendor deliveries</button>
                    </span>
                  )}
                />
              ) : (
                <div className="tbl-wrap">
                  <table className="tbl">
                    <thead>
                      <tr><th>What</th><th>Where</th><th>Status</th><th>Detail</th></tr>
                    </thead>
                    <tbody>
                      {attention.map((row) => (
                        <tr key={row.id} className="click" onClick={() => openRow(row)}>
                          <td>
                            <b>{row.title}</b>
                            <div className="faint" style={{ fontSize: ".76rem" }}>{row.kind === "batch" ? "Batch" : "Scheduled delivery"}</div>
                          </td>
                          <td>{row.subtitle || "—"}</td>
                          <td><Status s={row.status} /></td>
                          <td className="faint" style={{ fontSize: ".84rem" }}>{row.meta || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}

      <section className="stack" style={{ gap: 12 }}>
        <div>
          <span className="eyebrow">Your work today</span>
          <h2 style={{ fontSize: "1.08rem", marginTop: 4 }}>Queues for {who.label}</h2>
        </div>
        {cards.length === 0 ? (
          <EmptyState
            title="You’re caught up"
            body="No open queues for your role right now."
            action={<button type="button" className="btn" onClick={() => go("guide")}>Walk the product</button>}
          />
        ) : (
          <div className="queue-grid">
            {cards.map((c) => (
              <QueueCard
                key={c.id}
                title={c.title}
                detail={c.detail}
                cta={c.cta}
                onClick={() => {
                  if (c.page === "overview") {
                    document.getElementById("desk-attention")?.scrollIntoView({ behavior: "smooth", block: "start" });
                    return;
                  }
                  go(c.page, c.qs || "");
                }}
              />
            ))}
          </div>
        )}
      </section>

      {e && a && (
        <details className="panel" style={{ padding: "12px 16px" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Portfolio signal</summary>
          <p className="faint" style={{ fontSize: ".84rem", margin: "6px 0 12px" }}>Executive KPIs and exception charts — deep dive stays on Analytics.</p>
          <Kpis items={[
            { label: "Loans boarded", value: fmt(e.loans_boarded_total), detail: `${fmtMoney(e.upb_boarded)} UPB` },
            { label: "Straight-through", value: `${fmt(e.straight_through_rate, 1)}%`, detail: `of ${fmt(e.loans_processed)} processed` },
            { label: "Blocking exceptions", value: fmt(e.open_blocking_exceptions), detail: "holding loans out of SSE" },
            { label: "Projected capacity", value: `${fmtCompact(e.projected_capacity_24h)}/24h`, detail: `${fmt(e.projected_capacity_24h / e.target_24h, 0)}× the 1M target at peak` },
          ]} />
          <div className="grid g-side" style={{ marginTop: 12 }}>
            {a.trend.length >= 3 ? (
              <Panel title="Exceptions over time" sub="Created vs resolved per day, last 30 days">
                <Lines x={a.trend.map((t) => t.date)} series={[
                  { name: "Created", color: "var(--chart-2)", values: a.trend.map((t) => t.created) },
                  { name: "Resolved", color: "var(--chart-1)", values: a.trend.map((t) => t.resolved) },
                ]} />
              </Panel>
            ) : (
              <Panel title="Exception flow today" sub="Daily trend appears once there are three days of history">
                <HBars items={[
                  { label: "Raised by rules", value: a.total, color: "var(--chart-2)" },
                  { label: "Resolved by reviewers", value: a.by_status.resolved || 0 },
                  { label: "Auto-applied (T1)", value: a.auto_applied },
                  { label: "Still open", value: a.open, color: "var(--chart-3)" },
                ]} />
              </Panel>
            )}
            <Panel title="Where exceptions land" sub="Confidence × risk routing" actions={<button type="button" className="btn sm" onClick={() => go("exceptions")}>Open queues</button>}>
              <VBars items={a.by_tier.map((t) => ({ label: t.tier, title: `${t.tier} · ${TIER_NAMES[t.tier]}`, value: t.count, color: `var(--t${t.tier[1]})` }))} />
              <div className="row" style={{ marginTop: 8, gap: 12, fontSize: ".78rem" }}>
                {a.by_tier.map((t) => <span key={t.tier} className="row" style={{ gap: 4 }}><Tier t={t.tier} />{t.label}</span>)}
              </div>
            </Panel>
          </div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <Panel title="Top failing rules" sub="Exceptions by rule">
              <HBars items={a.by_rule.slice(0, 8).map((r) => ({ label: `${r.rule_id} ${r.rule_name}`, value: r.count }))} />
            </Panel>
            <Panel title="Portfolio boarded" sub="Loans by investor category">
              <HBars items={Object.entries(e.by_investor).sort((x, y) => y[1] - x[1]).map(([k, v]) => ({ label: k, value: v }))} color="var(--chart-3)" />
            </Panel>
          </div>
        </details>
      )}

      {batchId && (
        <BatchModal
          id={batchId}
          persona={who}
          go={go}
          onClose={() => setBatchId(null)}
          nav={(() => {
            const ids = attention.filter((r) => r.batchId).map((r) => r.batchId);
            const uniq = [...new Set(ids)];
            const idx = uniq.indexOf(batchId);
            return {
              label: idx >= 0 ? `${idx + 1} of ${uniq.length}` : "",
              onPrev: idx > 0 ? () => setBatchId(uniq[idx - 1]) : null,
              onNext: idx >= 0 && idx < uniq.length - 1 ? () => setBatchId(uniq[idx + 1]) : null,
            };
          })()}
        />
      )}
      {watch && (
        <DeliveryWatch
          delivery={watch}
          persona={who}
          onClose={() => setWatch(null)}
          go={go}
          onChanged={() => { delivApi.reload(); batchesApi.reload(); }}
          onOpenBatch={(id) => { setWatch(null); setBatchId(id); }}
        />
      )}
    </>
  );
}
