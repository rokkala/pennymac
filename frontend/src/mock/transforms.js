// JS port of the transform ops (backend/lbp/mapping/transforms.py) so the demo can re-run an
// edited transform chain on the sample values in the browser.
const STATES = { alabama: "AL", alaska: "AK", arizona: "AZ", arkansas: "AR", california: "CA", colorado: "CO", connecticut: "CT", delaware: "DE", florida: "FL", georgia: "GA", hawaii: "HI", idaho: "ID", illinois: "IL", indiana: "IN", iowa: "IA", kansas: "KS", kentucky: "KY", louisiana: "LA", maine: "ME", maryland: "MD", massachusetts: "MA", michigan: "MI", minnesota: "MN", mississippi: "MS", missouri: "MO", montana: "MT", nebraska: "NE", nevada: "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", ohio: "OH", oklahoma: "OK", oregon: "OR", pennsylvania: "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", tennessee: "TN", texas: "TX", utah: "UT", vermont: "VT", virginia: "VA", washington: "WA", "west virginia": "WV", wisconsin: "WI", wyoming: "WY" };
const TABLES = {
  state_name_to_code: STATES,
  amortization_type: { fixed: "FRM", "fixed rate": "FRM", frm: "FRM", adjustable: "ARM", arm: "ARM", variable: "ARM" },
  occupancy_type: { primary: "P", "primary residence": "P", owner: "P", "owner occupied": "P", o: "P", p: "P", "second home": "S", s: "S", investment: "I", investor: "I", i: "I" },
  loan_purpose: { purchase: "PUR", pur: "PUR", "rate/term refi": "REF", refinance: "REF", ref: "REF", "cash-out refi": "CSH", "cash out": "CSH", csh: "CSH" },
  loan_type: { conventional: "CNV", conv: "CNV", cnv: "CNV", fha: "FHA", va: "VA", usda: "USDA" },
  property_type: { "single family": "SFR", sfr: "SFR", condo: "CON", con: "CON", pud: "PUD", "multi family": "MFR", mfr: "MFR" },
  ofac_status: { clear: "C", c: "C", hit: "H", h: "H", pending: "P", p: "P" },
};
const empty = (v) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");
const err = (m) => { const e = new Error(m); e.transform = true; throw e; };
const num = (v) => {
  if (typeof v === "number") return v;
  const s = String(v).replace(/[$,%\s]/g, "");
  const n = Number(s);
  if (s === "" || Number.isNaN(n)) err(`not a number: '${v}'`);
  return n;
};
const pad = (n) => String(n).padStart(2, "0");
const parseDate = (v, fmt) => {
  const s = String(v).trim();
  const tries = { "%Y-%m-%d": /^(\d{4})-(\d{2})-(\d{2})$/, "%m/%d/%Y": /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, "%Y%m%d": /^(\d{4})(\d{2})(\d{2})$/ };
  for (const [f, rx] of Object.entries(tries)) {
    if (fmt && fmt !== f) continue;
    const m = s.match(rx);
    if (!m) continue;
    const [y, mo, d] = f === "%m/%d/%Y" ? [m[3], m[1], m[2]] : [m[1], m[2], m[3]];
    if (+mo >= 1 && +mo <= 12 && +d >= 1 && +d <= 31) return `${y}-${pad(mo)}-${pad(d)}`;
  }
  err(`unparseable date: '${v}'`);
};
const ADDR = /^\s*([^,]+),\s*([^,]+),\s*([A-Za-z ]{0,4}?)\s*(\d{0,9}(-\d{4})?)\s*$/;

