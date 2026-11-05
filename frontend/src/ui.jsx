import React, { useEffect, useLayoutEffect, useRef, useState, useCallback, createContext, useContext } from "react";
import { api } from "./api.js";

export const fmt = (n, d = 0) => (n === null || n === undefined || Number.isNaN(n) ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
export const fmtCompact = (n) => (n === null || n === undefined ? "—" : Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n));
export const fmtMoney = (n) => (n === null || n === undefined ? "—" : "$" + fmtCompact(n));
export const ago = (iso) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};
export const human = (s) => String(s || "").replace(/_/g, " ");

const ToastCtx = createContext(() => {});
export function ToastHost({ children }) {
  const [t, setT] = useState(null);
  const show = useCallback((msg, err = false) => { setT({ msg, err }); setTimeout(() => setT(null), 4200); }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && <div className={`toast ${t.err ? "err" : ""}`} role="status">{t.msg}</div>}
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

export function useApi(path, deps = [], { poll } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const load = useCallback(async () => {
    if (!path) return;
    try { const data = await api(path); setState({ data, error: null, loading: false }); }
    catch (e) { setState((s) => ({ ...s, error: e.message, loading: false })); }
  }, [path]);
  useEffect(() => { load(); if (!poll) return; const id = setInterval(load, poll); return () => clearInterval(id); }, [load, poll, ...deps]);
  return { ...state, reload: load };
}

export function useAction() {
  const toast = useToast();
  return useCallback(async (fn, okMsg) => {
    try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); return r; }
    catch (e) { toast(e.message, true); return null; }
  }, [toast]);
}

export const Panel = ({ title, actions, children, pad = true, sub }) => (
  <section className="panel">
    {(title || actions) && (
      <div className="panel-h">
        <div className="stack" style={{ gap: 2 }}><h2>{title}</h2>{sub && <span className="faint" style={{ fontSize: ".8rem" }}>{sub}</span>}</div>
        {actions && <div className="row">{actions}</div>}
      </div>
    )}
    {pad ? <div className="panel-b">{children}</div> : children}
  </section>
);

export const Kpis = ({ items }) => (
  <div className="kpis">
    {items.map((k) => (
      <div className="kpi" key={k.label}>
        <span className="eyebrow">{k.label}</span>
        <span className="v">{k.value}</span>
        {k.detail && <span className="d">{k.detail}</span>}
      </div>
    ))}
  </div>
);

const STATUS_CLASS = { PASS: "pass", completed: "pass", resolved: "pass", approved: "pass", active: "pass", live: "pass", accepted: "pass", auto_applied: "pass",
  WARN: "warn", running: "accent", in_review: "warn", pending_checker: "warn", needs_review: "warn", canary: "accent", shadow: "accent", overridden: "accent", suggested: "accent", mapping: "warn", draft: "", paused: "warn",
  FAIL: "fail", failed: "fail", rejected: "fail", escalated: "fail", open: "warn", pending_review: "warn", retired: "", blocked: "fail", superseded: "",
  pass: "pass", warn: "warn", block: "fail", claimed: "accent", queued: "",
  expected: "", received: "pass", received_late: "warn", late: "warn", missed: "fail", waived: "", pending_approval: "warn",
  waiting: "warn", out_of_order: "fail", discarded: "", UNCHANGED: "" };
export const Status = ({ s }) => <span className={`pill ${STATUS_CLASS[s] ?? ""}`}>{human(s)}</span>;
export const Tier = ({ t }) => <span className={`tier ${t}`} title={TIER_NAMES[t]}>{t}</span>;
export const TIER_NAMES = { T1: "Auto-Apply", T2: "Suggest", T3: "Mandatory Review", T4: "Dual Control", T5: "Block & Escalate" };

export const Conf = ({ v }) => {
  if (v === null || v === undefined) return <span className="faint">—</span>;
  const cls = v >= 0.95 ? "pass" : v >= 0.8 ? "" : "warn";
  return <span className="conf"><span className={`bar ${cls}`}><i style={{ width: `${Math.round(v * 100)}%` }} /></span>{v.toFixed(2)}</span>;
};

export const Bar = ({ pct, kind = "" }) => <span className={`bar ${kind}`}><i style={{ width: `${Math.max(0, Math.min(100, pct || 0))}%` }} /></span>;

/* ------------------------------------------------------------------ modals
   One modal system for the whole app: sizes, stacking (a modal can open another), focus trap and
   restore, body scroll lock, Escape / backdrop close for the top-most modal only, optional
   prev / next navigation (arrow keys when not typing). */
