#!/usr/bin/env node
/**
 * Captures console screenshots and builds docs/LBP-Platform-Guide.pdf
 * Requires: Vite on :5173, playwright installed in frontend/
 */
import { chromium } from "../../frontend/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../..");
const SHOTS = path.join(__dirname, "screenshots");
const OUT_HTML = path.join(__dirname, "LBP-Platform-Guide.html");
const OUT_PDF = path.join(ROOT, "docs", "LBP-Platform-Guide.pdf");
const BASE = process.env.LBP_GUIDE_URL || "http://127.0.0.1:5173";

fs.mkdirSync(SHOTS, { recursive: true });

const PAGES = [
  { id: "overview", label: "Overview" },
  { id: "guide", label: "How it works" },
  { id: "imports", label: "Import Monitor" },
  { id: "deliveries", label: "Vendor Deliveries" },
  { id: "sources", label: "Vendors & Mapping" },
  { id: "exceptions", label: "Exception Manager" },
  { id: "rules", label: "Rule Engine" },
  { id: "analytics", label: "Analytics" },
  { id: "governance", label: "Policy & Audit" },
  { id: "maintenance", label: "Maintenance" },
];

const PERSONAS = [
  {
    id: "priya.analyst",
    label: "Priya · Data Analyst",
    roles: "analyst",
    job: "Draft mappings & delivery profiles",
    guide: "Setup a feed",
    functions: [
      "Own the first pass of vendor field mapping to SSE attributes",
      "Build and iterate delivery profiles (full / change / snapshot)",
      "Propose vendor & feed metadata without publishing live config",
      "Author draft rules in plain English for SME / Compliance to harden",
    ],
    helps: [
      "Vendors & Mapping workbench with field inspector and value maps — no hand edits in SSE",
      "How it works → Setup path highlights her steps and deep-links to the right screens",
      "CAPS hide publish / approve / T5 actions so she cannot accidentally go live",
      "Audit-friendly drafts: every mapping change is versioned before SME sign-off",
    ],
    screens: "Vendors & Mapping, Rule Engine (author), How it works (Setup), Overview",
  },
  {
    id: "dan.sme",
    label: "Dan · SME",
    roles: "sme, analyst",
    job: "Approve, publish, rules, vendor lifecycle",
    guide: "Setup a feed",
    functions: [
      "Approve mappings and delivery profiles; publish signed feed config",
      "Move feeds through lifecycle; skip gaps / apply out-of-order with judgment",
      "Edit and peer-review boarding rules; shadow / canary / retire",
      "Resume blocked batches, override preflight with reason, read Maintenance",
      "Approve vendor schedules with Compliance when required",
    ],
    helps: [
      "Single publish action writes HMAC-signed config Glue will load — no SSH / ticket sprawl",
      "Maintenance surfaces Glue / SFN / notebooks for ops truth without raw AWS console hunting",
      "Capability matrix + persona switch lets him rehearse Priya’s drafts then approve as SME",
      "Rule Engine lifecycle (draft → review → deploy → monitor) keeps model-risk evidence with the rule",
    ],
    screens: "Vendors & Mapping, Rule Engine, Import Monitor, Vendor Deliveries, Maintenance, Policy & Audit (read)",
  },
  {
    id: "maria.ops",
    label: "Maria · Boarding Ops",
    roles: "ops",
    job: "Upload, monitor batches, schedules, replay",
    guide: "Run a file",
    functions: [
      "Upload or monitor vendor files; watch preflight and batch status",
      "Pause / resume / replay / discard batches within ops policy",
      "Maintain delivery schedules (SME/Compliance approve when gated)",
      "Skip sequencing gaps when authorized; escalate the rest",
    ],
    helps: [
      "Import Monitor is the run cockpit — status, preflight, sequencing, actions in one place",
      "How it works → Run a file defaults for ops so training matches the day job",
      "Vendor Deliveries shows due windows and pull health without opening SFTP tooling",
      "Platform blocks actions outside her CAPS (no mapping publish, no T5, no policy edit)",
    ],
    screens: "Import Monitor, Vendor Deliveries, How it works (Run), Overview, Analytics",
  },
  {
    id: "lee.reviewer",
    label: "Lee · Exception Reviewer",
    roles: "reviewer",
    job: "Work exception queues",
    guide: "Run a file",
    functions: [
      "Clear T2–T3 exception queues so loans can continue boarding",
      "Apply suggested fixes, document decisions, escalate dual-control items",
      "Watch open counts and root-cause patterns day to day",
    ],
    helps: [
      "Exception Manager queues by tier with root-cause rollups — not a raw Glue log dump",
      "Suggested fixes and confidence from rules / models cut average handle time",
      "Nav badge shows open exception count so backlog is visible without a report",
      "Guide marks “Your step” on exception handling; dual-control items route to Compliance (checker)",
    ],
    screens: "Exception Manager, How it works (Run), Overview, Analytics",
  },
  {
    id: "ana.compliance",
    label: "Ana · Compliance",
    roles: "compliance, checker",
    job: "Regulated rules, policy, T5, audit + T4 checker",
    guide: "Setup a feed",
    functions: [
      "Own T5 (OFAC / fraud halt) and compliance-gated exception acts",
      "Second-person approve on T4 dual-control items after Lee (maker ≠ checker)",
      "Edit exception / auto-apply policy; kill-switch T1 when override rates spike",
      "Approve regulated rules and vendor lifecycle / schedule gates",
      "Read full audit history; confirm NPI masking for other roles",
    ],
    helps: [
      "Policy & Audit is purpose-built — thresholds, kill switch, demo scale, evidence trail",
      "CAPS reserve complianceAct / editPolicy so ops and analysts cannot bypass regulation",
      "Rule Engine requires compliance sign-off on regulatory-tagged rules before go-live",
      "Same checker powers when dual-control needs a compliance-grade second signature",
    ],
    screens: "Policy & Audit, Exception Manager (T4 checker + T5), Rule Engine, Vendor Deliveries (approve), Overview",
  },
  {
    id: "admin",
    label: "Platform Admin",
    roles: "admin (+ all)",
    job: "Full access + demo setup + Maintenance",
    guide: "Setup a feed",
    functions: [
      "Bypass role checks for break-glass and environment setup",
      "Run demo seed / scale tooling; validate every screen",
      "Read Maintenance artifacts (Glue, orchestration, notebooks)",
      "Support production cutover and training with persona switching in demo mode",
    ],
    helps: [
      "Admin role short-circuits CAPS for recovery without redeploying IAM mid-incident",
      "Demo setup recreates realistic volume for UAT and executive walkthroughs",
      "Maintenance + full nav visibility for platform owners validating AWS wiring",
      "Persona switcher still available in demo so training can role-play without new accounts",
    ],
    screens: "All pages including Maintenance and demo controls on Policy & Audit / Overview",
  },
];

async function setPersona(page, personaId) {
  await page.selectOption("#persona", personaId);
  await page.waitForTimeout(600);
}

