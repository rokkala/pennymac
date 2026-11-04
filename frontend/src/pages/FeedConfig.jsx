import React, { useState } from "react";
import { api } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Modal, ago, human, useDialog } from "../ui.jsx";

/** What the Glue data plane will run for this feed: the signed, published configuration. */
export function FeedConfigChip({ sourceId, persona }) {
  const c = useApi(`/api/sources/${sourceId}/config`, [sourceId]);
  const [open, setOpen] = useState(false);
  if (!c.data) return null;
  const cur = c.data.current;
  const cls = !cur.verified ? "bad" : cur.in_sync === false ? "stale" : "";
  const label = !cur.verified ? "No published configuration" : `Glue config v${cur.version}${cur.in_sync === false ? " · out of date" : ""}`;
  return <>
    <button className={`cfg-chip ${cls}`} title="The approved configuration Glue runs for this feed" onClick={() => setOpen(true)}><span className="dot" />{label}</button>
    {open && <FeedConfigModal data={c.data} persona={persona} onClose={() => setOpen(false)} onChanged={c.reload} />}
  </>;
}

function FeedConfigModal({ data, persona, onClose, onChanged }) {
  const [dialog, ask] = useDialog();
  const act = useAction();
  const cur = data.current;
  const allowPublish = canCap(persona, "publishConfig");
  return (
    <Modal title="Published feed configuration" size="lg" onClose={onClose}
      sub="Glue reads only this: the approved mapping, delivery profile and live rules, compiled and signed when they are approved. Drafts are never published."
      footer={<><span className="lead faint">Republish only after a failed publication or a key rotation; approvals publish automatically.</span>
        <button className="btn" onClick={onClose}>Close</button>
        {allowPublish && <button className="btn" onClick={() => ask({ kind: "reason", title: "Republish configuration", confirmLabel: "Republish",
          help: "Recompiles the feed's approved mapping, delivery profile and live rule set, signs it and makes it current for the next Glue run. No new version is created if nothing changed.",
          presets: ["Republish after signing-key rotation", "Republish after failed publication"],
          onSubmit: (reason) => act(() => api(`/api/sources/${data.source_id}/publish`, { method: "POST", body: { reason } }), (r) => (r.unchanged ? `Already current (v${r.version})` : `Published v${r.version}`)).then((r) => { if (r) onChanged(); return r; }) })}>Republish…</button>}</>}>
      {!cur.verified ? <div className="callout t5"><b>Glue will refuse files for this feed.</b> {cur.error}</div> : <>
        <div className="kpis" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
          <div className="kpi"><span className="eyebrow">Version</span><span className="v">v{cur.version}</span><span className="d">{ago(cur.published_at)}</span></div>
          <div className="kpi"><span className="eyebrow">Mapping</span><span className="v">v{cur.mapping_version}</span><span className="d">{cur.fields} fields</span></div>
          <div className="kpi"><span className="eyebrow">Rules</span><span className="v">{(cur.rules?.active || 0) + (cur.rules?.canary || 0)}</span><span className="d">{cur.rules?.shadow || 0} in shadow</span></div>
          <div className="kpi"><span className="eyebrow">Loads as</span><span className="v" style={{ fontSize: "1.1rem" }}>{human(cur.load_type || "full")}</span><span className="d">{cur.vendor_feeds} feed(s) for this vendor</span></div>
        </div>
        <div className={`callout ${cur.in_sync === false ? "t4" : ""}`} style={{ fontSize: ".84rem" }}>
          {cur.in_sync === false ? <><b>Out of date.</b> The feed's active mapping is newer than the published configuration. Republish so Glue runs the approved mapping.</>
            : <><b>Signature verified.</b> <span className="mono faint">sha256 {String(cur.sha256).slice(0, 24)}…</span></>}
        </div></>}
      <div className="stack" style={{ gap: 6 }}><span className="eyebrow">Publication history</span>
        {!data.history.length ? <div className="empty">Nothing published yet.</div> :
          <div className="tbl-wrap" style={{ maxHeight: 300 }}><table className="tbl"><thead><tr><th>Version</th><th>Mapping</th><th>Why</th><th>By</th><th>When</th><th>SHA-256</th></tr></thead>
            <tbody>{data.history.map((h) => <tr key={h.version}><td className="num">v{h.version}{h.version === cur.version && <span className="pill pass" style={{ marginLeft: 6 }}>current</span>}</td>
              <td className="num">v{h.mapping_version}</td><td>{h.reason}</td><td>{h.actor}</td><td className="faint">{ago(h.published_at)}</td><td className="mono faint" style={{ fontSize: ".74rem" }}>{String(h.sha256).slice(0, 12)}</td></tr>)}</tbody></table></div>}
      </div>
      {dialog}
    </Modal>
  );
}

