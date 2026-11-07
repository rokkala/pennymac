// In-browser mock of the LBP API for the demo build. Read paths come from a snapshot exported
// by backend/scripts/export_demo_snapshot.py (real engine output on synthetic loans); write
// paths replay the server's guardrails (maker-checker, Compliance-only T5, rule lifecycle gates).
import snapshot from "./snapshot.json";
import { traceExample } from "./transforms.js";
import { getMaintenanceArtifact, listMaintenanceArtifacts } from "./maintenanceCatalog.js";

const clone = (o) => JSON.parse(JSON.stringify(o));
const now = () => new Date().toISOString();
const uid = (p) => `${p}_${Math.random().toString(16).slice(2, 14)}`;

class ApiError extends Error {}
const fail = (m) => { throw new ApiError(m); };

const LIFECYCLE = {
  draft: ["in_review"], in_review: ["approved", "rejected", "draft"], approved: ["shadow", "canary", "active"],
  shadow: ["canary", "active", "retired"], canary: ["active", "retired", "shadow"], active: ["retired"], rejected: ["draft"], retired: [],
};

export function createMockApi() {
  const s = clone(snapshot);
  const exById = Object.fromEntries(s.exceptions.map((e) => [e.exception_id, e]));
  const details = s.exception_details;
  const sim = {}; // simulated batches
  const audit = s.audit.items;
  const log = (actor, action, entity_type, entity_id, detail = {}) =>
    audit.unshift({ id: audit.length + 1, ts: now(), actor, action, entity_type, entity_id, detail });
  const tiers = s.exceptions_summary.tiers;
  const bump = (tier, from, to) => {
    const t = tiers[tier];
    if (!t) return;
    if (from) t[from] = Math.max(0, (t[from] || 0) - 1);
    if (to) t[to] = (t[to] || 0) + 1;
  };
  const fromKey = (st) => (st === "pending_review" ? "open" : st);
  const setStatus = (ex, status, extra = {}) => {
    bump(ex.tier, fromKey(ex.status), fromKey(status));
    Object.assign(ex, { status, ...extra });
    if (details[ex.exception_id]) Object.assign(details[ex.exception_id], { status, ...extra });
  };

  const LEGACY = { analyst: "onboarding", sme: "onboarding_reviewer", ops: "monitoring", reviewer: "monitoring", checker: "monitoring_reviewer" };
  const REVIEWER_MEMBER = { onboarding_reviewer: "onboarding", monitoring_reviewer: "monitoring", compliance_reviewer: "compliance" };
  const expandRoles = (roles) => {
    const out = [];
    for (const raw of roles || []) {
      const r = LEGACY[raw] || raw;
      if (!out.includes(r)) out.push(r);
      const m = REVIEWER_MEMBER[r];
      if (m && !out.includes(m)) out.push(m);
    }
    return out;
  };
  const has = (user, ...roles) => {
    const rs = expandRoles(user.roles || []);
    return rs.includes("admin") || roles.some((r) => rs.includes(r));
  };
  const notifications = []; // in-app review inbox (demo)
  const PEERS = [
    { id: "onboarding.reviewer", roles: ["onboarding_reviewer"] },
    { id: "compliance.reviewer", roles: ["compliance_reviewer"] },
    { id: "admin", roles: ["admin"] },
  ];
  const pushNtf = (userId, kind, title, body, entity_id) => {
    notifications.unshift({ id: uid("ntf"), user_id: userId, kind, title, body: body || "", entity_type: "rule", entity_id, read_at: null, created_at: now() });
  };
  const notifyPeers = (exclude, kind, title, body, entity_id) => {
    PEERS.forEach((p) => {
      if (p.id === exclude) return;
      const rs = expandRoles(p.roles);
      if (rs.includes("onboarding_reviewer") || rs.includes("compliance_reviewer") || rs.includes("admin")) {
        pushNtf(p.id, kind, title, body, entity_id);
      }
    });
  };

  // Published feed configurations (what Glue runs). Approvals publish a new signed version, as on the server.
  const hex = (n) => Array.from({ length: n }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");
  const configs = s.feed_configs || {};
  const ruleCounts = () => {
    const out = { active: 0, canary: 0, shadow: 0 };
    Object.values(s.rule_versions || {}).forEach((r) => r.versions.forEach((v) => { if (out[v.status] !== undefined) out[v.status] += 1; }));
    return out;
  };
  const feedConfig = (sid) => {
    if (configs[sid]) return configs[sid];
    const src = s.sources.sources.find((x) => x.source_id === sid);
    if (!src?.active_mapping_id) return { source_id: sid, current: { verified: false, in_sync: null, error: `no published configuration for feed ${sid}; approve its mapping first` }, history: [] };
    configs[sid] = { source_id: sid, current: {}, history: [] };
    publishCfg(sid, "migration", "ensure every live feed has a published configuration");
    return configs[sid];
  };
  function publishCfg(sid, actor, reason) {
    const src = s.sources.sources.find((x) => x.source_id === sid);
    if (!src?.active_mapping_id) return null;
    const c = configs[sid] || (configs[sid] = { source_id: sid, current: {}, history: [] });
    const mp = s.mappings[src.active_mapping_id];
    const version = (c.history[0]?.version || 0) + 1;
    const sha = hex(64);
    const vendorFeeds = s.sources.sources.filter((x) => x.vendor_id === src.vendor_id).length;
    c.current = { version, sha256: sha, published_at: now(), mapping_id: src.active_mapping_id, mapping_version: mp?.version, fields: (mp?.fields || []).filter((f) => f.status !== "rejected").length,
      rules: ruleCounts(), load_type: s.delivery_profiles[sid]?.delivery?.load_type || src.load_type || "full", vendor_feeds: vendorFeeds, verified: true, in_sync: true };
    c.history.unshift({ source_id: sid, version, sha256: sha, mapping_id: src.active_mapping_id, mapping_version: mp?.version, reason, actor, published_at: now() });
    log(actor, "config.publish", "source", sid, { version, reason });
    return { source_id: sid, version, sha256: sha };
  }
  const publishAll = (actor, reason) => s.sources.sources.filter((x) => x.active_mapping_id).forEach((x) => { feedConfig(x.source_id); publishCfg(x.source_id, actor, reason); });
  const routesGet = (path) => { for (const [mth, rx, fn] of routes) { if (mth !== "GET") continue; const mm = path.match(rx); if (mm) return fn(mm, {}, null, new URLSearchParams()); } return null; };

  // In-browser cron preview for the schedule editor (the server uses zoneinfo + the Fed holiday calendar).
  const DOWS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  function cronField(spec, lo, hi, names) {
    const out = new Set();
    for (let part of String(spec).toUpperCase().split(",")) {
      let step = 1; if (part.includes("/")) { const [a, st] = part.split("/"); part = a; step = +st; if (!(step >= 1)) return null; }
      const val = (x) => (names && names.indexOf(x) >= 0 ? names.indexOf(x) : /^\d+$/.test(x) ? +x : NaN);
      let a, z;
      if (part === "*") { a = lo; z = hi; } else if (part.includes("-")) { [a, z] = part.split("-").map(val); } else { a = val(part); z = step > 1 ? hi : a; }
      if (!(a >= lo && z <= hi && a <= z)) return null;
      for (let i = a; i <= z; i += step) out.add(i % (hi === 7 ? 7 : 1000));
    }
    return out;
  }
  function cronPreview(cron, tz = "America/New_York", calendar = "us_federal", holiday = "skip", n = 8) {
    const p = String(cron || "").trim().split(/\s+/);
    if (p.length !== 5) return { valid: false, errors: ["cron: cron needs 5 fields: minute hour day-of-month month day-of-week"] };
    const [mi, hr, dom, mon, dow] = [cronField(p[0], 0, 59), cronField(p[1], 0, 23), cronField(p[2], 1, 31), cronField(p[3], 1, 12), cronField(p[4], 0, 7, DOWS)];
    if ([mi, hr, dom, mon, dow].some((x) => !x)) return { valid: false, errors: ["cron: a field is outside its range"] };
    const fmtLocal = (d, h, m) => { const short = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(d).find((x) => x.type === "timeZoneName")?.value || tz;
      return `${d.toISOString().slice(0, 10)} ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")} ${short}`; };
    const out = [];
    const d = new Date(); d.setUTCHours(12, 0, 0, 0);
    for (let i = 0; i < 400 && out.length < n; i++, d.setUTCDate(d.getUTCDate() + 1)) {
      const wd = d.getUTCDay(), md = d.getUTCDate(), mo = d.getUTCMonth() + 1;
      const domR = p[2] !== "*", dowR = p[4] !== "*";
      const dayOk = mon.has(mo) && (domR && dowR ? dom.has(md) || dow.has(wd) : dom.has(md) && dow.has(wd));
      if (!dayOk) continue;
      if (calendar === "us_federal" && (wd === 0 || wd === 6) && holiday === "skip") continue;
      for (const h of [...hr].sort((a, b) => a - b)) for (const m of [...mi].sort((a, b) => a - b)) if (out.length < n) out.push({ utc: new Date(d).toISOString(), local: fmtLocal(d, h, m) });
    }
    const at = mi.size === 1 && hr.size === 1 ? `${String([...hr][0]).padStart(2, "0")}:${String([...mi][0]).padStart(2, "0")}` : null;
    const describe = at && p[2] === "*" && p[4] === "MON-FRI" ? `Business days at ${at}` : at && p[2] === "*" && p[4] === "*" ? `Daily at ${at}` : p[1].startsWith("*/") && mi.size === 1 ? `Every ${p[1].slice(2)} hours at :${String([...mi][0]).padStart(2, "0")}` : at && p[2] === "*" && DOWS.includes(p[4]) ? `Weekly on ${p[4][0] + p[4].slice(1).toLowerCase()} at ${at}` : at && /^\d+$/.test(p[2]) ? `Monthly on day ${p[2]} at ${at}` : cron;
    return { valid: true, describe, next: out };
  }
  // ?vendor_id= on list endpoints: the snapshot rows carry vendor_id, so the mock narrows them like the server does
  function vendorFilter(method, path, vid, out) {
    if (!vid || method !== "GET" || !out) return out;
    const keep = (x) => x.vendor_id === vid;
    if (path === "/api/batches") return { ...out, batches: out.batches.filter(keep) };
    if (path === "/api/sources") return { ...out, sources: out.sources.filter(keep) };
    if (path === "/api/exceptions") { const items = out.items.filter(keep); return { ...out, items, total: items.length }; }
    if (path === "/api/deliveries") return { ...out, deliveries: out.deliveries.filter(keep) };
    if (path === "/api/schedules") return { ...out, schedules: out.schedules.filter(keep) };
    return out;
  }

  function filenameTest(sourceId, filename, draft) {
    const d = s.delivery_profiles[sourceId];
    const prof = (draft && d?.draft) || d?.delivery || { load_type: "full", action: {}, sequence: { source: "none" } };
    const out = { filename, load_type: prof.load_type, file_action: null, ok: true, sequence: null };
    if (prof.load_type === "incremental" && prof.action?.mode === "filename") {
      out.file_action = Object.entries(prof.action.filename_patterns || {}).find(([, pat]) => new RegExp(pat, "i").test(filename))?.[0] || null;
      if (!out.file_action) Object.assign(out, { ok: false, error: "no add/update/close pattern matches this name" });
    }
    if (prof.load_type !== "full" && prof.sequence?.source === "filename") {
      const mm = filename.match(new RegExp(prof.sequence.pattern || "$^"));
      if (!mm) return { ...out, ok: false, error: `filename '${filename}' does not contain a sequence (pattern ${prof.sequence.pattern})` };
      out.sequence = prof.sequence.kind === "integer" ? String(+mm[1]) : mm[1];
    }
    return out;
  }

  function simBatchView(b) {
    const el = (Date.now() - b.t0) / 1000;
    const processed = Math.min(b.total_rows, Math.floor(el * b.lps));
    const done = processed >= b.total_rows;
    const failed = Math.round(processed * 0.038), warned = Math.round(processed * 0.004);
    const passed = processed - failed - warned;
    const mbs = [];
    for (let i = 0; i * 1000 < processed; i++) mbs.push({ index: i, rows: Math.min(1000, processed - i * 1000), seconds: +(1000 / b.lps).toFixed(2), failed: Math.round(38 + Math.random() * 10) });
    return {
      ...b.base, status: b.paused ? "paused" : done ? "completed" : "running", processed, passed, warned, failed, loaded: passed + warned,
      progress_pct: +(processed / b.total_rows * 100).toFixed(1), throughput_lps: done ? b.lps : b.lps, projected_24h: b.lps * 86400,
      eta_seconds: done ? null : Math.round((b.total_rows - processed) / b.lps), micro_batches: mbs.length, last_micro_batches: mbs.slice(-20),
      micro_batch_log: mbs, finished_at: done ? now() : null, replays: [],
      reconciliation: done ? { source_rows: b.total_rows, staged: b.total_rows, boarded: passed + warned, held_in_exceptions: failed, rejected: 0, in_sse: passed + warned, duplicate_loan_numbers: 0, balanced: true } : null,
    };
  }

  const PERSONA_ROLES = ["onboarding", "onboarding_reviewer", "monitoring", "monitoring_reviewer", "compliance", "compliance_reviewer", "admin"];
  const PERSONA_SCREENS = [
    { id: "overview", label: "Overview" }, { id: "guide", label: "How it works" }, { id: "monitor", label: "Monitor" },
    { id: "imports", label: "File loads" },
    { id: "deliveries", label: "Delivery schedule" }, { id: "sources", label: "Vendors" }, { id: "exceptions", label: "Loans to fix" },
    { id: "rules", label: "Rules" }, { id: "analytics", label: "Analytics" }, { id: "governance", label: "Policy" },
    { id: "maintenance", label: "Maintenance" }, { id: "personas", label: "Personas" },
  ];
  const personaAccess = {
    overview: ["monitoring", "monitoring_reviewer", "compliance", "compliance_reviewer", "admin"], guide: PERSONA_ROLES,
    monitor: ["monitoring", "monitoring_reviewer", "admin"],
    imports: ["monitoring", "monitoring_reviewer", "admin"],
    deliveries: ["monitoring", "monitoring_reviewer", "onboarding", "onboarding_reviewer", "admin"],
    sources: ["onboarding", "onboarding_reviewer", "admin"],
    exceptions: ["monitoring", "monitoring_reviewer", "compliance", "compliance_reviewer", "admin"],
    rules: ["onboarding", "onboarding_reviewer", "compliance", "compliance_reviewer", "admin"],
    analytics: ["monitoring", "monitoring_reviewer", "compliance", "compliance_reviewer", "admin"],
    governance: ["compliance", "compliance_reviewer", "onboarding_reviewer", "admin"],
    maintenance: ["onboarding_reviewer", "admin"], personas: ["admin"],
  };
  const personaDefaults = Object.fromEntries(PERSONA_ROLES.map((r) => [r, PERSONA_SCREENS.map((x) => x.id).filter((id) => personaAccess[id].includes(r))]));
  const personaMatrix = clone(personaDefaults);
  const DEMO_CAST = [
    { id: "onboarding", email: "onboarding@demo.lbp.local", label: "Onboarding", role: "onboarding" },
    { id: "onboarding.reviewer", email: "onboarding.reviewer@demo.lbp.local", label: "Onboarding · Reviewer", role: "onboarding_reviewer" },
    { id: "monitoring", email: "monitoring@demo.lbp.local", label: "Monitoring", role: "monitoring" },
    { id: "monitoring.reviewer", email: "monitoring.reviewer@demo.lbp.local", label: "Monitoring · Reviewer", role: "monitoring_reviewer" },
    { id: "compliance.reviewer", email: "compliance.reviewer@demo.lbp.local", label: "Compliance · Reviewer", role: "compliance_reviewer" },
    { id: "admin", email: "admin@demo.lbp.local", label: "Platform Admin", role: "admin" },
  ];
  const personaUsers = DEMO_CAST.map((r) => ({
    username: r.id, email: r.email, label: r.label, role: r.role, enabled: true, status: "CONFIRMED", demo_cast: true,
  }));
  const castPayload = () => ({
    cast: personaUsers.filter((u) => u.enabled).map((u) => ({
      id: u.username || u.email, label: u.label || u.email, email: u.email, roles: [u.role],
    })),
  });
  const screensPayload = () => ({ screens: PERSONA_SCREENS, roles: PERSONA_ROLES, defaults: personaDefaults, matrix: personaMatrix });
  const visibleScreens = (user) => {
    if (has(user, "admin")) return PERSONA_SCREENS.map((x) => x.id);
    return PERSONA_SCREENS.map((x) => x.id).filter((id) => expandRoles(user.roles).some((r) => (personaMatrix[r] || []).includes(id)));
  };

  const routes = [
    ["GET", /^\/api\/health$/, () => ({ ...s.health, env: "demo" })],
    // ---------------- vendors
    ["GET", /^\/api\/vendors$/, () => s.vendors],
    ["GET", /^\/api\/vendors\/([^/]+)$/, (m) => s.vendor_details[m[1]] || fail("vendor not found")],
    ["POST", /^\/api\/vendors$/, (m, b, user) => {
      if (!has(user, "onboarding")) fail("requires one of: analyst, sme");
      if (!b.name) fail("vendor name is required");
      if (s.vendors.vendors.some((v) => v.name.toLowerCase() === b.name.toLowerCase())) fail(`a vendor named '${b.name}' already exists`);
      const vid = uid("ven");
      const row = { vendor_id: vid, name: b.name, vendor_type: b.vendor_type || "other", legal_name: b.legal_name, external_ref: b.external_ref, contact: b.contact, notes: b.notes,
        status: "onboarding", created_by: user.id, created_at: now(), feeds: 0, live_feeds: 0, load_types: [], active_loans: 0, open_exceptions: 0, last_file: null,
        attention_files: 0, late_or_missed: 0, on_time_pct: null, schedules: 0, pending_mapping_review: 0 };
      s.vendors.vendors.push(row); s.vendors.vendors.sort((a, c) => a.name.localeCompare(c.name));
      s.vendor_details[vid] = { ...clone(row), feeds: [] };
      log(user.id, "vendor.create", "vendor", vid, { name: b.name });
      return s.vendor_details[vid];
    }],
    ["PUT", /^\/api\/vendors\/([^/]+)$/, (m, b, user) => {
      if (!has(user, "onboarding", "compliance_reviewer")) fail("requires one of: analyst, sme, compliance");
      const d = s.vendor_details[m[1]] || fail("vendor not found");
      if (b.status && ["suspended", "offboarded"].includes(b.status)) { if (!has(user, "onboarding_reviewer", "compliance_reviewer")) fail("requires one of: sme, compliance"); if (!b.reason) fail("a reason is required to suspend or offboard a vendor"); }
      const { reason, ...vals } = b;
      Object.assign(d, vals); const row = s.vendors.vendors.find((x) => x.vendor_id === m[1]); if (row) Object.assign(row, vals);
      log(user.id, b.status ? `vendor.${b.status}` : "vendor.update", "vendor", m[1], { ...vals, reason });
      return d;
    }],
    ["POST", /^\/api\/sources\/([^/]+)\/vendor$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer")) fail("requires one of: sme");
      if (!b.reason) fail("a reason is required");
      const from = Object.values(s.vendor_details).find((v) => v.feeds.some((f) => f.source_id === m[1])) || fail("feed not found");
      const to = s.vendor_details[b.vendor_id] || fail("vendor not found");
      const feed = from.feeds.find((f) => f.source_id === m[1]);
      from.feeds = from.feeds.filter((f) => f.source_id !== m[1]); to.feeds.push(feed);
      [[from, -1], [to, 1]].forEach(([v, d]) => { const row = s.vendors.vendors.find((x) => x.vendor_id === v.vendor_id); if (row) row.feeds += d; });
      const src = s.sources.sources.find((x) => x.source_id === m[1]); if (src) Object.assign(src, { vendor_id: to.vendor_id, vendor_name: to.name });
      log(user.id, "source.move_vendor", "source", m[1], { from: from.vendor_id, to: to.vendor_id, reason: b.reason });
      publishAll(user.id, `feed moved to ${to.name}`);
      return { source_id: m[1], vendor_id: to.vendor_id };
    }],
    // ---------------- vendor deliveries, change files, sequencing
    ["GET", /^\/api\/deliveries$/, (m, b, u, q) => {
      const hist = +(q.get("days_back") || 7) > 7;
      const src = q.get("source_id");
      const list = (hist ? s.deliveries_hist : s.deliveries_board).deliveries.filter((d) => !src || d.source_id === src);
      return { now: s.generated_at, deliveries: list };
    }],
    ["POST", /^\/api\/deliveries\/([^/]+)\/waive$/, (m, b, user) => {
      if (!has(user, "monitoring", "onboarding_reviewer")) fail("requires one of: ops, sme");
      if (!b.reason) fail("a reason is required");
      let hit = null;
      [s.deliveries_board, s.deliveries_hist].forEach((L) => L.deliveries.forEach((d) => {
        if (d.delivery_id === m[1]) { if (!["expected", "late", "missed"].includes(d.status)) fail(`cannot waive a delivery that is ${d.status}`); Object.assign(d, { status: "waived", waived_by: user.id, waive_reason: b.reason }); hit = d; }
      }));
      if (!hit) fail("delivery not found");
      log(user.id, "delivery.waive", "delivery", m[1], { reason: b.reason });
      return { delivery_id: m[1], status: "waived" };
    }],
    ["GET", /^\/api\/schedules\/preview$/, (m, b, u, q) => cronPreview(q.get("cron"), q.get("timezone"), q.get("calendar"), q.get("holiday_rule"), +(q.get("n") || 8))],
    ["GET", /^\/api\/schedules$/, (m, b, u, q) => ({ schedules: s.schedules.schedules.filter((x) => !q.get("source_id") || x.source_id === q.get("source_id")) })],
    ["POST", /^\/api\/schedules$/, (m, b, user) => {
      if (!has(user, "monitoring", "onboarding_reviewer")) fail("requires one of: ops, sme");
      const pv = cronPreview(b.config.cron, b.config.timezone, b.config.calendar, b.config.holiday_rule, 1);
      if (!pv.valid) fail(pv.errors.join("; "));
      const src = s.sources.sources.find((x) => x.source_id === b.source_id) || fail("unknown source");
      const x = { schedule_id: uid("sch"), source_id: b.source_id, source_name: src.name, name: b.name, config: null, proposed: b.config, status: "pending_approval",
        version: 0, proposed_by: user.id, created_by: user.id, created_at: now(), describe: pv.describe, kind: b.config.pull ? "pull" : "push", next_due: null, stats_30d: {} };
      s.schedules.schedules.push(x); src.schedules = (src.schedules || 0) + 1;
      log(user.id, "schedule.propose", "schedule", x.schedule_id, { source_id: b.source_id });
      return x;
    }],
    ["PUT", /^\/api\/schedules\/([^/]+)$/, (m, b, user) => {
      if (!has(user, "monitoring", "onboarding_reviewer")) fail("requires one of: ops, sme");
      const x = s.schedules.schedules.find((y) => y.schedule_id === m[1]) || fail("schedule not found");
      const pv = cronPreview(b.config.cron, b.config.timezone, b.config.calendar, b.config.holiday_rule, 1);
      if (!pv.valid) fail(pv.errors.join("; "));
      Object.assign(x, { proposed: { ...b.config, name: b.name }, proposed_by: user.id });
      log(user.id, "schedule.propose_change", "schedule", m[1], {});
      return x;
    }],
    ["POST", /^\/api\/schedules\/([^/]+)\/approve$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer", "compliance_reviewer")) fail("requires one of: sme, compliance");
      const x = s.schedules.schedules.find((y) => y.schedule_id === m[1]) || fail("schedule not found");
      if (!x.proposed) fail("nothing is awaiting approval");
      if (x.proposed_by === user.id) fail("maker-checker: the approver must be a different user from the proposer");
      if (!b.approve) { x.proposed = null; if (x.status === "pending_approval") x.status = "rejected"; log(user.id, "schedule.reject", "schedule", m[1], {}); return x; }
      const { name, ...cfg } = x.proposed;
      const pv = cronPreview(cfg.cron, cfg.timezone, cfg.calendar, cfg.holiday_rule, 1);
      Object.assign(x, { config: cfg, proposed: null, version: (x.version || 0) + 1, approved_by: user.id, approved_at: now(), status: x.status === "pending_approval" ? "active" : x.status,
        name: name || x.name, describe: pv.describe, kind: cfg.pull ? "pull" : "push", next_due: pv.next[0]?.utc, next_due_local: pv.next[0]?.local });
      log(user.id, "schedule.approve", "schedule", m[1], { version: x.version });
      return x;
    }],
    ["POST", /^\/api\/schedules\/([^/]+)\/status$/, (m, b, user) => {
      if (!has(user, "monitoring", "onboarding_reviewer")) fail("requires one of: ops, sme");
      const x = s.schedules.schedules.find((y) => y.schedule_id === m[1]) || fail("schedule not found");
      if (!x.config) fail("schedule has never been approved");
      x.status = b.status; if (b.status !== "active") x.next_due_local = null;
      log(user.id, `schedule.${b.status}`, "schedule", m[1], { reason: b.reason });
      return x;
    }],
    ["POST", /^\/api\/schedules\/([^/]+)\/pull-now$/, (m, b, user) => {
      if (!has(user, "monitoring", "onboarding_reviewer")) fail("requires one of: ops, sme");
      return { schedule_id: m[1], fetched: [], batches: [], skipped: [], error: "demo: outbound SFTP/S3 connectors don't run in the browser" };
    }],
    ["POST", /^\/api\/scheduler\/tick$/, () => ({ materialized: 0, late: [], missed: [], pulled: [], batches: [] })],
    ["GET", /^\/api\/sources\/([^/]+)\/config$/, (m) => feedConfig(m[1])],
    ["POST", /^\/api\/sources\/([^/]+)\/publish$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer")) fail("requires one of: sme");
      const c = feedConfig(m[1]);
      if (!c.current.verified) fail("feed has no approved mapping");
      return publishCfg(m[1], user.id, b.reason || "manual republish");
    }],
    ["GET", /^\/api\/sources\/([^/]+)\/delivery\/test$/, (m, b, u, q) => filenameTest(m[1], q.get("filename") || "", q.get("draft") === "true")],
    ["GET", /^\/api\/sources\/([^/]+)\/delivery$/, (m) => s.delivery_profiles[m[1]] || { ...clone(Object.values(s.delivery_profiles)[0]), source_id: m[1], delivery: clone(Object.values(s.delivery_profiles)[0].defaults), configured: false, draft: null, proposed_by: null, last_sequence: null }],
    ["PUT", /^\/api\/sources\/([^/]+)\/delivery$/, (m, b, user) => {
      if (!has(user, "onboarding")) fail("requires one of: analyst, sme");
      if (b.load_type === "incremental" && b.action?.mode === "column" && !b.action?.column) fail("action.column is required for mode=column");
      const d = s.delivery_profiles[m[1]] || (s.delivery_profiles[m[1]] = clone(routesGet(`/api/sources/${m[1]}/delivery`)));
      Object.assign(d, { draft: { ...d.delivery, ...b }, proposed_by: user.id });
      const src = s.sources.sources.find((x) => x.source_id === m[1]); if (src) src.delivery_pending = true;
      log(user.id, "source.delivery_propose", "source", m[1], {});
      return { source_id: m[1], delivery_draft: d.draft, proposed_by: user.id };
    }],
    ["POST", /^\/api\/sources\/([^/]+)\/delivery\/approve$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer")) fail("requires one of: sme");
      const d = s.delivery_profiles[m[1]];
      if (!d?.draft) fail("no delivery profile change is awaiting approval");
      if (d.proposed_by === user.id) fail("maker-checker: the approver must be a different user from the proposer");
      if (b.approve) Object.assign(d, { delivery: d.draft, configured: true });
      Object.assign(d, { draft: null, proposed_by: null });
      const src = s.sources.sources.find((x) => x.source_id === m[1]); if (src) { src.delivery_pending = false; if (b.approve) src.load_type = d.delivery.load_type; }
      log(user.id, b.approve ? "source.delivery_approve" : "source.delivery_reject", "source", m[1], {});
      if (b.approve) { feedConfig(m[1]); publishCfg(m[1], user.id, "delivery profile approved"); }
      return { source_id: m[1], approved: !!b.approve };
    }],
    ["GET", /^\/api\/batches\/([^/]+)\/changes$/, (m) => s.batch_changes[m[1]] || { total_applied: 0, by_action: {}, applied: [], held: [] }],
    ["POST", /^\/api\/batches\/([^/]+)\/(skip-gap|apply-out-of-order|discard)$/, (m, b, user) => {
      const need = m[2] === "apply-out-of-order" ? ["onboarding_reviewer", "compliance_reviewer"] : ["monitoring", "onboarding_reviewer"];
      if (!has(user, ...need)) fail(`requires one of: ${need.join(", ")}`);
      if (!b.reason) fail("a reason is required");
      const d = s.batch_details[m[1]] || fail("batch not found");
      const row = s.batches.batches.find((x) => x.batch_id === m[1]);
      if (m[2] === "discard") {
        if (!["waiting", "out_of_order", "blocked", "queued", "failed"].includes(d.status)) fail(`cannot discard a batch in status ${d.status}`);
        Object.assign(d, { status: "discarded", error: `discarded: ${b.reason}` }); if (row) row.status = "discarded";
      } else {
        const ov = { type: m[2] === "skip-gap" ? "skip_gap" : "apply_out_of_order", actor: user.id, reason: b.reason, ts: now() };
        d.sequence_detail = { ...(d.sequence_detail || {}), override: ov };
        Object.assign(d, { status: "completed", error: null, processed: d.total_rows, progress_pct: 100 });
        const n = d.total_rows || 0;
        d.change_summary = { update_rows: n, updates_applied: n, add_rows: 0, adds_applied: 0, close_rows: 0, closes_applied: 0, unchanged_rows: 0, conflicts: 0 };
        d.reconciliation = { source_rows: n, staged: n, boarded: n, held_in_exceptions: 0, rejected: 0, unchanged: 0, in_sse: 0, balanced: true };
        if (row) Object.assign(row, { status: "completed", processed: n, passed: n, change_summary: d.change_summary });
      }
      log(user.id, `batch.${m[2].replace(/-/g, "_")}`, "batch", m[1], { reason: b.reason });
      return { batch_id: m[1], status: d.status };
    }],
    ["GET", /^\/api\/schema\/target$/, () => s.schema],
    ["GET", /^\/api\/meta\/transforms$/, () => s.transforms],
    // ---------------- sources & mappings
    ["GET", /^\/api\/sources$/, () => s.sources],
    ["GET", /^\/api\/sources\/([^/]+)$/, (m) => ({ source_id: m[1], profile: s.source_profiles[m[1]] })],
    ["POST", /^\/api\/sources$/, (m, form, user) => {
      const base = s.mappings[s.new_source_mapping_id];
      const sid = uid("src"), mid = uid("map");
      const name = (form && form.get && form.get("name")) || "New feed";
      const vid = (form && form.get && form.get("vendor_id")) || null;
      const vd = vid && s.vendor_details[vid];
      const fields = clone(base.fields).map((f) => ({ ...f, status: f.confidence >= 0.8 ? "suggested" : "needs_review", reviewed_by: undefined }));
      s.mappings[mid] = { ...clone(base), mapping_id: mid, source_id: sid, status: "draft", fields, created_by: user.id, created_at: now(), source: { ...base.source, source_id: sid, name, status: "mapping", vendor_id: vid, vendor_name: vd?.name } };
      s.source_profiles[sid] = s.source_profiles[base.source_id];
      s.previews[mid] = s.previews[s.new_source_mapping_id];
      s.sources.sources.unshift({ source_id: sid, name, vendor_id: vid, vendor_name: vd?.name, load_type: "full", schedules: 0, format: base.source.format, status: "mapping", created_by: user.id, created_at: now(), mappings: [{ mapping_id: mid, version: 1, status: "draft", auto_mapped_pct: base.stats.auto_mapped_pct }] });
      if (vd) {
        vd.feeds.push({ source_id: sid, name, format: base.source.format, status: "mapping", active_mapping_id: null, load_type: "full", delivery_pending: false, last_sequence: null,
          active_loans: 0, last_file: null, columns: base.source.columns.length, created_by: user.id, mappings: [{ mapping_id: mid, version: 1, status: "draft", auto_mapped_pct: base.stats.auto_mapped_pct }], schedules: [] });
        const row = s.vendors.vendors.find((x) => x.vendor_id === vid); if (row) { row.feeds += 1; row.pending_mapping_review += 1; }
      }
      log(user.id, "source.register", "source", sid, { name });
      return { source_id: sid, mapping_id: mid, stats: base.stats };
    }],
    ["POST", /^\/api\/mappings\/([^/]+)\/suggest$/, (m, b) => {
      const mp = s.mappings[m[1]]; const attr = attrOf(b.target);
      const feeds = {};
      mp.fields.forEach((f) => (f.sources || [f.source]).forEach((src) => { if (b.sources.includes(src) && f.target !== b.target && f.status !== "rejected") (feeds[src] = feeds[src] || []).push(f.target); }));
      const existing = mp.fields.find((f) => f.target === b.target && f.status !== "rejected");
      return { target: b.target, sources: b.sources, confidence: null, transform: defaultTransform(m[1], b.sources, attr), already_feeds: feeds,
        replaces: existing ? { sources: existing.sources, status: existing.status } : null };
    }],
    ["POST", /^\/api\/mappings\/([^/]+)\/fields$/, (m, b, user) => {
      const mp = s.mappings[m[1]]; if (mp.status !== "draft") fail("mapping is not a draft");
      if (!(b.sources || []).length && b.default == null) fail("choose at least one source column, a constant step or a default value");
      const attr = attrOf(b.target);
      const others = [...new Set(mp.fields.filter((f) => f.target !== b.target && f.status !== "rejected" && (f.sources || [f.source]).some((x) => (b.sources || []).includes(x))).map((f) => f.target))];
      mp.fields = mp.fields.filter((f) => f.target !== b.target);
      const f = { source: (b.sources || [])[0], sources: b.sources || [], target: b.target, module: attr.module, confidence: 1, transform: b.transform || [],
        rationale: "Added by analyst" + (others.length ? `; source also feeds ${others.join(", ")}` : ""), composite: (b.sources || []).length > 1, one_to_many: others.length > 0,
        status: "overridden", required: attr.required, risk: attr.risk, manual: true, reviewed_by: user.id };
      mp.fields.push(f); log(user.id, "mapping.field_add", "mapping", m[1], { target: b.target, sources: b.sources }); return f;
    }],
    ["POST", /^\/api\/mappings\/([^/]+)\/fields\/([^/]+)\/retarget$/, (m, b, user) => {
      const mp = s.mappings[m[1]]; if (mp.status !== "draft") fail("mapping is not a draft");
      const f = mp.fields.find((x) => x.target === m[2]) || fail("field not in mapping");
      const clash = mp.fields.find((x) => x.target === b.new_target && x.status !== "rejected");
      if (clash) fail(`${b.new_target} is already mapped from ${(clash.sources || [clash.source]).join(", ")}; remove or reject it first`);
      const attr = attrOf(b.new_target);
      const casts = ["to_decimal", "to_int", "to_date", "to_bool", "truncate", "upper"];
      const steps = [...f.transform]; while (steps.length && casts.includes(steps[steps.length - 1].op)) steps.pop();
      const moved = { ...f, target: b.new_target, module: attr.module, required: attr.required, risk: attr.risk, transform: [...steps, castFor(attr)].filter(Boolean),
        status: "overridden", reviewed_by: user.id, retargeted_from: m[2], rationale: `Re-pointed by ${user.id} from ${m[2]}` };
      mp.fields = mp.fields.filter((x) => x.target !== m[2] && x.target !== b.new_target); mp.fields.push(moved);
      log(user.id, "mapping.field_retarget", "mapping", m[1], { from: m[2], to: b.new_target }); return moved;
    }],
    ["GET", /^\/api\/mappings\/([^/]+)\/fields\/([^/]+)\/inspect$/, (m) => inspectOf(m[1], m[2])],
    ["POST", /^\/api\/mappings\/([^/]+)\/fields\/([^/]+)\/inspect$/, (m, b) => {
      const base = inspectBase(m[1], m[2], b.sources);
      return retrace(base, b.sources || base.sources, b.transform || base.transform);
    }],
    ["POST", /^\/api\/sources\/([^/]+)\/mappings\/new-version$/, (m, b, user) => newVersion(m[1], user)],
    ["GET", /^\/api\/mappings\/([^/]+)\/diff$/, (m) => s.diffs[m[1]] || diffOf(m[1])],
    ["GET", /^\/api\/mappings\/([^/]+)\/fields\/([^/]+)\/values$/, (m) => valuesOf(m[1], m[2])],
    ["POST", /^\/api\/mappings\/([^/]+)\/fields\/([^/]+)\/values$/, (m, b, user) => {
      const mp = s.mappings[m[1]]; const f = mp.fields.find((x) => x.target === m[2]) || fail("field not mapped");
      const steps = withValueMap(f.transform, b.value_map || {});
      if (b.save) { if (mp.status !== "draft") fail("mapping is not a draft"); f.transform = steps; f.status = "overridden"; f.reviewed_by = user.id; log(user.id, "mapping.field_override", "mapping", m[1], { target: m[2], value_map: b.value_map }); }
      return { ...valuesOf(m[1], m[2], steps), transform: steps, saved: !!b.save };
    }],
    ["GET", /^\/api\/mapping-memory$/, () => s.mapping_memory],
    ["GET", /^\/api\/analytics\/systemic$/, () => s.systemic],
    ["GET", /^\/api\/mappings\/([^/]+)\/dq$/, (m) => s.mapping_dq[m[1]] || s.mapping_dq[s.new_source_mapping_id]],
    ["GET", /^\/api\/mappings\/([^/]+)$/, (m) => s.mappings[m[1]] || fail("mapping not found")],
    ["GET", /^\/api\/mappings\/([^/]+)\/preview/, (m) => s.previews[m[1]] || s.previews[s.new_source_mapping_id]],
    ["POST", /^\/api\/mappings\/([^/]+)\/accept-all/, (m, b, user) => {
      const mp = s.mappings[m[1]]; if (mp.status !== "draft") fail("mapping is not a draft");
      let n = 0; mp.fields.forEach((f) => { if (["suggested", "needs_review"].includes(f.status) && f.confidence >= 0.8) { f.status = "accepted"; f.reviewed_by = user.id; n++; } });
      log(user.id, "mapping.accept_all", "mapping", m[1], { count: n }); return { accepted: n };
    }],
    ["POST", /^\/api\/mappings\/([^/]+)\/fields\/([^/]+)$/, (m, b, user) => {
      const mp = s.mappings[m[1]]; if (mp.status !== "draft") fail("mapping is not a draft");
      if (b.action === "remove") { mp.fields = mp.fields.filter((x) => x.target !== m[2]); log(user.id, "mapping.field_remove", "mapping", m[1], { target: m[2] }); return { target: m[2], removed: true }; }
      const f = mp.fields.find((x) => x.target === m[2]); if (!f) fail("field not in mapping");
      f.original_suggestion = f.original_suggestion || { source: f.source, transform: f.transform, confidence: f.confidence };
      if (b.action === "accept") f.status = "accepted";
      else if (b.action === "reject") f.status = "rejected";
      else { if (b.source) { f.source = b.source; f.sources = [b.source]; } if (b.transform) f.transform = b.transform; f.status = "overridden"; }
      f.reviewed_by = user.id; log(user.id, `mapping.field_${b.action}`, "mapping", m[1], { target: m[2] }); return f;
    }],
    ["POST", /^\/api\/mappings\/([^/]+)\/submit$/, (m, b, user) => {
      const mp = s.mappings[m[1]];
      const pending = mp.fields.filter((f) => ["suggested", "needs_review"].includes(f.status));
      if (pending.length) fail(`${pending.length} field(s) not yet reviewed: ${pending.slice(0, 6).map((f) => f.target).join(", ")}`);
      mp.status = "in_review"; mp.reviewed_by = user.id; log(user.id, "mapping.submit", "mapping", m[1]); return mp;
    }],
    ["POST", /^\/api\/mappings\/([^/]+)\/approve$/, (m, b, user) => {
      const mp = s.mappings[m[1]];
      if (mp.status !== "in_review") fail("mapping is not awaiting approval");
      if (!has(user, "onboarding_reviewer")) fail("Onboarding reviewer role required to approve mappings");
      if ([mp.created_by, mp.reviewed_by].includes(user.id)) fail("approver must differ from the person who prepared the mapping");
      if (!b.approve) { mp.status = "draft"; log(user.id, "mapping.send_back", "mapping", m[1], { comment: b.comment }); return mp; }
      mp.status = "approved"; mp.approved_by = user.id; mp.approved_at = now(); mp.source.status = "live";
      const src = s.sources.sources.find((x) => x.source_id === mp.source_id);
      if (src) {
        src.status = "live"; src.active_mapping_id = m[1];
        src.mappings.forEach((x) => { if (x.mapping_id === m[1]) x.status = "approved"; else if (x.status === "approved") { x.status = "superseded"; if (s.mappings[x.mapping_id]) s.mappings[x.mapping_id].status = "superseded"; } });
      }
      log(user.id, "mapping.approve", "mapping", m[1], { comment: b.comment });
      if (configs[mp.source_id]) publishCfg(mp.source_id, user.id, `mapping v${mp.version} approved`); else feedConfig(mp.source_id);
      return mp;
    }],
    // ---------------- batches
    ["GET", /^\/api\/batches(\?.*)?$/, () => {
      const simulated = Object.values(sim).map(simBatchView);
      const batches = [...simulated, ...s.batches.batches];
      const running = simulated.filter((b) => b.status === "running");
      return { ...s.batches, batches, running: running.length, current_throughput_lps: running.reduce((a, b) => a + b.throughput_lps, 0) };
    }],
    ["GET", /^\/api\/batches\/([^/?]+)$/, (m) => (sim[m[1]] ? simBatchView(sim[m[1]]) : s.batch_details[m[1]] || fail("batch not found"))],
    ["POST", /^\/api\/upload$/, (m, form, user) => {
      const sourceId = form.get("source_id"); const file = form.get("file");
      const src = s.sources.sources.find((x) => x.source_id === sourceId);
      if (!src || !src.active_mapping_id) fail("source has no approved mapping; complete onboarding first");
      const bid = uid("bat"); const total = 3000 + Math.floor(Math.random() * 3000);
      sim[bid] = { t0: Date.now(), lps: 380, total_rows: total, paused: false,
        base: { batch_id: bid, source_id: sourceId, source_name: src.name, filename: file?.name || "upload.csv", total_rows: total, created_at: now(), started_at: now(), submitted_by: user.id } };
      log(user.id, "batch.create", "batch", bid, { file: file?.name }); return { batch_id: bid, status: "running" };
    }],
    ["POST", /^\/api\/batches\/([^/]+)\/replay$/, (m, b, user, q) => {
      const bd = s.batch_details[m[1]] || fail("batch not found");
      const prev = s.replay_previews[m[1]];
      if (!prev) return { batch_id: m[1], dry_run: true, mapping_version: 1, replayed: 0, now_boarded: 0, still_held: 0, exceptions_before: 0, exceptions_after: 0, by_rule_before: {}, by_rule_after: {},
        message: "Nothing would change: the current mapping produces the same exceptions." };
      if (q.get("dry_run") !== "false") return prev;
      if (!has(user, "monitoring", "onboarding_reviewer")) fail("Monitoring or Onboarding reviewer role required to replay a batch");
      const done = { ...prev, dry_run: false };
      const hist = { ts: now(), actor: user.id, mapping_version: prev.mapping_version, replayed: prev.replayed, now_boarded: prev.now_boarded, still_held: prev.still_held };
      for (const target of [bd, s.batches.batches.find((x) => x.batch_id === m[1])]) {
        if (!target) continue;
        target.loaded += prev.now_boarded; target.failed -= prev.now_boarded; target.passed += prev.now_boarded;
        target.replays = [...(target.replays || []), hist];
        if (target.reconciliation) target.reconciliation = { ...target.reconciliation, boarded: target.reconciliation.boarded + prev.now_boarded, in_sse: target.reconciliation.in_sse + prev.now_boarded, held_in_exceptions: target.reconciliation.held_in_exceptions - prev.now_boarded };
      }
      const fixedRules = Object.keys(prev.by_rule_before).filter((r) => (prev.by_rule_after[r] || 0) < prev.by_rule_before[r]);
      s.exceptions.filter((e) => e.batch_id === m[1] && fixedRules.includes(e.rule_id) && ["open", "pending_review"].includes(e.status)).forEach((e) => setStatus(e, "superseded"));
      s.systemic.issues = s.systemic.issues.filter((i) => !(i.batches.includes(m[1]) && fixedRules.includes(i.rule_id)));
      delete s.replay_previews[m[1]];
      log(user.id, "batch.replay", "batch", m[1], hist); return done;
    }],
    ["POST", /^\/api\/batches\/([^/]+)\/remap$/, (m, b, user) => {
      const bd = s.batch_details[m[1]] || fail("batch not found");
      const src = s.sources.sources.find((x) => x.source_id === bd.source_id);
      const draftId = src.mappings.find((x) => x.status === "draft")?.mapping_id;
      const mp = draftId ? s.mappings[draftId] : newVersion(bd.source_id, user);
      mp.fields = mp.fields.map((f) => {
        const srcs = f.sources?.length ? f.sources : [f.source];
        let g = { ...f, transform: f.transform.map((x) => ({ ...x })) };
        if (srcs.some((c) => b.renames[c])) { g.sources = srcs.map((c) => b.renames[c] || c); g.source = g.sources[0]; g.status = "overridden"; g.rationale = `Column renamed in source file: ${srcs.filter((c) => b.renames[c]).map((c) => `${c} → ${b.renames[c]}`).join(", ")}`; }
        srcs.forEach((c) => { if (b.date_formats?.[c]) { g.transform.forEach((st) => { if (st.op === "to_date") st.format = b.date_formats[c]; }); g.status = "overridden"; } });
        return g;
      });
      Object.values(b.renames || {}).forEach((c) => { if (!mp.source.columns.includes(c)) mp.source.columns.push(c); });
      log(user.id, "mapping.remap_drift", "mapping", mp.mapping_id, b); return mp;
    }],
    ["POST", /^\/api\/batches\/([^/]+)\/override-preflight$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer", "compliance_reviewer")) fail("Onboarding or Compliance reviewer role required to override a drift block");
      if (!b.reason) fail("a reason is required");
      const bd = s.batch_details[m[1]]; if (!bd || bd.status !== "blocked") fail("batch is not blocked");
      startSim(m[1], bd, { ...bd.preflight, override: { actor: user.id, reason: b.reason, ts: now() } });
      log(user.id, "batch.preflight_override", "batch", m[1], { reason: b.reason }); return { status: "running" };
    }],
    ["POST", /^\/api\/batches\/([^/]+)\/(pause|resume)$/, (m, b, user) => {
      const bd = s.batch_details[m[1]];
      if (m[2] === "resume" && bd && bd.status === "blocked") {
        const src = s.sources.sources.find((x) => x.source_id === bd.source_id);
        if (src.active_mapping_id === bd.mapping_id) fail("Still blocked: approve the mapping fix first (or an SME can override).");
        const mp = s.mappings[src.active_mapping_id];
        const missing = bd.preflight.missing_columns.filter((x) => mp.fields.some((f) => (f.sources || [f.source]).includes(x.column)));
        if (missing.length) fail(`Still blocked: ${missing.map((x) => x.column).join(", ")} is still mapped but missing from the file.`);
        startSim(m[1], bd, { ...bd.preflight, decision: "pass", summary: `Re-checked on mapping v${mp.version}: file matches.`, mapping_version: mp.version, checked_at: now() });
        log(user.id, "batch.resume", "batch", m[1]); return { status: "running" };
      }
      if (sim[m[1]]) sim[m[1]].paused = m[2] === "pause";
      log(user.id, `batch.${m[2]}`, "batch", m[1]); return { status: m[2] === "pause" ? "paused" : "running" };
    }],
    // ---------------- exceptions
    ["GET", /^\/api\/exceptions\/summary$/, (m, b, u, q) => (q.get("vendor_id") ? s.by_vendor[q.get("vendor_id")]?.exceptions_summary : null) || s.exceptions_summary],
    ["GET", /^\/api\/exceptions\/loads$/, (m, b, u, q) => {
      const open = ["open", "pending_review", "pending_checker", "escalated"];
      const byBatch = s.analytics["import-status"].batches.reduce((a, x) => { a[x.batch_id] = x; return a; }, {});
      const status = q.get("status");
      const matched = s.exceptions.filter((e) => {
        if (status === "open" ? !open.includes(e.status) : status && e.status !== status) return false;
        if (q.get("vendor_id") && e.vendor_id !== q.get("vendor_id")) return false;
        return true;
      });
      const map = new Map();
      matched.forEach((e) => {
        const bch = byBatch[e.batch_id] || {};
        const loaded = bch.started_at || bch.created_at || e.created_at;
        const cur = map.get(e.batch_id) || {
          batch_id: e.batch_id, source_id: e.source_id, filename: bch.filename || e.filename || e.batch_id,
          loaded_at: loaded, loaded_on: (loaded || "").slice(0, 10), vendor_id: e.vendor_id, vendor_name: e.vendor_name,
          feed_name: e.feed_name, open_count: 0,
        };
        cur.open_count += 1;
        map.set(e.batch_id, cur);
      });
      return { loads: [...map.values()].sort((a, b) => String(b.loaded_at).localeCompare(String(a.loaded_at))) };
    }],
    ["GET", /^\/api\/exceptions(\?.*)?$/, (m, b, u, q) => {
      const open = ["open", "pending_review", "pending_checker", "escalated"];
      const byBatch = s.analytics["import-status"].batches.reduce((a, x) => { a[x.batch_id] = x; return a; }, {});
      let items = s.exceptions.filter((e) => {
        if (q.get("status") === "open" ? !open.includes(e.status) : q.get("status") && e.status !== q.get("status")) return false;
        if (q.get("tier") && e.tier !== q.get("tier")) return false;
        if (q.get("rule_id") && e.rule_id !== q.get("rule_id")) return false;
        if (q.get("batch_id") && e.batch_id !== q.get("batch_id")) return false;
        if (q.get("vendor_id") && e.vendor_id !== q.get("vendor_id")) return false;
        if (q.get("q") && !String(e.loan_number).includes(q.get("q"))) return false;
        const bch = byBatch[e.batch_id] || {};
        const loaded = bch.started_at || bch.created_at || e.created_at || "";
        if (q.get("loaded_on") && String(loaded).slice(0, 10) !== q.get("loaded_on")) return false;
        return true;
      }).map((e) => {
        const bch = byBatch[e.batch_id] || {};
        const loaded = bch.started_at || bch.created_at || e.created_at;
        return { ...e, filename: bch.filename || e.filename, loaded_at: loaded };
      });
      return { total: items.length, items: items.slice(0, +(q.get("limit") || 100)) };
    }],
    ["GET", /^\/api\/exceptions\/([^/]+)$/, (m) => details[m[1]] || fail("exception not found")],
    ["POST", /^\/api\/exceptions\/bulk-resolve$/, (m, b, user) => {
      const ids = s.exceptions.filter((e) => e.rule_id === b.rule_id && String(e.original_value) === String(b.original_value) && ["open", "pending_review"].includes(e.status) && ["T2", "T3"].includes(e.tier)).map((e) => e.exception_id);
      ids.forEach((id) => { const ex = exById[id]; setStatus(ex, "resolved", { resolved_value: b.use_proposal ? ex.proposal?.value : b.value, maker: user.id, resolved_at: now() }); log(user.id, "exception.resolve", "exception", id, { bulk: true }); });
      return { matched: ids.length, resolved: ids.length, errors: [] };
    }],
    ["POST", /^\/api\/exceptions\/([^/]+)\/(resolve|checker|reject|escalate|compliance-clear|rollback|qa|ai-suggest)$/, (m, b, user) => {
      const ex = exById[m[1]] || fail("exception not found");
      const act = m[2];
      const has = (...r) => user.roles.some((x) => r.includes(x));
      if (act === "resolve") {
        if (!["open", "pending_review"].includes(ex.status)) fail(`cannot resolve an exception in status ${ex.status}`);
        if (ex.tier === "T5") fail("T5 exceptions are blocked; only Compliance can clear or reject them");
        const value = b.use_proposal ? ex.proposal?.value : b.value;
        if (value === undefined || value === null || value === "") fail("a corrected value is required");
        if (ex.tier === "T4") { setStatus(ex, "pending_checker", { maker: user.id, resolved_value: String(value) }); log(user.id, "exception.maker_submit", "exception", ex.exception_id, { value }); return { status: "pending_checker" }; }
        setStatus(ex, "resolved", { maker: user.id, resolved_value: String(value), resolved_at: now() });
        log(user.id, "exception.resolve", "exception", ex.exception_id, { value, accepted_ai: !!b.use_proposal });
        return { status: "resolved", loan_boarded: !(details[ex.exception_id]?.related || []).some((r) => ["open", "pending_review", "pending_checker", "escalated"].includes(r.status)) };
      }
      if (act === "checker") {
        if (ex.status !== "pending_checker") fail("exception is not awaiting a checker");
        if (user.id === ex.maker) fail("maker-checker: checker must be a different user from the maker");
        if (!has(user, "monitoring_reviewer")) fail("monitoring reviewer role required");
        if (!b.approve) { setStatus(ex, "open", { checker: user.id }); log(user.id, "exception.checker_reject", "exception", ex.exception_id); return { status: "open" }; }
        setStatus(ex, "resolved", { checker: user.id, resolved_at: now() }); log(user.id, "exception.checker_approve", "exception", ex.exception_id); return { status: "resolved", loan_boarded: true };
      }
      if (act === "reject") {
        if (ex.tier === "T5" && !has(user, "compliance_reviewer")) fail("only Compliance can act on T5 exceptions");
        setStatus(ex, "rejected", { maker: user.id }); log(user.id, "loan.reject", "exception", ex.exception_id, { reason: b.reason }); return { status: "rejected" };
      }
      if (act === "compliance-clear") {
        if (!has(user, "compliance_reviewer")) fail("Compliance role required");
        if (!b.reason) fail("an investigation note is required");
        setStatus(ex, "resolved", { checker: user.id, resolved_value: b.value, resolved_at: now() }); log(user.id, "exception.compliance_clear", "exception", ex.exception_id, { note: b.reason }); return { status: "resolved" };
      }
      if (act === "rollback") {
        if (ex.status !== "auto_applied") fail("only auto-applied fixes can be rolled back");
        setStatus(ex, "open", { resolved_value: null }); bump(ex.tier, "open"); ex.tier = "T3"; bump("T3", null, "open");
        log(user.id, "exception.rollback", "exception", ex.exception_id, { reason: b.reason }); return { status: "open", tier: "T3" };
      }
      if (act === "qa") { ex.qa_sample = false; log(user.id, b.correct ? "exception.qa_pass" : "exception.qa_fail", "exception", ex.exception_id); return { qa: "passed" }; }
      if (act === "escalate") { setStatus(ex, "escalated"); log(user.id, "exception.escalate", "exception", ex.exception_id, { reason: b.reason }); return { status: "escalated" }; }
      if (act === "ai-suggest") return { exception_id: ex.exception_id, proposal: ex.proposal, note: "Demo uses the heuristic engine; configure Bedrock for LLM suggestions." };
    }],
    // ---------------- notifications
    ["GET", /^\/api\/notifications$/, (m, b, user) => {
      const items = notifications.filter((n) => n.user_id === user.id);
      return { notifications: items, unread: items.filter((n) => !n.read_at).length };
    }],
    ["POST", /^\/api\/notifications\/read-all$/, (m, b, user) => {
      let updated = 0;
      notifications.forEach((n) => { if (n.user_id === user.id && !n.read_at) { n.read_at = now(); updated += 1; } });
      return { ok: true, updated };
    }],
    ["POST", /^\/api\/notifications\/([^/]+)\/read$/, (m, b, user) => {
      const n = notifications.find((x) => x.id === m[1] && x.user_id === user.id) || fail("notification not found");
      n.read_at = n.read_at || now();
      return n;
    }],
    // ---------------- rules
    ["GET", /^\/api\/rules$/, (m, b, user, q) => {
      const queue = q?.get("queue");
      if (!queue) return s.rules;
      const all = Object.values(s.rule_versions || {}).flatMap((rv) => rv.versions);
      let filtered = all;
      if (queue === "awaiting_review") filtered = all.filter((r) => r.status === "in_review" && r.author !== user.id);
      else if (queue === "my_drafts") filtered = all.filter((r) => r.status === "draft" && r.author === user.id);
      const latest = {};
      filtered.forEach((r) => {
        const cur = latest[r.rule_id];
        if (!cur || r.version > cur.version) latest[r.rule_id] = r;
      });
      return {
        rules: Object.values(latest).map((r) => {
          const vs = s.rule_versions[r.rule_id]?.versions || [r];
          const listed = s.rules.rules.find((x) => x.rule_id === r.rule_id);
          return { ...r, exception_count: listed?.exception_count || 0, versions: vs.map((x) => [x.version, x.status]) };
        }),
      };
    }],
    ["GET", /^\/api\/rules\/([^/]+)$/, (m) => s.rule_versions[m[1]] || fail("rule not found")],
    ["POST", /^\/api\/rules\/author$/, (m, b) => s.author_examples[b.text] || demoAuthor(b.text)],
    ["POST", /^\/api\/rules\/test$/, () => ({ valid: true })],
    ["POST", /^\/api\/rules$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer", "compliance_reviewer")) fail("requires one of: sme, compliance");
      const existing = b.rule_id && s.rule_versions[b.rule_id];
      if (existing) {
        const ver = Math.max(...existing.versions.map((x) => x.version)) + 1;
        const body = { severity: "FAIL", category: "custom", ...b, rule_id: b.rule_id, version: ver, status: "draft", author: user.id, approvals: [], owner: user.id,
          effective_from: now().slice(0, 10), history: [{ ts: now(), actor: user.id, to: "draft" }], canary_pct: 0 };
        existing.versions.push(body);
        const i = s.rules.rules.findIndex((x) => x.rule_id === b.rule_id);
        if (i >= 0) s.rules.rules[i] = { ...s.rules.rules[i], versions: existing.versions.map((x) => [x.version, x.status]) };
        log(user.id, "rule.draft", "rule", `${b.rule_id}:v${ver}`); return body;
      }
      const nums = s.rules.rules.map((r) => +r.rule_id.slice(1)).filter(Boolean);
      const id = `R${String(Math.max(0, ...nums) + 1).padStart(3, "0")}`;
      const body = { severity: "FAIL", category: "custom", ...b, rule_id: id, version: 1, status: "draft", author: user.id, approvals: [], owner: user.id,
        effective_from: now().slice(0, 10), history: [{ ts: now(), actor: user.id, to: "draft" }], exception_count: 0, versions: [[1, "draft"]] };
      s.rules.rules.push(body); s.rule_versions[id] = { rule_id: id, versions: [body] }; log(user.id, "rule.draft", "rule", `${id}:v1`); return body;
    }],
    ["PUT", /^\/api\/rules\/([^/]+)\/(\d+)$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer", "compliance_reviewer")) fail("requires one of: sme, compliance");
      const vs = s.rule_versions[m[1]]?.versions || fail("rule not found");
      const r = vs.find((x) => x.version === +m[2]) || fail("version not found");
      if (r.status !== "draft") fail("only drafts can be edited; create a new version instead");
      Object.assign(r, Object.fromEntries(Object.entries(b || {}).filter(([k]) => !["rule_id", "version", "status", "approvals", "history"].includes(k))));
      log(user.id, "rule.edit", "rule", `${m[1]}:v${m[2]}`); return r;
    }],
    ["DELETE", /^\/api\/rules\/([^/]+)$/, (m, b, user, q) => {
      if (!has(user, "onboarding_reviewer", "compliance_reviewer")) fail("requires one of: sme, compliance");
      const rid = m[1];
      const pack = s.rule_versions[rid] || fail("rule not found");
      const wasLive = pack.versions.some((v) => ["active", "canary", "shadow"].includes(v.status));
      const n = pack.versions.length;
      delete s.rule_versions[rid];
      s.rules.rules = s.rules.rules.filter((x) => x.rule_id !== rid);
      log(user.id, "rule.delete", "rule", rid, { versions_removed: n, reason: q?.get("reason") });
      if (wasLive) publishAll(user.id, `rule ${rid} deleted`);
      return { ok: true, rule_id: rid, versions_removed: n, republished: wasLive };
    }],
    ["POST", /^\/api\/rules\/([^/]+)\/(\d+)\/transition$/, (m, b, user) => {
      const vs = s.rule_versions[m[1]].versions; const r = vs.find((x) => x.version === +m[2]) || fail("version not found");
      if (!(LIFECYCLE[r.status] || []).includes(b.to)) fail(`cannot move ${m[1]} v${m[2]} from ${r.status} to ${b.to}`);
      if (b.to === "in_review" && !(r.tests || []).length) fail("rule has no test cases; add at least one passing and one failing case");
      if (b.to === "approved") {
        const author = r.author || r.owner;
        if (!author) fail("maker-checker: rule has no author recorded; cannot approve");
        if (user.id === author) fail("maker-checker: the author cannot approve their own rule");
        const submittedBy = [...(r.history || [])].reverse().find((h) => h.to === "in_review")?.actor;
        if (submittedBy && user.id === submittedBy) fail("maker-checker: the submitter cannot approve their own submission");
        r.approvals = [...(r.approvals || []), { actor: user.id, roles: user.roles }];
        if (r.regulatory_tag && !r.approvals.some((a) => expandRoles(a.roles || []).includes("compliance_reviewer"))) {
          log(user.id, "rule.peer_approved", "rule", `${m[1]}:v${m[2]}`);
          notifyPeers(r.author, "rule.peer_approved", `Compliance review needed: ${r.name || m[1]}`, `${user.id} peer-approved; Compliance still required.`, m[1]);
          if (r.author && r.author !== user.id) pushNtf(r.author, "rule.peer_approved", `Peer approved ${r.name || m[1]} — waiting on Compliance`, "", m[1]);
          return { ...r, pending: "compliance approval required" };
        }
      }
      if (b.to === "canary") r.canary_pct = b.canary_pct || 5;
      if (b.to === "active") vs.forEach((x) => { if (x !== r && ["active", "canary", "shadow"].includes(x.status)) x.status = "retired"; });
      const from = r.status;
      r.history = [...(r.history || []), { ts: now(), actor: user.id, from, to: b.to, comment: b.comment }];
      r.status = b.to;
      const i = s.rules.rules.findIndex((x) => x.rule_id === m[1]);
      const shown = vs.find((x) => x.status === "active") || vs[vs.length - 1];
      s.rules.rules[i] = { ...shown, exception_count: s.rules.rules[i].exception_count, versions: vs.map((x) => [x.version, x.status]) };
      log(user.id, `rule.${b.to}`, "rule", `${m[1]}:v${m[2]}`, { comment: b.comment });
      if (["active", "canary", "shadow", "retired"].includes(b.to)) publishAll(user.id, `rule ${m[1]} v${m[2]} ${b.to}`);
      if (b.to === "in_review") notifyPeers(r.author, "rule.in_review", `Review requested: ${r.name || m[1]}`, `${user.id} submitted for peer review.`, m[1]);
      if (b.to === "approved" && r.author && r.author !== user.id) pushNtf(r.author, "rule.approved", `Approved: ${r.name || m[1]}`, `${user.id} approved ${m[1]} v${m[2]}.`, m[1]);
      if (b.to === "draft" && from === "in_review" && r.author && r.author !== user.id) pushNtf(r.author, "rule.sent_back", `Sent back: ${r.name || m[1]}`, `${user.id} returned the rule to draft.`, m[1]);
      return r;
    }],
    // ---------------- policy, analytics, audit
    ["GET", /^\/api\/policy$/, () => s.policy],
    ["PUT", /^\/api\/policy$/, (m, b, user) => {
      if (!has(user, "compliance_reviewer")) fail("policy changes require Compliance approval");
      const emergencyOff = JSON.stringify(b.changes) === JSON.stringify({ t1_enabled: false });
      if (b.requested_by === user.id && !emergencyOff) fail("requester and approver must be different users");
      if (b.changes.t1_min_confidence !== undefined && +b.changes.t1_min_confidence < 0.9) fail("t1_min_confidence below 0.90 is not permitted");
      Object.assign(s.policy.policy, b.changes);
      if (b.changes.t1_enabled === false && s.policy.effective) Object.assign(s.policy.effective, { t1_effective: false });
      log(user.id, "policy.update", "policy", "routing", { changes: b.changes, requested_by: b.requested_by, reason: b.reason });
      return { policy: s.policy.policy };
    }],
    ["GET", /^\/api\/audit\/verify$/, () => ({ valid: true, entries: audit.length, head: hex(64) })],
    ["GET", /^\/api\/analytics\/([a-z-]+)/, (m, b, u, q) => (q.get("vendor_id") ? s.by_vendor[q.get("vendor_id")]?.analytics?.[m[1]] : null) || s.analytics[m[1]] || fail("unknown dashboard")],
    ["POST", /^\/api\/analytics\/ask$/, (m, b) => {
      const ql = b.question.toLowerCase();
      const hit = Object.entries(s.ask_examples).find(([k]) => k.toLowerCase() === ql)
        || Object.entries(s.ask_examples).find(([k]) => k.toLowerCase().split(/\W+/).filter((w) => w.length > 4).some((w) => ql.includes(w)));
      return hit ? { ...hit[1], question: b.question } : { question: b.question, answer: null, suggestions: Object.keys(s.ask_examples) };
    }],
    ["GET", /^\/api\/audit/, () => ({ items: audit.slice(0, 200) })],
    ["GET", /^\/api\/maintenance\/artifacts\/([^/]+)$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer", "admin")) fail("requires one of: sme, admin");
      try { return getMaintenanceArtifact(m[1]); } catch (e) { fail(e.message); }
    }],
    ["GET", /^\/api\/maintenance\/artifacts$/, (m, b, user) => {
      if (!has(user, "onboarding_reviewer", "admin")) fail("requires one of: sme, admin");
      return { artifacts: listMaintenanceArtifacts() };
    }],
    ["GET", /^\/api\/personas\/me\/screens$/, (m, b, user) => ({ screens: visibleScreens(user) })],
    ["GET", /^\/api\/personas\/cast$/, () => castPayload()],
    ["GET", /^\/api\/personas\/screens$/, (m, b, user) => {
      if (!has(user, "admin")) fail("requires one of: admin");
      return screensPayload();
    }],
    ["PUT", /^\/api\/personas\/screens$/, (m, b, user) => {
      if (!has(user, "admin")) fail("requires one of: admin");
      Object.entries(b.matrix || {}).forEach(([r, list]) => {
        if (!PERSONA_ROLES.includes(r)) fail(`unknown role: ${r}`);
        const grant = (list || []).filter((s) => !(personaDefaults[r] || []).includes(s));
        if (grant.length) fail(`cannot grant ${grant.join(", ")} to ${r} beyond default access`);
        personaMatrix[r] = (list || []).filter((s) => (personaDefaults[r] || []).includes(s));
      });
      log(user.id, "personas.screens.update", "policy", "screen_matrix", { matrix: personaMatrix });
      return screensPayload();
    }],
    ["GET", /^\/api\/personas\/users$/, (m, b, user) => {
      if (!has(user, "admin")) fail("requires one of: admin");
      return { users: personaUsers.slice().sort((a, c) => (a.email || "").localeCompare(c.email || "")) };
    }],
    ["POST", /^\/api\/personas\/users$/, (m, b, user) => {
      if (!has(user, "admin")) fail("requires one of: admin");
      const email = String(b.email || "").trim().toLowerCase();
      if (!email.includes("@")) fail("valid email required");
      if (!PERSONA_ROLES.includes(b.role)) fail("invalid role");
      if (!b.temporary_password || b.temporary_password.length < 14) fail("temporary password needs 14+ chars with upper, lower, number, and symbol");
      if (personaUsers.some((u) => u.email === email)) fail(`user already exists: ${email}`);
      const u = { username: email, email, role: b.role, enabled: true, status: "FORCE_CHANGE_PASSWORD" };
      personaUsers.push(u);
      log(user.id, "personas.user.create", "persona", email, { role: b.role });
      return { user: u };
    }],
    ["PUT", /^\/api\/personas\/users\/([^/]+)$/, (m, b, user) => {
      if (!has(user, "admin")) fail("requires one of: admin");
      const key = decodeURIComponent(m[1]).toLowerCase();
      const u = personaUsers.find((x) => x.username === key || x.email === key) || fail(`user not found: ${key}`);
      const admins = personaUsers.filter((x) => x.role === "admin" && x.enabled);
      if (u.role === "admin" && admins.length <= 1 && (b.enabled === false || (b.role && b.role !== "admin"))) {
        fail("cannot disable or demote the last admin");
      }
      if (b.role) { if (!PERSONA_ROLES.includes(b.role)) fail("invalid role"); u.role = b.role; }
      if (typeof b.enabled === "boolean") u.enabled = b.enabled;
      log(user.id, "personas.user.update", "persona", u.email, { role: u.role, enabled: u.enabled });
      return { user: u };
    }],
    ["POST", /^\/api\/personas\/users\/([^/]+)\/reset-password$/, (m, b, user) => {
      if (!has(user, "admin")) fail("requires one of: admin");
      const key = decodeURIComponent(m[1]).toLowerCase();
      const u = personaUsers.find((x) => x.username === key || x.email === key) || fail(`user not found: ${key}`);
      if (!b.temporary_password || b.temporary_password.length < 14) fail("temporary password needs 14+ chars with upper, lower, number, and symbol");
      u.status = "FORCE_CHANGE_PASSWORD";
      log(user.id, "personas.user.reset_password", "persona", u.email, {});
      return { username: u.username, email: u.email, status: u.status };
    }],
  ];

  function startSim(bid, bd, preflight) {
    sim[bid] = { t0: Date.now(), lps: 380, total_rows: bd.total_rows, paused: false,
      base: { ...bd, preflight, status: "running", processed: 0, passed: 0, warned: 0, failed: 0, loaded: 0, started_at: now(), reconciliation: null } };
    s.batches.batches = s.batches.batches.filter((x) => x.batch_id !== bid);
    delete s.batch_details[bid];
  }
  function newVersion(sourceId, user) {
    const src = s.sources.sources.find((x) => x.source_id === sourceId) || fail("source not found");
    if (src.mappings.some((x) => ["draft", "in_review"].includes(x.status))) fail("a draft already exists");
    const latest = s.mappings[src.mappings[src.mappings.length - 1].mapping_id];
    const mid = uid("map");
    s.mappings[mid] = { ...clone(latest), mapping_id: mid, version: latest.version + 1, status: "draft", created_by: user.id, created_at: now(), approved_by: null, approved_at: null, reviewed_by: null };
    s.field_inspect[mid] = s.field_inspect[latest.mapping_id]; s.mapping_dq[mid] = s.mapping_dq[latest.mapping_id];
    s.previews[mid] = s.previews[latest.mapping_id]; s.value_coverage[mid] = s.value_coverage[latest.mapping_id];
    s.column_samples[mid] = s.column_samples[latest.mapping_id];
    src.mappings.push({ mapping_id: mid, version: latest.version + 1, status: "draft", auto_mapped_pct: latest.stats?.auto_mapped_pct });
    log(user.id, "mapping.new_version", "mapping", mid, { from: latest.mapping_id }); return s.mappings[mid];
  }
  function diffOf(mid) {
    const mp = s.mappings[mid]; const src = s.sources.sources.find((x) => x.source_id === mp.source_id);
    const prevRef = src.mappings.filter((x) => x.version < mp.version).pop();
    if (!prevRef) return { mapping_id: mid, against: null, changes: [], summary: { added: 0, removed: 0, changed: 0 } };
    const prev = s.mappings[prevRef.mapping_id];
    const act = (fs) => Object.fromEntries(fs.filter((f) => f.status !== "rejected").map((f) => [f.target, f]));
    const a = act(prev.fields), b = act(mp.fields);
    const srcs = (f) => (f.sources?.length ? f.sources : [f.source]);
    const changes = [];
    [...new Set([...Object.keys(a), ...Object.keys(b)])].sort().forEach((t) => {
      if (a[t] && !b[t]) changes.push({ target: t, change: "removed", before: { sources: srcs(a[t]), transform: a[t].transform } });
      else if (b[t] && !a[t]) changes.push({ target: t, change: "added", after: { sources: srcs(b[t]), transform: b[t].transform } });
      else {
        const what = [srcs(a[t]).join() !== srcs(b[t]).join() && "source", JSON.stringify(a[t].transform) !== JSON.stringify(b[t].transform) && "transform"].filter(Boolean);
        if (what.length) changes.push({ target: t, change: "changed", what, before: { sources: srcs(a[t]), transform: a[t].transform }, after: { sources: srcs(b[t]), transform: b[t].transform } });
      }
    });
    return { mapping_id: mid, version: mp.version, against: prev.mapping_id, against_version: prev.version, changes,
      summary: { added: changes.filter((c) => c.change === "added").length, removed: changes.filter((c) => c.change === "removed").length, changed: changes.filter((c) => c.change === "changed").length } };
  }
  function withValueMap(transform, vm) {
    const steps = transform.map((x) => ({ ...x }));
    const map = Object.fromEntries(Object.entries(vm).filter(([, v]) => v).map(([k, v]) => [String(k).trim().toLowerCase(), v]));
    const lk = steps.find((x) => x.op === "lookup");
    if (lk) { lk.map = map; return steps; }
    const casts = ["upper", "to_decimal", "to_int", "to_date", "to_bool", "truncate"];
    let i = steps.length; while (i > 0 && casts.includes(steps[i - 1].op)) i--;
    steps.splice(i, 0, { op: "lookup", map }); return steps;
  }
  function valuesOf(mid, target, steps) {
    const base = (s.value_coverage[mid] || {})[target] || (s.value_coverage[s.new_source_mapping_id] || {})[target];
    const mp = s.mappings[mid]; const f = mp?.fields.find((x) => x.target === target);
    if (!base) fail("No value data for this field in the demo");
    if (!base.editable && !steps) return base;
    const transform = steps || f?.transform || [];
    if (!f || (!steps && JSON.stringify(transform) === JSON.stringify(base.__t || null))) return base;
    const a = attrOf(target);
    const srcs = f.sources?.length ? f.sources : [f.source];
    const values = base.values.map((v) => {
      const t = traceExample({ [srcs[0]]: v.source }, [srcs[0]], transform, false);
      const out = t.error ? null : t.output;
      const problems = t.error ? [t.error.message] : (a.codes.length && out !== null && out !== "" && !a.codes.includes(String(out)) ? ["Code list"] : (a.required && (out === null || out === "") ? ["Required"] : []));
      return { ...v, output: out, valid: !problems.length, problems };
    });
    const bad = values.filter((v) => !v.valid);
    const rows = values.reduce((x, v) => x + v.count, 0) || 1;
    const lk = transform.find((x) => x.op === "lookup");
    return { ...base, values: [...bad, ...values.filter((v) => v.valid)], invalid_distinct: bad.length, invalid_rows: bad.reduce((x, v) => x + v.count, 0),
      coverage_pct: +((1 - bad.reduce((x, v) => x + v.count, 0) / rows) * 100).toFixed(1), value_map: lk?.map || {} };
  }
  function inspectBase(mid, target, wantSources) {
    const byField = s.field_inspect[mid] || s.field_inspect[s.new_source_mapping_id] || {};
    const mp = s.mappings[mid];
    const f = mp && mp.fields.find((x) => x.target === target);
    const sources = wantSources || (f ? (f.sources?.length ? f.sources : [f.source]) : null);
    const base = byField[target];
    if (base && (!sources || JSON.stringify(sources) === JSON.stringify(base.sources))) return base;
    return synthInspect(byField, target, sources || base?.sources || []);
  }
  function inspectOf(mid, target) {
    const mp = s.mappings[mid];
    const f = mp && mp.fields.find((x) => x.target === target);
    const base = inspectBase(mid, target);
    if (f && (base.mapping_id === null || JSON.stringify(f.transform) !== JSON.stringify(base.transform))) {
      return retrace(base, f.sources?.length ? f.sources : [f.source], f.transform); // edited in this demo session
    }
    return base;
  }
  function retrace(base, sources, transform) {
    const a = base.attribute;
    const examples = base.examples.map((ex) => traceExample(ex.inputs, sources, transform, a.pii));
    const outs = examples.filter((e) => !e.error).map((e) => e.output);
    const blank = (v) => v === null || v === undefined || v === "";
    const checks = base.schema_checks.map((c) => {
      const bad = c.id === "type" ? examples.filter((e) => e.error)
        : c.id === "required" ? examples.filter((e) => !e.error && blank(e.output))
        : c.id === "codes" ? examples.filter((e) => !e.error && !blank(e.output) && e.output !== "(masked)" && !a.codes.includes(String(e.output)))
        : c.id === "length" ? examples.filter((e) => !e.error && !blank(e.output) && String(e.output).length > a.length) : [];
      return { ...c, evaluated: examples.length, failed: bad.length, examples: bad.slice(0, 4).map((e) => String(e.error ? e.error.message : e.output)) };
    });
    return { ...base, sources, transform, examples, schema_checks: checks, demo_partial: true,
      steps: transform.map((st) => ({ op: st.op, params: Object.fromEntries(Object.entries(st).filter(([k]) => k !== "op")), description: describeStep(st) })),
      stats: { rows: examples.length, transform_errors: examples.filter((e) => e.error).length, blank_outputs: outs.filter(blank).length, distinct_outputs: new Set(outs.map(String)).size } };
  }
  const attrOf = (name) => s.schema.attributes.find((a) => a.name === name) || fail(`unknown SSE attribute ${name}`);
  const castFor = (a) => ({ decimal: { op: "to_decimal" }, int: { op: "to_int" }, date: { op: "to_date" }, bool: { op: "to_bool" }, code: { op: "upper" } }[a.dtype] || { op: "truncate", length: a.length || 255 });
  const LOOKUPS = { amortization_type: "amortization_type", occupancy_type: "occupancy_type", loan_purpose: "loan_purpose", loan_type: "loan_type", property_type: "property_type", ofac_check_status: "ofac_status", property_state: "state_name_to_code", mailing_state: "state_name_to_code" };
  const RATES = ["interest_rate", "original_interest_rate", "servicing_fee_rate", "guaranty_fee_rate", "pass_through_rate", "arm_margin", "apr"];
  function defaultTransform(mid, sources, a) {
    if (sources.length > 1) return [{ op: "concat", separator: " " }, ...(a.length ? [{ op: "truncate", length: a.length }] : [])];
    const prof = s.source_profiles[s.mappings[mid].source_id] || s.source_profiles[s.mappings[s.new_source_mapping_id].source_id];
    const col = prof?.columns.find((c) => c.name === sources[0]) || {};
    const steps = [{ op: "trim" }];
    if (a.dtype === "date") return [...steps, { op: "to_date", ...(col.date_format ? { format: col.date_format } : {}) }];
    if (RATES.includes(a.name)) return [...steps, { op: "to_decimal" }, { op: "normalize_rate" }];
    if (LOOKUPS[a.name]) steps.push({ op: "lookup", table: LOOKUPS[a.name] });
    return [...steps, castFor(a)];
  }
  function synthInspect(byField, target, sources) {
    // examples for these source columns, taken from any field that already reads them
    const mid = Object.keys(s.field_inspect).find((k) => s.field_inspect[k] === byField) || s.new_source_mapping_id;
    const rows = s.column_samples[mid] || s.column_samples[s.new_source_mapping_id];
    const donor = { examples: rows.map((r) => ({ inputs: r })) };
    const a = attrOf(target);
    const checks = [
      ...(a.required ? [{ id: "required", label: "Required: must be populated" }] : []), { id: "type", label: `Type: must cast to ${a.dtype}` },
      ...(a.length && ["string", "code"].includes(a.dtype) ? [{ id: "length", label: `Length: at most ${a.length} characters` }] : []),
      ...(a.codes.length ? [{ id: "codes", label: a.codes.length <= 8 ? `Code list: one of ${a.codes.join(", ")}` : `Code list: one of ${a.codes.length} SSE codes` }] : []),
    ].map((c) => ({ ...c, kind: "schema", evaluated: 0, failed: 0, examples: [] }));
    const rules = (s.mapping_dq[s.new_source_mapping_id]?.rules || []).filter((r) => r.primary_field === target || r.reads_fields.includes(target))
      .map((r) => ({ ...r, failed: null, evaluated: 0, examples: [] }));
    return { mapping_id: null, target, attribute: { ...a }, sources, transform: [], steps: [], schema_checks: checks, dq_rules: rules,
      examples: donor.examples.map((e) => ({ inputs: Object.fromEntries(sources.map((src) => [src, e.inputs[src]])), steps: [], output: null, error: null })),
      stats: { rows: donor.examples.length, transform_errors: 0, blank_outputs: 0, distinct_outputs: 0 } };
  }
  const describeStep = (st) => ({ trim: "Trim surrounding whitespace", upper: "Convert to upper case", lower: "Convert to lower case", title: "Convert to title case",
    digits_only: "Keep digits only", to_decimal: "Cast to decimal (strips $ , %)", to_int: "Cast to integer", to_bool: "Cast to Yes/No flag",
    to_date: `Parse date${st.format ? " as " + st.format : " (auto-detect format)"} → ISO yyyy-mm-dd`, normalize_rate: "Normalise rate to percent (0.065 → 6.5)",
    cents_to_dollars: "Convert cents to dollars (÷100)", scale: `Multiply by ${st.factor}`, divide: `Divide by ${st.divisor}`, lookup: `Translate via lookup table '${st.table}'`,
    default: `Default to '${st.value}' when blank`, constant: `Set constant '${st.value}'`, pad_left: `Left-pad to ${st.width} with '${st.char ?? "0"}'`,
    truncate: `Truncate to ${st.length} characters (SSE column length)`, split: `Split on '${st.delimiter ?? ","}' and take part ${st.index ?? 0}`,
    parse_address: `Parse single-line address → ${st.part ?? "line1"}`, regex_extract: `Extract pattern ${st.pattern}`, concat: `Join source columns with '${st.separator ?? " "}' (N:1)`,
    template: `Fill template ${st.template} (N:1)`, substr: `Take characters from ${st.start ?? 0}` }[st.op] || st.op);

  function demoAuthor(text) {
    const t = text.trim();
    const m = t.match(/^(.+?) must be between (-?[\d.]+)\s*%? and (-?[\d.]+)/i) || null;
    if (m) {
      const field = m[1].toLowerCase().replace(/^the /, "").replace(/\s+/g, "_");
      return { source: "heuristic", draft: { name: t, description: t, field, severity: "FAIL", category: "range", expression: { "<=": [+m[2], { var: field }, +m[3]] },
        tests: [{ record: { [field]: (+m[2] + +m[3]) / 2 }, expect: true }, { record: { [field]: +m[3] * 10 + 1 }, expect: false }] },
        test_results: [{ case: 0, passed: true }, { case: 1, passed: true }], problems: [] };
    }
    return { draft: null, source: "heuristic", test_results: [], problems: ["The demo recognises the example phrasings below; the full engine handles required, range, comparison, code-list, pattern, date-order and conditional rules."] };
  }

  return {
    async handle(method, path, body, user) {
      await new Promise((r) => setTimeout(r, 120));
      const [p, qs] = path.split("?");
      const q = new URLSearchParams(qs || "");
      for (const [mth, rx, fn] of routes) {
        if (mth !== method) continue;
        const m = p.match(rx);
        if (m) return clone(vendorFilter(method, p, q.get("vendor_id"), fn(m, body || {}, user, q)));
      }
      throw new ApiError(`demo: no handler for ${method} ${p}`);
    },
  };
}
