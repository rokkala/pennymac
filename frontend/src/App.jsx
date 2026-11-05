import React, { useEffect, useState } from "react";
import { DEMO, PERSONAS, SIGNED_IN, setPersona, getPersona, getVendorScope, setVendorScope, scoped } from "./api.js";
import { ToastHost, useApi, EmptyState } from "./ui.jsx";
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
import { parseHash, buildHash } from "./hash.js";
import { NAV_GROUPS, visibleNav } from "./navModel.js";
import { getTheme, setTheme } from "./theme.js";

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

const pageById = Object.fromEntries(PAGES.map((p) => [p.id, p]));

const pageIdFromHash = () => {
  const { id } = parseHash(window.location.hash || "");
  return pageById[id] ? id : "overview";
};

class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <EmptyState
        title="This page hit an error"
        body="Nothing was changed. Reload the page; if it keeps happening, send the time and page to the platform team."
        action={<button type="button" className="btn" onClick={() => this.setState({ error: null })}>Try again</button>}
      />
    );
  }
}

export default function App() {
  const [page, setPage] = useState(pageIdFromHash());
  const [persona, setP] = useState(getPersona());
  const [nonce, setNonce] = useState(0);
  const [vendor, setVendor] = useState(getVendorScope());
  const [theme, setThemeState] = useState(getTheme);
  const vendors = useApi("/api/vendors", [nonce]);
  const screens = useApi("/api/personas/me/screens", [nonce, persona.id]);
  const { data: summary } = useApi(scoped("/api/exceptions/summary"), [nonce, vendor], { poll: 15000 });
  const { data: ntf } = useApi("/api/notifications", [nonce, persona.id], { poll: 20000 });
  useEffect(() => {
    if (vendor && vendors.data && !vendors.data.vendors.some((v) => v.vendor_id === vendor)) { setVendorScope(null); setVendor(null); }
  }, [vendors.data]);
  const pickVendor = (id) => { setVendorScope(id); setVendor(id || null); };
  useEffect(() => { const h = () => setPage(pageIdFromHash()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  const openCount = summary ? Object.values(summary.tiers).reduce((a, t) => a + (t.open || 0) + (t.pending_checker || 0) + (t.escalated || 0), 0) : null;
  const ntfCount = ntf?.unread ?? (ntf?.notifications || []).filter((x) => !x.read_at).length;
  const allowed = screens.data?.screens;
  const navPages = PAGES.filter((p) => {
    if (allowed) return allowed.includes(p.id);
    if (p.id === "maintenance") return canCap(persona, "readMaintenance");
    if (p.id === "personas") return canCap(persona, "managePersonas");
    return true;
  });
  const groups = visibleNav(NAV_GROUPS, navPages.map((p) => p.id));
  useEffect(() => {
    if (allowed && !allowed.includes(page)) {
      window.location.hash = "overview";
      setPage("overview");
    }
  }, [allowed, page]);
  const Page = (pageById[page] || PAGES[0]).el;
  const go = (id, qs = "") => { window.location.hash = buildHash(id, qs); setPage(id); };
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
            {groups.map((g) => (
              <div key={g.id} className="nav-group">
                <span className="eyebrow">{g.label}</span>
                {g.pages.map((id) => {
                  const p = pageById[id];
                  if (!p) return null;
                  return (
                    <a key={id} href={`#${id}`} className={page === id ? "on" : ""} onClick={(e) => {
                      e.preventDefault();
                      if (id === "rules" && ntfCount > 0) go("rules", "queue=awaiting_review");
                      else go(id);
                    }}>
                      {p.label}
                      {id === "exceptions" && openCount !== null && openCount > 0 && <span className="count">{openCount}</span>}
                      {id === "rules" && ntfCount > 0 && <span className="count">{ntfCount}</span>}
                    </a>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className="rail-foot">
            <div className="theme-toggle" role="group" aria-label="Color theme">
              <button type="button" className={theme === "light" ? "on" : ""} aria-pressed={theme === "light"}
                onClick={() => setThemeState(setTheme("light"))}>Light</button>
              <button type="button" className={theme === "dark" ? "on" : ""} aria-pressed={theme === "dark"}
                onClick={() => setThemeState(setTheme("dark"))}>Dark</button>
            </div>
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
