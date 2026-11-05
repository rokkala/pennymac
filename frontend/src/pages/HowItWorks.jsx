import React, { useEffect, useMemo, useState } from "react";
import { can, canCap } from "../roles.js";
import { PageHeader } from "../ui.jsx";
import { parseHash } from "../hash.js";

/** Product guide: Setup vs Execution, filtered by what this persona can do. */

const SETUP = [
  {
    id: "vendor",
    title: "Register the vendor",
    why: "A vendor is the company sending files. Nothing else works until they exist in the console.",
    where: "Vendors & Mapping",
    page: "sources",
    youIf: "editVendors",
    ask: "Analyst or SME",
    rolesCare: ["analyst", "sme", "admin"],
  },
  {
    id: "feed",
    title: "Add their feed",
    why: "A feed is one file pattern (format, schedule, sequencing). One vendor can have several feeds.",
    where: "Vendors & Mapping",
    page: "sources",
    youIf: "editVendors",
    ask: "Analyst or SME",
    rolesCare: ["analyst", "sme", "admin"],
  },
  {
    id: "mapping",
    title: "Map columns → SSE fields",
    why: "Tell the platform how their columns become PennyMac loan fields. Draft first; SME approves.",
    where: "Vendors & Mapping",
    page: "sources",
    youIf: "editMapping",
    youAlt: "approveMapping",
    ask: "Analyst drafts · SME approves",
    rolesCare: ["analyst", "sme", "admin"],
  },
  {
    id: "rules",
    title: "Attach validation rules",
    why: "Rules catch bad data before boarding. Regulated rules need Compliance as well as SME.",
    where: "Rule Engine",
    page: "rules",
    youIf: "authorRules",
    ask: "SME / Compliance / Analyst (author)",
    rolesCare: ["sme", "compliance", "analyst", "admin"],
  },
  {
    id: "delivery",
    title: "Set the delivery profile",
    why: "How often they send, full vs change files, and sequencing so files don’t board out of order.",
    where: "Vendors & Mapping · delivery",
    page: "sources",
    youIf: "editDelivery",
    youAlt: "approveDelivery",
    ask: "Analyst proposes · SME approves",
    rolesCare: ["analyst", "sme", "admin"],
  },
  {
    id: "publish",
    title: "Publish the live config",
    why: "Glue only reads a signed, published configuration — never a draft. Publish is the go-live switch.",
    where: "Vendors & Mapping",
    page: "sources",
    youIf: "publishConfig",
    ask: "SME",
    rolesCare: ["sme", "admin"],
    critical: true,
  },
  {
    id: "schedule",
    title: "Optional: schedule pulls",
    why: "If we fetch from them (SFTP/S3) instead of them dropping files, Ops sets the window; SME or Compliance approves.",
    where: "Vendor Deliveries",
    page: "deliveries",
    youIf: "schedules",
    youAlt: "approveSchedule",
    ask: "Ops schedules · SME/Compliance approves",
    rolesCare: ["ops", "sme", "compliance", "admin"],
  },
  {
    id: "ready",
    title: "Ready for files",
    why: "Setup is done. The next file for this feed starts the execution path — upload, pull, or S3 arrival.",
    where: "Import Monitor",
    page: "imports",
    youIf: "upload",
    ask: "Ops uploads · or wait for arrival/pull",
    rolesCare: ["ops", "sme", "admin"],
  },
];

