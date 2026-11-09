import React, { useEffect, useMemo, useState } from "react";
import { api, setIntent, scoped } from "../api.js";
import { parseHash, buildHash } from "../hash.js";
import { canCap, canRaiseExceptions, exceptionTabsFor, defaultExceptionTab, isMonitoringExceptionDesk } from "../roles.js";
import { helpForExceptionTab } from "../exceptionTabHelp.js";
import {
  groupExceptions, exceptionFiltersFromSearch, groupsFromLoads, fileScopedAllOpen,
  nextOpenId, tierForLoads, PAGE_SIZE, hasMoreExceptions,
} from "../exceptionGroups.js";
import { SCREEN, exceptionDeskSub } from "../screenCopy.js";
import { useApi, useAction, Panel, Status, Conf, Tier, TIER_NAMES, Tabs, Loading, ago, human, fmt, Modal, useDialog, PageHeader, EmptyState } from "../ui.jsx";

const TIER_RULE = {
  T1: "Low-risk formatting or code fix at ≥ 0.95 confidence. Applied automatically, audited, 5% sampled for QA, reversible within the rollback window.",
  T2: "Medium-risk field at 0.80–0.95 confidence. Monitoring confirms; the AI pre-fills the fix with its rationale and precedents.",
  T3: "Confidence below 0.80. Monitoring review queue; any AI output is a hint only.",
  T4: "Regulated or high-risk field (rate, term, FICO, DTI, HMDA, identity). Monitoring raises a fix; a different Monitoring reviewer must approve. AI never auto-applies.",
  T5: "OFAC hit or fraud alert. The loan stays halted until Compliance clears or rejects it.",
};
const KEY_FIELDS = ["loan_number", "loan_type", "original_loan_amount", "current_principal_balance", "interest_rate", "original_term_months", "note_date", "first_payment_date", "maturity_date",
  "borrower_first_name", "borrower_last_name", "borrower_ssn", "borrower_fico", "property_address_line1", "property_city", "property_state", "property_zip", "occupancy_type", "investor_category"];

const show = (v) => (v === null || v === undefined || v === "" ? <span className="faint">(blank)</span> : String(v));

const ACTION_LABEL = { value_map: "Add value translation", fix_transform: "Fix transformation", review_duplicates: "Review duplicates", bulk_fix: "Show these exceptions", source_quality: "Show these exceptions" };

function RootCauses({ onFilter, go }) {
  const { data } = useApi(scoped("/api/analytics/systemic"));
  const [open, setOpen] = useState(false);
  if (!data || !data.issues.length) return null;
  const act = (i) => {
    if (["value_map", "fix_transform"].includes(i.action) && i.mapping_id) { setIntent({ page: "sources", mappingId: i.mapping_id, target: i.field }); go("sources"); }
    else onFilter(i.rule_id);
  };
  return (
    <Panel title={`${data.issues.length} patterns explain ${data.explained_pct}% of these`} sub="Fix the cause once in the mapping or with the seller, then replay the file."
      actions={<button className="btn sm" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show patterns"}</button>} pad={false}>
      {open && <div className="causes">{data.issues.slice(0, 6).map((i) => (
        <div key={`${i.source_id}${i.rule_id}${i.field}`} className="cause">
          <div className="row" style={{ gap: 6 }}><span className="pill fail num">{fmt(i.exceptions)}</span><b style={{ fontSize: ".88rem" }}>{i.cause}</b></div>
          <span className="faint" style={{ fontSize: ".78rem" }}>{i.source_name} · {i.rule_id} · <span className="mono">{i.field}</span>{i.mapped_from ? <> ← <span className="mono">{i.mapped_from.join(" + ")}</span></> : null} · {i.share_pct}% of loans</span>
          <span style={{ fontSize: ".82rem" }}>{i.detail}</span>
          <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => act(i)}>{ACTION_LABEL[i.action]}</button>
        </div>))}</div>}
    </Panel>
  );
}

function SseCompare({ c }) {
  if (!c) return null;
  if (!c.existing) return <div className="callout" style={{ fontSize: ".84rem" }}>The earlier copy is no longer in SSE.</div>;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="eyebrow">Incoming vs loan already in SSE (batch {c.existing_batch_id})</span>
      {c.identical ? <span className="pill pass" style={{ alignSelf: "flex-start" }}>Identical to the boarded loan: safe to reject the resend</span> : (
        <div className="tbl-wrap"><table className="tbl trace"><thead><tr><th>Field</th><th>In SSE</th><th>Incoming</th></tr></thead>
          <tbody>{c.differences.map((d) => <tr key={d.field}><td className="mono">{d.field}</td><td className="mono">{show(d.in_sse)}</td><td className="mono"><b>{show(d.incoming)}</b></td></tr>)}</tbody></table></div>)}
    </div>
  );
}

const CHANGE_RULES = ["ACT01", "CHG01", "CHG02", "CHG03", "CHG04", "CHG05", "CHG06"];

