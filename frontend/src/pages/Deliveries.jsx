import React, { useEffect, useMemo, useState } from "react";
import { api, scoped } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, Loading, Kpis, Modal, Tabs, fmt, ago, human, useDialog, PageHeader, EmptyState, ActionBar } from "../ui.jsx";

const TZS = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "UTC", "Europe/London", "Asia/Kolkata"];
const DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const OPEN = ["expected", "late", "missed"];
const CELL = { received: "var(--pass)", received_late: "var(--warn)", late: "var(--warn)", missed: "var(--fail)", waived: "var(--line)", expected: "transparent" };

export const vlabel = (x) => (x.vendor_name && x.vendor_name !== x.source_name ? `${x.vendor_name} · ${x.source_name}` : x.vendor_name || x.source_name);

const until = (iso) => {
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  if (s < 0) return ago(iso);
  if (s < 3600) return `in ${Math.round(s / 60)} min`;
  if (s < 86400) return `in ${Math.round(s / 3600)} h`;
  return `in ${Math.round(s / 86400)} d`;
};

function cronFrom(f) {
  const [h, m] = (f.time || "06:00").split(":").map((x) => +x);
  switch (f.preset) {
    case "business": return `${m} ${h} * * MON-FRI`;
    case "daily": return `${m} ${h} * * *`;
    case "hours": return `${m} */${f.every || 4} * * *`;
    case "weekly": return `${m} ${h} * * ${f.dow || "MON"}`;
    case "monthly": return `${m} ${h} ${f.dom || 1} * *`;
    default: return f.cron || "";
  }
}

function presetOf(cron) {
  const p = (cron || "").split(" ");
  if (p.length !== 5) return { preset: "custom", cron };
  const time = /^\d+$/.test(p[0]) && /^\d+$/.test(p[1]) ? `${p[1].padStart(2, "0")}:${p[0].padStart(2, "0")}` : "06:00";
  if (p[2] === "*" && p[3] === "*" && p[4] === "MON-FRI") return { preset: "business", time };
  if (p[2] === "*" && p[3] === "*" && p[4] === "*" && p[1].startsWith("*/")) return { preset: "hours", every: p[1].slice(2), time: `00:${p[0].padStart(2, "0")}` };
  if (p[2] === "*" && p[3] === "*" && p[4] === "*") return { preset: "daily", time };
  if (p[2] === "*" && p[3] === "*" && DOW.includes(p[4])) return { preset: "weekly", time, dow: p[4] };
  if (/^\d+$/.test(p[2]) && p[3] === "*" && p[4] === "*") return { preset: "monthly", time, dom: p[2] };
  return { preset: "custom", cron };
}

