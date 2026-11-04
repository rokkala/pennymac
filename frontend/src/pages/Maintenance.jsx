import React, { useEffect, useState } from "react";
import { canCap } from "../roles.js";
import { useApi, Panel, Loading } from "../ui.jsx";

const GROUP_LABEL = {
  jobs: "Glue jobs",
  shared: "Shared libraries",
  orchestration: "Orchestration",
  notebooks: "Notebooks (dev only)",
};
const GROUP_ORDER = ["jobs", "shared", "orchestration", "notebooks"];

function NotebookView({ cells }) {
  if (!Array.isArray(cells) || !cells.length) return <div className="empty">No cells.</div>;
  return (
    <div className="stack" style={{ gap: 12 }}>
      {cells.map((c, i) => (
        <div key={i} className="stack" style={{ gap: 4 }}>
          <span className="eyebrow">{c.cell_type === "markdown" ? "Markdown" : "Code"}</span>
          {c.cell_type === "markdown"
            ? <div className="muted" style={{ whiteSpace: "pre-wrap", fontSize: ".9rem" }}>{c.source}</div>
            : <pre className="code" style={{ maxHeight: 480, overflow: "auto" }}>{c.source}</pre>}
        </div>
      ))}
    </div>
  );
}

export default function Maintenance({ persona, go }) {
  const list = useApi("/api/maintenance/artifacts");
  const [sel, setSel] = useState(null);
  const detail = useApi(sel ? `/api/maintenance/artifacts/${sel}` : null, [sel]);
  useEffect(() => {
    if (!sel && list.data?.artifacts?.length) {
      const firstJob = list.data.artifacts.find((x) => x.group === "jobs") || list.data.artifacts[0];
      setSel(firstJob.id);
    }
  }, [list.data, sel]);
  if (!canCap(persona, "readMaintenance")) {
    return (
      <div className="empty stack" style={{ gap: 12, alignItems: "flex-start" }}>
        <span>Platform source is for Dan · SME or Platform Admin.</span>
        <button type="button" className="btn primary" onClick={() => go?.("guide")}>Open the product guide</button>
      </div>
    );
  }
  if (!list.data) return <Loading error={list.error} />;
  const artifacts = list.data.artifacts || [];
  const byGroup = GROUP_ORDER.map((g) => [g, artifacts.filter((x) => x.group === g)]).filter(([, rows]) => rows.length);
  const a = detail.data && detail.data.id === sel ? detail.data : null;
  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Platform · data plane</span>
          <h1>Maintenance</h1>
          <p className="sub">Read-only Glue jobs and orchestration source. For how boarding works in the product, use the guide.</p>
        </div>
        <button type="button" className="btn" onClick={() => go?.("guide")}>Product guide</button>
      </div>
      <div className="callout" style={{ marginBottom: 12, fontSize: ".86rem" }}>
        Production loads run as <b>lbp-feed</b> / <b>lbp-feed-spark</b> (and <b>lbp-vendor-pull</b> for fetches). Notebooks never board loans.
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(240px, 300px) minmax(0, 1fr)", alignItems: "start", gap: 16 }}>
        <Panel title="Jobs & code" pad={false}>
          <div className="stack" style={{ gap: 0 }}>
            {byGroup.map(([g, rows]) => (
              <div key={g}>
                <div className="eyebrow" style={{ padding: "10px 12px 4px", color: "var(--ink-3)" }}>{GROUP_LABEL[g] || g}</div>
                {rows.map((x) => (
                  <button key={x.id} type="button" className={`btn ${sel === x.id ? "primary" : ""}`}
                    style={{ justifyContent: "flex-start", borderRadius: 0, border: "none", borderBottom: "1px solid var(--line)", width: "100%" }}
                    onClick={() => setSel(x.id)}>
                    <span className="stack" style={{ gap: 2, alignItems: "flex-start", textAlign: "left" }}>
                      <span><b>{x.title}</b></span>
                      {x.subtitle && <span className="faint" style={{ fontSize: ".76rem" }}>{x.subtitle}</span>}
                      <span className="chip">{x.kind}</span>
                    </span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </Panel>
        <Panel title={a ? a.title : "Select a job"} sub={a ? `${a.path}${a.subtitle ? ` · ${a.subtitle}` : ""}` : "Open a job to read the script"}>
          {!sel ? <div className="empty">Select a job on the left.</div>
            : !a ? <Loading error={detail.error} />
              : a.kind === "notebook" ? <NotebookView cells={a.content} />
                : <pre className="code" style={{ maxHeight: "70vh", overflow: "auto" }}>{a.content}</pre>}
        </Panel>
      </div>
    </>
  );
}
