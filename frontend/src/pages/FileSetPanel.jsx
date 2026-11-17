import React from "react";
import { overrideFileSet } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, useDialog, Panel, ago, fmt } from "../ui.jsx";
import { setStatusLabel, setStatusKind, missingRoles } from "../layoutModel.js";

/** Rows read / matched / no match per file role, from a batch's join summary. */
export function JoinCounts({ summary }) {
  const per = summary?.per_role;
  if (!per || !Object.keys(per).length) return null;
  const n = (s, a, b) => s[a] ?? s[b] ?? 0;
  return (
    <div className="stack" style={{ gap: 4 }}>
      <span className="eyebrow">Files joined</span>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>File</th><th className="r">Rows read</th><th className="r">Matched</th><th className="r">No match</th><th className="r">Rejected</th></tr></thead>
        <tbody>{Object.entries(per).map(([role, s]) => <tr key={role}><td className="mono">{role}{(summary.absent_roles || []).includes(role) && <span className="pill warn" style={{ marginLeft: 6 }}>not received</span>}</td>
          <td className="r num">{fmt(n(s, "rows_in", "rows_read"))}</td><td className="r num">{fmt(s.matched)}</td><td className="r num">{fmt(s.orphaned)}</td><td className="r num">{fmt(s.rejected)}</td></tr>)}</tbody>
      </table></div>
    </div>
  );
}

const OVERRIDABLE = ["waiting", "expired", "ready", "overridden"];

function SourceSets({ sourceId, name, sets, canOverride, onChanged }) {
  const lay = useApi(`/api/sources/${sourceId}/layout`, [sourceId]);
  const [dialog, ask] = useDialog();
  const act = useAction();
  const layout = lay.data?.layout;
  const override = (set, action) => ask({
    kind: "reason", title: action === "discard" ? "Discard this set of files" : "Load with the files that are here", required: true, minLength: 5,
    confirmLabel: action === "discard" ? "Discard set" : "Load without the rest", danger: action === "discard",
    help: action === "discard"
      ? "The files in this set are set aside and never loaded. The vendor can send the set again."
      : "The feed loads now with the files that have arrived. Rows that needed a missing file follow the layout's missing-file rule. The reason is recorded in the audit trail.",
    presets: action === "discard" ? ["Vendor will resend the full set", "Delivered by mistake"] : ["Vendor confirmed the missing file is not coming"],
    onSubmit: (reason) => act(() => overrideFileSet(set.set_id, action, reason), action === "discard" ? "Set discarded" : "Loading with the files that arrived").then((r) => { if (r) onChanged(); return r; }),
  });
  return (
    <>
      {sets.map((s) => {
        const miss = s.status === "waiting" ? missingRoles(s, layout) : [];
        const view = { ...s, missing_roles: miss };
        return (
          <tr key={s.set_id}>
            <td>{name}<div className="faint mono" style={{ fontSize: ".72rem" }}>{s.pairing_key || s.set_id}</div></td>
            <td><span className={`pill ${setStatusKind(s)}`}>{setStatusLabel(view)}</span>
              {s.override?.timeout && <div className="faint" style={{ fontSize: ".72rem" }}>wait ran out</div>}
              {s.override?.error && <div className="faint" style={{ fontSize: ".72rem", color: "var(--fail)" }}>{s.override.error}</div>}</td>
            <td><span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{(s.members || []).map((m) => <span key={m.role} className="chip" title={m.filename}>{m.role}{m.row_count != null ? ` · ${fmt(m.row_count)} rows` : ""}</span>)}
              {!(s.members || []).length && <span className="faint">no files yet</span>}</span></td>
            <td className="faint">{ago(s.opened_at)}</td>
            <td className="r">{canOverride && OVERRIDE_OK(s) && <span className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
              {(s.members || []).length > 0 && s.status !== "overridden" && <button type="button" className="btn sm" onClick={() => override(s, "accept_partial")}>Accept partial…</button>}
              <button type="button" className="btn sm" onClick={() => override(s, "discard")}>Discard…</button></span>}</td>
          </tr>
        );
      })}
      {dialog && <tr><td colSpan={5}>{dialog}</td></tr>}
    </>
  );
}
const OVERRIDE_OK = (s) => OVERRIDABLE.includes(s.status) && !s.batch_id;

/** File sets of multi-file feeds (waiting / ready / loaded / expired / discarded). Renders nothing when there are none, so single-file feeds look as before. */
export default function FileSetPanel({ persona, sources, title = "Files that arrive together", sub = "A delivery of several files loads once the set is complete." }) {
  const q = useApi("/api/file-sets?limit=100", [], { poll: 5000 });
  const allowed = new Set((sources || []).map((s) => s.source_id));
  const sets = (Array.isArray(q.data) ? q.data : []).filter((s) => !sources || allowed.has(s.source_id));
  if (!sets.length) return null;
  const names = Object.fromEntries((sources || []).map((s) => [s.source_id, s.name]));
  const ids = [...new Set(sets.map((s) => s.source_id))];
  const waiting = sets.filter((s) => s.status === "waiting").length;
  return (
    <Panel title={title} sub={waiting ? `${waiting} waiting for more files. ${sub}` : sub} pad={false}>
      <div className="tbl-wrap"><table className="tbl">
        <thead><tr><th>Feed · delivery</th><th>Status</th><th>Files received</th><th>Opened</th><th></th></tr></thead>
        <tbody>{ids.map((id) => <SourceSets key={id} sourceId={id} name={names[id] || id} sets={sets.filter((s) => s.source_id === id)}
          canOverride={canCap(persona, "overrideFileSet")} onChanged={q.reload} />)}</tbody>
      </table></div>
    </Panel>
  );
}
