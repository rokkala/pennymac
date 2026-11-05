import React from "react";
import { DEMO, getPersona, scoped } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, Panel, Kpis, fmt, fmtCompact, fmtMoney, Loading, Tier, TIER_NAMES, PageHeader, QueueCard, EmptyState } from "../ui.jsx";
import { Lines, HBars, VBars } from "../charts.jsx";
import { buildWorkCards } from "../workToday.js";

export default function Overview({ go, persona }) {
  const ex = useApi(scoped("/api/analytics/executive"));
  const ea = useApi(scoped("/api/analytics/exceptions"));
  const cfg = useApi("/api/config");
  const { data: summary } = useApi(scoped("/api/exceptions/summary"), [], { poll: 15000 });
  const { data: ntf } = useApi("/api/notifications", [persona?.id], { poll: 20000 });
  if (!ex.data || !ea.data) return <Loading error={ex.error || ea.error} />;
  const e = ex.data, a = ea.data;
  const capX = e.projected_capacity_24h / e.target_24h;
  const who = persona || getPersona();
  const showDemo = !DEMO && cfg.data?.demo && cfg.data?.demo_setup?.available && canCap(who, "demoSetup");
  const openExceptions = summary
    ? Object.values(summary.tiers).reduce((acc, t) => acc + (t.open || 0) + (t.pending_checker || 0) + (t.escalated || 0), 0)
    : (e.open_blocking_exceptions || 0);
  const ntfUnread = ntf?.unread ?? (ntf?.notifications || []).filter((x) => !x.read_at).length;
  const cards = buildWorkCards({
    canWorkExceptions: canCap(who, "workExceptions"),
    openExceptions,
    canReviewRules: canCap(who, "authorRules") || canCap(who, "editRules"),
    ntfUnread,
    canDemoSetup: showDemo,
    showMappingLink: canCap(who, "editMapping") || canCap(who, "approveMapping") || canCap(who, "editVendors") || canCap(who, "publishConfig"),
    showPolicyLink: canCap(who, "editPolicy") || canCap(who, "readAudit"),
  });

  let primary = <button type="button" className="btn primary" onClick={() => go("guide")}>Walk the product</button>;
  if (canCap(who, "workExceptions")) {
    primary = <button type="button" className="btn primary" onClick={() => go("exceptions")}>Work exceptions</button>;
  } else if (canCap(who, "upload")) {
    primary = <button type="button" className="btn primary" onClick={() => go("imports")}>Upload a file</button>;
  }
  const secondary = (
    <>
      <button type="button" className="btn" onClick={() => go("guide")}>How it works</button>
      {showDemo && <button type="button" className="btn" onClick={() => go("governance")}>Demo setup…</button>}
      {canCap(who, "upload") && canCap(who, "workExceptions") && (
        <button type="button" className="btn" onClick={() => go("imports")}>Upload a file</button>
      )}
    </>
  );

  return (
    <>
      <PageHeader
        eyebrow="Home"
        title="Loan boarding"
        sub="Loans mapped from every vendor feed, validated against the SSE rule set, and boarded in micro-batches. Failures route by confidence and risk tier."
        primary={primary}
        secondary={secondary}
      />
      <Kpis items={[
        { label: "Loans boarded", value: fmt(e.loans_boarded_total), detail: `${fmtMoney(e.upb_boarded)} UPB` },
        { label: "Straight-through", value: `${fmt(e.straight_through_rate, 1)}%`, detail: `of ${fmt(e.loans_processed)} processed` },
        { label: "Blocking exceptions", value: fmt(e.open_blocking_exceptions), detail: "holding loans out of SSE" },
        { label: "Compliance blocks", value: fmt(e.compliance_blocks), detail: "OFAC / fraud · T5" },
        { label: "Projected capacity", value: `${fmtCompact(e.projected_capacity_24h)}/24h`, detail: `${fmt(capX, 0)}× the 1M target at peak` },
      ]} />

      <section className="stack" style={{ gap: 12 }}>
        <div>
          <span className="eyebrow">Your work today</span>
          <h2 style={{ fontSize: "1.08rem", marginTop: 4 }}>Queues for {who.label}</h2>
        </div>
        {cards.length === 0 ? (
          <EmptyState
            title="You’re caught up"
            body="No open queues for your role right now."
            action={<button type="button" className="btn primary" onClick={() => go("guide")}>Walk the product</button>}
          />
        ) : (
          <div className="queue-grid">
            {cards.map((c) => (
              <QueueCard
                key={c.id}
                title={c.title}
                detail={c.detail}
                cta={c.cta}
                onClick={() => go(c.page, c.qs || "")}
              />
            ))}
          </div>
        )}
      </section>

      <div className="grid g-side">
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
      <div className="grid g2">
        <Panel title="Top failing rules" sub="Exceptions by rule">
          <HBars items={a.by_rule.slice(0, 8).map((r) => ({ label: `${r.rule_id} ${r.rule_name}`, value: r.count }))} />
        </Panel>
        <Panel title="Portfolio boarded" sub="Loans by investor category">
          <HBars items={Object.entries(e.by_investor).sort((x, y) => y[1] - x[1]).map(([k, v]) => ({ label: k, value: v }))} color="var(--chart-3)" />
        </Panel>
      </div>
    </>
  );
}