async function shot(page, name) {
  const file = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

async function capture() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  await page.goto(`${BASE}/#overview`, { waitUntil: "networkidle" });
  await page.waitForSelector("#persona");

  // Full tour as Dan (SME) — sees Maintenance + most of product
  await setPersona(page, "dan.sme");
  for (const p of PAGES) {
    await page.goto(`${BASE}/#${p.id}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    await shot(page, `dan-${p.id}`);
    console.log("shot dan", p.id);
  }

  // Guide as Lee (execution-heavy persona)
  await setPersona(page, "lee.reviewer");
  await page.goto(`${BASE}/#guide`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  await shot(page, "lee-guide");

  // Guide setup as Priya
  await setPersona(page, "priya.analyst");
  await page.goto(`${BASE}/#guide`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  // click Setup tab
  const setup = page.getByRole("tab", { name: /Setup a feed/i });
  if (await setup.count()) await setup.click();
  await page.waitForTimeout(400);
  await shot(page, "priya-guide-setup");

  // Ops import monitor
  await setPersona(page, "maria.ops");
  await page.goto(`${BASE}/#imports`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  await shot(page, "maria-imports");

  // Compliance governance
  await setPersona(page, "ana.compliance");
  await page.goto(`${BASE}/#governance`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  await shot(page, "ana-governance");

  await browser.close();
}

function img(name, caption) {
  const p = path.join(SHOTS, `${name}.png`);
  if (!fs.existsSync(p)) return `<p class="miss">[Screenshot missing: ${name}]</p>`;
  const b64 = fs.readFileSync(p).toString("base64");
  return `<figure><img src="data:image/png;base64,${b64}" alt="${caption}"/><figcaption>${caption}</figcaption></figure>`;
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function filesTable(rows) {
  return `<table class="files">
    <tr><th>Step</th><th>What happens</th><th>Code file</th><th>Entry</th></tr>
    ${rows.map(([step, what, file, entry]) =>
      `<tr><td>${esc(step)}</td><td>${esc(what)}</td><td>${esc(file)}</td><td class="mono">${esc(entry)}</td></tr>`).join("\n")}
  </table>`;
}

function flowHighLevel() {
  return `<div class="flow-board">
  <div class="flow-caption">Read left → right. Onboarding unlocks daily boarding via signed config.</div>
  <div class="flow-hl">
    <div class="flow-hl-card once">
      <div class="flow-hl-kicker">Once per vendor / feed</div>
      <b>1. Onboard</b>
      <p>Vendor → feed → map → delivery → rules → <em>publish</em></p>
      <code>vendors.py · mapping/ · delivery.py · config_store.py</code>
    </div>
    <div class="flow-arr big">→</div>
    <div class="flow-hl-bridge">
      <div class="flow-chip">signed current.json</div>
      <span>required before any file boards</span>
    </div>
    <div class="flow-arr big">→</div>
    <div class="flow-hl-card daily">
      <div class="flow-hl-kicker">Every file</div>
      <b>2. Execute</b>
      <p>Pickup → dispatch → Glue → SSE / exceptions</p>
      <code>dispatch.py · batch.py · boarding.asl.json · glue/</code>
    </div>
    <div class="flow-arr big">→</div>
    <div class="flow-hl-card watch">
      <div class="flow-hl-kicker">Ongoing</div>
      <b>3. Monitor</b>
      <p>Import Monitor · queues · policy · SNS</p>
      <code>Imports.jsx · Exceptions.jsx · manager.py</code>
    </div>
  </div>
</div>`;
}

function flowOnboard() {
  const phaseA = [
    { n: 1, label: "Create vendor", file: "vendors.py", who: "Analyst / SME" },
    { n: 2, label: "Create feed", file: "api/main.py", who: "Analyst / SME" },
    { n: 3, label: "Sample / source", file: "mapping/service.py", who: "Analyst" },
  ];
  const phaseB = [
    { n: 4, label: "Draft mapping", file: "mapping/service.py", who: "Analyst" },
    { n: 5, label: "Draft delivery", file: "pipeline/delivery.py", who: "Analyst" },
    { n: 6, label: "Draft rules", file: "rules/registry.py", who: "optional" },
    { n: 7, label: "Approve mapping", file: "api/main.py", who: "SME ≠ preparer" },
    { n: 8, label: "Approve delivery", file: "api/main.py", who: "2nd SME" },
    { n: 9, label: "Publish config", file: "config_store.py", who: "SME" },
    { n: 10, label: "Deploy rules", file: "rules/ + publish_all", who: "SME / Compliance" },
    { n: 11, label: "Schedule pull", file: "scheduling/service.py", who: "optional" },
  ];
  return `<div class="flow-board">
  <div class="flow-caption">Vendor onboarding — straight line. Drafts stay in RDS until step 9 publishes signed current.json.</div>
  <div class="flow-phase-label">Phase A — relationship</div>
  <div class="flow-pipe">${phaseA.map((s, i) => `<div class="flow-stage"><span class="flow-n">${s.n}</span><b>${esc(s.label)}</b><code>${esc(s.file)}</code><span class="flow-who">${esc(s.who)}</span></div>${i < phaseA.length - 1 ? `<div class="flow-arr">→</div>` : ""}`).join("")}</div>
  <div class="flow-down">↓</div>
  <div class="flow-phase-label">Phase B — setup &amp; go-live</div>
  <div class="flow-pipe wrap">${phaseB.map((s, i) => `<div class="flow-stage${s.n === 9 ? " accent" : ""}"><span class="flow-n">${s.n}</span><b>${esc(s.label)}</b><code>${esc(s.file)}</code><span class="flow-who">${esc(s.who)}</span></div>${i < phaseB.length - 1 ? `<div class="flow-arr">→</div>` : ""}`).join("")}</div>
  <div class="flow-note">Suspended vendor: steps still exist, but files are recorded and <b>not</b> processed. Regulated rules need Compliance before step 10 goes active.</div>
</div>`;
}

function flowExecute() {
  return `<div class="flow-board">
  <div class="flow-caption">Daily boarding — three pickup doors join one spine. Loan bytes move only inside Glue (or the local worker).</div>
  <div class="flow-doors">
    <div class="flow-door"><b>S3 push</b><code>handlers.py → on_file_arrival</code></div>
    <div class="flow-door"><b>Pull / schedule</b><code>vendor_pull_job.py → raw/</code></div>
    <div class="flow-door"><b>Ops upload</b><code>api/main.py → upload()</code></div>
  </div>
  <div class="flow-down">↓ all become a batch</div>
  <div class="flow-pipe wrap">
    <div class="flow-stage"><span class="flow-n">1</span><b>create_batch</b><code>pipeline/batch.py</code></div><div class="flow-arr">→</div>
    <div class="flow-stage accent"><span class="flow-n">2</span><b>dispatch</b><code>dispatch.py</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">3</span><b>Route engine</b><code>boarding.asl · route_batch</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">4</span><b>Glue job</b><code>feed_job / feed_spark</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">5</span><b>Sequencing</b><code>sequencing.py</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">6</span><b>Pre-flight</b><code>preflight.py</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">7</span><b>Map · rules · triage</b><code>batch.py · executor</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">8</span><b>SSE load</b><code>_persist_chunk</code></div><div class="flow-arr">→</div>
    <div class="flow-stage"><span class="flow-n">9</span><b>Finalize · SNS</b><code>finalize_batch</code></div>
  </div>
  <div class="flow-branches">
    <div><b>Hold</b> sequencing wait / out_of_order → SNS attention; followers release later</div>
    <div><b>Block</b> preflight fail → Import Monitor; SME/Compliance may override</div>
    <div><b>Exceptions</b> T1–T5 rows in RDS → Exception Manager (no Glue re-run)</div>
    <div><b>Fail</b> mark_failed + SNS; Spark fail resumes on lbp-feed from checkpoint</div>
  </div>
</div>`;
}

function flowMonitor() {
  return `<div class="flow-board">
  <div class="flow-caption">Daily monitoring — three consoles. Ops re-enters dispatch; reviewers finalize loans in the DB.</div>
  <div class="flow-monitor">
    <div class="flow-mon-col">
      <b>Batches</b>
      <code>Imports.jsx · api/main.py</code>
      <ul>
        <li>Status · preflight · sequencing</li>
        <li>pause / resume / skip-gap</li>
        <li>replay → dispatch again</li>
      </ul>
    </div>
    <div class="flow-mon-col">
      <b>Exceptions</b>
      <code>Exceptions.jsx · manager.py</code>
      <ul>
        <li>T2–T3 reviewer</li>
        <li>T4 maker → checker</li>
        <li>T5 compliance only</li>
        <li>→ _finalize_loan</li>
      </ul>
    </div>
    <div class="flow-mon-col">
      <b>Governance</b>
      <code>Governance.jsx · analytics/</code>
      <ul>
        <li>T1 kill switch · policy</li>
        <li>Audit chain</li>
        <li>Overview KPIs · SNS</li>
        <li>Maintenance (Glue / SFN)</li>
      </ul>
    </div>
  </div>
</div>`;
}

function buildHtml() {
  const today = new Date().toISOString().slice(0, 10);
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>PennyMac Loan Boarding Platform — Complete Guide</title>
<style>
  @page { size: Letter; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif; color: #15232b; font-size: 10.5pt; line-height: 1.45; }
  h1 { font-size: 22pt; letter-spacing: -0.02em; margin: 0 0 8pt; }
  h2 { font-size: 14pt; margin: 22pt 0 8pt; border-bottom: 2px solid #0b6e72; padding-bottom: 4pt; page-break-after: avoid; }
  h3 { font-size: 11.5pt; margin: 14pt 0 6pt; color: #0b6e72; page-break-after: avoid; }
  h4 { font-size: 10.5pt; margin: 10pt 0 4pt; }
  p, li { orphans: 3; widows: 3; }
  .cover { page-break-after: always; min-height: 90vh; display: flex; flex-direction: column; justify-content: center; }
  .cover .eyebrow { text-transform: uppercase; letter-spacing: .08em; color: #0b6e72; font-weight: 700; font-size: 9pt; }
  .cover .meta { margin-top: 40pt; color: #4a5a63; font-size: 10pt; }
  .toc a { color: #15232b; text-decoration: none; }
  .toc li { margin: 3pt 0; }
  table { width: 100%; border-collapse: collapse; margin: 8pt 0 14pt; font-size: 9pt; }
  th, td { border: 1px solid #d6dee2; padding: 5pt 6pt; vertical-align: top; text-align: left; }
  th { background: #e8f1f2; font-weight: 650; }
  tr { page-break-inside: avoid; }
  figure { margin: 10pt 0 16pt; page-break-inside: avoid; }
  figure img { width: 100%; border: 1px solid #d6dee2; border-radius: 4px; }
  figcaption { font-size: 8.5pt; color: #4a5a63; margin-top: 4pt; }
  .callout { background: #d8eeee; border-left: 3px solid #0b6e72; padding: 8pt 10pt; margin: 10pt 0; }
  .muted { color: #4a5a63; }
  code, .mono { font-family: "IBM Plex Mono", Menlo, monospace; font-size: 8.5pt; }
  pre { background: #f3f5f6; padding: 8pt; overflow: hidden; font-size: 8pt; white-space: pre-wrap; border-radius: 4px; }
  .section { page-break-before: auto; margin-top: 18pt; padding-top: 4pt; }
  .toc { page-break-after: always; }
  .appendix { margin-top: 22pt; padding-top: 10pt; border-top: 2px solid #0b6e72; }
  .persona { margin: 12pt 0 18pt; padding: 10pt 12pt; border: 1px solid #d6dee2; border-radius: 6px; background: #f8fbfb; page-break-inside: auto; }
  .persona h3 { margin-top: 0; page-break-after: avoid; }
  .persona .meta-row { font-size: 9pt; color: #4a5a63; margin: 0 0 8pt; }
  .persona ul { margin: 4pt 0 8pt 14pt; }
  .persona li { margin-bottom: 3pt; }
  .lld h3 { margin-top: 16pt; }
  .lld h4 { margin-top: 12pt; }
  .lld pre.code { font-size: 7.5pt; margin: 6pt 0 12pt; background: #eef2f3; }
  .files th:nth-child(3), .files td:nth-child(3) { font-family: "IBM Plex Mono", Menlo, monospace; font-size: 8pt; }
  .step-list { margin: 6pt 0 10pt 16pt; }
  .step-list li { margin-bottom: 4pt; }
  .flow-board { border: 1px solid #c5d4d8; border-radius: 8px; background: #f7fafb; padding: 10pt 12pt; margin: 8pt 0 14pt; page-break-inside: avoid; break-inside: avoid; }
  .flow-caption { font-size: 9pt; color: #4a5a63; margin: 0 0 8pt; }
  .flow-phase-label { font-size: 8.5pt; font-weight: 700; color: #0b6e72; text-transform: uppercase; letter-spacing: .04em; margin: 6pt 0 4pt; }
  .flow-pipe { display: flex; flex-wrap: nowrap; align-items: stretch; gap: 0; overflow: hidden; }
  .flow-pipe.wrap { flex-wrap: wrap; row-gap: 8pt; }
  .flow-stage { flex: 1 1 72pt; min-width: 64pt; max-width: 110pt; background: #fff; border: 1px solid #d6dee2; border-radius: 6px; padding: 5pt 6pt; text-align: center; }
  .flow-stage.accent { border-color: #0b6e72; background: #e7f4f4; }
  .flow-stage b { display: block; font-size: 8.5pt; line-height: 1.25; margin: 2pt 0; }
  .flow-stage code { display: block; font-size: 6.5pt; color: #4a5a63; word-break: break-word; }
  .flow-stage .flow-who { display: block; font-size: 7pt; color: #0b6e72; margin-top: 2pt; }
  .flow-n { display: inline-block; width: 14pt; height: 14pt; line-height: 14pt; border-radius: 50%; background: #0b6e72; color: #fff; font-size: 7.5pt; font-weight: 700; }
  .flow-arr { flex: 0 0 14pt; align-self: center; text-align: center; color: #0b6e72; font-size: 12pt; font-weight: 700; }
  .flow-arr.big { flex: 0 0 18pt; font-size: 16pt; }
  .flow-down { text-align: center; color: #0b6e72; font-size: 12pt; font-weight: 700; margin: 4pt 0; }
  .flow-note { font-size: 8pt; color: #4a5a63; margin-top: 8pt; padding-top: 6pt; border-top: 1px dashed #c5d4d8; }
  .flow-hl { display: flex; align-items: stretch; gap: 4pt; }
  .flow-hl-card { flex: 1; background: #fff; border: 1px solid #d6dee2; border-radius: 6px; padding: 8pt; }
  .flow-hl-card.once { border-top: 3px solid #0b6e72; }
  .flow-hl-card.daily { border-top: 3px solid #2a6f97; }
  .flow-hl-card.watch { border-top: 3px solid #5c6b73; }
  .flow-hl-kicker { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .05em; color: #4a5a63; font-weight: 700; }
  .flow-hl-card b { display: block; font-size: 11pt; margin: 3pt 0; }
  .flow-hl-card p { margin: 0 0 6pt; font-size: 8.5pt; }
  .flow-hl-card code { font-size: 6.5pt; color: #4a5a63; }
  .flow-hl-bridge { flex: 0 0 78pt; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; font-size: 7.5pt; color: #4a5a63; gap: 4pt; }
  .flow-chip { background: #0b6e72; color: #fff; border-radius: 999px; padding: 3pt 8pt; font-size: 7pt; font-weight: 700; white-space: nowrap; }
  .flow-doors { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6pt; margin-bottom: 2pt; }
  .flow-door { background: #fff; border: 1px dashed #0b6e72; border-radius: 6px; padding: 6pt; text-align: center; }
  .flow-door b { display: block; font-size: 9pt; }
  .flow-door code { display: block; font-size: 6.5pt; color: #4a5a63; margin-top: 3pt; }
  .flow-branches { display: grid; grid-template-columns: 1fr 1fr; gap: 4pt 10pt; margin-top: 8pt; font-size: 8pt; color: #4a5a63; }
  .flow-branches b { color: #0b6e72; }
  .flow-monitor { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8pt; }
  .flow-mon-col { background: #fff; border: 1px solid #d6dee2; border-radius: 6px; padding: 8pt; }
  .flow-mon-col b { display: block; font-size: 10pt; margin-bottom: 2pt; }
  .flow-mon-col code { display: block; font-size: 6.5pt; color: #4a5a63; margin-bottom: 6pt; }
  .flow-mon-col ul { margin: 0; padding-left: 14pt; font-size: 8pt; }
  .flow-mon-col li { margin-bottom: 2pt; }
  ol.steps li { margin-bottom: 6pt; }
  .miss { color: #b3261e; }
  .flow-box { border: 1px solid #d6dee2; border-radius: 6px; padding: 8pt 10pt; margin: 6pt 0; background: #f8fbfb; page-break-inside: avoid; }
  .flow-box b.phase { display: block; color: #0b6e72; font-size: 9pt; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 3pt; }
  .flow-arrow { text-align: center; color: #0b6e72; font-size: 14pt; margin: 2pt 0; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }
</style>
</head>
<body>

<section class="cover">
  <div class="eyebrow">PennyMac · Servicing Systems of Engagement</div>
  <h1>Loan Boarding Platform<br/>Complete Product &amp; Capabilities Guide</h1>
  <p style="font-size:12pt;max-width:34em">How PennyMac onboards a vendor, sets up a feed, picks up files, boards loans into SSE, and resolves exceptions — end to end. Powered by LDS IntelliMap.</p>
  <div class="meta">
    <div>Document: LBP-Platform-Guide</div>
    <div>Generated: ${today}</div>
    <div>Audience: Product, operations, SME, compliance, platform, executives</div>
    <div>Start here: §1 Product · Appendix A personas · Appendix B LLD flows</div>
  </div>
</section>

<section class="toc">
  <h2>Contents</h2>
  <ol>
    <li>Product description — what LBP is and why it exists</li>
    <li>The whole process at a glance</li>
    <li>Phase A — Onboard the vendor</li>
    <li>Phase B — Setup the feed &amp; publish</li>
    <li>Phase C — How a file is picked up</li>
    <li>Phase D — Boarding execution</li>
    <li>Phase E — Exceptions, outcomes &amp; notifications</li>
    <li>Who does what — personas</li>
    <li>Full capability matrix</li>
    <li>Architecture (control plane vs data plane)</li>
    <li>Signed configuration &amp; publish events</li>
    <li>Glue jobs &amp; orchestration</li>
    <li>Delivery scheduler &amp; vendor pull</li>
    <li>Vendors, feeds, incremental loads &amp; sequencing</li>
    <li>Exception tiers and change-file rules</li>
    <li>Console tour (every screen)</li>
    <li>Security, compliance &amp; production readiness</li>
    <li>Operator runbook</li>
    <li>Web app UX patterns</li>
    <li>Verified evidence &amp; go-live checklist</li>
    <li>Glossary</li>
    <li>Appendix A — Personas in depth</li>
    <li>Appendix B — LLD: onboarding, daily execution &amp; monitoring</li>
  </ol>
  <p class="muted">Reading order: product story (§1–7) → people (§8–9) → how it is built (§10–12) → domain depth (§13–15) → screens (§16) → ops (§17–21) → Appendix A (personas) → Appendix B (LLD flows).</p>
</section>

<section class="section">
  <h2>1. Product description — what LBP is and why it exists</h2>

  <h3>The problem</h3>
  <p>PennyMac boards loans from many counterparties (correspondents, bulk sellers, sub-servicers, retail channels). Each sends files in their own layout, on their own schedule, sometimes as full tapes and sometimes as change or snapshot files. Those loans must land correctly in the Servicing System of Engagement (SSE), under regulated rules, with a clear audit trail — without Ops hand-editing rows in production.</p>

  <h3>What the product is</h3>
  <p>The <b>Loan Boarding Platform (LBP)</b> is the product that:</p>
  <ol>
    <li><b>Onboards</b> a vendor and their feed(s) into the console.</li>
    <li><b>Sets up</b> mapping, rules, and delivery behaviour — then <b>publishes</b> a signed live configuration.</li>
    <li><b>Picks up</b> every arriving file (push to S3, scheduled pull, or Ops upload).</li>
    <li><b>Boards</b> loans through Glue: map → validate → triage → load to SSE, with sequencing and checkpoints.</li>
    <li><b>Routes</b> bad or risky rows to people by exception tier (auto → reviewer → checker → compliance).</li>
    <li><b>Governs</b> change with maker-checker, hash-chained audit, and role-based access.</li>
  </ol>

  <h3>What users see</h3>
  <p>The <b>Loan Boarding Console</b> (React web app) is the day-to-day product surface: Overview, How it works, Import Monitor, Vendor Deliveries, Vendors &amp; Mapping, Exception Manager, Rule Engine, Analytics, Policy &amp; Audit. SME and Platform Admin also get <b>Maintenance</b> (read-only Glue / orchestration source).</p>
  <p>Behind the console, the <b>control plane</b> (API + Lambdas + Step Functions) never transforms loan data. The <b>data plane</b> (AWS Glue jobs) does all parsing, mapping, validation and loading — and only from a <b>signed, published</b> feed configuration. Drafts never run.</p>

  <h3>Outcomes the product is judged on</h3>
  <table>
    <tr><th>Outcome</th><th>How the product delivers it</th></tr>
    <tr><td>Straight-through boarding</td><td>Published mapping + rules; micro-batch load; reconciliation</td></tr>
    <tr><td>Controlled exceptions</td><td>Tiers T1–T5; dual control on protected fields; Compliance for OFAC/fraud</td></tr>
    <tr><td>Vendor correctness</td><td>Per-feed sequencing; delivery windows; late/missed alerts; pull connectors</td></tr>
    <tr><td>Change without chaos</td><td>Incremental/snapshot load types; change log; optimistic concurrency</td></tr>
    <tr><td>Auditability</td><td>Maker-checker; signed configs; hash-chained audit; CloudTrail alignment</td></tr>
  </table>
  ${img("dan-overview", "Overview — the product’s executive view (Dan · SME)")}
</section>

<section class="section">
  <h2>2. The whole process at a glance</h2>
  <p>Everything in LBP is one of two journeys. <b>Setup</b> happens once per feed (and again when mapping/rules/delivery change). <b>Execution</b> happens for every file.</p>

  <div class="flow-box">
    <b class="phase">Phase A — Onboard</b>
    Agree counterpart → create <b>Vendor</b> → create one or more <b>Feeds</b> → set lifecycle (active / suspended)
  </div>
  <div class="flow-arrow">↓</div>
  <div class="flow-box">
    <b class="phase">Phase B — Setup</b>
    Map columns → attach rules → delivery profile → <b>SME publish signed config</b> → optional pull schedule
  </div>
  <div class="flow-arrow">↓</div>
  <div class="flow-box">
    <b class="phase">Phase C — File pickup</b>
    Three doors into the same pipe: <b>S3 push</b> · <b>scheduled / pull-now</b> · <b>Ops upload</b>
  </div>
  <div class="flow-arrow">↓</div>
  <div class="flow-box">
    <b class="phase">Phase D — Boarding run</b>
    Register batch → sequence gate → route engine → Glue board → checkpoint → reconcile
  </div>
  <div class="flow-arrow">↓</div>
  <div class="flow-box">
    <b class="phase">Phase E — Finish</b>
    Straight-through loans in SSE · exceptions in queues · SNS / Import Monitor status · release waiting files
  </div>

  <pre style="margin-top:12pt">ONBOARD          SETUP (once)              PICKUP (every file)           RUN                         FINISH
Vendor ──▶ Feed ──▶ Map+Rules+Delivery ──▶ S3 | Pull | Upload ──▶ Batch+Gate+Glue ──▶ SSE + Exceptions + Notify
                         │ publish │
                         ▼
                   signed current.json
                   (only thing Glue trusts)</pre>

  <div class="callout"><b>Read this first.</b> Sections 3–7 walk each phase in product language. Later sections are depth (architecture, CAPS, screens, ops).</div>
  ${img("dan-guide", "In-app How it works — same Setup / Run story for every persona")}
</section>

<section class="section">
  <h2>3. Phase A — Onboard the vendor relationship</h2>
  <p><b>Goal:</b> PennyMac can receive and attribute files from a named counterparty without mixing them with another vendor’s portfolio.</p>
  <ol class="steps">
    <li><b>Identify the counterparty</b> — correspondent, bulk seller, sub-servicer, internal channel, etc.</li>
    <li><b>Create the Vendor</b> in Vendors &amp; Mapping (Analyst / SME). Capture identity and status.</li>
    <li><b>Create one or more Feeds</b> under that vendor. A feed = one file layout (boarding tape vs intraday changes can be separate feeds).</li>
    <li><b>Lifecycle</b> — SME/Compliance can suspend a vendor. Suspended vendors’ files are <i>recorded</i> but <i>not processed</i>.</li>
    <li><b>Scope the console</b> — the left-rail vendor selector limits Import Monitor, exceptions, deliveries, and APIs to that vendor.</li>
  </ol>
  <p class="muted">Integrity: a change file cannot quietly alter another vendor’s loans (CHG06 → dual control, servicing transfer only).</p>
  ${img("dan-sources", "Vendors & Mapping — where onboarding and feed setup live")}
</section>

<section class="section">
  <h2>4. Phase B — Setup the feed (configuration &amp; publish)</h2>
  <p><b>Goal:</b> Glue knows exactly how to interpret this feed’s files. Until publish, nothing is live.</p>
  <ol class="steps">
    <li><b>Mapping</b> — Analyst maps vendor columns → SSE fields (draft). SME (not the preparer) approves.</li>
    <li><b>Rules</b> — Attach validation rules. Regulated rules need Compliance as well as SME.</li>
    <li><b>Delivery profile</b> — full / incremental / snapshot; action codes; clear tokens; protected fields; sequencing. Second SME approves changes.</li>
    <li><b>Publish</b> — SME publishes the signed configuration (“Glue config vN”). This is the go-live switch.</li>
    <li><b>Optional schedule</b> — If PennyMac pulls files, Ops proposes a schedule; SME/Compliance approve. Hosts/keys allow-listed.</li>
  </ol>
  <div class="callout"><b>Publish is the contract with Glue.</b> Drafts and proposed profiles stay in the console only. Glue reads <code>current.json</code> (HMAC-signed). A hand-edited or stale bundle is refused and the batch fails as configuration rejected.</div>
  ${img("priya-guide-setup", "Setup path as Priya · Analyst — Your step chips show what she can do")}
</section>

<section class="section">
  <h2>5. Phase C — How a file is picked up</h2>
  <p><b>Goal:</b> Every file, however it arrives, becomes the same kind of <b>batch</b> on the same boarding path.</p>
  <table>
    <tr><th>Door</th><th>Who / what</th><th>What happens</th></tr>
    <tr><td><b>S3 push</b></td><td>Vendor (or gateway) writes to <code>raw/incoming/&lt;feed&gt;/…</code></td><td>EventBridge Object Created → Lambda <code>on_file_arrival</code> → <code>create_batch</code> → dispatch</td></tr>
    <tr><td><b>Scheduled / pull-now</b></td><td>Scheduler tick or Ops/SME Pull now</td><td>Glue <code>lbp-vendor-pull</code> fetches via SFTP/S3 into raw → same arrival event</td></tr>
    <tr><td><b>Ops upload</b></td><td>Maria · Boarding Ops in Import Monitor</td><td>API stores file under uploads/raw → dispatch (same pipeline)</td></tr>
  </table>
  <p>Duplicates are ignored (linked to the prior batch). Bad prefixes are logged and skipped. Load type can come from metadata or the delivery profile (Ops can override on upload).</p>
  ${img("maria-imports", "Import Monitor — Ops uploads and watches every batch")}
</section>

<section class="section">
  <h2>6. Phase D — Boarding execution (the run)</h2>
  <p><b>Goal:</b> Turn one batch into boarded SSE loans (and held exceptions), safely and restartably.</p>
  <ol class="steps">
    <li><b>Dispatch</b> — AWS: start Step Functions boarding. Local/demo: in-process thread. Same business steps.</li>
    <li><b>Route</b> — Choose engine: standard <code>lbp-feed</code> (default) or <code>lbp-feed-spark</code> for very large full text tapes.</li>
    <li><b>Sequencing gate</b> — Is this the next file for the vendor? If not → waiting / out_of_order (see §14).</li>
    <li><b>Pre-flight</b> — Schema/drift vs published config. Block → Import Monitor remediation or SME/Compliance override.</li>
    <li><b>Map → validate → triage (T1–T5)</b> — Good rows proceed; failures become exceptions by tier.</li>
    <li><b>Apply</b> — Full tape: board new loans. Incremental/snapshot: merge/plan changes (CHG rules as needed).</li>
    <li><b>Checkpoint</b> — Micro-batches commit; crash/resume continues; Spark failure can fall back to standard.</li>
    <li><b>Reconcile</b> — Source rows accounted for; advance vendor sequence cursor on success.</li>
  </ol>
  <pre>dispatch → route_batch → Glue (lbp-feed | lbp-feed-spark .sync)
        → finalize_batch → Outcome → SNS
        → release queued followers (dispatch again)</pre>
  ${img("dan-maintenance", "Maintenance — Glue jobs and orchestration artifacts (SME/Admin)")}
</section>

<section class="section">
  <h2>7. Phase E — Exceptions, outcomes &amp; notifications</h2>
  <p><b>Goal:</b> Humans only touch what needs judgment; everything else is audible and auditable.</p>
  <div class="two-col">
    <div>
      <h4>Outcomes (Import Monitor / SNS)</h4>
      <ul>
        <li><b>completed + balanced</b> — success notify</li>
        <li><b>waiting</b> — sequencing gate; not a failure</li>
        <li><b>blocked / out_of_order / paused</b> — needs attention</li>
        <li><b>failed</b> — mark_failed + SNS; fix and resume/replay</li>
      </ul>
    </div>
    <div>
      <h4>Exceptions (Exception Manager)</h4>
      <ul>
        <li><b>T1</b> — auto (kill switch / rate limit)</li>
        <li><b>T2–T3</b> — Reviewer</li>
        <li><b>T4</b> — Maker + Checker</li>
        <li><b>T5</b> — Compliance only (OFAC/fraud halt)</li>
      </ul>
    </div>
  </div>
  ${img("dan-exceptions", "Exception Manager — human work after Glue triage")}
  ${img("lee-guide", "Lee · Reviewer — guide highlights execution steps that are theirs")}
</section>

<section class="section">
  <h2>8. Who does what — personas</h2>
  <p>Demo and local modes switch persona in the left rail. Production uses Cognito groups mapped to the same roles. For functions and how the platform helps each person, see <b>Appendix A</b>.</p>
  <table>
    <tr><th>Persona</th><th>Roles</th><th>Primary job</th><th>Default guide path</th></tr>
    ${PERSONAS.map((p) => `<tr><td>${p.label}</td><td class="mono">${p.roles}</td><td>${p.job}</td><td>${p.guide}</td></tr>`).join("\n")}
  </table>
  ${img("lee-guide", "How it works — Lee · Reviewer defaults to Execution (“Run a file”) with Your step chips")}
  ${img("priya-guide-setup", "How it works — Priya · Analyst on Setup a feed")}
</section>

<section class="section">
  <h2>9. Full capability matrix</h2>
  <p>Capabilities mirror backend <code>ROUTE_ROLES</code> / <code>CAPS</code>. Admin bypasses any role check.</p>
  <table>
    <tr><th>Capability</th><th>Roles</th><th>Where in console</th></tr>
    <tr><td>editMapping</td><td>analyst, sme</td><td>Vendors &amp; Mapping</td></tr>
    <tr><td>approveMapping</td><td>sme</td><td>Vendors &amp; Mapping</td></tr>
    <tr><td>upload</td><td>ops</td><td>Import Monitor</td></tr>
    <tr><td>pauseBatch</td><td>ops</td><td>Import Monitor</td></tr>
    <tr><td>resumeBatch</td><td>ops, sme</td><td>Import Monitor</td></tr>
    <tr><td>overridePreflight</td><td>sme, compliance</td><td>Import Monitor</td></tr>
    <tr><td>replay</td><td>ops, sme</td><td>Import Monitor</td></tr>
    <tr><td>workExceptions</td><td>reviewer, checker, compliance</td><td>Exception Manager</td></tr>
    <tr><td>checkerApprove</td><td>checker, compliance</td><td>Exception Manager</td></tr>
    <tr><td>complianceAct</td><td>compliance</td><td>Exception Manager (T5)</td></tr>
    <tr><td>editRules / authorRules</td><td>sme, compliance (+ analyst author)</td><td>Rule Engine</td></tr>
    <tr><td>editPolicy</td><td>compliance</td><td>Policy &amp; Audit</td></tr>
    <tr><td>demoSetup</td><td>admin</td><td>Policy &amp; Audit / Overview</td></tr>
    <tr><td>editVendors / vendorLifecycle</td><td>analyst/sme · sme/compliance</td><td>Vendors &amp; Mapping</td></tr>
    <tr><td>moveFeed / publishConfig</td><td>sme</td><td>Vendors &amp; Mapping</td></tr>
    <tr><td>editDelivery / approveDelivery</td><td>analyst/sme · sme</td><td>Vendors &amp; Mapping</td></tr>
    <tr><td>skipGap / applyOutOfOrder / discardBatch</td><td>ops/sme · sme/compliance · ops/sme</td><td>Import Monitor</td></tr>
    <tr><td>snapshotReviews</td><td>sme</td><td>Import Monitor / Exceptions</td></tr>
    <tr><td>schedules / approveSchedule</td><td>ops/sme · sme/compliance</td><td>Vendor Deliveries</td></tr>
    <tr><td>readAudit</td><td>compliance, sme</td><td>Policy &amp; Audit</td></tr>
    <tr><td>readMaintenance</td><td>sme, admin</td><td>Maintenance</td></tr>
  </table>
</section>

<section class="section">
  <h2>10. Architecture (control plane vs data plane)</h2>
  <h3>End-to-end path</h3>
  <pre>Web app (React) ──JWT──▶ API Gateway ─▶ api Lambda (FastAPI)
                              │  approve mapping / delivery / rules
                              ▼
                    config_store.publish ─▶ S3 processed/config/feeds/&lt;feed&gt;/ (HMAC-signed)

Vendor file ─▶ S3 raw/incoming/ ─EventBridge─▶ on_file_arrival ─▶ Step Functions
API upload  ─▶ S3 raw/uploads/  ──────────────────────────────▶   Route → Glue lbp-feed | lbp-feed-spark
Vendor pull (lbp-vendor-pull) ─▶ raw/incoming/ ─┘                 Finalize → SNS / MarkFailed</pre>
  <h3>Why this split</h3>
  <table>
    <tr><th>Concern</th><th>Decision</th></tr>
    <tr><td>All data integration on Glue</td><td>Every byte of loan data is parsed, mapped, validated and loaded inside Glue. Lambdas only register, route, report and serve the API.</td></tr>
    <tr><td>Driven by the web app</td><td>Glue jobs take <code>--batch_id</code> (or <code>--schedule_id</code>). Everything else comes from the published feed configuration.</td></tr>
    <tr><td>Drafts never run</td><td>Draft mapping / proposed delivery profile is not published. Glue reads <code>current.json</code>.</td></tr>
    <tr><td>Tamper-evident</td><td>Each bundle has SHA-256 + HMAC. Tampered/stale config → batch fails with audited <code>batch.config_rejected</code>.</td></tr>
    <tr><td>Live safety switches</td><td>T1 kill switch, auto-suspension, vendor suspended status are read from DB at run time.</td></tr>
    <tr><td>Same code everywhere</td><td>The <code>lbp</code> wheel runs in Glue, local worker and tests.</td></tr>
  </table>
</section>

<section class="section">
  <h2>11. Signed configuration &amp; publish events</h2>
  <p>Belongs with Phase B (setup). Glue never boards from a draft.</p>
  <table>
    <tr><th>Event</th><th>Published</th></tr>
    <tr><td>Mapping version approved (SME ≠ preparer)</td><td>that feed</td></tr>
    <tr><td>Delivery profile approved (second SME)</td><td>that feed</td></tr>
    <tr><td>Rule enters/leaves active/canary/shadow or retires</td><td>every live feed</td></tr>
    <tr><td>Feed moved to another vendor</td><td>every live feed</td></tr>
    <tr><td>migrate Lambda on deploy</td><td>any live feed missing a bundle</td></tr>
    <tr><td>Republish (SME + reason)</td><td>that feed</td></tr>
  </table>
  <p>UI shows “Glue config vN” chips with version, mapping version, rule counts, signature status, sync with active mapping, and history.</p>
</section>

<section class="section">
  <h2>12. Glue jobs &amp; orchestration</h2>
  <p>Belongs with Phase D (boarding run).</p>
  <table>
    <tr><th>Job</th><th>Runtime</th><th>Used for</th></tr>
    <tr><td><code>lbp-feed</code></td><td>Glue 5.0 Python 3.11, driver</td><td>Default every batch; also replay</td></tr>
    <tr><td><code>lbp-feed-spark</code></td><td>Glue Spark</td><td>Very large full CSV/TXT/PSV/DAT; fallback to standard on failure</td></tr>
    <tr><td><code>lbp-vendor-pull</code></td><td>Glue 5.0 driver</td><td>Fetch into raw zone only</td></tr>
  </table>
  <h3>Step Functions boarding (ASL)</h3>
  <pre>Route (route_batch) → Engine choice
  → GlueStandard (lbp-feed .sync) | GlueSpark (lbp-feed-spark .sync)
  → Spark TaskFailed may fall back to GlueStandard
  → Finalize (finalize_batch) → Outcome
       completed+balanced → NotifyCompleted (SNS)
       waiting → Succeed (sequencing gate)
       out_of_order / blocked / paused → NotifyAttention
       else → NotifyFailed → Failed
  Catch → mark_failed → SNS → Failed</pre>
  <p>Notebooks under <code>aws/glue/notebooks/</code> are development only — they never board loans.</p>
  ${img("dan-maintenance", "Maintenance — Glue / SFN / Lambda source (SME)")}
</section>

<section class="section">
  <h2>13. Delivery scheduler &amp; vendor pull</h2>
  <p>Belongs with Phase C (file pickup). Arrival stays <b>event-driven</b>; the scheduler watches deadlines and pulls — it never delays a file that already landed.</p>
  <ul>
    <li>EventBridge Scheduler ~every 5 minutes → <code>scheduler_tick</code> (reserved concurrency 1).</li>
    <li>Cron in vendor IANA timezone (DST-safe), Fed holidays (skip / next business day).</li>
    <li>Options: grace, miss-after, early accept, files per delivery, filename filter, load type for pulls.</li>
    <li>Delivery states: expected → received | late → missed → received_late; waived stops alerts.</li>
    <li>Due pulls start Glue <code>lbp-vendor-pull</code> (SFTP pinned host key or S3). Files land in <code>raw/incoming/</code> and follow normal arrival.</li>
    <li>Pull-now from console for Ops/SME with schedule rights. Manual: <code>python -m lbp.cli tick</code>.</li>
    <li>Leader lease; alerts stamped once; dead-man’s-switch if no tick for 15 minutes.</li>
    <li>SFTP: host key mandatory; credentials from Secrets Manager; allow-listed hosts/CIDRs; never delete remote.</li>
  </ul>
  ${img("dan-deliveries", "Vendor Deliveries — schedules and pull windows")}
</section>

<section class="section">
  <h2>14. Vendors, feeds, incremental loads &amp; sequencing</h2>
  <h3>Vendors and feeds</h3>
  <ul>
    <li>A <b>vendor</b> is the counterparty; a <b>feed</b> is one file layout with its own mapping, delivery profile, schedules and numbering.</li>
    <li>Sidebar vendor scope filters operational pages and APIs (<code>?vendor_id=</code>).</li>
    <li>Suspended vendor files are recorded but not processed.</li>
    <li>CHG06: change file touching another vendor’s loan → dual control (servicing transfer only).</li>
  </ul>
  <h3>Load types</h3>
  <table>
    <tr><th>Type</th><th>Meaning</th><th>Platform behaviour</th></tr>
    <tr><td>full</td><td>Complete boarding tape</td><td>New loans; DUP02 re-board protection</td></tr>
    <tr><td>incremental</td><td>Add / update / close</td><td>Merge onto live SSE, then full rules</td></tr>
    <tr><td>snapshot</td><td>Whole current portfolio</td><td>Adds/updates/unchanged + missing → CHG04</td></tr>
  </table>
  <h3>Change application (summary)</h3>
  <ul>
    <li>Blank = no change (or clear if profile says so); <code>clear_token</code> empties a field.</li>
    <li>Identical to SSE → unchanged (slim marker only).</li>
    <li>Protected fields → CHG01 (T4 dual control). Set-once originals never overwritten by change files.</li>
    <li>Optimistic concurrency via <code>lbp_version</code>; conflicts → CHG05.</li>
    <li>Closes set <code>lbp_status=closed</code>; never delete. All applied changes in <code>loan_changes</code>.</li>
  </ul>
  <h3>File order &amp; sequencing outcomes</h3>
  <p>Sequence from file name regex or column. Gate + lease in one transaction — exactly one “next” file under concurrency. Vendor cursor (<code>sources.last_sequence</code>) only moves forward on completed batches.</p>
  <table>
    <tr><th>Situation</th><th>Status</th><th>Resolution</th></tr>
    <tr><td>Earlier file of this vendor still pending</td><td><code>waiting</code></td><td>Released when that file completes</td></tr>
    <tr><td>Integer gap (44 arrives, 43 missing), strict profile</td><td><code>waiting</code></td><td>43 arrives; or Ops skips gap with reason</td></tr>
    <tr><td>File not newer than last applied</td><td><code>out_of_order</code></td><td>SME discards or applies with every change dual-controlled</td></tr>
    <tr><td>Same sequence as a pending file</td><td>Refused at arrival</td><td>Discard the pending one first</td></tr>
  </table>
</section>

<section class="section">
  <h2>15. Exception tiers and change-file rules</h2>
  <p>Belongs with Phase E (finish / human work).</p>
  <h3>Tiers (confidence × risk)</h3>
  <table>
    <tr><th>Tier</th><th>Who acts</th><th>Notes</th></tr>
    <tr><td>T1</td><td>Auto-apply (kill switch / rate limit)</td><td>AI never on regulated fields</td></tr>
    <tr><td>T2–T3</td><td>Reviewer</td><td>Standard exception work</td></tr>
    <tr><td>T4</td><td>Maker + Checker</td><td>Protected / dual control</td></tr>
    <tr><td>T5</td><td>Compliance only</td><td>OFAC / fraud — loan halted</td></tr>
  </table>
  <h3>Change-file exception codes</h3>
  <table>
    <tr><th>Rule</th><th>When</th><th>Resolution</th></tr>
    <tr><td>CHG01</td><td>Protected field changed</td><td>Apply vendor / keep SSE / reject (T4)</td></tr>
    <tr><td>CHG02</td><td>Update/close for loan not in SSE</td><td>Correct loan number</td></tr>
    <tr><td>CHG03</td><td>Change for closed loan</td><td>Reopen+apply or reject</td></tr>
    <tr><td>CHG04</td><td>Loan missing from snapshot</td><td>Confirm closed or keep active</td></tr>
    <tr><td>CHG05</td><td>Concurrent change</td><td>Keep SSE or apply vendor</td></tr>
    <tr><td>CHG06</td><td>Other vendor’s loan</td><td>Servicing transfer dual control or reject</td></tr>
    <tr><td>ACT01</td><td>Unknown action code</td><td>Default action or reject; update profile</td></tr>
  </table>
</section>

<section class="section">
  <h2>16. Console tour (every screen)</h2>
  <p>Screenshots of the live product after the process story. Use §1–7 to learn the flow; use this section to find the screen.</p>

  <h3>16.1 Overview</h3>
  <p>Executive KPIs: loans boarded, straight-through rate, blocking exceptions, compliance blocks, projected capacity. Charts for exception flow and investor mix. Shortcuts by persona.</p>
  ${img("dan-overview", "Overview")}

  <h3>16.2 How it works</h3>
  <p>In-app product guide for Phases A–E. Two tabs: Setup a feed / Run a file. Persona-aware “Your step” and Go-to CTAs. SME/Admin link to Maintenance.</p>
  ${img("dan-guide", "How it works")}

  <h3>16.3 Import Monitor</h3>
  <p>Batches: upload, pause/resume, pre-flight override, sequencing skip/out-of-order, replay, discard, loan change log.</p>
  ${img("dan-imports", "Import Monitor (SME)")}
  ${img("maria-imports", "Import Monitor — Maria · Ops")}

  <h3>16.4 Vendor Deliveries</h3>
  <p>Schedules, windows, late/missed alerts, pull-now, waivers, maker-checker on schedule changes.</p>
  ${img("dan-deliveries", "Vendor Deliveries")}

  <h3>16.5 Vendors &amp; Mapping</h3>
  <p>Vendors and feeds, mapping workbench, field inspector, validation preview, version diff, delivery profile, Glue config chip.</p>
  ${img("dan-sources", "Vendors & Mapping")}

  <h3>16.6 Exception Manager</h3>
  <p>Queues by tier T1–T5. Reviewer / checker / compliance actions with reasons.</p>
  ${img("dan-exceptions", "Exception Manager")}

  <h3>16.7 Rule Engine</h3>
  <p>Author in plain English, draft edit, lifecycle transitions. Regulatory tags force Compliance.</p>
  ${img("dan-rules", "Rule Engine")}

  <h3>16.8 Analytics</h3>
  <p>Executive and exception analytics; ask-style questions where enabled.</p>
  ${img("dan-analytics", "Analytics")}

  <h3>16.9 Policy &amp; Audit</h3>
  <p>Routing policy, T1 kill switch, hash-chained audit, demo scenario (admin).</p>
  ${img("dan-governance", "Policy & Audit")}
  ${img("ana-governance", "Policy & Audit — Ana · Compliance")}

  <h3>16.10 Maintenance</h3>
  <p>Read-only Glue jobs, shared libraries, Step Functions ASL, Lambdas, notebooks. SME/Admin only.</p>
  ${img("dan-maintenance", "Maintenance")}
</section>

<section class="section">
  <h2>17. Security, compliance &amp; production readiness</h2>
  <table>
    <tr><th>Requirement</th><th>Control</th></tr>
    <tr><td>SOX</td><td>Maker-checker; signed configs; hash-chained audit (+ CloudTrail)</td></tr>
    <tr><td>GLBA / NPI</td><td>KMS, TLS, role masking, retention purge, no NPI in logs/SFN</td></tr>
    <tr><td>SR 11-7</td><td>No AI auto-apply on T4/T5; T1 kill switch &amp; override-rate suspend</td></tr>
    <tr><td>ECOA/HMDA/TILA/RESPA</td><td>Regulatory tags; Compliance approval; dual control on sensitive fields</td></tr>
    <tr><td>OFAC / BSA-AML</td><td>T5 halt; Compliance only</td></tr>
    <tr><td>Least privilege</td><td>Cognito groups; scoped IAM; limited egress</td></tr>
    <tr><td>Credentials</td><td>Secrets Manager rotation; OIDC deploys; no long-lived keys in TF</td></tr>
    <tr><td>Edge</td><td>WAF, rate limit, geo, CSP/headers</td></tr>
  </table>
  <p class="muted">Status: ready for UAT in PennyMac AWS; go-live needs account-specific items outside the codebase.</p>
</section>

<section class="section">
  <h2>18. Operator runbook</h2>
  <table>
    <tr><th>Situation</th><th>What to do</th></tr>
    <tr><td>Batch <b>blocked</b> by pre-flight</td><td>Import Monitor → mapping fix + SME approve + resume; or SME/Compliance override with reason</td></tr>
    <tr><td>Batch stuck <b>running</b></td><td>Auto-requeue after 10 min without heartbeat; <code>python -m lbp.cli recover</code></td></tr>
    <tr><td>Reconciliation <b>mismatch</b></td><td>SNS alert; compare staged/boarded/held/rejected; LOAD/SCHEMA exceptions</td></tr>
    <tr><td><b>T1 auto-suspended</b></td><td>Policy &amp; Audit; re-enable needs two Compliance users</td></tr>
    <tr><td>Emergency stop of AI fixes</td><td>Compliance sets <code>t1_enabled=false</code></td></tr>
    <tr><td>Audit integrity</td><td><code>python -m lbp.cli verify-audit</code> (daily)</td></tr>
    <tr><td>Retention</td><td><code>python -m lbp.cli purge</code> (daily)</td></tr>
    <tr><td>Glue run <b>failed</b></td><td>Fix cause; Resume from checkpoint; Spark may fall back to standard</td></tr>
    <tr><td>Batch failed <b>configuration</b></td><td>Glue config chip → SME Republish → Resume</td></tr>
    <tr><td>Vendor file <b>late / missed</b></td><td>Chase vendor; Pull now or Waive</td></tr>
    <tr><td>Change file <b>waiting</b> / <b>out of order</b></td><td>Wait / Skip gap / Discard / SME apply with dual control</td></tr>
    <tr><td>Snapshot truncation suspected</td><td>Confirm with vendor; resend or SME raise closes</td></tr>
    <tr><td><b>Scheduler silent</b></td><td>Check Lambda / EventBridge; <code>python -m lbp.cli tick</code></td></tr>
  </table>
</section>

<section class="section">
  <h2>19. Web app UX patterns</h2>
  <p>React 18 + Vite; no UI framework. Pages hold lists; dialogs hold work on one item.</p>
  <ul>
    <li>Shared <code>Modal</code>: sizes sm/md/lg/xl; stacking; focus trap; Esc/backdrop closes top only; blocked while busy; ←/→ when not typing; full-screen on phone.</li>
    <li><code>ConfirmModal</code>, <code>ReasonModal</code>, <code>useDialog()</code> for audited actions.</li>
    <li>Demo single-file build runs mock API in the browser.</li>
  </ul>
</section>

<section class="section">
  <h2>20. Verified evidence &amp; go-live checklist</h2>
  <h3>Verified in-repo (summary)</h3>
  <ul>
    <li>Functional pytest (mapping, rules, T1–T5, drift, replay, incremental/snapshot, vendors, sequencing, scheduler, API, Glue/Spark, lambdas/SFN).</li>
    <li>PostgreSQL 16 suite; Alembic migrations; concurrency (audit chain + sequencing lease).</li>
    <li>Crash safety / stale lease recovery; Cognito JWT + role matrix deny-by-default.</li>
    <li>NPI masking; hash-chained audit; ruff/hadolint; tofu validate; checkov.</li>
    <li>Throughput: see <code>docs/load-test-1m.txt</code>.</li>
  </ul>
  <h3>Required before go-live (PennyMac / Sonata)</h3>
  <ol>
    <li>Real SSE data dictionary and remaining Hangfire rule migration.</li>
    <li>Live SSE intake integration (beyond typed staging).</li>
    <li>SQL Server verification in CI.</li>
    <li>Parallel/shadow run vs Hangfire; loan-by-loan reconcile.</li>
    <li>Deploy into PennyMac AWS (ACM, domain, Cognito IdP, VPC/TGW).</li>
    <li>Container build in CI with digest-pinned bases.</li>
    <li>Security sign-off (threat model, pen test, InfoSec, data classification).</li>
    <li>SR 11-7 model risk validation (live Bedrock).</li>
    <li>DR: cross-region S3/RDS, RTO/RPO, tested restore.</li>
    <li>Perf test vs real SSE; tune Glue concurrency / Spark workers / SSE throttle.</li>
    <li>Per-vendor onboarding (load type, numbering, protected fields, due times, SFTP).</li>
    <li>UAT, training, on-call handover.</li>
  </ol>
</section>

<section class="section">
  <h2>21. Glossary</h2>
  <table>
    <tr><th>Term</th><th>Meaning</th></tr>
    <tr><td>SSE</td><td>Servicing System of Engagement — target loan store</td></tr>
    <tr><td>Feed</td><td>One vendor file layout + mapping + delivery profile</td></tr>
    <tr><td>Batch</td><td>One registered file run through boarding</td></tr>
    <tr><td>Publish</td><td>Sign and write the live config Glue will load</td></tr>
    <tr><td>Dispatch</td><td>Start processing (SFN in AWS, thread locally)</td></tr>
    <tr><td>Pre-flight</td><td>Schema/drift check before boarding</td></tr>
    <tr><td>Sequencing gate</td><td>Enforces vendor file order</td></tr>
    <tr><td>T1–T5</td><td>Exception risk tiers</td></tr>
    <tr><td>Maker-checker</td><td>Two-person control for sensitive changes</td></tr>
    <tr><td>NPI</td><td>Nonpublic personal information — masked by role</td></tr>
  </table>
</section>

<section class="section appendix">
  <h2>22. Appendix A — Personas in depth</h2>
  <p>Each demo persona maps to Cognito groups in production. Capabilities are enforced by <code>CAPS</code> / <code>canCap</code> (admin bypasses). For low-level design and code-level flows, see <b>Appendix B</b>.</p>
  ${PERSONAS.map((p) => `
  <div class="persona">
    <h3>${p.label}</h3>
    <p class="meta-row"><b>Roles:</b> <span class="mono">${p.roles}</span> · <b>Primary job:</b> ${p.job} · <b>Guide default:</b> ${p.guide}<br/><b>Home screens:</b> ${p.screens}</p>
    <h4>Functions</h4>
    <ul>${p.functions.map((f) => `<li>${f}</li>`).join("")}</ul>
    <h4>How the platform helps</h4>
    <ul>${p.helps.map((h) => `<li>${h}</li>`).join("")}</ul>
  </div>`).join("\n")}
</section>

<section class="section appendix lld">
  <h2>23. Appendix B — LLD: onboarding, daily execution &amp; monitoring</h2>
  <p>Low-level design starts from the platform lifecycle, then drills into <b>vendor onboarding</b> (once per feed) and <b>daily execution &amp; monitoring</b> (every file). Each flow is a single print board (kept on one page) with the code file on every stage. Control plane configures and dispatches; Glue (or the local worker) is the only place loan bytes are transformed.</p>

  <h3>B.1 High-level flow</h3>
  <p>One spine: onboard once, then every file executes, then people monitor. Signed <code>current.json</code> is the bridge.</p>
  ${flowHighLevel()}
  <table>
    <tr><th>Track</th><th>Ends when</th><th>Primary code</th></tr>
    <tr><td>Vendor onboarding</td><td><code>current.json</code> signed for the feed</td><td><code>backend/lbp/vendors.py</code>, <code>mapping/service.py</code>, <code>pipeline/delivery.py</code>, <code>config_store.py</code>, <code>rules/registry.py</code></td></tr>
    <tr><td>Daily execution</td><td>Batch outcome + SNS; loans in SSE or exception queues</td><td><code>dispatch.py</code>, <code>pipeline/batch.py</code>, <code>aws/stepfunctions/boarding.asl.json</code>, <code>aws/glue/*.py</code></td></tr>
    <tr><td>Monitoring</td><td>Humans clear blocks / exceptions; audit intact</td><td><code>frontend/src/pages/Imports.jsx</code>, <code>Exceptions.jsx</code>, <code>Governance.jsx</code>, <code>exceptions/manager.py</code></td></tr>
  </table>

  <h3>B.2 Vendor onboarding — all steps</h3>
  <p>Phases A–B. Drafts stay in RDS until SME approve + publish. Suspended vendors still accept file records but do not board.</p>
  ${flowOnboard()}

  <h4>Step list</h4>
  <ol class="step-list">
    <li><b>Create vendor</b> — identity, type, status (active / suspended).</li>
    <li><b>Create feed</b> — one file layout per feed under that vendor.</li>
    <li><b>Register / sample</b> — upload a sample or create source so mapping can start.</li>
    <li><b>Draft mapping</b> — analyst maps vendor columns → SSE attributes (versioned drafts).</li>
    <li><b>Draft delivery profile</b> — full / incremental / snapshot, sequencing, protected fields.</li>
    <li><b>Author rules (optional)</b> — plain-English / DSL drafts; regulated tags flagged.</li>
    <li><b>SME approve mapping</b> — approver ≠ preparer; triggers publish for that feed.</li>
    <li><b>SME approve delivery</b> — second SME; publish again with delivery in the bundle.</li>
    <li><b>Deploy rules</b> — peer / Compliance as required → active|canary|shadow → <code>publish_all</code>.</li>
    <li><b>Confirm Glue config vN</b> — console chip; in sync with active mapping.</li>
    <li><b>Optional schedule</b> — Ops proposes pull window; SME/Compliance approve; hosts allow-listed.</li>
  </ol>

  <h4>Code map — onboarding</h4>
  ${filesTable([
    ["1. Create vendor", "Persist vendor + audit lifecycle", "backend/lbp/vendors.py", "create_vendor()"],
    ["1–2. API surface", "HTTP routes for vendors / feeds / sources", "backend/lbp/api/main.py", "create_source(), vendor routes"],
    ["2–3. Feed / sample", "Register source, parse sample headers", "backend/lbp/mapping/service.py", "register_source()"],
    ["3. Inspect sample", "Field inspector / value maps", "backend/lbp/mapping/inspect.py", "inspect helpers"],
    ["3. Parse options", "File format / delimiter / sheet", "backend/lbp/ingestion/parser.py", "read_sample(), ParseOptions"],
    ["4. Mapping drafts", "Versioned mapping CRUD + AI assist", "backend/lbp/mapping/service.py", "mapping draft / revise"],
    ["4. SSE dictionary", "Target attribute catalog", "backend/lbp/schema/sse_target.py", "SSE field defs"],
    ["5. Delivery profile", "Propose / decide load type & sequencing", "backend/lbp/pipeline/delivery.py", "propose_profile(), decide_profile()"],
    ["5. Approve delivery", "Second SME gate → publish", "backend/lbp/api/main.py", "approve_delivery()"],
    ["6–9. Rules", "Author, transition, registry", "backend/lbp/rules/registry.py", "RuleRegistry / transitions"],
    ["6. Rule execute shape", "JSON Logic executor used later in Glue", "backend/lbp/rules/executor.py", "RuleExecutor"],
    ["7. Approve mapping", "SME ≠ preparer → publish", "backend/lbp/api/main.py", "approve_mapping()"],
    ["7–9. Signed publish", "build + HMAC + current.json", "backend/lbp/config_store.py", "publish(), publish_all(), load()"],
    ["2. Move feed", "Re-home feed → publish_all", "backend/lbp/vendors.py", "move_feed()"],
    ["11. Schedules", "Cron windows, pull-now", "backend/lbp/scheduling/service.py", "tick(), pull_now()"],
    ["11. Pullers", "SFTP / S3 fetchers", "backend/lbp/scheduling/pullers.py", "pull implementations"],
    ["11. Cron parse", "Schedule expressions", "backend/lbp/scheduling/cron.py", "cron helpers"],
    ["Caps / roles", "UI capability gates", "frontend/src/roles.js", "can(), canCap(), CAPS"],
    ["Console — vendors", "Vendors & Mapping UI", "frontend/src/pages/Sources.jsx", "Workbench / mapping"],
    ["Console — delivery", "Delivery profile dialogs", "frontend/src/pages/DeliveryProfile.jsx", "edit / review"],
    ["Console — vendors list", "Vendor cards / feeds", "frontend/src/pages/Vendors.jsx", "VendorWorkspace"],
    ["Console — rules", "Rule Engine UI", "frontend/src/pages/Rules.jsx", "AuthorModal / transitions"],
    ["Console — schedules", "Vendor Deliveries UI", "frontend/src/pages/Deliveries.jsx", "ScheduleEditor"],
    ["Deploy backfill", "Missing bundles on deploy", "aws/lambdas/handlers.py", "migrate()"],
  ])}

  <h4>Publish contract (snippet)</h4>
  <pre class="code">${esc(`# backend/lbp/config_store.py — publish()
body = build(source_id)                 # mapping + delivery + live rules
sha, sig = _sign(body)                  # Secrets Manager HMAC key
_write(source_id, f"v{version}.json", data)
_write(source_id, "current.json", data) # only pointer Glue trusts
audit(actor, "config.publish", …)

# Glue / local worker — same wheel
cfg = config_store.load(source_id)      # verify or batch.config_rejected`)}</pre>

  <h3>B.3 Daily execution</h3>
  <p>Phases C–E. Same boarding path for S3 push, scheduled pull, and Ops upload. API Lambda never transforms loan rows.</p>
  ${flowExecute()}

  <h4>Step list</h4>
  <ol class="step-list">
    <li><b>Pickup</b> — S3 ObjectCreated, vendor-pull into raw/, or Ops upload.</li>
    <li><b>Register batch</b> — <code>create_batch</code> with path, feed, load type; dedupe linked batches.</li>
    <li><b>Dispatch</b> — local thread or Step Functions <code>boarding.asl.json</code>.</li>
    <li><b>Route</b> — choose <code>lbp-feed</code> vs <code>lbp-feed-spark</code>.</li>
    <li><b>Load config</b> — signature-verify <code>current.json</code>.</li>
    <li><b>Sequencing gate</b> — wait / out_of_order / proceed.</li>
    <li><b>Pre-flight</b> — schema/drift; block → Import Monitor; override path for SME/Compliance.</li>
    <li><b>Board</b> — parse → map → RuleExecutor → Triage T1–T5 → apply (full / change / snapshot).</li>
    <li><b>Persist</b> — throttled micro-batches to SSE; checkpoint; reconcile; advance cursor.</li>
    <li><b>Finalize</b> — outcome, SNS, release queued followers via <code>dispatch</code> again.</li>
    <li><b>Failures</b> — <code>mark_failed</code>; Spark failure resumes on standard engine from checkpoint.</li>
  </ol>

  <h4>Code map — execution</h4>
  ${filesTable([
    ["1. S3 / EventBridge arrival", "Register file from object event", "aws/lambdas/handlers.py", "on_file_arrival()"],
    ["1. Scheduler tick", "Due windows → pull jobs", "aws/lambdas/handlers.py", "scheduler_tick()"],
    ["1. Vendor pull job", "SFTP/S3 → raw/incoming", "aws/glue/vendor_pull_job.py", "Glue job entry"],
    ["1. Pull orchestration", "start_glue vendor-pull", "backend/lbp/scheduling/service.py", "pull_now(), tick()"],
    ["1. Ops upload", "Multipart upload → dispatch", "backend/lbp/api/main.py", "upload()"],
    ["2. Create batch", "Persist batch row + path", "backend/lbp/pipeline/batch.py", "create_batch()"],
    ["3. Dispatch", "Local thread or SFN start", "backend/lbp/dispatch.py", "dispatch(), start_glue()"],
    ["3. Boarding ASL", "Route → Glue.sync → Finalize → SNS", "aws/stepfunctions/boarding.asl.json", "State machine"],
    ["4. Route engine", "standard vs spark choice", "aws/lambdas/handlers.py", "route_batch()"],
    ["4–9. Standard Glue", "Driver job wrapper", "aws/glue/feed_job.py", "invokes lbp pipeline"],
    ["4–9. Spark Glue", "mapInPandas + fallback", "aws/glue/feed_spark_job.py", "Spark entry"],
    ["5–9. Pipeline core", "Same code local + Glue", "backend/lbp/pipeline/batch.py", "run_batch(), _persist_chunk()"],
    ["5. Signed config load", "Verify HMAC bundle", "backend/lbp/config_store.py", "load()"],
    ["6. Sequencing", "Vendor file order gate", "backend/lbp/pipeline/sequencing.py", "check / wait / release"],
    ["7. Pre-flight", "Schema / drift checks", "backend/lbp/pipeline/preflight.py", "check_file()"],
    ["7. Override preflight", "SME/Compliance with reason", "backend/lbp/api/main.py", "override_preflight()"],
    ["8. Parse rows", "Chunked file iteration", "backend/lbp/ingestion/parser.py", "iter_rows()"],
    ["8. Rules", "Per-loan validation", "backend/lbp/rules/executor.py", "RuleExecutor"],
    ["8. Triage tiers", "T1–T5 classification", "backend/lbp/exceptions/manager.py", "Triage"],
    ["8. Change / snapshot", "Incremental apply plans", "backend/lbp/pipeline/changes.py", "change apply"],
    ["8. Delivery decide", "Load-type behaviour", "backend/lbp/pipeline/delivery.py", "profile_of(), display_sequence()"],
    ["9. Glue job catalog", "Job names / concurrency knobs", "backend/lbp/glue_jobs.py", "job helpers"],
    ["10. Finalize", "Outcome + release followers", "aws/lambdas/handlers.py", "finalize_batch()"],
    ["11. Mark failed", "Terminal failure + notify", "aws/lambdas/handlers.py", "mark_failed()"],
    ["Replay held loans", "Glue --mode replay", "backend/lbp/pipeline/replay.py", "replay_batch()"],
    ["Storage paths", "Local/S3 path helpers", "backend/lbp/storage.py", "local_path()"],
  ])}

  <h4>Dispatch (snippet)</h4>
  <pre class="code">${esc(`# backend/lbp/dispatch.py
def dispatch(batch_id: str) -> str:
    if not aws_mode():
        start_batch_async(batch_id)   # pipeline.batch — same as Glue
        return "local"
    return sfn.start_execution(
        stateMachineArn=…, name=f"{batch_id}-…",
        input={"batch_id", "source_id", "bucket", "key"})`)}</pre>

  <h3>B.4 Daily monitoring &amp; human follow-through</h3>
  <p>After Glue writes outcomes and exception rows, people work only the judgment paths. Resolving an exception does not re-run Glue unless Ops explicitly replays a failed batch.</p>
  ${flowMonitor()}

  <h4>Step list</h4>
  <ol class="step-list">
    <li><b>Watch batches</b> — Import Monitor status, preflight blocks, sequencing waits, SNS.</li>
    <li><b>Ops actions</b> — pause / resume / discard / skip-gap / replay (re-enters <code>dispatch</code>).</li>
    <li><b>Clear T2–T3</b> — Exception Manager review + suggested fixes.</li>
    <li><b>T4 maker-checker</b> — second person ≠ maker; then finalize loan.</li>
    <li><b>T5 compliance</b> — OFAC/fraud halt; compliance-only act.</li>
    <li><b>Policy knobs</b> — T1 kill switch and thresholds (DB-live on next row).</li>
    <li><b>Audit / analytics</b> — hash-chained audit; Overview KPIs; Maintenance for Glue/SFN artifacts.</li>
  </ol>

  <h4>Code map — monitoring</h4>
  ${filesTable([
    ["1. Batch list / detail", "Import Monitor API", "backend/lbp/api/main.py", "list_batches(), pause/resume"],
    ["1. Console — imports", "Ops cockpit UI", "frontend/src/pages/Imports.jsx", "Imports / Preflight / UploadModal"],
    ["2. Pause / resume / override", "Control-plane batch controls", "backend/lbp/api/main.py", "pause_batch, resume_batch, override_preflight"],
    ["2. Replay", "Held-loan replay path", "backend/lbp/pipeline/replay.py", "replay_batch()"],
    ["2. Re-dispatch", "After ops action", "backend/lbp/dispatch.py", "dispatch()"],
    ["3–5. Exception API", "Queue + resolve", "backend/lbp/api/main.py", "list_exceptions, resolve_exception"],
    ["3–5. Exception core", "Actions + finalize loan", "backend/lbp/exceptions/manager.py", "ExceptionManager, _finalize_loan()"],
    ["3. Console — exceptions", "Queues / tiers UI", "frontend/src/pages/Exceptions.jsx", "ExceptionModal, RootCauses"],
    ["6. Policy", "Thresholds + kill switch", "frontend/src/pages/Governance.jsx", "PolicyModal"],
    ["6–7. Audit reads", "Audit API", "backend/lbp/api/main.py", "audit list / verify"],
    ["7. Analytics", "KPI services", "backend/lbp/analytics/service.py", "analytics aggregates"],
    ["7. Console — overview", "Executive KPIs", "frontend/src/pages/Overview.jsx", "Overview"],
    ["7. Console — analytics", "Charts", "frontend/src/pages/Analytics.jsx", "Analytics"],
    ["7. Maintenance", "Glue / SFN / notebook artifacts", "frontend/src/pages/Maintenance.jsx", "Maintenance"],
    ["Caps", "Who can click what", "frontend/src/roles.js", "CAPS / canCap"],
    ["SNS / metrics", "Boarding ASL notify + Glue metrics", "aws/stepfunctions/boarding.asl.json", "Notify* states"],
  ])}

  <div class="callout"><b>Remember.</b> Onboarding ends at signed <code>publish</code>. Daily execution starts at <code>dispatch</code>. Monitoring clears human gates — loan transformation stays in Glue.</div>
  <p class="muted" style="margin-top:24pt">End of guide · Loan Boarding Console · ${today}</p>
</section>

</body>
</html>`;
  fs.writeFileSync(OUT_HTML, html);
  console.log("wrote", OUT_HTML);
}

async function pdf() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(`file://${OUT_HTML}`, { waitUntil: "networkidle" });
  await page.pdf({
    path: OUT_PDF,
    format: "Letter",
    printBackground: true,
    margin: { top: "14mm", bottom: "14mm", left: "12mm", right: "12mm" },
  });
  await browser.close();
  console.log("wrote", OUT_PDF);
}

const mode = process.argv[2] || "all";
if (mode === "capture" || mode === "all") await capture();
buildHtml();
if (mode === "pdf" || mode === "all") await pdf();
