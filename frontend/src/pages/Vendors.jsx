import React, { useState } from "react";
import { api, scoped } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, Modal, Loading, Tabs, Kpis, fmt, ago, human, Tier, Field, PageHeader, ActionBar } from "../ui.jsx";
import { FeedConfigChip } from "./FeedConfig.jsx";
import { BatchModal } from "./Imports.jsx";

export const VENDOR_TYPES = { correspondent: "Correspondent", bulk_seller: "Bulk seller", sub_servicer: "Sub-servicer", retail: "Retail channel", other: "Other" };
const LT = { full: "full tapes", incremental: "change files", snapshot: "snapshots" };

export function VendorModal({ initial, onClose, onSaved }) {
  const [f, setF] = useState({ name: initial?.name || "", vendor_type: initial?.vendor_type || "correspondent", legal_name: initial?.legal_name || "",
    external_ref: initial?.external_ref || "", notes: initial?.notes || "", contact: { name: "", email: "", phone: "", ...(initial?.contact || {}) } });
  const act = useAction();
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    const r = await act(() => initial ? api(`/api/vendors/${initial.vendor_id}`, { method: "PUT", body: f }) : api("/api/vendors", { method: "POST", body: f }),
      initial ? "Vendor updated" : "Vendor created. Add its first feed from a sample file.");
    if (r) onSaved(r);
  };
  const lab = (id, t, el) => <label className="stack" style={{ gap: 4 }} htmlFor={id}><span className="eyebrow">{t}</span>{el}</label>;
  return (
    <Modal title={initial ? `Edit ${initial.name}` : "Onboard a vendor"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!f.name} onClick={save}>{initial ? "Save" : "Create vendor"}</button></>}>
      <div className="stack">
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {lab("vn-name", "Vendor name", <input id="vn-name" className="input" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Westside Lending" />)}
          {lab("vn-type", "Type", <select id="vn-type" className="input" value={f.vendor_type} onChange={(e) => set("vendor_type", e.target.value)}>
            {Object.entries(VENDOR_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>)}
          {lab("vn-legal", "Legal name", <input id="vn-legal" className="input" value={f.legal_name} onChange={(e) => set("legal_name", e.target.value)} />)}
          {lab("vn-ref", "Seller / counterparty number", <input id="vn-ref" className="input mono" value={f.external_ref} onChange={(e) => set("external_ref", e.target.value)} />)}
        </div>
        <span className="eyebrow">Delivery contact (who to call when a file is late or wrong)</span>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
          {["name", "email", "phone"].map((k) => <input key={k} aria-label={`Contact ${k}`} className="input" placeholder={k} value={f.contact[k] || ""} onChange={(e) => set("contact", { ...f.contact, [k]: e.target.value })} />)}
        </div>
        {lab("vn-notes", "Notes", <textarea id="vn-notes" className="input" rows={2} value={f.notes} onChange={(e) => set("notes", e.target.value)} />)}
      </div>
    </Modal>
  );
}

export function FeedModal({ vendor, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const go = async () => {
    setBusy(true);
    const f = new FormData(); f.append("name", name); f.append("file", file); f.append("vendor_id", vendor.vendor_id);
    const r = await act(() => api("/api/sources", { method: "POST", form: f }), (x) => `Profiled and mapped: ${x.stats?.auto_mapped_pct}% auto-mapped`);
    setBusy(false);
    if (r) onCreated(r.mapping_id);
  };
  return (
    <Modal title={`Add a feed for ${vendor.name}`} onClose={onClose} footer={<button className="btn primary" disabled={!name || !file || busy} onClick={go}>{busy ? "Profiling…" : "Profile and suggest mappings"}</button>}>
      <p className="muted">A feed is one file layout this vendor sends (for example a boarding tape, a daily change file or a monthly snapshot). Each feed has its own mapping, delivery profile and schedule. Upload a sample: IntelliMap profiles every column, flags PII and proposes the mapping to SSE.</p>
      <label className="stack" style={{ gap: 4 }} htmlFor="fd-name"><span className="eyebrow">Feed name</span>
        <input id="fd-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Boarding tape, Daily changes" /></label>
      <label className="stack" style={{ gap: 4 }} htmlFor="fd-file"><span className="eyebrow">Sample file</span>
        <input id="fd-file" type="file" accept=".csv,.txt,.xlsx,.dat,.psv" onChange={(e) => setFile(e.target.files[0])} /></label>
    </Modal>
  );
}

export function VendorList({ persona, onOpen, onCreated }) {
  const v = useApi("/api/vendors");
  const [create, setCreate] = useState(false);
  if (!v.data) return <Loading error={v.error} />;
  const list = v.data.vendors;
  return (
    <>
      <PageHeader
        eyebrow="Setup"
        title="Vendors & Mapping"
        sub="Each vendor owns one or more feeds. Every feed has mapping versions, a delivery profile, and a schedule — configuration, not a code change."
        guideHref="#guide?path=setup&step=vendor"
        primary={canCap(persona, "editVendors") ? <button type="button" className="btn primary" onClick={() => setCreate(true)}>Onboard vendor</button> : null}
      />
      <Kpis items={[
        { label: "Vendors", value: list.length, detail: `${list.filter((x) => x.status === "active").length} active · ${list.filter((x) => x.status === "onboarding").length} onboarding` },
        { label: "Feeds", value: list.reduce((a, x) => a + x.feeds, 0), detail: `${list.reduce((a, x) => a + x.live_feeds, 0)} live` },
        { label: "Active loans", value: fmt(list.reduce((a, x) => a + x.active_loans, 0)) },
        { label: "Needing attention", value: list.filter((x) => x.late_or_missed || x.attention_files || x.pending_mapping_review).length, detail: "late files, held files or mappings to review" },
      ]} />
      <Panel title="Vendors" pad={false}>
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Vendor</th><th>Type</th><th>Status</th><th>Feeds</th><th className="r">Active loans</th><th className="r">Open exceptions</th><th className="r">Last file</th><th className="r">On time (30 d)</th><th>Attention</th></tr></thead>
          <tbody>{list.map((x) => (
            <tr key={x.vendor_id} className="click" onClick={() => onOpen(x.vendor_id)}>
              <td><b>{x.name}</b>{x.external_ref && <div className="faint mono" style={{ fontSize: ".72rem" }}>{x.external_ref}</div>}</td>
              <td>{VENDOR_TYPES[x.vendor_type] || human(x.vendor_type)}</td><td><Status s={x.status} /></td>
              <td><span className="row" style={{ gap: 4 }}>{x.feeds} feed{x.feeds === 1 ? "" : "s"}{x.load_types.map((l) => <span key={l} className="chip">{LT[l] || l}</span>)}</span></td>
              <td className="r num">{fmt(x.active_loans)}</td><td className="r num">{fmt(x.open_exceptions)}</td>
              <td className="r faint">{ago(x.last_file)}</td><td className="r num">{x.on_time_pct === null ? "—" : `${x.on_time_pct}%`}</td>
              <td><span className="row" style={{ gap: 4 }}>
                {x.late_or_missed > 0 && <span className="pill fail" title="Late or missed in the last 48 hours">{x.late_or_missed} late/missed</span>}
                {x.attention_files > 0 && <span className="pill warn">{x.attention_files} file{x.attention_files > 1 ? "s" : ""} held</span>}
                {x.pending_mapping_review > 0 && <span className="pill warn">mapping to review</span>}
                {!x.feeds && <span className="pill">no feed yet</span>}</span></td>
            </tr>))}</tbody>
        </table></div>
      </Panel>
      {create && <VendorModal onClose={() => setCreate(false)} onSaved={(r) => { setCreate(false); onCreated(r.vendor_id); }} />}
    </>
  );
}

function FeedCard({ f, onOpenMapping, onDelivery, go, onMove, persona }) {
  const latest = f.mappings[f.mappings.length - 1];
  const live = f.mappings.find((m) => m.mapping_id === f.active_mapping_id);
  return (
    <div className="feed-card">
      <div className="row" style={{ justifyContent: "space-between" }}><b>{f.name}</b><Status s={f.status} /></div>
      <div className="row" style={{ gap: 4, fontSize: ".8rem" }}><span className="chip">{f.format}</span><span className="chip">{LT[f.load_type] || f.load_type}</span>
        {f.last_sequence && <span className="chip">last #{f.last_sequence}</span>}{f.delivery_pending && <span className="pill warn">delivery change pending</span>}</div>
      {f.active_mapping_id && <div><FeedConfigChip sourceId={f.source_id} persona={persona} /></div>}
      <dl className="kv" style={{ fontSize: ".82rem" }}>
        <dt>Active loans</dt><dd className="num">{fmt(f.active_loans)}</dd>
        <dt>Last file</dt><dd>{ago(f.last_file)}</dd>
        <dt>Schedule</dt><dd>{f.schedules.length ? f.schedules.map((s) => <span key={s.schedule_id} className="row" style={{ gap: 4 }}>{s.name}<Status s={s.status} /></span>) : <span className="faint">none: no late-file alerts</span>}</dd>
      </dl>
      <div className="stack" style={{ gap: 4 }}><span className="eyebrow">Mapping versions</span>
        <div className="row" style={{ gap: 4 }}>{f.mappings.map((m) => (
          <button key={m.mapping_id} className={`btn sm ${m.mapping_id === f.active_mapping_id ? "primary" : ""}`} title={`${human(m.status)}${m.approved_by ? ` · approved by ${m.approved_by}` : ""}`} onClick={() => onOpenMapping(m.mapping_id)}>
            v{m.version} · {human(m.status)}</button>))}</div></div>
      <div className="row">
        <button className="btn sm" onClick={() => onOpenMapping((live || latest).mapping_id)}>{latest.status === "draft" || latest.status === "in_review" ? "Review mapping" : "Open mapping"}</button>
        <button className="btn sm" onClick={() => onDelivery((live || latest).mapping_id)}>Delivery & schedule</button>
        <button className="btn sm" onClick={() => go("imports")}>Files</button>
        <span className="spacer" />
        {canCap(persona, "moveFeed") && <button className="btn sm" onClick={() => onMove(f)}>Move…</button>}
      </div>
    </div>
  );
}

function VendorFiles({ vendorId, persona, go }) {
  const b = useApi(`/api/batches?limit=50&vendor_id=${vendorId}`);
  const [sel, setSel] = useState(null);
  if (!b.data) return <Loading error={b.error} />;
  const list = b.data.batches;
  const i = list.findIndex((x) => x.batch_id === sel);
  return (
    <Panel title="Recent files" pad={false}>
      {!b.data.batches.length ? <div className="empty">No files yet.</div> : <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>File</th><th>Feed</th><th>Type</th><th>Status</th><th className="r">Rows</th><th className="r">Loaded</th><th className="r">Failed</th><th>Received</th></tr></thead>
        <tbody>{list.map((x) => <tr key={x.batch_id} className="click" onClick={() => setSel(x.batch_id)}><td className="mono">{x.filename}</td><td>{x.source_name}</td>
          <td><span className="chip">{LT[x.load_type] || x.load_type}</span>{x.sequence && <span className="chip" style={{ marginLeft: 4 }}>#{x.sequence}</span>}</td>
          <td><Status s={x.status} /></td><td className="r num">{fmt(x.processed)}</td><td className="r num">{fmt(x.loaded)}</td><td className="r num">{fmt(x.failed)}</td>
          <td className="faint">{ago(x.created_at)}</td></tr>)}</tbody></table></div>}
      {sel && <BatchModal id={sel} persona={persona} go={go} onClose={() => { setSel(null); b.reload(); }}
        nav={{ label: `${i + 1} of ${list.length}`, onPrev: i > 0 ? () => setSel(list[i - 1].batch_id) : null, onNext: i >= 0 && i < list.length - 1 ? () => setSel(list[i + 1].batch_id) : null }} />}
    </Panel>
  );
}

function VendorDeliveries({ vendorId }) {
  const d = useApi(`/api/deliveries?days_back=14&days_ahead=3&vendor_id=${vendorId}`);
  const s = useApi(`/api/schedules?vendor_id=${vendorId}`);
  if (!d.data || !s.data) return <Loading error={d.error || s.error} />;
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", alignItems: "start" }}>
      <Panel title="Schedules" pad={false}>
        {!s.data.schedules.length ? <div className="empty">No schedules: files are processed when they arrive, but nobody is alerted when one doesn't.</div> :
          <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Schedule</th><th>Feed</th><th>When</th><th>Next due</th><th>Status</th></tr></thead>
            <tbody>{s.data.schedules.map((x) => <tr key={x.schedule_id}><td>{x.name}</td><td>{x.source_name}</td><td>{x.describe}<div className="faint" style={{ fontSize: ".74rem" }}>{(x.config || x.proposed || {}).timezone}</div></td>
              <td className="num">{x.next_due_local || "—"}</td><td><Status s={x.status} /></td></tr>)}</tbody></table></div>}
      </Panel>
      <Panel title="Deliveries · last 14 days and next 3" pad={false}>
        <div className="tbl-wrap" style={{ maxHeight: 420 }}><table className="tbl"><thead><tr><th>Due</th><th>Feed</th><th>Status</th><th>File</th></tr></thead>
          <tbody>{d.data.deliveries.map((x) => <tr key={x.delivery_id}><td className="num">{x.local_label}</td><td>{x.source_name}</td><td><Status s={x.status} /></td>
            <td className="mono" style={{ fontSize: ".76rem" }}>{x.batches.map((b) => b.filename).join(", ") || "—"}</td></tr>)}</tbody></table></div>
      </Panel>
    </div>
  );
}

function VendorExceptions({ vendorId, go, pickVendor }) {
  const e = useApi(`/api/analytics/exceptions?vendor_id=${vendorId}`);
  const sys = useApi(`/api/analytics/systemic?vendor_id=${vendorId}`);
  const sum = useApi(`/api/exceptions/summary?vendor_id=${vendorId}`);
  if (!e.data || !sum.data) return <Loading error={e.error || sum.error} />;
  const tiers = Object.entries(sum.data.tiers);
  return (
    <div className="stack">
      <div className="row">{tiers.map(([t, x]) => <span key={t} className="row" style={{ gap: 4 }}><Tier t={t} />{fmt((x.open || 0) + (x.pending_checker || 0) + (x.escalated || 0))} open</span>)}
        <span className="spacer" /><button className="btn sm primary" onClick={() => { pickVendor(vendorId); go("exceptions"); }}>Work this vendor's queue</button></div>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", alignItems: "start" }}>
        <Panel title="Top rules (30 days)" pad={false}><div className="tbl-wrap"><table className="tbl"><thead><tr><th>Rule</th><th className="r">Count</th></tr></thead>
          <tbody>{e.data.by_rule.slice(0, 10).map((r) => <tr key={r.rule_id}><td><span className="mono">{r.rule_id}</span> {r.rule_name}</td><td className="r num">{fmt(r.count)}</td></tr>)}</tbody></table></div></Panel>
        <Panel title="Likely root causes" sub="Fix once in the mapping or with the vendor">
          {!sys.data?.issues?.length ? <div className="empty">No systemic issue for this vendor.</div> : <div className="stack" style={{ gap: 8 }}>{sys.data.issues.slice(0, 5).map((i, k) => (
            <div key={k} className="callout" style={{ fontSize: ".84rem" }}><b>{i.cause}</b><div className="faint">{i.source_name} · {i.rule_id} · {i.field} · {fmt(i.open_exceptions)} open</div><div>{i.action}</div></div>))}</div>}
        </Panel>
      </div>
    </div>
  );
}

export function VendorWorkspace({ vendorId, persona, go, onBack, onOpenMapping, pickVendor, reloadVendors }) {
  const v = useApi(`/api/vendors/${vendorId}`, [vendorId]);
  const all = useApi("/api/vendors");
  const [tab, setTab] = useState("feeds");
  const [modal, setModal] = useState(null); // "feed" | "edit" | "status" | {move: feed}
  if (!v.data) return <Loading error={v.error} />;
  const x = v.data;
  const reload = () => { v.reload(); reloadVendors && reloadVendors(); };
  return (
    <>
      <PageHeader
        eyebrow={<span className="crumbs">{onBack && <><a onClick={onBack}>All vendors</a><span className="faint">›</span></>}<span>{x.name}</span></span>}
        title={x.name}
        sub={<>{VENDOR_TYPES[x.vendor_type] || human(x.vendor_type)} · <Status s={x.status} />{x.external_ref ? ` · ${x.external_ref}` : ""}{x.legal_name ? ` · ${x.legal_name}` : ""}
          {x.contact?.email && <> · contact <a href={`mailto:${x.contact.email}`}>{x.contact.name || x.contact.email}</a></>}</>}
        guideHref="#guide?path=setup&step=feed"
        primary={canCap(persona, "editVendors") ? <button type="button" className="btn primary" onClick={() => setModal("feed")}>Add feed</button> : null}
        secondary={(
          <ActionBar>
            <button type="button" className="btn" onClick={() => { pickVendor(vendorId); }} title="Scope every page to this vendor">Focus on this vendor</button>
            {canCap(persona, "vendorLifecycle") && <button type="button" className="btn" onClick={() => setModal("status")}>Change status…</button>}
          </ActionBar>
        )}
      />
      {x.status === "suspended" && <div className="callout t5" style={{ marginBottom: 12 }}><b>Suspended.</b> Files from this vendor are recorded but not processed.</div>}
      <Kpis items={[
        { label: "Feeds", value: x.feeds.length, detail: `${x.live_feeds || 0} live` },
        { label: "Active loans", value: fmt(x.active_loans) },
        { label: "Open exceptions", value: fmt(x.open_exceptions) },
        { label: "On time (30 d)", value: x.on_time_pct === null || x.on_time_pct === undefined ? "—" : `${x.on_time_pct}%`, detail: x.late_or_missed ? `${x.late_or_missed} late or missed` : "no late files" },
        { label: "Last file", value: ago(x.last_file) },
      ]} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "feeds", label: "Feeds & mappings", count: x.feeds.length }, { id: "deliveries", label: "Deliveries & schedules" },
        { id: "files", label: "Files" }, { id: "exceptions", label: "Exceptions", count: x.open_exceptions }, { id: "profile", label: "Vendor profile" }]} />
      {tab === "feeds" && (x.feeds.length ? <div className="feeds">{x.feeds.map((f) => <FeedCard key={f.source_id} f={f} go={(p) => { pickVendor(vendorId); go(p); }}
        persona={persona} onMove={(feed) => setModal({ move: feed })}
        onOpenMapping={(mid) => onOpenMapping(mid, "fields")} onDelivery={(mid) => onOpenMapping(mid, "delivery")} />)}</div>
        : <Panel><div className="empty">No feeds yet. Add the vendor's first feed from a sample file.</div></Panel>)}
      {tab === "deliveries" && <VendorDeliveries vendorId={vendorId} />}
      {tab === "files" && <VendorFiles vendorId={vendorId} persona={persona} go={go} />}
      {tab === "exceptions" && <VendorExceptions vendorId={vendorId} go={go} pickVendor={pickVendor} />}
      {tab === "profile" && (
        <Panel title="Details" actions={canCap(persona, "editVendors") ? <button className="btn sm" onClick={() => setModal("edit")}>Edit…</button> : null}>
          <dl className="kv">
            <dt>Type</dt><dd>{VENDOR_TYPES[x.vendor_type] || x.vendor_type}</dd><dt>Status</dt><dd><Status s={x.status} /></dd><dt>Legal name</dt><dd>{x.legal_name || "—"}</dd>
            <dt>Counterparty #</dt><dd className="mono">{x.external_ref || "—"}</dd>
            <dt>Contact</dt><dd>{x.contact ? [x.contact.name, x.contact.email, x.contact.phone].filter(Boolean).join(" · ") || "—" : "—"}</dd>
            <dt>Notes</dt><dd>{x.notes || "—"}</dd><dt>Created</dt><dd>{x.created_by} · {ago(x.created_at)}</dd>
          </dl>
        </Panel>)}
      {modal === "feed" && <FeedModal vendor={x} onClose={() => setModal(null)} onCreated={(mid) => { setModal(null); reload(); onOpenMapping(mid, "fields"); }} />}
      {modal === "edit" && <VendorModal initial={x} onClose={() => setModal(null)} onSaved={() => { setModal(null); reload(); }} />}
      {modal === "status" && <VendorStatusModal vendor={x} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
      {modal?.move && <MoveFeedModal feed={modal.move} vendor={x} vendors={(all.data?.vendors || []).filter((o) => o.vendor_id !== vendorId)} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    </>
  );
}

const STATUS_HELP = {
  onboarding: "Feeds can be set up and tested; scheduled deliveries are not alerted on.",
  active: "Files are processed and deliveries are tracked against the schedule.",
  suspended: "Files from this vendor are recorded but not processed until the vendor is re-activated. Takes effect immediately, including for runs about to start.",
  offboarded: "The relationship has ended. Files are refused; boarded loans and their history stay in SSE.",
};

function VendorStatusModal({ vendor, onClose, onDone }) {
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const needsReason = ["suspended", "offboarded"].includes(status);
  const go = async () => {
    setBusy(true);
    const r = await act(() => api(`/api/vendors/${vendor.vendor_id}`, { method: "PUT", body: { status, reason } }), `${vendor.name} is now ${human(status)}`);
    setBusy(false);
    if (r) onDone();
  };
  return (
    <Modal title={`Change status of ${vendor.name}`} sub={<>Currently <Status s={vendor.status} /></>} size="sm" onClose={onClose} busy={busy}
      footer={<><button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className={`btn ${needsReason ? "danger" : "primary"}`} disabled={!status || (needsReason && reason.trim().length < 5) || busy} onClick={go}>{status ? `Make ${human(status)}` : "Apply"}</button></>}>
      <div className="stack" style={{ gap: 8 }}>{["onboarding", "active", "suspended", "offboarded"].filter((s) => s !== vendor.status).map((s) => (
        <label key={s} className={`choice ${status === s ? "on" : ""}`}><input type="radio" name="vstatus" checked={status === s} onChange={() => setStatus(s)} />
          <span className="stack" style={{ gap: 2 }}><b>{human(s)}</b><span className="faint" style={{ fontSize: ".8rem" }}>{STATUS_HELP[s]}</span></span></label>))}</div>
      {status && <Field id="vs-r" label={`Reason${needsReason ? "" : " (optional)"} · audited`}><textarea id="vs-r" className="input" rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder={needsReason ? "e.g. Data quality hold pending vendor remediation plan" : ""} /></Field>}
    </Modal>
  );
}

function MoveFeedModal({ feed, vendor, vendors, onClose, onDone }) {
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const target = vendors.find((v) => v.vendor_id === to);
  const go = async () => {
    setBusy(true);
    const r = await act(() => api(`/api/sources/${feed.source_id}/vendor`, { method: "POST", body: { vendor_id: to, reason } }), `${feed.name} moved to ${target?.name}`);
    setBusy(false);
    if (r) onDone();
  };
  return (
    <Modal title={`Move ${feed.name}`} sub={`from ${vendor.name}`} size="sm" onClose={onClose} busy={busy}
      footer={<><button className="btn" onClick={onClose} disabled={busy}>Cancel</button><button className="btn primary" disabled={!to || reason.trim().length < 5 || busy} onClick={go}>Move feed</button></>}>
      <span className="muted" style={{ fontSize: ".86rem" }}>For grouping a feed under the right counterparty, or after an acquisition. The feed keeps its mappings, schedules and history; its loans count toward the new vendor, and every feed's published configuration is refreshed. SME; audited.</span>
      <Field id="mv-to" label="Move to vendor"><select id="mv-to" className="input" value={to} onChange={(e) => setTo(e.target.value)}>
        <option value="">Choose a vendor…</option>{vendors.map((o) => <option key={o.vendor_id} value={o.vendor_id}>{o.name}</option>)}</select></Field>
      <Field id="mv-r" label="Reason (audited)"><textarea id="mv-r" className="input" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Westside acquired by Harbor Lending, effective 1 Oct" /></Field>
    </Modal>
  );
}

export const scopedApi = scoped;
