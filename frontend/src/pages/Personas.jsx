import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Loading, Modal, Field, PageHeader } from "../ui.jsx";

const ROLE_ORDER = ["admin", "sme", "analyst", "ops", "reviewer", "checker", "compliance"];

export default function Personas({ persona, go }) {
  const act = useAction();
  const usersApi = useApi("/api/personas/users");
  const screensApi = useApi("/api/personas/screens");
  const [tab, setTab] = useState("users");
  const [createOpen, setCreateOpen] = useState(false);
  const [resetFor, setResetFor] = useState(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("ops");
  const [tempPw, setTempPw] = useState("");
  const [draft, setDraft] = useState(null);

  useEffect(() => {
    if (screensApi.data?.matrix) setDraft(JSON.parse(JSON.stringify(screensApi.data.matrix)));
  }, [screensApi.data]);

  if (!canCap(persona, "managePersonas")) {
    return (
      <div className="empty stack" style={{ gap: 12, alignItems: "flex-start" }}>
        <span>Persona Maintenance is for Platform Admin only.</span>
        <button type="button" className="btn primary" onClick={() => go?.("overview")}>Back to Overview</button>
      </div>
    );
  }
  if (!usersApi.data || !screensApi.data) return <Loading error={usersApi.error || screensApi.error} />;

  const roles = screensApi.data.roles || ROLE_ORDER;
  const screenList = screensApi.data.screens || [];
  const defaults = screensApi.data.defaults || {};
  const matrix = draft || screensApi.data.matrix;

  const toggleScreen = (r, screenId) => {
    const allowed = new Set(defaults[r] || []);
    if (!allowed.has(screenId)) return;
    setDraft((prev) => {
      const next = { ...(prev || matrix) };
      const cur = new Set(next[r] || []);
      if (cur.has(screenId)) cur.delete(screenId);
      else cur.add(screenId);
      next[r] = screenList.map((s) => s.id).filter((id) => cur.has(id));
      return next;
    });
  };

  const saveMatrix = () => act(async () => {
    const r = await api("/api/personas/screens", { method: "PUT", body: { matrix } });
    setDraft(r.matrix);
    screensApi.reload();
    return r;
  }, "Screen access saved");

  const createUser = () => act(async () => {
    await api("/api/personas/users", { method: "POST", body: { email, role, temporary_password: tempPw } });
    setCreateOpen(false); setEmail(""); setTempPw(""); setRole("ops");
    usersApi.reload();
  }, "User created");

  const patchUser = (username, body, ok) => act(async () => {
    await api(`/api/personas/users/${encodeURIComponent(username)}`, { method: "PUT", body });
    usersApi.reload();
  }, ok);

  const doReset = () => act(async () => {
    await api(`/api/personas/users/${encodeURIComponent(resetFor)}/reset-password`, {
      method: "POST", body: { temporary_password: tempPw },
    });
    setResetFor(null); setTempPw("");
  }, "Temporary password set");

  return (
    <>
      <PageHeader
        eyebrow="Govern"
        title="Personas"
        sub="Create Cognito users (one role each) and hide screens a role does not need. API permissions stay fixed in code."
        primary={tab === "screens" ? <button type="button" className="btn primary" onClick={saveMatrix}>Save access</button> : <button type="button" className="btn primary" onClick={() => setCreateOpen(true)}>Add user</button>}
        secondary={(
          <>
            <button type="button" className={`btn sm ${tab === "users" ? "primary" : ""}`} onClick={() => setTab("users")}>Users</button>
            <button type="button" className={`btn sm ${tab === "screens" ? "primary" : ""}`} onClick={() => setTab("screens")}>Screen access</button>
          </>
        )}
      />

      {tab === "users" && (
        <Panel title="Users" sub="One Cognito group per person. Temp password forces change on first sign-in.">
          <div className="tbl-wrap" style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead><tr><th>Email</th><th>Role</th><th>Status</th><th>Enabled</th><th /></tr></thead>
              <tbody>
                {(usersApi.data.users || []).map((u) => (
                  <tr key={u.username || u.email}>
                    <td>{u.email}</td>
                    <td>
                      <select aria-label={`Role for ${u.email}`} value={u.role || ""}
                        onChange={(e) => patchUser(u.username || u.email, { role: e.target.value }, "Role updated")}>
                        {roles.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td><span className="muted" style={{ fontSize: ".85rem" }}>{u.status || "—"}</span></td>
                    <td>{u.enabled ? "Yes" : "No"}</td>
                    <td className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                      <button type="button" className="btn sm" onClick={() => { setResetFor(u.username || u.email); setTempPw(""); }}>Reset password</button>
                      <button type="button" className="btn sm" onClick={() => patchUser(u.username || u.email, { enabled: !u.enabled }, u.enabled ? "User disabled" : "User enabled")}>
                        {u.enabled ? "Disable" : "Enable"}
                      </button>
                    </td>
                  </tr>
                ))}
                {!usersApi.data.users?.length && <tr><td colSpan={5} className="muted">No users yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {tab === "screens" && (
        <Panel title="Screen access by role" sub="Uncheck to hide a screen in the nav. You cannot grant a screen the role does not already have by default.">
          <div className="tbl-wrap" style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Screen</th>
                  {ROLE_ORDER.filter((r) => roles.includes(r)).map((r) => <th key={r}>{r}</th>)}
                </tr>
              </thead>
              <tbody>
                {screenList.map((s) => (
                  <tr key={s.id}>
                    <td>{s.label}</td>
                    {ROLE_ORDER.filter((r) => roles.includes(r)).map((r) => {
                      const allowed = (defaults[r] || []).includes(s.id);
                      const on = (matrix[r] || []).includes(s.id);
                      return (
                        <td key={r}>
                          <input type="checkbox" checked={on} disabled={!allowed || r === "admin"}
                            aria-label={`${s.label} for ${r}`}
                            onChange={() => toggleScreen(r, s.id)} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ marginTop: 8, fontSize: ".85rem" }}>Admin always sees every screen. Hiding a screen does not change API roles.</p>
        </Panel>
      )}

      {createOpen && (
        <Modal title="Add user" onClose={() => setCreateOpen(false)}
          footer={<><button type="button" className="btn" onClick={() => setCreateOpen(false)}>Cancel</button>
            <button type="button" className="btn primary" onClick={createUser} disabled={!email || tempPw.length < 14}>Create</button></>}>
          <div className="stack">
            <Field id="persona-email" label="Email"><input id="persona-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" /></Field>
            <Field id="persona-role" label="Role">
              <select id="persona-role" value={role} onChange={(e) => setRole(e.target.value)}>
                {roles.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </Field>
            <Field id="persona-pw" label="Temporary password" hint="14+ characters with upper, lower, number, and symbol">
              <input id="persona-pw" type="text" value={tempPw} onChange={(e) => setTempPw(e.target.value)} autoComplete="new-password" />
            </Field>
          </div>
        </Modal>
      )}

      {resetFor && (
        <Modal title="Reset temporary password" onClose={() => setResetFor(null)}
          footer={<><button type="button" className="btn" onClick={() => setResetFor(null)}>Cancel</button>
            <button type="button" className="btn primary" onClick={doReset} disabled={tempPw.length < 14}>Set password</button></>}>
          <Field id="persona-reset-pw" label={`New temporary password for ${resetFor}`} hint="14+ characters with upper, lower, number, and symbol">
            <input id="persona-reset-pw" type="text" value={tempPw} onChange={(e) => setTempPw(e.target.value)} autoComplete="new-password" />
          </Field>
        </Modal>
      )}
    </>
  );
}
