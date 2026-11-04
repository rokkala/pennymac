import React, { useEffect, useState } from "react";
import { DEMO, PERSONAS, SIGNED_IN, setPersona, getPersona, getVendorScope, setVendorScope, scoped } from "./api.js";
import { ToastHost, useApi } from "./ui.jsx";
import Overview from "./pages/Overview.jsx";
import Imports from "./pages/Imports.jsx";
import Deliveries from "./pages/Deliveries.jsx";
import Sources from "./pages/Sources.jsx";
import Exceptions from "./pages/Exceptions.jsx";
import Rules from "./pages/Rules.jsx";
import Analytics from "./pages/Analytics.jsx";
import Governance from "./pages/Governance.jsx";
import Maintenance from "./pages/Maintenance.jsx";
import Personas from "./pages/Personas.jsx";
import HowItWorks from "./pages/HowItWorks.jsx";
import { canCap } from "./roles.js";

const PAGES = [
  { id: "overview", label: "Overview", el: Overview },
  { id: "guide", label: "How it works", el: HowItWorks },
  { id: "imports", label: "Import Monitor", el: Imports },
  { id: "deliveries", label: "Vendor Deliveries", el: Deliveries },
  { id: "sources", label: "Vendors & Mapping", el: Sources },
  { id: "exceptions", label: "Exception Manager", el: Exceptions },
  { id: "rules", label: "Rule Engine", el: Rules },
  { id: "analytics", label: "Analytics", el: Analytics },
  { id: "governance", label: "Policy & Audit", el: Governance },
  { id: "maintenance", label: "Maintenance", el: Maintenance },
  { id: "personas", label: "Personas", el: Personas },
];

const fromHash = () => {
  const h = (window.location.hash || "").replace("#", "");
  return PAGES.some((p) => p.id === h) ? h : "overview";
};

class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel"><div className="panel-b stack">
        <h2>This page hit an error</h2>
        <p className="muted">Nothing was changed. Reload the page; if it keeps happening, send the time and page to the platform team.</p>
        <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => this.setState({ error: null })}>Try again</button>
      </div></div>
    );
  }
}

export default function App() {
  const [page, setPage] = useState(fromHash());
  const [persona, setP] = useState(getPersona());
  const [nonce, setNonce] = useState(0);
  const [vendor, setVendor] = useState(getVendorScope());
  const vendors = useApi("/api/vendors", [nonce]);
  const screens = useApi("/api/personas/me/screens", [nonce, persona.id]);
  const { data: summary } = useApi(scoped("/api/exceptions/summary"), [nonce, vendor], { poll: 15000 });
  useEffect(() => { // a stored scope for a vendor that no longer exists falls back to all vendors
    if (vendor && vendors.data && !vendors.data.vendors.some((v) => v.vendor_id === vendor)) { setVendorScope(null); setVendor(null); }
  }, [vendors.data]);
  const pickVendor = (id) => { setVendorScope(id); setVendor(id || null); };
  useEffect(() => { const h = () => setPage(fromHash()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  const openCount = summary ? Object.values(summary.tiers).reduce((a, t) => a + (t.open || 0) + (t.pending_checker || 0) + (t.escalated || 0), 0) : null;
  const allowed = screens.data?.screens;
  const navPages = PAGES.filter((p) => {
    if (allowed) return allowed.includes(p.id);
    if (p.id === "maintenance") return canCap(persona, "readMaintenance");
    if (p.id === "personas") return canCap(persona, "managePersonas");
    return true;
  });
  useEffect(() => {
    if (allowed && !allowed.includes(page)) {
      window.location.hash = "overview";
      setPage("overview");
    }
  }, [allowed, page]);
  const Page = (PAGES.find((p) => p.id === page) || PAGES[0]).el;
  const go = (id) => { window.location.hash = id; setPage(id); };
  return (
    <ToastHost>
      <div className="shell">
        <aside className="rail">
          <div className="brand"><b>Loan Boarding Console</b><span>PennyMac SSE · powered by LDS IntelliMap</span></div>
          <label className="vendor-scope" htmlFor="vendor-scope">
            <span className="eyebrow" style={{ color: "var(--rail-ink)" }}>Vendor</span>
            <select id="vendor-scope" value={vendor || ""} onChange={(e) => pickVendor(e.target.value)}>
              <option value="">All vendors</option>
              {(vendors.data?.vendors || []).map((v) => <option key={v.vendor_id} value={v.vendor_id}>{v.name}{v.status !== "active" ? ` (${v.status})` : ""}</option>)}
            </select>
          </label>
          <nav className="nav" aria-label="Sections">
            {navPages.map((p) => (
              <a key={p.id} href={`#${p.id}`} className={page === p.id ? "on" : ""} onClick={(e) => { e.preventDefault(); go(p.id); }}>
                {p.label}{p.id === "exceptions" && openCount !== null && <span className="count">{openCount}</span>}
              </a>
            ))}
          </nav>
          <div className="rail-foot">
            <span className="eyebrow" style={{ color: "var(--rail-ink)" }}>Signed in as</span>
            {SIGNED_IN ? (
              <span className="stack" style={{ gap: 4 }}><b style={{ color: "#fff", overflowWrap: "anywhere" }}>{SIGNED_IN.label}</b>
                <span>{SIGNED_IN.roles.join(", ") || "no roles"}</span>
                <button className="btn sm" onClick={async () => (await import("./auth.js")).logout()}>Sign out</button></span>
            ) : (
              <select id="persona" aria-label="Signed in as" value={persona.id} onChange={(e) => { const p = PERSONAS.find((x) => x.id === e.target.value); setPersona(p); setP(p); setNonce((n) => n + 1); }}>
                {PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>)}
            {DEMO && <span className="demo-tag">DEMO · synthetic loans, in-browser API</span>}
          </div>
        </aside>
        <main className="main" key={`${page}-${persona.id}-${vendor || "all"}`}>
          {vendor && <div className="scope-bar"><span>Showing <b>{vendors.data?.vendors.find((v) => v.vendor_id === vendor)?.name || "one vendor"}</b> only</span>
            <button className="btn sm" onClick={() => pickVendor(null)}>Show all vendors</button></div>}
          <ErrorBoundary><Page go={go} persona={persona} vendor={vendor} pickVendor={pickVendor} vendors={vendors.data?.vendors || []} reloadVendors={vendors.reload} /></ErrorBoundary>
        </main>
      </div>
    </ToastHost>
  );
}
