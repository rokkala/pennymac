// Cognito hosted-UI sign-in (OAuth 2.0 authorization code + PKCE). No client secret in the browser.
// Tokens live in sessionStorage (tab-scoped, cleared when the tab closes) and are refreshed
// before expiry. The API verifies every token itself (lbp/security.py).
const KEY = "lbp.auth";
let cfg = null;
let session = null;

const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (n = 64) => b64url(crypto.getRandomValues(new Uint8Array(n)));
const decode = (jwt) => JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
const redirectUri = () => `${location.origin}/auth/callback`;
const load = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; } };
const save = (s) => { session = s; try { s ? sessionStorage.setItem(KEY, JSON.stringify(s)) : sessionStorage.removeItem(KEY); } catch { /* storage blocked */ } };

async function tokenRequest(body) {
  const r = await fetch(`https://${cfg.cognito_domain}/oauth2/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: cfg.client_id, ...body }),
  });
  if (!r.ok) throw new Error(`sign-in failed (${r.status})`);
  const t = await r.json();
  return { id_token: t.id_token, access_token: t.access_token, refresh_token: t.refresh_token || session?.refresh_token,
    expires_at: Date.now() + (t.expires_in - 60) * 1000 };
}

export async function login() {
  const verifier = randomString();
  const state = randomString(16);
  sessionStorage.setItem("lbp.pkce", JSON.stringify({ verifier, state, returnTo: location.hash || "" }));
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const q = new URLSearchParams({ response_type: "code", client_id: cfg.client_id, redirect_uri: redirectUri(), scope: "openid email profile",
    code_challenge_method: "S256", code_challenge: challenge, state });
  location.assign(`https://${cfg.cognito_domain}/oauth2/authorize?${q}`);
}

export function logout() {
  save(null);
  const q = new URLSearchParams({ client_id: cfg.client_id, logout_uri: `${location.origin}/` });
  location.assign(`https://${cfg.cognito_domain}/logout?${q}`);
}

/** Resolve the signed-in user before the app renders. Returns null in dev/demo mode. */
export async function initAuth() {
  try { cfg = await (await fetch("/api/config")).json(); } catch { cfg = { auth: "dev" }; }
  if (cfg.auth !== "cognito") return null;
  if (location.pathname === "/auth/callback") {
    const p = new URLSearchParams(location.search);
    const pk = JSON.parse(sessionStorage.getItem("lbp.pkce") || "{}");
    sessionStorage.removeItem("lbp.pkce");
    if (!p.get("code") || p.get("state") !== pk.state) throw new Error("sign-in response did not match this browser session");
    save(await tokenRequest({ grant_type: "authorization_code", code: p.get("code"), redirect_uri: redirectUri(), code_verifier: pk.verifier }));
    history.replaceState(null, "", `/${/^#[A-Za-z0-9-]*$/.test(pk.returnTo || "") ? pk.returnTo : ""}`);
  } else {
    session = load();
  }
  if (!session) { await login(); return new Promise(() => {}); }
  await bearer();
  const c = decode(session.id_token);
  return { id: c.email || c["cognito:username"], label: c.email || c["cognito:username"], roles: c["cognito:groups"] || [] };
}

/** Current id token, refreshed when close to expiry. */
export async function bearer() {
  if (!session) return null;
  if (Date.now() > session.expires_at) {
    try { save(await tokenRequest({ grant_type: "refresh_token", refresh_token: session.refresh_token })); }
    catch { save(null); await login(); return null; }
  }
  return session.id_token;
}

export const authMode = () => cfg?.auth || "dev";
