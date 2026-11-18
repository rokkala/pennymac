// Pure model for the multi-file feed layout editor. No React, no network: everything here is unit-tested.
// Mirrors the server rules for phase 1 (backend/lbp/multifile/layout.py); the server stays the authority.

export const SUPPORTED_MODES = ["merge", "aggregate"];
export const AGG_OPS = ["sum", "count", "min", "max", "first", "last", "any", "concat_distinct"];
export const PAIRINGS = ["business_date", "sequence", "filename_token", "window_minutes"];
const NAMED_GROUP_PAIRINGS = ["sequence", "business_date", "filename_token"];

const clone = (o) => JSON.parse(JSON.stringify(o));

export const emptyReadiness = () => ({ require: "all_required", pairing: "business_date", wait_timeout_minutes: 240, on_timeout: "alert_only" });

export const emptyLayout = () => ({
  files: [{ role: "master", name_pattern: "", required: true, entity: "", key: [], parse_options: {} }],
  relations: [],
});

export const newRelation = (detail) => ({
  detail, to: "master", on: [{ parent: "", detail: "" }], normalize: ["trim"], mode: "merge", cardinality: "one", join: "left",
  on_orphan_detail: "exception", on_missing_detail: "allow", on_duplicate_master: "reject_all", min_match_rate: 0,
});

/** A copy of `layout` with one more detail file and its relation to the master. */
export function addDetail(layout, role) {
  const name = String(role || "").trim();
  if (!name) throw new Error("A file role needs a name");
  if (name !== "master" && !roleNameOk(name)) throw new Error("Use lowercase letters, digits and underscores, starting with a letter (not layout, readiness, manifest or files)");
  if (name === "master") throw new Error("master is the main file; add a different role");
  if ((layout.files || []).some((f) => f.role === name)) throw new Error(`There is already a file called ${name}`);
  const out = clone(layout);
  out.files.push({ role: name, name_pattern: "", required: true, parse_options: {} });
  out.relations = [...(out.relations || []), newRelation(name)];
  return out;
}

/** A copy of `layout` without a detail file and its relation. */
export function removeDetail(layout, role) {
  const out = clone(layout);
  out.files = out.files.filter((f) => f.role !== role);
  out.relations = (out.relations || []).filter((r) => r.detail !== role);
  return out;
}