function ChangeControl({ ex, persona, run, askReject }) {
  const p = ex.proposal || {};
  const [val, setVal] = useState("");
  const maker = ex.tier === "T4";
  const submit = (value, msg) => run("resolve", { value, comment: msg }, maker ? "Submitted. A different user must check it." : "Resolved. The change is re-applied on the live SSE record.");
  const canRaise = canRaiseExceptions(persona);
  const box = (title, body, actions) => (
    <div className="stack">
      <div className="callout t4" style={{ fontSize: ".84rem" }}><b>{title}</b><div style={{ marginTop: 4 }}>{body}</div></div>
      <div className="row">{actions}</div>
    </div>);
  const reject = (label, reason) => canRaise ? <button className="btn danger" onClick={() => askReject(label, reason, "Change rejected; SSE is unchanged")}>{label}…</button> : null;
  const waiting = <span className="faint" style={{ fontSize: ".82rem" }}>{maker ? "Monitoring raises; Monitoring · Reviewer accepts" : "Monitoring can act"}</span>;
  switch (ex.rule_id) {
    case "CHG01":
      return box("Protected field change from the vendor's change file",
        <div className="diff"><span className="old">{show(p.previous)}</span>→<span className="new val">{show(p.value)}</span><span className="faint" style={{ marginLeft: 8 }}>{ex.field}</span></div>,
        canRaise ? <><button className="btn primary" onClick={() => submit(p.value, "Vendor value verified")}>{maker ? "Submit vendor value for approval" : "Apply vendor value"}</button>
          {p.previous !== undefined && p.previous !== null && <button className="btn" onClick={() => submit(String(p.previous), "Kept SSE value; rest of the change applies")}>{maker ? "Submit keep-SSE for approval" : "Keep SSE value, apply the rest"}</button>}
          {reject("Reject whole change", "Protected change rejected")}</> : waiting);
    case "CHG05":
      return box("SSE changed after the vendor produced this file",
        <div className="stack" style={{ gap: 4 }}><span>Vendor saw <span className="mono">{show(p.previous)}</span> and sent <b className="mono">{show(p.vendor)}</b>; SSE now holds <b className="mono">{show(p.value)}</b>.</span>
          <span className="faint">Only this field conflicts; the loan's other changes apply once you choose.</span></div>,
        canRaise ? <><button className="btn primary" onClick={() => submit(String(p.value ?? ""), "Kept newer SSE value")}>Keep SSE value</button>
          {p.vendor !== undefined && <button className="btn" onClick={() => submit(String(p.vendor ?? ""), "Applied vendor value over SSE")}>Apply vendor value</button>}
          {reject("Reject whole change", "Conflicting change rejected")}</> : waiting);
    case "CHG04":
      return box("Loan missing from the vendor's full snapshot",
        <span>Absence from a snapshot usually means a payoff or transfer, but it is not proof. Confirm to close the loan in SSE (never deleted), or keep it active.</span>,
        canRaise ? <><button className="btn primary" onClick={() => submit("closed", "Payoff confirmed")}>Confirm closed</button>
          <button className="btn" onClick={() => askReject("Keep loan active", "Loan still serviced; vendor omission", "Kept active", false)}>Keep active…</button></> : waiting);
    case "CHG02":
      return box("Change for a loan number that is not in SSE",
        <div className="stack" style={{ gap: 6 }}><span>If the vendor mistyped the loan number, enter the correct one: the change is merged onto that loan (protected fields are still checked).</span>
          {canRaise && <input aria-label="Correct loan number" className="input mono" value={val} onChange={(e) => setVal(e.target.value)} placeholder="Correct loan number" />}</div>,
        canRaise ? <><button className="btn primary" disabled={!val} onClick={() => submit(val, "Loan number corrected")}>Apply to this loan</button>
          {reject("Reject change", "Unknown loan")}</> : waiting);
    case "CHG03":
      return box("Change for a loan that is closed in SSE",
        <span>Reopen only if the closure was wrong (for example a payoff that reversed). Reopening applies the vendor's change and marks the loan active.</span>,
        canRaise ? <><button className="btn" onClick={() => submit("active", "Closure reversed")}>Reopen and apply</button>
          {reject("Reject change", "Loan stays closed")}</> : waiting);
    case "CHG06":
      return box("Change for a loan boarded under another vendor",
        <span>A vendor's file may only change its own loans. Document a servicing transfer to apply the change and move the loan to this vendor (Monitoring raises; Monitoring reviewer approves).</span>,
        canRaise ? <><button className="btn" onClick={() => submit(ex.loan_number, "Servicing transfer documented")}>Submit transfer for approval</button>
          {reject("Reject change", "Not this vendor's loan")}</> : waiting);
    case "ACT01":
      return box("Unrecognised action code",
        <span>Add the code to the vendor's delivery profile (Sources → Delivery & schedule) so future files are understood. For this row you can apply it as an update when the loan is in SSE (a new loan otherwise), or reject it.</span>,
        canRaise ? <><button className="btn" onClick={() => submit(ex.loan_number, "Applied with default action")}>Apply (update if boarded, else add)</button>
          {reject("Reject row", "Unknown action code")}</> : waiting);    default:
      return null;
  }
}