const modalStack = [];
let modalSeq = 0;
const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const typing = (el) => el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);

export function Modal({ title, sub, onClose, children, footer, actions, size = "md", nav, busy = false, className = "" }) {
  const ref = useRef(null);
  const idRef = useRef(null);
  const closeRef = useRef(onClose);
  const navRef = useRef(nav);
  closeRef.current = onClose;
  navRef.current = nav;
  const [z, setZ] = useState(60);
  useLayoutEffect(() => {
    const id = ++modalSeq;
    idRef.current = id;
    modalStack.push(id);
    setZ(60 + modalStack.length * 2);
    const prevFocus = document.activeElement;
    if (modalStack.length === 1) document.body.classList.add("modal-open");
    const first = ref.current?.querySelector("[data-autofocus]") || ref.current?.querySelector(`.modal-b ${FOCUSABLE}`) || ref.current;
    first?.focus({ preventScroll: true });
    return () => {
      const i = modalStack.indexOf(id);
      if (i >= 0) modalStack.splice(i, 1);
      if (!modalStack.length) document.body.classList.remove("modal-open");
      if (prevFocus && typeof prevFocus.focus === "function" && document.contains(prevFocus)) prevFocus.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (modalStack[modalStack.length - 1] !== idRef.current) return;
      if (e.key === "Escape") { e.stopPropagation(); if (!busy) closeRef.current?.(); return; }
      if (e.key === "Tab" && ref.current) {
        const els = [...ref.current.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
        if (!els.length) return;
        const [a, b] = [els[0], els[els.length - 1]];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); b.focus(); }
        else if (!e.shiftKey && document.activeElement === b) { e.preventDefault(); a.focus(); }
        return;
      }
      const n = navRef.current;
      if (n && !typing(document.activeElement) && !e.metaKey && !e.ctrlKey && !e.altKey) {
        if ((e.key === "ArrowLeft" || e.key === "k") && n.onPrev) { e.preventDefault(); n.onPrev(); }
        if ((e.key === "ArrowRight" || e.key === "j") && n.onNext) { e.preventDefault(); n.onNext(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy]);
  const down = useRef(false);
  return (
    <div className="scrim" style={{ zIndex: z }} onMouseDown={(e) => { down.current = e.target === e.currentTarget; }}
      onMouseUp={(e) => { if (down.current && e.target === e.currentTarget && !busy) onClose?.(); down.current = false; }}>
      <div ref={ref} className={`modal ${size} ${className}`} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} tabIndex={-1}>
        <div className="modal-h">
          <div className="stack" style={{ gap: 2, minWidth: 0 }}><h2>{title}</h2>{sub && <span className="faint modal-sub">{sub}</span>}</div>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            {actions}
            {nav && <span className="row modal-nav" style={{ gap: 4, flexWrap: "nowrap" }}>
              <button className="btn sm" aria-label="Previous" title="Previous (←)" disabled={!nav.onPrev} onClick={nav.onPrev}>‹</button>
              {nav.label && <span className="faint num" style={{ fontSize: ".78rem", whiteSpace: "nowrap" }}>{nav.label}</span>}
              <button className="btn sm" aria-label="Next" title="Next (→)" disabled={!nav.onNext} onClick={nav.onNext}>›</button></span>}
            <button className="btn sm icon" aria-label="Close" title="Close (Esc)" disabled={busy} onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
      </div>
    </div>
  );
}

/** Confirmation for a consequential action. onConfirm may be async; the modal closes when it returns truthy. */
export function ConfirmModal({ title, children, confirmLabel = "Confirm", danger = false, onConfirm, onClose, size = "sm" }) {
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); const ok = await onConfirm(); setBusy(false); if (ok !== false && ok !== null && ok !== undefined) onClose(); };
  return (
    <Modal title={title} size={size} onClose={onClose} busy={busy}
      footer={<><button className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? "danger" : "primary"}`} data-autofocus disabled={busy} onClick={go}>{busy ? "Working…" : confirmLabel}</button></>}>
      <div className="stack" style={{ fontSize: ".9rem" }}>{children}</div>
    </Modal>
  );
}

/** Asks for the reason / comment an audited action needs. onSubmit(reason) may be async; closes on truthy. */
export function ReasonModal({ title, help, label = "Reason (recorded in the audit trail)", placeholder = "", confirmLabel = "Submit", danger = false,
  required = true, presets = [], initial = "", onSubmit, onClose, children, size = "sm", minLength = 0 }) {
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const ok = !required || text.trim().length >= Math.max(1, minLength);
  const go = async () => { if (!ok) return; setBusy(true); const r = await onSubmit(text.trim()); setBusy(false); if (r !== false && r !== null && r !== undefined) onClose(); };
  return (
    <Modal title={title} size={size} onClose={onClose} busy={busy}
      footer={<><button className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? "danger" : "primary"}`} disabled={!ok || busy} onClick={go}>{busy ? "Working…" : confirmLabel}</button></>}>
      <div className="stack">
        {help && <div className="muted" style={{ fontSize: ".88rem" }}>{help}</div>}
        {children}
        <label className="stack" style={{ gap: 4 }} htmlFor="reason-text"><span className="eyebrow">{label}{!required && " (optional)"}</span>
          <textarea id="reason-text" className="input" rows={3} data-autofocus value={text} placeholder={placeholder}
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go(); }} /></label>
        {presets.length > 0 && <div className="row" style={{ gap: 4 }}>{presets.map((p) => <button key={p} type="button" className="chip btnchip" onClick={() => setText(p)}>{p}</button>)}</div>}
        {minLength > 0 && <span className="faint" style={{ fontSize: ".74rem" }}>At least {minLength} characters.</span>}
      </div>
    </Modal>
  );
}