const RESERVED_ROLES = ["layout", "readiness", "manifest", "files", "source_id", "auto_start"];
export const roleNameOk = (r) => /^[a-z][a-z0-9_]*$/.test(String(r || "")) && !RESERVED_ROLES.includes(r);
const hasNamedGroup = (p) => /\(\?P?<(?![=!])[A-Za-z_]/.test(String(p || ""));

/** Problems found on the form before it is sent. `columns` (optional): {role: [column names]} when known. */
export function validateLayoutForm(layout, readiness, columns) {
  const errs = [];
  const files = Array.isArray(layout?.files) ? layout.files : [];
  const rels = Array.isArray(layout?.relations) ? layout.relations : [];
  const ready = { ...emptyReadiness(), ...(readiness || {}) };
  const masters = files.filter((f) => f.role === "master");
  if (masters.length !== 1) errs.push(`The layout needs exactly one master file; it has ${masters.length}.`);
  const roles = files.map((f) => f.role);
  for (const r of [...new Set(roles.filter((x, i) => roles.indexOf(x) !== i))]) errs.push(`The file ${r || "(no name)"} is listed more than once.`);
  for (const f of files) {
    if (!f.role) { errs.push("Every file needs a role name."); continue; }
    if (f.role !== "master" && !roleNameOk(f.role)) errs.push(`The role name ${f.role} is not allowed: use lowercase letters, digits and underscores, starting with a letter (not layout, readiness, manifest or files).`);
    if (!String(f.name_pattern || "").trim()) errs.push(`The ${f.role} file needs a file name pattern.`);
  }
  if (masters.length === 1) {
    const k = masters[0].key;
    if (!Array.isArray(k) || !k.length || k.some((x) => !String(x || "").trim())) errs.push("The master file needs at least one key column.");
  }
  const masterCols = new Set((columns && columns.master) || []);
  const seenDetail = new Set();
  const outputs = new Map();
  for (const r of rels) {
    const tag = `${r.detail || "?"} to ${r.to || "?"}`;
    if (!roles.includes(r.detail)) errs.push(`${tag}: the detail file ${r.detail || "(none)"} is not in the file list.`);
    if (!roles.includes(r.to)) errs.push(`${tag}: the parent file ${r.to || "(none)"} is not in the file list.`);
    if (r.detail === "master") errs.push(`${tag}: the master cannot be a detail file.`);
    else if (roles.includes(r.to) && r.to !== "master") errs.push(`${tag}: every detail file must join the master in this phase; a detail of a detail is a later phase.`);
    if (seenDetail.has(r.detail)) errs.push(`${tag}: ${r.detail} has more than one relation.`);
    seenDetail.add(r.detail);
    const on = Array.isArray(r.on) ? r.on : [];
    if (!on.length || on.some((p) => !String(p?.parent || "").trim() || !String(p?.detail || "").trim())) errs.push(`${tag}: pick at least one join column on each side.`);
    const pk = (files.find((f) => f.role === r.to) || {}).key;
    if (on.length && Array.isArray(pk) && pk.length && on.length !== pk.length) errs.push(`${tag}: the join has ${on.length} column pair(s) but the key of ${r.to} has ${pk.length}.`);
    if (!SUPPORTED_MODES.includes(r.mode)) errs.push(`${tag}: mode ${r.mode || "(none)"} is not supported yet; use merge or aggregate.`);
    const card = r.cardinality || (r.mode === "merge" ? "one" : "many");
    if (r.mode === "merge" && card !== "one") errs.push(`${tag}: merge needs one detail row per master row (cardinality one). Use aggregate for several.`);
    const rate = Number(r.min_match_rate ?? 0);
    if (!(rate >= 0 && rate <= 1)) errs.push(`${tag}: the match rate must be between 0% and 100%.`);
    if (r.mode === "aggregate") {
      const cols = Array.isArray(r.aggregate?.columns) ? r.aggregate.columns : [];
      if (!cols.length) errs.push(`${tag}: aggregate needs at least one summary column.`);
      for (const c of cols) {
        const name = String(c.as || "").trim();
        if (!name) { errs.push(`${tag}: every summary column needs an output name.`); continue; }
        if (!AGG_OPS.includes(c.op)) errs.push(`${tag}: ${name} has an unknown operation.`);
        else if (c.op !== "count" && !String(c.col || "").trim()) errs.push(`${tag}: ${name} needs a source column.`);
        if (outputs.has(name)) errs.push(`The output column ${name} is produced more than once (${outputs.get(name)} and ${r.detail}).`);
        else if (masterCols.has(name)) errs.push(`The output column ${name} from ${r.detail} clashes with a master column.`);
        if (!outputs.has(name)) outputs.set(name, r.detail);
      }
    }
  }
  if (!["all_required", "master_only"].includes(ready.require)) errs.push("Readiness: choose all required files or the master only.");
  else if (ready.require === "master_only") {
    const req = files.filter((f) => f.role !== "master" && f.required).map((f) => f.role);
    if (req.length) errs.push(`Readiness: a delivery cannot be ready on the master alone while detail files are required (${req.join(", ")}).`);
  }
  if (!PAIRINGS.includes(ready.pairing)) errs.push("Readiness: choose how the files of one delivery are paired.");
  if (!(Number(ready.wait_timeout_minutes) >= 0)) errs.push("Readiness: the wait time must be 0 or more minutes.");
  if (!["fail", "load_master_only", "alert_only"].includes(ready.on_timeout)) errs.push("Readiness: choose what happens when the wait runs out.");
  else if (ready.on_timeout === "load_master_only") {
    const req = files.filter((f) => f.role !== "master" && f.required).map((f) => f.role);
    if (req.length) errs.push(`Readiness: loading the master alone is not allowed while detail files are required (${req.join(", ")}).`);
  }
  if (ready.pairing === "window_minutes") {
    if (!(Number(ready.window_minutes) > 0)) errs.push("Readiness: the pairing window must be a positive number of minutes.");
  } else if (NAMED_GROUP_PAIRINGS.includes(ready.pairing)) {
    for (const f of files) {
      if (f.name_pattern && !hasNamedGroup(f.name_pattern)) errs.push(`The ${f.role} file name pattern needs a named group such as (?P<date>\\d+) to pair files.`);
    }
  }
  return errs;
}

/** [{role, columns}] for a mapping picker: plain names under master, `role.col` names under their role. Values stay the full column name. */
export function groupColumnsByRole(columns) {
  const master = [];
  const by = new Map();
  for (const c of columns || []) {
    const i = String(c).indexOf(".");
    if (i <= 0) { master.push(c); continue; }
    const role = c.slice(0, i);
    if (!by.has(role)) by.set(role, []);
    by.get(role).push(c);
  }
  return [...(master.length ? [{ role: "master", columns: master }] : []), ...[...by].map(([role, cols]) => ({ role, columns: cols }))];
}

/** Required roles of the layout that a file set has not received yet. */
export function missingRoles(set, layout) {
  const have = new Set((set?.members || []).map((m) => m.role));
  return (layout?.files || []).filter((f) => f.role && f.required !== false && !have.has(f.role)).map((f) => f.role);
}

/** Plain-words status of a file set. A waiting set may carry `missing_roles` (see missingRoles). */
export function setStatusLabel(set) {
  switch (set?.status) {
    case "waiting": {
      const m = set.missing_roles || [];
      return m.length ? `Waiting for ${m.join(", ")} file${m.length > 1 ? "s" : ""}` : "Waiting for more files";
    }
    case "ready": return "Ready";
    case "consumed": return "Loaded";
    case "expired": return "Expired";
    case "discarded": return "Discarded";
    case "overridden": return "Accepted without all files";
    default: return set?.status ? String(set.status).replace(/_/g, " ") : "Unknown";
  }
}

/** Pill kind for a set status (matches the .pill classes). */
export const setStatusKind = (set) => ({ waiting: "warn", ready: "accent", consumed: "pass", expired: "fail", discarded: "", overridden: "warn" }[set?.status] ?? "");

/** "ok" | "warn" | "block" for a match rate (0..1) against the layout's minimum (0..1). */
export function matchRateBadge(rate, threshold) {
  if (rate === null || rate === undefined || Number.isNaN(Number(rate))) return "warn";
  const t = Number(threshold) || 0;
  if (t > 0) return Number(rate) >= t ? "ok" : "block";
  return Number(rate) >= 0.95 ? "ok" : "warn";
}

export const SAMPLE_ROWS = 2000;

/** Whether a preview's match rates and block flag can be believed. A sampled preview cuts masters, so their details look like orphans. */
export function previewTrust(preview) {
  if (preview?.sampled) {
    return { reliable: false, note: `Only the first ${SAMPLE_ROWS.toLocaleString("en-US")} rows of the main file were read, so details of the rows that were cut count as orphans. Match rates and the block warning are low here and are not a verdict; a full file is checked again before it loads.` };
  }
  return { reliable: true, note: "" };
}

const JOIN_TEXT = {
  JOIN01: "A detail row has no matching row in the main file (an orphan).",
  JOIN02: "A required detail row is missing for a main-file row, so that row is left out.",
  JOIN03: "The same key appears on more than one main-file row, so those rows are left out.",
  JOIN04: "More than one detail row matched a main-file row that allows only one.",
  JOIN05: "A join column is empty, so the row can never match and is rejected.",
  JOIN06: "An inner join dropped a main-file row that has no detail rows.",
  JOIN07: "A summary value was not a number and was skipped; the row still joins.",
};
export const joinCodeText = (code) => JOIN_TEXT[code] || "";

/** Join exceptions have no staged loan: their only action is acknowledge (close) with a reason, never a value
 * resolve, bulk resolve, escalate or reject-loan (the server refuses those too). */
export const isJoinException = (ex) => ex?.category === "join";
export const canAcknowledgeJoin = (ex) => isJoinException(ex) && ["open", "pending_review", "pending_checker", "escalated"].includes(ex?.status);

/** {role: File} limited to the roles the layout has now (a removed role's sample must not be sent). */
export function filesToSend(layout, files) {
  const out = {};
  for (const f of layout?.files || []) if (f.role && files?.[f.role]) out[f.role] = files[f.role];
  return out;
}

let idSeq = 0;
/** Copy of the layout with a client-only `_id` on every aggregate column (stable React keys). Never persisted: see stripClientIds. */
export function ensureColumnIds(layout) {
  const out = clone(layout);
  for (const r of out.relations || []) for (const c of r.aggregate?.columns || []) if (!c._id) c._id = `col${++idSeq}`;
  return out;
}

export function stripClientIds(layout) {
  const out = clone(layout);
  for (const r of out.relations || []) for (const c of r.aggregate?.columns || []) delete c._id;
  return out;
}

const escapeRegex = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A file-name regex for a sample file: an 8-digit date becomes a named group, anything else must match exactly. */
export function guessPattern(filename) {
  const name = String(filename || "");
  const m = /\d{8}/.exec(name);
  if (!m) return escapeRegex(name);
  return `${escapeRegex(name.slice(0, m.index))}(?P<date>\\d{8})${escapeRegex(name.slice(m.index + 8))}`;
}

/** A first layout for sample files: roles = [{role, filename, columns}]. The master is required and keyed on its first id-like column (loan_id, LoanID);
 * each detail joins the master as a one-to-one merge on the columns the two files share by name (empty when none). */
export function starterLayout(roles, masterRole) {
  const list = roles || [];
  const master = list.find((r) => r.role === masterRole) || list[0];
  const mcols = master?.columns || [];
  const key = mcols.find((c) => /(^|_)id$/i.test(c) || /[a-z](ID|Id)$/.test(c)) || mcols[0];
  const layout = {
    files: [{ role: masterRole, name_pattern: guessPattern(master?.filename), required: true, entity: "", key: key ? [key] : [], parse_options: {} }],
    relations: [],
  };
  for (const d of list) {
    if (d === master) continue;
    layout.files.push({ role: d.role, name_pattern: guessPattern(d.filename), required: true, parse_options: {} });
    const rel = newRelation(d.role);
    rel.to = masterRole;
    const shared = (d.columns || []).filter((c) => mcols.includes(c));
    const pick = shared.includes(key) ? key : shared[0];
    rel.on = pick ? [{ parent: pick, detail: pick }] : [];
    layout.relations.push(rel);
  }
  return layout;
}

/** What a join check was run on. A result is only valid while this still equals the current one (layout, readiness, sample files). */
export function checkSignature(layout, ready, filesByRole) {
  const files = Object.keys(filesByRole || {}).sort().map((r) => { const f = filesByRole[r]; return [r, f?.name, f?.size, f?.lastModified]; });
  return JSON.stringify([stripClientIds(layout || { files: [], relations: [] }), ready || {}, files]);
}