function ExceptionModal({ id, persona, onChanged, sameCount, onClose, nav }) {
  const { data, reload } = useApi(`/api/exceptions/${id}`, [id]);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const act = useAction();
  const [dialog, ask] = useDialog();
  useEffect(() => { if (data) setValue(data.proposal?.value ?? data.resolved_value ?? ""); setNote(""); }, [data?.exception_id]);
  if (!data || data.exception_id !== id) return <Modal title="Loading…" size="lg" onClose={onClose} nav={nav}><Loading /></Modal>;
  const ex = data;
  const canRaise = canRaiseExceptions(persona);
  const canCheck = canCap(persona, "checkerApprove");
  const canComp = canCap(persona, "complianceAct");
  const run = async (path, body, msg) => { const r = await act(() => api(`/api/exceptions/${id}/${path}`, { method: "POST", body }), msg); if (r) { reload(); onChanged(id); } return r; };
  const askReason = ({ title, path = "reject", preset, msg, danger = true, help, field = "reason", extra = {} }) => ask({
    kind: "reason", title: title.replace(/…$/, ""), danger, confirmLabel: title.replace(/…$/, ""), help, presets: preset ? [preset] : [],
    onSubmit: (reason) => run(path, { ...extra, [field]: reason }, msg) });
  const askReject = (title, preset, msg, danger = true) => askReason({ title, preset, msg, danger,
    help: "Rejecting leaves SSE unchanged for this row. The reason is kept with the loan's audit trail and shown to the vendor relationship team." });
  const shownOriginal = ex.loan_record?.[ex.field] !== undefined && ex.original_value && /\*/.test(String(ex.loan_record[ex.field])) ? ex.loan_record[ex.field] : ex.original_value;
  const p = ex.proposal;
  const openish = ["open", "pending_review"].includes(ex.status);
  return (
    <Modal title={<span className="row" style={{ gap: 8 }}><Tier t={ex.tier} />{ex.rule_name}</span>} size="lg" onClose={onClose} nav={nav}
      sub={`${ex.rule_id} v${ex.rule_version ?? 1} · ${ex.loan_number}${ex.vendor_name ? ` · ${ex.vendor_name}` : ""} · ${TIER_NAMES[ex.tier]}`}>
      <div className="stack">
        <div className={`callout ${ex.tier === "T5" ? "t5" : ex.tier === "T4" ? "t4" : ""}`} style={{ fontSize: ".84rem" }}>{TIER_RULE[ex.tier]}</div>
        <dl className="kv">
          <dt>Status</dt><dd><Status s={ex.status} />{ex.qa_sample && <span className="pill accent" style={{ marginLeft: 6 }}>QA sample</span>}</dd>
          <dt>Field</dt><dd><span className="mono">{ex.field}</span> · {ex.risk} risk · {human(ex.category)}</dd>
          <dt>Message</dt><dd>{ex.message}</dd>
          <dt>Current value</dt><dd className="mono">{show(shownOriginal)}</dd>
          <dt>Blocks boarding</dt><dd>{ex.blocking ? "Yes" : "No (warning)"}</dd>
          {ex.maker && <><dt>Maker</dt><dd>{ex.maker}{ex.resolved_value != null && <> → <span className="mono">{ex.resolved_value}</span></>}</dd></>}
          {ex.checker && <><dt>Checker</dt><dd>{ex.checker}</dd></>}
        </dl>

        {CHANGE_RULES.includes(ex.rule_id) && openish && <ChangeControl ex={ex} persona={persona} run={run} askReject={askReject} />}
        {p && ex.tier !== "T5" && !CHANGE_RULES.includes(ex.rule_id) && (
          <div className="proposal">
            <div className="row"><span className="eyebrow">{p.hint_only ? "AI hint (not auto-applied)" : ex.status === "auto_applied" ? "Applied automatically" : "AI proposed fix"}</span><span className="spacer" /><Conf v={p.confidence} /></div>
            <div className="diff"><span className="old">{show(shownOriginal)}</span>→<span className="new val">{show(p.value)}</span></div>
            <span className="muted" style={{ fontSize: ".84rem" }}>{p.rationale}</span>
            {p.precedents?.length > 0 && (
              <div style={{ fontSize: ".78rem" }} className="stack"><span className="eyebrow">Precedents (past human fixes)</span>
                {p.precedents.map((x, i) => <span key={i} className="mono faint">{show(x.original)} → {show(x.corrected)} · ×{x.count} · sim {x.similarity}</span>)}</div>)}
          </div>
        )}

        {ex.sse_compare && <SseCompare c={ex.sse_compare} />}
        {/* actions by tier and state */}
        {openish && ["T2", "T3"].includes(ex.tier) && !CHANGE_RULES.includes(ex.rule_id) && (
          canRaise ? <div className="stack">
            {p && !p.hint_only && <button className="btn primary" onClick={() => run("resolve", { use_proposal: true }, "Fix accepted. Loan re-validated.")}>Confirm fix</button>}
            <label className="stack" style={{ gap: 4 }} htmlFor="fix-val"><span className="eyebrow">Corrected value</span>
              <div className="row"><input id="fix-val" className="input" style={{ flex: 1 }} value={value ?? ""} onChange={(e) => setValue(e.target.value)} />
                <button className="btn" onClick={() => run("resolve", { value }, "Resolved. Loan re-validated.")}>Confirm this value</button></div></label>
            {p && sameCount > 1 && <button className="btn sm" onClick={() => ask({ kind: "confirm", title: `Accept the AI fix on ${sameCount} exceptions`, confirmLabel: `Resolve ${sameCount}`,
              body: <><span>Every open <span className="mono">{ex.rule_id}</span> exception in this queue with the value <b className="mono">{show(ex.original_value_masked ?? ex.original_value)}</b> gets the same fix:</span>
                <div className="diff"><span className="old">{show(shownOriginal)}</span>→<span className="new val">{show(p.value)}</span></div>
                <span className="faint" style={{ fontSize: ".82rem" }}>Each loan is re-validated and the change is audited per loan. Better still: fix the cause in the mapping and replay the batch.</span></>,
              onConfirm: () => act(() => api("/api/exceptions/bulk-resolve", { method: "POST", body: { rule_id: ex.rule_id, original_value: ex.original_value, use_proposal: true } }), (r) => `Bulk resolved ${r.resolved} exceptions`).then((r) => { if (r) onChanged(id); return r; }) })}>Accept the AI fix on all {sameCount} matching exceptions…</button>}
            <div className="row"><button className="btn sm danger" onClick={() => askReject("Reject loan…", "Data cannot be corrected from the file; vendor to resend", "Loan rejected")}>Reject loan…</button>
              <button className="btn sm" onClick={() => askReason({ title: "Escalate…", path: "escalate", preset: "Needs further judgement", msg: "Escalated", danger: false, help: "Moves the exception up with your note." })}>Escalate…</button></div>
          </div> : <span className="faint" style={{ fontSize: ".82rem" }}>{canCheck ? "Monitoring raises this; it appears here after submit for acceptance" : "Monitoring can resolve this tier"}</span>
        )}
        {openish && ex.tier === "T4" && ["DUP01", "DUP02"].includes(ex.rule_id) && (
          <div className="stack">
            <span className="faint" style={{ fontSize: ".84rem" }}>Dual control: Monitoring raises an update; a different Monitoring · Reviewer must accept before the boarded loan is overwritten.</span>
            {canRaise ? <div className="row"><button className="btn primary" onClick={() => run("resolve", { value: ex.loan_number, comment: "Approved as update of boarded loan" }, "Submitted for acceptance. A Monitoring · Reviewer must accept it.")}>Submit for acceptance</button>
              <button className="btn danger" onClick={() => askReject("Reject resend…", "Duplicate resend rejected", "Resend rejected; boarded loan unchanged")}>Reject resend…</button></div>
              : <span className="faint" style={{ fontSize: ".82rem" }}>{canCheck ? "Waiting for Monitoring to submit — then Accept appears under Waiting for you" : "Monitoring raises this for acceptance"}</span>}
          </div>
        )}
        {openish && ex.tier === "T4" && !["DUP01", "DUP02", ...CHANGE_RULES].includes(ex.rule_id) && (
          <div className="stack">
            {canRaise ? <>
              <label className="stack" style={{ gap: 4 }} htmlFor="mk-val"><span className="eyebrow">Corrected value (verify against source documents)</span>
                <div className="row"><input id="mk-val" className="input" style={{ flex: 1 }} value={value ?? ""} onChange={(e) => setValue(e.target.value)} />
                  <button className="btn primary" onClick={() => run("resolve", { value }, "Submitted for acceptance. A different Monitoring · Reviewer must accept it.")}>Submit for acceptance</button></div></label>
              <button className="btn sm danger" style={{ alignSelf: "flex-start" }} onClick={() => askReject("Reject loan…", "Source documents do not support the vendor value", "Loan rejected")}>Reject loan…</button>
            </> : <span className="faint" style={{ fontSize: ".82rem" }}>{canCheck ? "Waiting for Monitoring to submit — then Accept appears under Waiting for you" : "Monitoring raises this for acceptance"}</span>}
          </div>
        )}
        {ex.status === "pending_checker" && (
          <div className="stack">
            {persona.id === ex.maker && <span className="callout t4" style={{ fontSize: ".84rem" }}>You raised this. Switch to Monitoring · Reviewer (a different person) to accept it.</span>}
            {canCheck && persona.id !== ex.maker ? <div className="row">
              <button className="btn primary" onClick={() => run("checker", { approve: true, comment: "Verified" }, "Accepted. Loan re-validated.")}>Accept</button>
              <button className="btn" onClick={() => askReason({ title: "Return to Monitoring…", path: "checker", field: "comment", extra: { approve: false }, danger: false, msg: "Returned to Monitoring",
                preset: "Value does not match the note; please re-verify", help: "Monitoring sees your comment and can correct and resubmit." })}>Return…</button></div>
              : persona.id !== ex.maker && <span className="faint" style={{ fontSize: ".82rem" }}>Waiting for a Monitoring · Reviewer</span>}
          </div>
        )}
        {ex.tier === "T5" && ["escalated", "open"].includes(ex.status) && (
          <div className="stack">
            {!canComp && <span className="callout t5" style={{ fontSize: ".84rem" }}>Only Compliance · Reviewer can act on this loan.</span>}
            {canComp && <>
              <label className="stack" style={{ gap: 4 }} htmlFor="inv-note"><span className="eyebrow">Investigation note (required)</span>
                <textarea id="inv-note" className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Case reference and outcome" /></label>
              <div className="row">
                <button className="btn" disabled={!note} onClick={() => run("compliance-clear", { value: ex.field === "fraud_alert_flag" ? "false" : "C", reason: note }, "Cleared by Compliance")}>Clear as false positive</button>
                <button className="btn danger" disabled={!note} onClick={() => ask({ kind: "confirm", title: "Confirm hit and reject loan", danger: true, confirmLabel: "Confirm and reject",
                  body: <><span>The loan is rejected and held. Your investigation note is recorded:</span><div className="callout" style={{ fontSize: ".84rem" }}>{note}</div></>,
                  onConfirm: () => run("reject", { reason: note }, "Loan rejected and held") })}>Confirm and reject loan…</button></div>
            </>}
          </div>
        )}
        {ex.status === "auto_applied" && canRaise && (
          <div className="row">
            <button className="btn" onClick={() => askReason({ title: "Roll back auto-fix…", path: "rollback", preset: "AI fix was wrong", msg: "Rolled back. Moved to T3 review.", danger: false,
              help: "Restores the vendor's original value and sends the loan to T3 review. Roll-backs count toward the T1 override rate that can auto-suspend AI auto-apply." })}>Roll back…</button>
            {ex.qa_sample && <><button className="btn sm" onClick={() => run("qa", { correct: true }, "QA passed")}>QA: correct</button><button className="btn sm danger" onClick={() => ask({ kind: "confirm", title: "QA: mark incorrect", danger: true, confirmLabel: "Mark incorrect and roll back",
              body: "The auto-applied fix is rolled back and counts against the T1 override rate.", onConfirm: () => run("qa", { correct: false }, "QA failed, rolled back") })}>QA: incorrect…</button></>}
          </div>
        )}

        <details>
          <summary className="eyebrow" style={{ cursor: "pointer" }}>Loan record (PII masked)</summary>
          <dl className="kv" style={{ marginTop: 8, fontSize: ".8rem" }}>{KEY_FIELDS.filter((k) => ex.loan_record?.[k] !== undefined).map((k) => <React.Fragment key={k}><dt className="mono">{k}</dt><dd className="mono" style={{ color: k === ex.field ? "var(--fail)" : undefined }}>{show(ex.loan_record[k])}</dd></React.Fragment>)}</dl>
        </details>
        {ex.related?.length > 0 && <div className="stack" style={{ gap: 4 }}><span className="eyebrow">Other exceptions on this loan</span>
          {ex.related.map((r) => <span key={r.exception_id} className="row" style={{ gap: 6, fontSize: ".82rem" }}><Tier t={r.tier} /><span className="mono">{r.rule_id}</span>{r.field}<Status s={r.status} /></span>)}</div>}
        {ex.audit?.length > 0 && <div className="timeline">{ex.audit.map((a) => <div key={a.id}><b>{a.action}</b> · {a.actor} · <span className="faint">{ago(a.ts)}</span></div>)}</div>}
      </div>
      {dialog}
    </Modal>
  );
}