function ScheduleEditor({ sources, initial, onClose, onSaved }) {
  const cfg = initial?.proposed || initial?.config || {};
  const vendorList = [...new Map(sources.filter((s) => s.active_mapping_id).map((s) => [s.vendor_id, s.vendor_name])).entries()];
  const [f, setF] = useState(() => ({
    source_id: initial?.source_id || sources.find((s) => s.active_mapping_id)?.source_id || "", name: initial?.name || "Daily file",
    ...presetOf(cfg.cron || "0 6 * * MON-FRI"), timezone: cfg.timezone || "America/New_York", calendar: cfg.calendar || "us_federal",
    holiday_rule: cfg.holiday_rule || "skip", grace_minutes: cfg.grace_minutes ?? 30, miss_after_minutes: cfg.miss_after_minutes ?? 240,
    window_before_minutes: cfg.window_before_minutes ?? 720, expected_files: cfg.expected_files ?? 1, filename_glob: cfg.filename_glob || "",
    load_type: cfg.load_type || "", pull: cfg.pull || null,
  }));
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const setPull = (k, v) => setF((x) => ({ ...x, pull: { ...(x.pull || {}), [k]: v } }));
  const cron = cronFrom(f);
  const [pv, setPv] = useState(null);
  const act = useAction();
  useEffect(() => {
    const t = setTimeout(async () => {
      const q = new URLSearchParams({ cron, timezone: f.timezone, calendar: f.calendar, holiday_rule: f.holiday_rule, n: "6" });
      try { setPv(await api(`/api/schedules/preview?${q}`)); } catch (e) { setPv({ valid: false, errors: [e.message] }); }
    }, 250);
    return () => clearTimeout(t);
  }, [cron, f.timezone, f.calendar, f.holiday_rule]);
  const save = async () => {
    const config = { cron, timezone: f.timezone, calendar: f.calendar, holiday_rule: f.holiday_rule, grace_minutes: +f.grace_minutes,
      miss_after_minutes: +f.miss_after_minutes, window_before_minutes: +f.window_before_minutes, expected_files: +f.expected_files,
      filename_glob: f.filename_glob || null, load_type: f.load_type || null,
      pull: f.pull?.protocol ? { ...f.pull, poll_minutes: +(f.pull.poll_minutes || 15), ...(f.pull.port ? { port: +f.pull.port } : {}) } : null };
    const body = { source_id: f.source_id, name: f.name, config };
    const r = await act(() => initial ? api(`/api/schedules/${initial.schedule_id}`, { method: "PUT", body }) : api("/api/schedules", { method: "POST", body }),
      initial ? "Change proposed. It takes effect when a different SME approves it." : "Schedule proposed. A different SME must approve it before it runs.");
    if (r) onSaved();
  };
  const lab = (id, text, el) => <label className="stack" style={{ gap: 4 }} htmlFor={id}><span className="eyebrow">{text}</span>{el}</label>;
  const pull = f.pull || {};
  return (
    <Modal title={initial ? `Change schedule · ${initial.name}` : "New delivery schedule"} onClose={onClose}
      footer={<><span className="faint" style={{ fontSize: ".8rem", marginRight: "auto" }}>Maker-checker: saving proposes; a different SME approves.</span>
        <button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!pv?.valid || !f.source_id} onClick={save}>Propose</button></>}>
      <div className="stack">
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {lab("sc-ven", "Vendor", <select id="sc-ven" className="input" value={sources.find((s) => s.source_id === f.source_id)?.vendor_id || ""} disabled={!!initial}
            onChange={(e) => set("source_id", sources.find((s) => s.active_mapping_id && s.vendor_id === e.target.value)?.source_id || "")}>
            {vendorList.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select>)}
          {lab("sc-src", "Feed", <select id="sc-src" className="input" value={f.source_id} disabled={!!initial} onChange={(e) => set("source_id", e.target.value)}>
            {sources.filter((s) => s.active_mapping_id && s.vendor_id === sources.find((x) => x.source_id === f.source_id)?.vendor_id).map((s) => <option key={s.source_id} value={s.source_id}>{s.name}</option>)}</select>)}
        </div>
        {lab("sc-name", "Schedule name", <input id="sc-name" className="input" value={f.name} onChange={(e) => set("name", e.target.value)} />)}
        <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
          {lab("sc-preset", "File is due", <select id="sc-preset" className="input" value={f.preset} onChange={(e) => set("preset", e.target.value)}>
            <option value="business">Every business day</option><option value="daily">Every day</option><option value="hours">Every N hours</option>
            <option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="custom">Custom (cron)</option></select>)}
          {f.preset === "custom" ? lab("sc-cron", "Cron (min hour dom mon dow)", <input id="sc-cron" className="input mono" value={f.cron || ""} onChange={(e) => set("cron", e.target.value)} />)
            : f.preset === "hours" ? lab("sc-every", "Every (hours)", <input id="sc-every" className="input" type="number" min={1} max={12} value={f.every || 4} onChange={(e) => set("every", e.target.value)} />)
              : lab("sc-time", "Due at (vendor local time)", <input id="sc-time" className="input" type="time" value={f.time} onChange={(e) => set("time", e.target.value)} />)}
          {f.preset === "weekly" && lab("sc-dow", "Day", <select id="sc-dow" className="input" value={f.dow || "MON"} onChange={(e) => set("dow", e.target.value)}>{DOW.map((d) => <option key={d}>{d}</option>)}</select>)}
          {f.preset === "monthly" && lab("sc-dom", "Day of month", <input id="sc-dom" className="input" type="number" min={1} max={28} value={f.dom || 1} onChange={(e) => set("dom", e.target.value)} />)}
          {lab("sc-tz", "Vendor timezone", <select id="sc-tz" className="input" value={f.timezone} onChange={(e) => set("timezone", e.target.value)}>{TZS.map((t) => <option key={t}>{t}</option>)}</select>)}
          {lab("sc-cal", "Business calendar", <select id="sc-cal" className="input" value={f.calendar} onChange={(e) => set("calendar", e.target.value)}>
            <option value="us_federal">US Federal Reserve holidays</option><option value="none">None (every matching day)</option></select>)}
          {f.calendar !== "none" && lab("sc-hol", "On a holiday", <select id="sc-hol" className="input" value={f.holiday_rule} onChange={(e) => set("holiday_rule", e.target.value)}>
            <option value="skip">No file expected</option><option value="next_business_day">Due next business day</option></select>)}
        </div>
        <div className={`callout ${pv && !pv.valid ? "t5" : ""}`} style={{ fontSize: ".84rem" }}>
          {pv?.valid ? <><b>{pv.describe}</b> · <span className="mono">{cron}</span><div className="row" style={{ marginTop: 6, gap: 6 }}>{pv.next.map((n) => <span key={n.utc} className="chip">{n.local}</span>)}</div></>
            : pv ? <span>{(pv.errors || []).join("; ")}</span> : "Checking…"}
        </div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
          {lab("sc-grace", "Late after (min)", <input id="sc-grace" className="input" type="number" min={0} value={f.grace_minutes} onChange={(e) => set("grace_minutes", e.target.value)} />)}
          {lab("sc-miss", "Missed after (min)", <input id="sc-miss" className="input" type="number" min={0} value={f.miss_after_minutes} onChange={(e) => set("miss_after_minutes", e.target.value)} />)}
          {lab("sc-win", "Accept early (min before)", <input id="sc-win" className="input" type="number" min={0} value={f.window_before_minutes} onChange={(e) => set("window_before_minutes", e.target.value)} />)}
          {lab("sc-n", "Files per delivery", <input id="sc-n" className="input" type="number" min={1} value={f.expected_files} onChange={(e) => set("expected_files", e.target.value)} />)}
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {lab("sc-glob", "Only files named like (optional)", <input id="sc-glob" className="input mono" placeholder="PCG_DELTA_*.csv" value={f.filename_glob} onChange={(e) => set("filename_glob", e.target.value)} />)}
          {lab("sc-lt", "Pulled files load as", <select id="sc-lt" className="input" value={f.load_type} onChange={(e) => set("load_type", e.target.value)}>
            <option value="">Vendor default</option><option value="full">Full tape</option><option value="incremental">Incremental changes</option><option value="snapshot">Full snapshot</option></select>)}
        </div>
        <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={!!f.pull?.protocol} onChange={(e) => set("pull", e.target.checked ? { protocol: "sftp", poll_minutes: 15, pattern: "*.csv" } : null)} />
          <b>Pull the file</b><span className="faint" style={{ fontSize: ".82rem" }}>(for vendors that don't drop files in the S3 raw zone)</span></label>
        {f.pull?.protocol && (
          <div className="stack callout">
            <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
              {lab("pl-proto", "Connector", <select id="pl-proto" className="input" value={pull.protocol} onChange={(e) => setPull("protocol", e.target.value)}>
                <option value="sftp">Vendor SFTP</option><option value="s3">Vendor S3 bucket</option><option value="local">Drop folder</option></select>)}
              {lab("pl-pat", "File pattern", <input id="pl-pat" className="input mono" value={pull.pattern || ""} onChange={(e) => setPull("pattern", e.target.value)} />)}
              {lab("pl-poll", "Poll every (min)", <input id="pl-poll" className="input" type="number" min={5} value={pull.poll_minutes || 15} onChange={(e) => setPull("poll_minutes", e.target.value)} />)}
            </div>
            {pull.protocol === "sftp" && <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
              {lab("pl-host", "Host (must be allow-listed)", <input id="pl-host" className="input mono" value={pull.host || ""} onChange={(e) => setPull("host", e.target.value)} />)}
              {lab("pl-port", "Port", <input id="pl-port" className="input" type="number" value={pull.port || 22} onChange={(e) => setPull("port", e.target.value)} />)}
              {lab("pl-path", "Remote folder", <input id="pl-path" className="input mono" value={pull.path || ""} onChange={(e) => setPull("path", e.target.value)} />)}
              {lab("pl-key", "Pinned host key (SHA256:…)", <input id="pl-key" className="input mono" value={pull.host_key_sha256 || ""} onChange={(e) => setPull("host_key_sha256", e.target.value)} />)}
              {lab("pl-sec", "Credentials secret (Secrets Manager)", <input id="pl-sec" className="input mono" placeholder="lbp/vendors/<vendor>" value={pull.secret_ref || ""} onChange={(e) => setPull("secret_ref", e.target.value)} />)}
            </div>}
            {pull.protocol === "s3" && <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
              {lab("pl-b", "Bucket (must be allow-listed)", <input id="pl-b" className="input mono" value={pull.bucket || ""} onChange={(e) => setPull("bucket", e.target.value)} />)}
              {lab("pl-pre", "Prefix", <input id="pl-pre" className="input mono" value={pull.prefix || ""} onChange={(e) => setPull("prefix", e.target.value)} />)}
              {lab("pl-role", "Cross-account role (optional)", <input id="pl-role" className="input mono" value={pull.role_arn || ""} onChange={(e) => setPull("role_arn", e.target.value)} />)}
            </div>}
            {pull.protocol === "local" && lab("pl-dir", "Folder under the drop root", <input id="pl-dir" className="input mono" value={pull.path || ""} onChange={(e) => setPull("path", e.target.value)} />)}
            <span className="faint" style={{ fontSize: ".78rem" }}>Passwords and keys are never stored here: the connector reads them from Secrets Manager at pull time. Remote files are never deleted or moved.</span>
          </div>)}
      </div>
    </Modal>
  );
}

function HistoryStrip({ items }) {
  const by = useMemo(() => {
    const m = {};
    items.forEach((d) => { const k = vlabel(d); (m[k] = m[k] || []).push(d); });
    Object.values(m).forEach((l) => l.sort((a, b) => a.due_at.localeCompare(b.due_at)));
    return m;
  }, [items]);
  if (!Object.keys(by).length) return <div className="empty">No delivery history yet.</div>;
  return (
    <div className="stack" style={{ gap: 6 }}>
      {Object.entries(by).map(([name, list]) => (
        <div key={name} className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
          <span style={{ width: 220, flex: "none", fontSize: ".84rem" }}>{name}</span>
          <span className="row" style={{ gap: 3, flexWrap: "nowrap", overflow: "hidden" }}>
            {list.slice(-28).map((d) => <span key={d.delivery_id} title={`${d.local_label} · ${human(d.status)}`} aria-label={`${d.local_label} ${human(d.status)}`}
              style={{ width: 14, height: 18, borderRadius: 3, background: CELL[d.status] || "transparent", border: "1px solid var(--line)", flex: "none" }} />)}
          </span>
        </div>))}
      <div className="legend">{[["received", "On time"], ["received_late", "Late, arrived"], ["missed", "Missed"], ["waived", "Waived"], ["expected", "Upcoming"]].map(([k, l]) =>
        <span key={k}><i style={{ background: CELL[k], border: "1px solid var(--line)" }} />{l}</span>)}</div>
    </div>
  );
}

export default function Deliveries({ persona }) {
  const board = useApi(scoped("/api/deliveries?days_back=2&days_ahead=2"), [], { poll: 15000 });
  const hist = useApi(scoped("/api/deliveries?days_back=30&days_ahead=0"));
  const sch = useApi(scoped("/api/schedules"), [], { poll: 30000 });
  const vend = useApi(scoped("/api/analytics/vendors"));
  const srcs = useApi(scoped("/api/sources"));
  const [edit, setEdit] = useState(null);
  const [filter, setFilter] = useState("attention");
  const [dialog, ask] = useDialog();
  const act = useAction();
  if (!board.data || !sch.data || !srcs.data) return <Loading error={board.error || sch.error || srcs.error} />;
  const canSched = canCap(persona, "schedules");
  const canApprove = canCap(persona, "approveSchedule");
  const all = board.data.deliveries;
  const shown = all.filter((d) => filter === "all" ? true : filter === "attention" ? ["late", "missed"].includes(d.status) || (d.status === "expected" && new Date(d.due_at) - Date.now() < 6 * 3600e3) : d.status === filter)
    .sort((a, b) => a.due_at.localeCompare(b.due_at));
  const reloadAll = () => { board.reload(); hist.reload(); sch.reload(); vend.reload(); };
  const done = (r) => { if (r) reloadAll(); return r; };
  const waive = (d) => ask({ kind: "reason", title: `Waive ${vlabel(d)} · ${d.local_label}`, confirmLabel: "Waive delivery",
    help: "Use this when the vendor has confirmed no file is coming for this window (vendor holiday, agreed skip). No further late or missed alerts are raised for it.",
    placeholder: "e.g. Vendor holiday confirmed by email, ticket OPS-1234", presets: ["Vendor holiday confirmed", "Agreed skip: no activity this cycle"],
    onSubmit: (reason) => act(() => api(`/api/deliveries/${d.delivery_id}/waive`, { method: "POST", body: { reason } }), "Waived. No further alerts for this delivery.").then(done) });
  const pull = (d) => ask({ kind: "confirm", title: `Pull from ${vlabel(d)} now`, confirmLabel: "Pull now",
    body: <span>Runs the vendor pull job now (SFTP with the pinned host key, or the vendor's S3). Fetched files land in the raw zone and board like any other delivery.</span>,
    onConfirm: () => act(() => api(`/api/schedules/${d.schedule_id}/pull-now`, { method: "POST" }), (r) => (r.glue_run_id || r.submitted ? "Pull started on Glue" : r.error ? `Pull failed: ${r.error}` : `${(r.fetched || []).length} file(s) fetched`)).then(done) });
  const decide = (x, approve) => approve
    ? ask({ kind: "confirm", title: `Approve schedule · ${x.name}`, confirmLabel: "Approve",
      body: <><span>{x.vendor_name || x.source_name} · proposed by <b>{x.proposed_by}</b></span>
        <dl className="kv"><dt>When</dt><dd>{x.describe}</dd><dt>Cron</dt><dd className="mono">{x.config?.cron && x.config.cron !== x.proposed?.cron ? `${x.config.cron} → ` : ""}{x.proposed?.cron}</dd>
          <dt>Timezone</dt><dd>{x.proposed?.timezone}</dd><dt>Late / missed</dt><dd>+{x.proposed?.grace_minutes}m / +{x.proposed?.miss_after_minutes}m</dd></dl></>,
      onConfirm: () => act(() => api(`/api/schedules/${x.schedule_id}/approve`, { method: "POST", body: { approve: true } }), "Approved. The schedule is live.").then(done) })
    : ask({ kind: "reason", title: `Reject schedule change · ${x.name}`, confirmLabel: "Reject", danger: true, label: "Comment for the proposer",
      onSubmit: (comment) => act(() => api(`/api/schedules/${x.schedule_id}/approve`, { method: "POST", body: { approve: false, comment } }), "Proposal rejected").then(done) });
  const pause = (x) => ask({ kind: "reason", title: `Pause ${x.name}`, confirmLabel: "Pause schedule",
    help: "While paused no deliveries are expected and no late or missed alerts are raised. Files that arrive are still processed.", presets: ["Vendor migration window", "Feed on hold pending contract renewal"],
    onSubmit: (reason) => act(() => api(`/api/schedules/${x.schedule_id}/status`, { method: "POST", body: { status: "paused", reason } }), "Paused: no deliveries expected, no alerts").then(done) });
  const pullSched = new Set(sch.data.schedules.filter((x) => x.kind === "pull" && x.status === "active").map((x) => x.schedule_id));
  const vendors = vend.data?.vendors || [];
  const waiting = vendors.reduce((a, v) => a + (v.waiting_files || 0), 0);
  const due24 = all.filter((d) => d.status === "expected" && new Date(d.due_at) - Date.now() < 24 * 3600e3 && new Date(d.due_at) > Date.now()).length;
  return (
    <>
      <PageHeader
        eyebrow="Setup"
        title="Vendor Deliveries"
        sub="When each vendor’s file is due, what arrived, and what is late. The scheduler watches deadlines, pulls when vendors don’t push, and alerts on late or missing files."
        guideHref="#guide?path=setup&step=schedule"
        primary={canSched ? <button type="button" className="btn primary" onClick={() => setEdit({})}>New schedule</button> : null}
      />
      <Kpis items={[
        { label: "Due in next 24 h", value: due24 },
        { label: "Late or missed", value: all.filter((d) => ["late", "missed"].includes(d.status)).length, detail: "open, not waived" },
        { label: "Files waiting in sequence", value: waiting, detail: "held behind an earlier file" },
        { label: "On-time (30 days)", value: (() => { const r = vendors.filter((v) => v.on_time_pct !== null); return r.length ? `${fmt(r.reduce((a, v) => a + v.on_time_pct, 0) / r.length, 0)}%` : "—"; })() },
      ]} />
      <div className="split wide">
        <Panel title="Delivery board" sub="Today and the next 48 hours, in each vendor's own timezone" pad={false}
          actions={<Tabs value={filter} onChange={setFilter} tabs={[{ id: "attention", label: "Needs attention" }, { id: "expected", label: "Expected" }, { id: "received", label: "Received" }, { id: "all", label: "All" }]} />}>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Due</th><th>Vendor · feed</th><th>Status</th><th>File(s)</th><th></th></tr></thead>
            <tbody>{shown.length === 0 ? <tr><td colSpan={5}><EmptyState title={filter === "attention" ? "Nothing needs attention" : "No deliveries in this view"} body="Switch the board filter, or open Schedules below." /></td></tr> : shown.map((d) => (
              <tr key={d.delivery_id}>
                <td><b className="num">{d.local_label}</b><div className="faint" style={{ fontSize: ".76rem" }}>{until(d.due_at)}</div></td>
                <td>{d.vendor_name || d.source_name}<div className="faint" style={{ fontSize: ".76rem" }}>{d.vendor_name && d.vendor_name !== d.source_name ? `${d.source_name} · ` : ""}{d.schedule_name}</div></td>
                <td><Status s={d.status} />{d.last_pull_error && <div className="faint" style={{ fontSize: ".74rem", color: "var(--fail)" }} title={d.last_pull_error}>pull failing ×{d.pull_attempts}</div>}
                  {d.waive_reason && <div className="faint" style={{ fontSize: ".74rem" }}>{d.waived_by}: {d.waive_reason}</div>}</td>
                <td>{d.batches.length ? d.batches.map((b) => <div key={b.batch_id} className="row" style={{ gap: 4 }}><span className="mono" style={{ fontSize: ".78rem" }}>{b.filename}</span>{b.sequence && <span className="chip">#{b.sequence}</span>}<Status s={b.status} /></div>) : <span className="faint">—</span>}</td>
                <td className="r"><span className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
                  {canSched && OPEN.includes(d.status) && pullSched.has(d.schedule_id) && <button className="btn sm" onClick={() => pull(d)}>Pull now…</button>}
                  {canSched && OPEN.includes(d.status) && <button className="btn sm" onClick={() => waive(d)}>Waive…</button>}</span></td>
              </tr>))}</tbody>
          </table></div>
        </Panel>
        <div className="stack">
          <Panel title="Last 30 days" sub="One square per expected delivery">{hist.data ? <HistoryStrip items={hist.data.deliveries} /> : <Loading />}</Panel>
          <Panel title="Vendor freshness" pad={false}>
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Vendor · feed</th><th>Mode</th><th className="r">Last file</th><th className="r">Applied #</th><th className="r">On time</th></tr></thead>
              <tbody>{vendors.map((v) => <tr key={v.source_id}><td>{v.vendor_name || v.name}{v.vendor_name && v.vendor_name !== v.name && <div className="faint" style={{ fontSize: ".74rem" }}>{v.name}</div>}{v.waiting_files > 0 && <span className="pill warn" style={{ marginLeft: 6 }}>{v.waiting_files} waiting</span>}</td>
                <td><span className="chip">{human(v.load_type)}</span></td><td className="r faint">{ago(v.last_arrival)}</td><td className="r num" style={{ whiteSpace: "nowrap" }}>{v.last_sequence ?? "—"}</td>
                <td className="r num">{v.on_time_pct === null ? "—" : `${v.on_time_pct}%`}</td></tr>)}</tbody>
            </table></div>
          </Panel>
        </div>
      </div>
      <Panel title="Schedules" sub="Timetables live in the application (per-vendor timezone and business calendar); changes need a second approver" pad={false}>
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Schedule</th><th>Vendor · feed</th><th>When</th><th>Channel</th><th>Next due</th><th className="r">On time (30 d)</th><th>Status</th><th></th></tr></thead>
          <tbody>{sch.data.schedules.length === 0 ? <tr><td colSpan={8}><EmptyState title="No schedules yet" body="Add one per vendor feed that needs a timetable." action={canSched ? <button type="button" className="btn primary" onClick={() => setEdit({})}>New schedule</button> : null} /></td></tr> : sch.data.schedules.map((x) => {
            const cfg = x.config || x.proposed || {};
            const pending = !!x.proposed;
            const canDecide = canApprove && persona.id !== x.proposed_by;
            return (
              <tr key={x.schedule_id}>
                <td><b>{x.name}</b><div className="faint mono" style={{ fontSize: ".72rem" }}>v{x.version} · {x.schedule_id}</div></td>
                <td>{x.vendor_name || x.source_name}{x.vendor_name && x.vendor_name !== x.source_name && <div className="faint" style={{ fontSize: ".74rem" }}>{x.source_name}</div>}</td>
                <td>{x.describe}<div className="faint" style={{ fontSize: ".76rem" }}>{cfg.timezone} · {cfg.calendar === "us_federal" ? "Fed holidays" : "every day"} · late +{cfg.grace_minutes}m · missed +{cfg.miss_after_minutes}m</div></td>
                <td><span className="chip">{x.kind === "pull" ? `pull · ${cfg.pull?.protocol}` : "push to S3"}</span></td>
                <td className="num">{x.next_due_local || "—"}</td>
                <td className="r num">{x.stats_30d?.on_time_pct ?? "—"}{x.stats_30d?.on_time_pct != null ? "%" : ""}</td>
                <td><Status s={x.status} />{pending && x.status !== "pending_approval" && <span className="pill warn" style={{ marginLeft: 4 }}>change pending</span>}
                  {pending && <div className="faint" style={{ fontSize: ".74rem" }}>proposed by {x.proposed_by}{x.proposed?.cron && x.config && x.proposed.cron !== x.config.cron ? ` · ${x.config.cron} → ${x.proposed.cron}` : ""}</div>}</td>
                <td className="r"><ActionBar
                  primary={pending && canDecide ? <button type="button" className="btn sm primary" onClick={() => decide(x, true)}>Approve…</button>
                    : canSched && x.status === "paused" ? <button type="button" className="btn sm primary" onClick={() => act(() => api(`/api/schedules/${x.schedule_id}/status`, { method: "POST", body: { status: "active" } }), "Resumed").then(reloadAll)}>Resume</button>
                    : null}
                >
                  {pending && canDecide && <button type="button" className="btn sm" onClick={() => decide(x, false)}>Reject…</button>}
                  {pending && canApprove && persona.id === x.proposed_by && <span className="faint" style={{ fontSize: ".74rem" }}>Awaiting another approver</span>}
                  {canSched && x.status === "active" && <button type="button" className="btn sm" onClick={() => pause(x)}>Pause…</button>}
                  {canSched && ["active", "paused", "pending_approval"].includes(x.status) && <button type="button" className="btn sm" onClick={() => setEdit(x)}>Change…</button>}
                </ActionBar></td>
              </tr>);
          })}</tbody>
        </table></div>
      </Panel>
      {edit && <ScheduleEditor sources={srcs.data.sources} initial={edit.schedule_id ? edit : null} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reloadAll(); }} />}
      {dialog}
    </>
  );
}