/** Imperative dialogs: const [dialog, ask] = useDialog(); ask({ kind: "reason" | "confirm", ...props }); render {dialog}. */
export function useDialog() {
  const [cfg, setCfg] = useState(null);
  const close = useCallback(() => setCfg(null), []);
  const el = !cfg ? null : cfg.kind === "confirm"
    ? <ConfirmModal {...cfg} onConfirm={cfg.onConfirm} onClose={close}>{cfg.body}</ConfirmModal>
    : <ReasonModal {...cfg} onSubmit={cfg.onSubmit} onClose={close}>{cfg.body}</ReasonModal>;
  return [el, setCfg];
}

/** Labelled form field. */
export const Field = ({ id, label, hint, children }) => (
  <label className="stack" style={{ gap: 4 }} htmlFor={id}><span className="eyebrow">{label}</span>{children}{hint && <span className="faint" style={{ fontSize: ".76rem" }}>{hint}</span>}</label>
);

export const Tabs = ({ tabs, value, onChange }) => (
  <div className="tabs" role="tablist">
    {tabs.map((t) => (
      <button key={t.id} role="tab" aria-selected={value === t.id} className={`tab ${value === t.id ? "on" : ""}`} onClick={() => onChange(t.id)}>
        {t.label}{t.count !== undefined && <span className="c">{t.count}</span>}
      </button>
    ))}
  </div>
);

export const Loading = ({ error }) => <div className="empty">{error ? `Could not load: ${error}` : "Loading…"}</div>;

/** Page chrome: eyebrow + title + sub + primary/secondary actions + optional guide link. */
export function PageHeader({ eyebrow, title, sub, primary, secondary, guideHref }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
        {guideHref && <a className="guide-link" href={guideHref}>Why this step</a>}
      </div>
      {(primary || secondary) && (
        <div className="row page-head-actions">
          {secondary}
          {primary}
        </div>
      )}
    </div>
  );
}

/** One primary action, then quieter secondary actions. */
export function ActionBar({ primary, children }) {
  return (
    <div className="action-bar row">
      {primary}
      {children}
    </div>
  );
}

export function EmptyState({ title, body, action }) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      {body && <p className="muted">{body}</p>}
      {action}
    </div>
  );
}

export function QueueCard({ title, detail, cta, onClick }) {
  return (
    <button type="button" className="queue-card" onClick={onClick}>
      <span className="stack" style={{ gap: 4, textAlign: "left" }}>
        <span className="queue-card-title">{title}</span>
        <span className="muted" style={{ fontSize: ".85rem" }}>{detail}</span>
      </span>
      <span className="queue-card-cta">{cta}</span>
    </button>
  );
}

export const Transform = ({ steps }) => (
  <span className="row" style={{ gap: 4 }}>
    {(steps || []).filter((s) => s.op !== "trim").map((s, i) => (
      <span className="chip" key={i} title={JSON.stringify(s)}>{s.op}{s.table ? `:${s.table}` : s.format ? `:${s.format}` : s.part ? `:${s.part}` : s.index !== undefined ? `[${s.index}]` : ""}</span>
    ))}
  </span>
);