const EXECUTION = [
  {
    id: "arrive",
    title: "A file arrives",
    why: "Three ways in: they drop to S3, we pull on a schedule, or Ops uploads in Import Monitor.",
    where: "Import Monitor",
    page: "imports",
    youIf: "upload",
    ask: "Ops (upload) · platform (S3/pull)",
    rolesCare: ["ops", "sme", "admin"],
  },
  {
    id: "batch",
    title: "We register a batch",
    why: "The file becomes a tracked batch for that feed — including duplicates and sequencing checks.",
    where: "Import Monitor",
    page: "imports",
    youIf: "upload",
    ask: "Automatic",
    rolesCare: ["ops", "sme", "admin"],
  },
  {
    id: "start",
    title: "Boarding starts",
    why: "In AWS this is Step Functions → Glue. Locally/demo it runs in-process. Same business steps either way.",
    where: "Import Monitor",
    page: "imports",
    youIf: "resumeBatch",
    ask: "Automatic (Ops/SME can resume if paused)",
    rolesCare: ["ops", "sme", "admin"],
    tech: "dispatch → route_batch → lbp-feed or lbp-feed-spark",
  },
  {
    id: "board",
    title: "Loans are validated and loaded",
    why: "Map → rules → triage. Good loans board; failures become exceptions by risk tier. Large full tapes may use Spark.",
    where: "Import Monitor · Exception Manager",
    page: "exceptions",
    youIf: "workExceptions",
    ask: "Automatic · reviewers handle holds",
    rolesCare: ["ops", "reviewer", "checker", "compliance", "sme", "admin"],
    tech: "Glue lbp-feed · published config only",
  },
  {
    id: "exceptions",
    title: "Exceptions need people",
    why: "Held loans wait in Exception Manager. Reviewer works them; Checker / Compliance for the higher bars.",
    where: "Exception Manager",
    page: "exceptions",
    youIf: "workExceptions",
    ask: "Reviewer → Checker → Compliance by tier",
    rolesCare: ["reviewer", "checker", "compliance", "admin"],
  },
  {
    id: "finish",
    title: "Batch finishes",
    why: "Reconcile, release files waiting in sequence, and notify. Waiting is normal if an earlier file isn’t done yet.",
    where: "Import Monitor",
    page: "imports",
    youIf: "pauseBatch",
    ask: "Automatic · Ops watches status",
    rolesCare: ["ops", "sme", "admin"],
    tech: "finalize_batch → Outcome → SNS",
  },
  {
    id: "attention",
    title: "If something’s wrong",
    why: "Blocked, out of order, or failed batches show in Import Monitor. SME/Compliance handle overrides; Ops can replay when safe.",
    where: "Import Monitor",
    page: "imports",
    youIf: "overridePreflight",
    youAlt: "replay",
    ask: "Ops / SME / Compliance by action",
    rolesCare: ["ops", "sme", "compliance", "admin"],
  },
];

function defaultMode(persona) {
  if (can(persona, "ops") && !can(persona, "sme") && !can(persona, "analyst")) return "execution";
  if (can(persona, "reviewer") && !can(persona, "sme") && !can(persona, "analyst")) return "execution";
  return "setup";
}

function yourMove(step, persona) {
  if (step.youIf && canCap(persona, step.youIf)) return { can: true, page: step.page, label: `Go to ${step.where}` };
  if (step.youAlt && canCap(persona, step.youAlt)) return { can: true, page: step.page, label: `Go to ${step.where}` };
  return { can: false, label: `Needs ${step.ask}` };
}

function isYourStep(step, persona) {
  const roles = persona?.roles || [];
  if (roles.includes("admin")) return true;
  return (step.rolesCare || []).some((r) => roles.includes(r)) && (canCap(persona, step.youIf) || (step.youAlt && canCap(persona, step.youAlt)));
}

function StepCard({ step, n, persona, go, showTech, active, onSelect }) {
  const move = yourMove(step, persona);
  const yours = isYourStep(step, persona);
  return (
    <div
      className={`guide-step ${active ? "on" : ""} ${yours ? "yours" : ""}`}
      role="listitem"
    >
      <button type="button" className="guide-step-hit" onClick={() => onSelect(step.id)} aria-expanded={active}>
        <span className="guide-num" aria-hidden>{n}</span>
        <span className="guide-step-body">
          <span className="guide-step-title">
            {step.title}
            {yours && <span className="chip">Your step</span>}
            {step.critical && <span className="chip" style={{ background: "var(--warn-soft)", color: "var(--warn)" }}>Go-live</span>}
          </span>
          <span className="guide-step-why">{step.why}</span>
        </span>
      </button>
      {active && (
        <div className="guide-step-detail">
          <span className="guide-meta"><b>Where:</b> {step.where}</span>
          <span className="guide-meta"><b>Who:</b> {step.ask}</span>
          {showTech && step.tech && <span className="guide-meta mono"><b>Platform:</b> {step.tech}</span>}
          {move.can
            ? <button type="button" className="btn primary sm" onClick={() => go(move.page)}>{move.label}</button>
            : <span className="guide-need">{move.label}</span>}
        </div>
      )}
    </div>
  );
}