export const OPS = {
  trim: (v) => (typeof v === "string" ? v.trim() : v),
  upper: (v) => (typeof v === "string" ? v.toUpperCase() : v),
  lower: (v) => (typeof v === "string" ? v.toLowerCase() : v),
  title: (v) => (typeof v === "string" ? v.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : v),
  to_decimal: (v) => (empty(v) ? null : num(v)),
  to_int: (v) => (empty(v) ? null : Math.round(num(v))),
  to_bool: (v) => { const s = String(v ?? "").trim().toLowerCase(); if (["y", "yes", "true", "t", "1", "x"].includes(s)) return true; if (["n", "no", "false", "f", "0"].includes(s)) return false; if (s === "") return null; err(`not a boolean: '${v}'`); },
  to_date: (v, p) => (empty(v) ? null : parseDate(v, p.format)),
  scale: (v, p) => (v === null ? null : num(v) * Number(p.factor ?? 1)),
  divide: (v, p) => (v === null ? null : num(v) / Number(p.divisor ?? 1)),
  normalize_rate: (v) => { if (v === null) return null; const n = num(v); return n > 0 && n < 0.25 ? +(n * 100).toFixed(6) : n; },
  cents_to_dollars: (v) => (empty(v) ? null : +(num(v) / 100).toFixed(2)),
  lookup: (v, p) => {
    if (empty(v)) return v;
    const k = String(v).trim().toLowerCase();
    for (const t of [p.map || {}, TABLES[p.table] || {}]) {
      if (k in t) return t[k];
      const hit = Object.keys(t).find((x) => String(x).trim().toLowerCase() === k);
      if (hit !== undefined) return t[hit];
    }
    if (p.on_miss === "error") err(`no lookup for '${v}'`);
    return v;
  },
  default: (v, p) => (empty(v) ? p.value : v),
  constant: (v, p) => p.value,
  digits_only: (v) => (v === null || v === undefined ? null : String(v).replace(/\D/g, "")),
  substr: (v, p) => (v === null ? null : String(v).substr(+(p.start || 0), p.length === undefined ? undefined : +p.length)),
  pad_left: (v, p) => (empty(v) ? null : String(v).padStart(+(p.width || 0), String(p.char ?? "0"))),
  truncate: (v, p) => (v === null || v === undefined ? null : String(v).slice(0, +(p.length || 255))),
  split: (v, p) => { if (empty(v)) return v; const parts = String(v).split(p.delimiter ?? ",").map((x) => x.trim()); const i = +(p.index || 0); return i < parts.length ? parts[i] : null; },
  regex_extract: (v, p) => { if (empty(v)) return v; const m = String(v).match(new RegExp(p.pattern)); if (!m) err(`pattern not found in '${v}'`); return m[p.group ?? 1]; },
  parse_address: (v, p) => { if (empty(v)) return v; const m = String(v).match(ADDR); if (!m) err(`cannot parse address: '${v}'`); const parts = { line1: m[1], city: m[2], state: m[3], zip: m[4] }; const out = (parts[p.part || "line1"] || "").trim(); return p.part === "state" ? out.toUpperCase() : out; },
  concat: (v, p, srcs) => srcs.filter((s) => !empty(s)).map((s) => String(s).trim()).join(p.separator ?? " ") || null,
  template: (v, p, srcs) => String(p.template || "").replace(/\{(\d+)\}/g, (_, i) => srcs[+i] ?? "").trim(),
};

/** Run a transform chain on one example's inputs; returns the same shape as the server trace. */
export function traceExample(inputs, sources, transform, isPii) {
  let srcVals = sources.map((s) => inputs[s]);
  let value = srcVals[0];
  const steps = [];
  const masked = false; // inputs are already masked server-side; only PII targets stay masked
  for (const st of transform) {
    const fn = OPS[st.op];
    try {
      if (!fn) err(`unknown op ${st.op}`);
      value = fn(value, st, srcVals);
      if (st.op === "concat" || st.op === "template") srcVals = [value];
      steps.push({ op: st.op, value: isPii || masked ? "(masked)" : value });
    } catch (e) {
      if (!e.transform) throw e;
      return { inputs, steps, output: null, error: { op: st.op, message: e.message } };
    }
  }
  return { inputs, steps, output: isPii || masked ? "(masked)" : value, error: null };
}
