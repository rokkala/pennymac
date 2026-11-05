// API client. In demo builds (VITE_DEMO=1) every call is served by the in-browser mock.
export const DEMO = import.meta.env.VITE_DEMO === "1";

export const PERSONAS = [
  { id: "priya.analyst", label: "Priya · Data Analyst", roles: ["analyst"] },
  { id: "dan.sme", label: "Dan · SME", roles: ["sme", "analyst"] },
  { id: "maria.ops", label: "Maria · Boarding Ops", roles: ["ops"] },
  { id: "lee.reviewer", label: "Lee · Exception Reviewer", roles: ["reviewer"] },
  { id: "ana.compliance", label: "Ana · Compliance", roles: ["compliance", "checker"] },
  { id: "admin", label: "Platform Admin", roles: ["admin", "analyst", "sme", "ops", "reviewer", "checker", "compliance"] },
];

let persona = PERSONAS[3];
export let SIGNED_IN = null; // set when Cognito sign-in is active (no persona switching)
export const setSignedIn = (u) => { SIGNED_IN = u; persona = u; };
export const setPersona = (p) => { persona = p; };
export const getPersona = () => persona;

export { can, canCap, CAPS } from "./roles.js";

let mock = null;
async function mockApi() {
  if (!mock) mock = (await import("./mock/mockApi.js")).createMockApi();
  return mock;
}

export async function api(path, { method = "GET", body, form } = {}) {
  if (DEMO) return (await mockApi()).handle(method, path, body ?? form, persona);
  const { authMode, bearer, login } = await import("./auth.js");
  const headers = {};
  if (authMode() === "cognito") headers.Authorization = `Bearer ${await bearer()}`;
  else { headers["X-User"] = persona.id; headers["X-Roles"] = persona.roles.join(","); }
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(path, { method, headers, body: payload });
  if (r.status === 401 && authMode() === "cognito") { await login(); throw new Error("Your session expired. Signing you in again."); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d?.message || (r.status === 403 ? "You don't have permission for this action." : `${r.status} ${r.statusText}`));
  }
  return data;
}

// Cross-page deep links (e.g. an exception root cause opening a mapping field).
let intent = null;
export const setIntent = (x) => { intent = x; };
export const takeIntent = (page) => { if (intent && intent.page === page) { const x = intent; intent = null; return x; } return null; };


// Vendor scope: one selector in the shell narrows every operational page to a vendor.
let vendorScope = (() => { try { return localStorage.getItem("lbp.vendor") || null; } catch { return null; } })();
export const getVendorScope = () => vendorScope;
export const setVendorScope = (id) => { vendorScope = id || null; try { id ? localStorage.setItem("lbp.vendor", id) : localStorage.removeItem("lbp.vendor"); } catch { /* storage unavailable */ } };
export const scoped = (path) => (vendorScope ? `${path}${path.includes("?") ? "&" : "?"}vendor_id=${encodeURIComponent(vendorScope)}` : path);