export default function Exceptions({ persona, go, vendor }) {
  const boot = exceptionFiltersFromSearch(parseHash(window.location.hash).params);
  const [tab, setTab] = useState(() => defaultExceptionTab(persona));
  const [rule, setRule] = useState(null);
  const [q, setQ] = useState("");
  const [filterVendor, setFilterVendor] = useState(boot.vendor_id);
  const [filterBatch, setFilterBatch] = useState(boot.batch_id);
  const [filterDay, setFilterDay] = useState(boot.loaded_on);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [sel, setSel] = useState(null);
  const [nonce, setNonce] = useState(0);
  const [extra, setExtra] = useState([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const acceptOnly = canCap(persona, "checkerApprove") && !canRaiseExceptions(persona);
  const homeTab = defaultExceptionTab(persona);
  // Keep query tab in the persona's eligible set (Tabs UI can look selected while state lags).
  const activeTab = exceptionTabsFor(persona, [{ id: tab }]).length ? tab : homeTab;
  useEffect(() => {
    setTab(defaultExceptionTab(persona));
    setSel(null);
  }, [persona?.id]);
  useEffect(() => {
    if (activeTab !== tab) setTab(activeTab);
  }, [activeTab, tab]);
  useEffect(() => {
    // rail vendor wins; clear page vendor override when rail is set
    if (vendor) setFilterVendor("");
  }, [vendor]);
  useEffect(() => {
    const apply = () => {
      const { id, params } = parseHash(window.location.hash);
      if (id !== "exceptions") return;
      const f = exceptionFiltersFromSearch(params);
      setFilterBatch(f.batch_id);
      setFilterDay(f.loaded_on);
      if (!vendor) setFilterVendor(f.vendor_id);
      setSel(null);
    };
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, [vendor]);
  const sum = useApi(scoped("/api/exceptions/summary"), [nonce], { poll: 15000 });
  const statusQ = { open: "status=open", T1: "status=auto_applied", T2: "status=open", T3: "status=open", T4: "status=open",
    checker: "status=pending_checker", T5: "status=escalated", resolved: "status=resolved" }[activeTab] || "status=open";
  const tierQ = { T2: "&tier=T2", T3: "&tier=T3", T4: "&tier=T4", T5: "&tier=T5" }[activeTab] || "";
  // Monitor → file: every open loan for that batch (counts match To fix), not one tier tab.
  const allOpenForFile = fileScopedAllOpen({ batchId: filterBatch, tab: activeTab });
  const listStatusQ = allOpenForFile ? "status=open" : statusQ;
  const listTierQ = allOpenForFile ? "" : tierQ;
  const effectiveVendor = vendor || filterVendor || "";
  const loadsTier = allOpenForFile ? "" : tierForLoads(activeTab);
  const loadsQ = [
    statusQ,
    loadsTier ? `tier=${loadsTier}` : "",
    effectiveVendor ? `vendor_id=${encodeURIComponent(effectiveVendor)}` : "",
  ].filter(Boolean).join("&");
  const loads = useApi(`/api/exceptions/loads?${loadsQ}`, [nonce, activeTab, effectiveVendor, loadsTier]);
  const loadRows = loads.data?.loads || [];
  const vendorOptions = useMemo(() => {
    const m = new Map();
    for (const L of loadRows) if (L.vendor_id) m.set(L.vendor_id, L.vendor_name || L.vendor_id);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [loadRows]);
  const fileOptions = useMemo(() => {
    const rows = filterDay ? loadRows.filter((L) => L.loaded_on === filterDay) : loadRows;
    return rows;
  }, [loadRows, filterDay]);
  const dayOptions = useMemo(() => [...new Set(loadRows.map((L) => L.loaded_on).filter(Boolean))].sort().reverse(), [loadRows]);
  const browseFiles = !filterBatch && !q && !rule;
  const filterQs = [
    q ? `q=${encodeURIComponent(q)}` : "",
    rule ? `rule_id=${encodeURIComponent(rule)}` : "",
    filterBatch ? `batch_id=${encodeURIComponent(filterBatch)}` : "",
    !filterBatch && filterDay ? `loaded_on=${encodeURIComponent(filterDay)}` : "",
    !vendor && filterVendor ? `vendor_id=${encodeURIComponent(filterVendor)}` : "",
  ].filter(Boolean).join("&");
  const listBase = browseFiles
    ? null
    : scoped(`/api/exceptions?${listStatusQ}${listTierQ}&limit=${PAGE_SIZE}${filterQs ? `&${filterQs}` : ""}`);
  const list = useApi(listBase, [nonce, activeTab, q, rule, filterBatch, filterDay, filterVendor, vendor], { poll: 10000 });
  useEffect(() => { setExtra([]); }, [listBase, nonce]);
  const t = sum.data?.tiers;
  const items = useMemo(() => [...(list.data?.items || []), ...extra], [list.data, extra]);
  const listTotal = list.data?.total ?? 0;
  const groups = useMemo(
    () => (browseFiles ? groupsFromLoads(fileOptions) : groupExceptions(items)),
    [browseFiles, fileOptions, items],
  );
  const [lastIdx, setLastIdx] = useState(0);
  useEffect(() => {
    if (!sel) return;
    if (!items.some((i) => i.exception_id === sel)) setSel(items.length ? items[Math.min(lastIdx, items.length - 1)].exception_id : null);
  }, [list.data, extra]);
  const idx = items.findIndex((i) => i.exception_id === sel);
  const open = (id) => { setSel(id); setLastIdx(items.findIndex((i) => i.exception_id === id)); };
  const selected = items[idx];
  const sameCount = selected ? items.filter((i) => i.rule_id === selected.rule_id && i.original_value === selected.original_value && ["T2", "T3"].includes(i.tier)).length : 0;
  const changed = (id) => {
    if (filterBatch) {
      const nxt = nextOpenId(items, id || sel);
      if (nxt && nxt !== (id || sel)) setSel(nxt);
      else setSel(null);
    }
    setLastIdx(Math.max(0, idx));
    setNonce((n) => n + 1);
  };
  const loadMore = async () => {
    if (!listBase || loadingMore || !hasMoreExceptions(items.length, listTotal)) return;
    setLoadingMore(true);
    try {
      const sep = listBase.includes("?") ? "&" : "?";
      const page = await api(`${listBase}${sep}offset=${items.length}`);
      setExtra((prev) => [...prev, ...(page.items || [])]);
    } finally { setLoadingMore(false); }
  };
  const syncHash = (next = {}) => {
    const { id } = parseHash(window.location.hash);
    if (id !== "exceptions") return;
    const params = new URLSearchParams();
    if (next.batch_id) params.set("batch_id", next.batch_id);
    if (next.loaded_on) params.set("loaded_on", next.loaded_on);
    if (next.vendor_id) params.set("vendor_id", next.vendor_id);
    const hash = buildHash("exceptions", params);
    if (`#${hash}` !== window.location.hash) window.location.hash = hash;
  };
  const clearFilters = () => {
    setFilterVendor(""); setFilterBatch(""); setFilterDay(""); setSel(null);
    syncHash({});
  };
  const hasFilters = !!(filterVendor || filterBatch || filterDay);
  const toggleGroup = (key) => setCollapsed((prev) => {
    const n = new Set(prev);
    if (n.has(key)) n.delete(key); else n.add(key);
    return n;
  });
  const onVendorChange = (vid) => {
    setFilterVendor(vid);
    setFilterBatch("");
    setFilterDay("");
    setSel(null);
    syncHash(vid ? { vendor_id: vid } : {});
  };
  const onDayChange = (day) => {
    setFilterDay(day);
    let bid = filterBatch;
    if (filterBatch) {
      const keep = loadRows.find((L) => L.batch_id === filterBatch && (!day || L.loaded_on === day));
      if (!keep) { setFilterBatch(""); bid = ""; }
    }
    setSel(null);
    syncHash({
      batch_id: bid || "",
      loaded_on: day || "",
      vendor_id: (!vendor && filterVendor) ? filterVendor : "",
    });
  };
  const onFileChange = (bid) => {
    setFilterBatch(bid);
    let day = filterDay;
    let vid = filterVendor;
    if (bid) {
      const L = loadRows.find((x) => x.batch_id === bid);
      if (L?.loaded_on) { setFilterDay(L.loaded_on); day = L.loaded_on; }
      if (L?.vendor_id && !vendor) { setFilterVendor(L.vendor_id); vid = L.vendor_id; }
    }
    setSel(null);
    syncHash({
      batch_id: bid || "",
      loaded_on: bid ? day : "",
      vendor_id: (!vendor && vid) ? vid : "",
    });
  };
  const colSpan = vendor || filterVendor ? 8 : 9;
  return (
    <>
      <PageHeader
        eyebrow="Run"
        title={SCREEN.exceptions.label}
        sub={exceptionDeskSub({ acceptOnly, monitoringDesk: isMonitoringExceptionDesk(persona) })}
        guideHref="#guide?path=execution&step=exceptions"
        primary={<input id="ex-search" className="input" placeholder="Search loan number" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search loan number" />}
      />
      {isMonitoringExceptionDesk(persona) && <RootCauses go={go} onFilter={(r) => { setRule(r); setTab(homeTab === "checker" ? "T2" : homeTab); setSel(null); }} />}
      {rule && <div className="row"><span className="pill accent">Filtered to rule {rule}</span><button className="btn sm" onClick={() => setRule(null)}>Clear filter</button></div>}
      {t && (() => {
        const awaiting = Object.values(t).reduce((a, x) => a + (x.pending_checker || 0), 0);
        const allTabs = [
          { id: "open", label: "All open" }, { id: "T1", label: helpForExceptionTab("T1").title, count: t.T1.auto_applied }, { id: "T2", label: helpForExceptionTab("T2").title, count: t.T2.open },
          { id: "T3", label: helpForExceptionTab("T3").title, count: t.T3.open }, { id: "T4", label: helpForExceptionTab("T4").title, count: t.T4.open },
          { id: "checker", label: helpForExceptionTab("checker").title, count: awaiting },
          { id: "T5", label: helpForExceptionTab("T5").title, count: t.T5.escalated }, { id: "resolved", label: helpForExceptionTab("resolved").title, count: Object.values(t).reduce((a, x) => a + (x.resolved || 0), 0) },
        ].map((tab) => ({ ...tab, help: helpForExceptionTab(tab.id) }));
        const tabs = exceptionTabsFor(persona, allTabs);
        return <Tabs value={activeTab} onChange={(v) => { setTab(v); setSel(null); }} tabs={tabs} />;
      })()}
      <div className="row filters" style={{ flexWrap: "wrap", gap: 10, marginBottom: 10 }}>
        {!vendor && (
          <label className="stack" style={{ gap: 2 }} htmlFor="ex-vendor">
            <span className="eyebrow">Vendor</span>
            <select id="ex-vendor" className="input" value={filterVendor} onChange={(e) => onVendorChange(e.target.value)}>
              <option value="">All vendors</option>
              {vendorOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
        )}
        <label className="stack" style={{ gap: 2 }} htmlFor="ex-day">
          <span className="eyebrow">Load date</span>
          <select id="ex-day" className="input" value={filterDay} onChange={(e) => onDayChange(e.target.value)}>
            <option value="">All dates</option>
            {dayOptions.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label className="stack" style={{ gap: 2 }} htmlFor="ex-file">
          <span className="eyebrow">File</span>
          <select id="ex-file" className="input" value={filterBatch} onChange={(e) => onFileChange(e.target.value)} style={{ minWidth: 220 }}>
            <option value="">All files</option>
            {fileOptions.map((L) => (
              <option key={L.batch_id} value={L.batch_id}>
                {L.filename} · {L.loaded_on} ({fmt(L.open_count)})
              </option>
            ))}
          </select>
        </label>
        {hasFilters && <button type="button" className="btn sm" style={{ alignSelf: "flex-end" }} onClick={clearFilters}>Clear load filters</button>}
      </div>
      <Panel
        pad={false}
        title={browseFiles
          ? `${fmt(groups.reduce((n, g) => n + (g.open_count || 0), 0))} open · ${fmt(groups.length)} files`
          : `${fmt(listTotal)} exceptions`}
        sub={browseFiles
          ? (loadsTier
            ? `Open for this tab (${loadsTier}). Click a file to open its loans.`
            : "All open by file. Click a file to open its loans.")
          : allOpenForFile
            ? "All open loans for this file (every tier). Resolve advances to the next loan."
            : `${groups.length} file${groups.length === 1 ? "" : "s"} by name. Open a row to act; use ← → in the detail.`}
      >
          {browseFiles ? (
            !loads.data ? <Loading error={loads.error} /> : !groups.length ? (
              <EmptyState
                title={activeTab === "checker" ? "Nothing waiting for you" : "Nothing in this queue"}
                body={activeTab === "checker"
                  ? "Monitoring submits a regulated fix first. Submitted items show Accept and Return here."
                  : "Try another tab, or clear vendor or date filters."}
              />
            ) : (
              <div className="tbl-wrap" style={{ maxHeight: 720 }}><table className="tbl">
                <thead><tr><th>File</th>{!(vendor || filterVendor) && <th>Vendor</th>}<th>Loaded</th><th className="r">Open</th></tr></thead>
                <tbody>
                  {groups.map((g) => (
                    <tr
                      key={g.key}
                      className="click"
                      role="button"
                      tabIndex={0}
                      aria-label={`Open loans for ${g.filename}`}
                      onClick={() => g.batch_id && onFileChange(g.batch_id)}
                      onKeyDown={(e) => {
                        if ((e.key === "Enter" || e.key === " ") && g.batch_id) { e.preventDefault(); onFileChange(g.batch_id); }
                      }}
                    >
                      <td className="mono">{g.filename}</td>
                      {!(vendor || filterVendor) && <td>{g.vendor_name}</td>}
                      <td className="faint">{g.loaded_on}</td>
                      <td className="r num">{fmt(g.open_count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )
          ) : !list.data ? <Loading error={list.error} /> : !items.length ? (
            <EmptyState
              title={activeTab === "checker" ? "Nothing waiting for you" : "Nothing in this queue"}
              body={activeTab === "checker"
                ? "Monitoring submits a regulated fix first. Submitted items show Accept and Return here."
                : "Try another tab, or clear vendor, file, or date filters."}
              action={(rule || hasFilters) ? <button type="button" className="btn primary" onClick={() => { setRule(null); clearFilters(); }}>Clear filters</button> : null}
            />
          ) : (
            <>
              <div className="tbl-wrap" style={{ maxHeight: 720 }}><table className="tbl">
                <thead><tr><th>Tier</th><th>Loan</th>{!(vendor || filterVendor) && <th>Vendor</th>}<th>Rule</th><th>Field</th><th>Value</th><th>Proposal</th><th>Status</th><th>Age</th></tr></thead>
                <tbody>
                  {groups.map((g) => {
                    const closed = collapsed.has(g.key);
                    const loanItems = g.items || [];
                    return (
                      <React.Fragment key={g.key}>
                        <tr className="group-h click" onClick={() => toggleGroup(g.key)}>
                          <td colSpan={colSpan}>
                            <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                              <span className="faint" aria-hidden="true">{closed ? "▸" : "▾"}</span>
                              <b>{g.vendor_name}</b>
                              <span className="mono">{g.filename}</span>
                              <span className="faint">loaded {g.loaded_on}</span>
                              <span className="pill">{fmt(loanItems.length)}</span>
                            </span>
                          </td>
                        </tr>
                        {!closed && loanItems.map((e) => (
                          <tr key={e.exception_id} className={`click ${sel === e.exception_id ? "sel" : ""}`} tabIndex={0} onClick={() => open(e.exception_id)} onKeyDown={(k) => k.key === "Enter" && open(e.exception_id)}>
                            <td><Tier t={e.tier} /></td>
                            <td className="mono">{e.loan_number}</td>
                            {!(vendor || filterVendor) && (
                              <td style={{ fontSize: ".82rem" }}>{e.vendor_name || "—"}{e.feed_name && e.feed_name !== e.vendor_name && <div className="faint" style={{ fontSize: ".72rem" }}>{e.feed_name}</div>}</td>
                            )}
                            <td><span className="mono">{e.rule_id}</span></td>
                            <td className="mono">{e.field}</td>
                            <td className="mono">{show(e.original_value_masked ?? e.original_value)}</td>
                            <td>{e.proposal && e.tier !== "T5" ? <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}><span className="mono">{show(e.proposal.value)}</span><Conf v={e.proposal.confidence} /></span> : <span className="faint">—</span>}</td>
                            <td><Status s={e.status} /></td>
                            <td className="faint">{ago(e.created_at)}</td>
                          </tr>
                        ))}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table></div>
              {hasMoreExceptions(items.length, listTotal) && (
                <div className="row" style={{ padding: "10px 14px", justifyContent: "center" }}>
                  <button type="button" className="btn" disabled={loadingMore} onClick={loadMore}>
                    {loadingMore ? "Loading…" : `Load more (${fmt(items.length)} of ${fmt(listTotal)})`}
                  </button>
                </div>
              )}
            </>
          )}
      </Panel>
      {sel && <ExceptionModal id={sel} persona={persona} onChanged={changed} sameCount={sameCount} onClose={() => setSel(null)}
        nav={{ label: idx >= 0 ? `${idx + 1} of ${items.length}${listTotal > items.length ? ` · ${fmt(listTotal)} total` : ""}` : "", onPrev: idx > 0 ? () => open(items[idx - 1].exception_id) : null,
          onNext: idx >= 0 && idx < items.length - 1 ? () => open(items[idx + 1].exception_id) : null }} />}
    </>
  );
}