function applyGuideHash(setMode, setSel) {
  const { params } = parseHash(window.location.hash || "");
  const path = params.get("path");
  const step = params.get("step");
  if (path === "setup" || path === "execution") setMode(path);
  if (step && SETUP.some((s) => s.id === step)) {
    setMode("setup");
    setSel(step);
  } else if (step && EXECUTION.some((s) => s.id === step)) {
    setMode("execution");
    setSel(step);
  }
}

export default function HowItWorks({ go, persona }) {
  const [mode, setMode] = useState(() => defaultMode(persona));
  const steps = mode === "setup" ? SETUP : EXECUTION;
  const firstYours = useMemo(() => steps.find((s) => isYourStep(s, persona))?.id || steps[0].id, [steps, persona]);
  const [sel, setSel] = useState(firstYours);
  const showTech = canCap(persona, "readMaintenance");
  useEffect(() => {
    applyGuideHash(setMode, setSel);
    const h = () => applyGuideHash(setMode, setSel);
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => {
    const { params } = parseHash(window.location.hash || "");
    if (params.get("step")) return; // Ruling: deep-link step wins over persona default
    setMode(defaultMode(persona));
  }, [persona?.id]);
  useEffect(() => {
    const { params } = parseHash(window.location.hash || "");
    if (params.get("step")) return;
    setSel(firstYours);
  }, [firstYours]);

  const yoursCount = steps.filter((s) => isYourStep(s, persona)).length;
  const blurb = mode === "setup"
    ? "How a vendor feed becomes live — from registration to published config."
    : "What happens when a file lands — from arrival to boarded loans or exceptions.";

  return (
    <>
      <PageHeader
        eyebrow="Product guide"
        title="How loan boarding works"
        sub={(
          <>
            Signed in as <b>{persona.label}</b>. {blurb}{" "}
            {yoursCount > 0
              ? `${yoursCount} step${yoursCount === 1 ? "" : "s"} on this path are yours to act on.`
              : "You’re mostly an observer on this path — follow Who to see who acts."}
          </>
        )}
      />

      <div className="guide-intro callout">
        <p style={{ margin: 0 }}>
          Think in two paths: <b>Setup</b> (configure a feed once) and <b>Execution</b> (every file that arrives).
          Click a step for where to go and whether you can do it.
        </p>
      </div>

      <div className="row" style={{ gap: 8, margin: "14px 0 12px", flexWrap: "wrap" }} role="tablist" aria-label="Guide path">
        <button type="button" role="tab" aria-selected={mode === "setup"} className={`btn ${mode === "setup" ? "primary" : ""}`} onClick={() => setMode("setup")}>
          1 · Setup a feed
        </button>
        <button type="button" role="tab" aria-selected={mode === "execution"} className={`btn ${mode === "execution" ? "primary" : ""}`} onClick={() => setMode("execution")}>
          2 · Run a file
        </button>
        {showTech && (
          <button type="button" className="btn" style={{ marginLeft: "auto" }} onClick={() => go("maintenance")}>
            Platform code (SME)…
          </button>
        )}
      </div>

      <div className="guide-layout">
        <div className="guide-rail" role="list">
          {steps.map((s, i) => (
            <StepCard
              key={s.id}
              step={s}
              n={i + 1}
              persona={persona}
              go={go}
              showTech={showTech}
              active={sel === s.id}
              onSelect={setSel}
            />
          ))}
        </div>
        <aside className="guide-aside panel">
          <div className="panel-b stack" style={{ gap: 10 }}>
            <span className="eyebrow">{mode === "setup" ? "Setup path" : "Execution path"}</span>
            <h2 style={{ fontSize: "1.05rem" }}>{mode === "setup" ? "Configure once, publish once" : "Every file follows this path"}</h2>
            <p className="muted" style={{ margin: 0, fontSize: ".9rem" }}>
              {mode === "setup"
                ? "Until publish, Glue will not use your mapping. Drafts stay in the console only."
                : "Exceptions are normal. Straight-through loans skip the human queues; the rest wait for your role’s tier."}
            </p>
            <div className="guide-legend">
              <span><span className="guide-dot yours" /> Your step</span>
              <span><span className="guide-dot" /> Someone else’s</span>
            </div>
            <p className="faint" style={{ margin: 0, fontSize: ".8rem" }}>
              Switch persona in the left rail to see how the guide changes for Ops, SME, Reviewer, and Compliance.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
