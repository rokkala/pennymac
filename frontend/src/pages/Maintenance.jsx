import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Loading, Modal, Field, PageHeader, EmptyState } from "../ui.jsx";
import { blankLeaf, ensureTree, LeafEditor } from "../ruleTree.jsx";

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

function JobsPane({ go }) {
  const list = useApi("/api/maintenance/artifacts");
  const [sel, setSel] = useState(null);
  const detail = useApi(sel ? `/api/maintenance/artifacts/${sel}` : null, [sel]);
  useEffect(() => {
    if (!sel && list.data?.artifacts?.length) {
      const firstJob = list.data.artifacts.find((x) => x.group === "jobs") || list.data.artifacts[0];
      setSel(firstJob.id);
    }
  }, [list.data, sel]);
  if (!list.data) return <Loading error={list.error} />;
  const artifacts = list.data.artifacts || [];
  const byGroup = GROUP_ORDER.map((g) => [g, artifacts.filter((x) => x.group === g)]).filter(([, rows]) => rows.length);
  const a = detail.data && detail.data.id === sel ? detail.data : null;
  return (
    <>
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
      <p className="faint" style={{ marginTop: 12, fontSize: ".82rem" }}>
        For how boarding works in the product, use the <button type="button" className="btn sm" onClick={() => go?.("guide")}>product guide</button>.
      </p>
    </>
  );
}

function TemplateEditor({ initial, onClose, onSaved }) {
  const { data: fieldData } = useApi("/api/rules/fields");
  const [id, setId] = useState(initial?.id || "");
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [tree, setTree] = useState(() => ensureTree(initial?.tree));
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState("");
  const act = useAction();
  const fields = fieldData?.fields || [];
  const isEdit = Boolean(initial?.id);

  const compose = async () => {
    setErr("");
    const res = await act(() => api("/api/rules/compose", { method: "POST", body: { tree, name: name || undefined } }));
    if (res) setPreview(res);
    else setPreview(null);
    return res;
  };

  const save = async () => {
    const res = preview || await compose();
    if (!res?.draft) { setErr(res?.problems?.join(" ") || "Fix the template before saving."); return; }
    if (res.problems?.length) { setErr(res.problems.join(" ")); return; }
    const body = { name: name || res.summary, description: description || res.summary || "", tree };
    if (!isEdit && id.trim()) body.id = id.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_");
    const r = isEdit
      ? await act(() => api(`/api/maintenance/rule-templates/${initial.id}`, { method: "PUT", body }), () => "Template updated")
      : await act(() => api("/api/maintenance/rule-templates", { method: "POST", body }), (x) => `Template ${x.id} created`);
    if (r) onSaved();
  };

  return (
    <Modal title={isEdit ? `Edit template · ${initial.id}` : "New rule template"} sub="Same builder as Rules Author. Preview sample checks, then save." size="xl" onClose={onClose}
      footer={<>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn" onClick={() => compose()}>Preview checks</button>
        <button type="button" className="btn primary" onClick={save}>Save</button>
      </>}>
      <div className="stack">
        <div className="grid g2">
          {!isEdit && (
            <Field id="tid" label="Id (optional)" hint="Letters, numbers, underscores. Auto-generated if blank.">
              <input id="tid" className="input mono" value={id} onChange={(e) => setId(e.target.value)} placeholder="e.g. interest_rate_range" />
            </Field>
          )}
          <Field id="tn" label="Name">
            <input id="tn" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Interest rate range" />
          </Field>
        </div>
        <Field id="td" label="Description">
          <input id="td" className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Shown on the Author templates tab" />
        </Field>
        <div className="row" style={{ gap: 6 }}>
          <button type="button" className="btn sm" onClick={() => setTree({ op: "and", children: [blankLeaf()] })}>Start group (All must pass)</button>
          <button type="button" className="btn sm" onClick={() => setTree(blankLeaf())}>Single check</button>
        </div>
        <LeafEditor node={tree} fields={fields} onChange={setTree} />
        {err && <div className="callout t5" style={{ fontSize: ".84rem" }}>{err}</div>}
        {preview?.draft && (
          <div className="stack">
            <span className="eyebrow">In plain English</span>
            <p style={{ margin: 0 }}>{preview.summary || preview.draft.summary}</p>
            {preview.problems?.length > 0 && <div className="callout t4">{preview.problems.join(" ")}</div>}
          </div>
        )}
      </div>
    </Modal>
  );
}

function TemplatesPane() {
  const list = useApi("/api/maintenance/rule-templates");
  const [editor, setEditor] = useState(null); // null | { mode: 'new' } | { mode: 'edit', row }
  const act = useAction();

  if (!list.data) return <Loading error={list.error} />;
  const rows = list.data.templates || [];

  const hide = async (t) => {
    if (await act(() => api(`/api/maintenance/rule-templates/${t.id}/hide`, { method: "POST" }), () => "Hidden from Author")) list.reload();
  };
  const unhide = async (t) => {
    if (await act(() => api(`/api/maintenance/rule-templates/${t.id}/unhide`, { method: "POST" }), () => "Visible in Author")) list.reload();
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete custom template “${t.name}”? Built-ins cannot be deleted.`)) return;
    if (await act(() => api(`/api/maintenance/rule-templates/${t.id}`, { method: "DELETE" }), () => "Deleted")) list.reload();
  };

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <p className="muted" style={{ margin: 0, fontSize: ".9rem" }}>
          Starters for Rules → Author. Built-ins can be hidden; custom templates can be deleted.
        </p>
        <button type="button" className="btn primary" onClick={() => setEditor({ mode: "new" })}>New template</button>
      </div>
      <Panel title="Rule templates" pad={false}>
        {!rows.length ? <EmptyState title="No templates yet" body="Create a starter for Rules → Author." action={<button type="button" className="btn primary" onClick={() => setEditor({ mode: "new" })}>New template</button>} /> : (
          <div className="stack" style={{ gap: 0 }}>
            {rows.map((t) => (
              <div key={t.id} className="row" style={{
                padding: "12px 14px", borderBottom: "1px solid var(--line)", gap: 12, alignItems: "flex-start", flexWrap: "wrap",
              }}>
                <div className="stack" style={{ gap: 2, flex: 1, minWidth: 200 }}>
                  <span className="row" style={{ gap: 8 }}>
                    <b>{t.name}</b>
                    <span className="chip mono">{t.id}</span>
                    {t.builtin && <span className="chip">built-in</span>}
                    {t.hidden && <span className="chip">hidden</span>}
                  </span>
                  <span className="faint" style={{ fontSize: ".82rem" }}>{t.description || "—"}</span>
                  {t.updated_by && (
                    <span className="faint" style={{ fontSize: ".76rem" }}>
                      v{t.version} · {t.updated_by}{t.updated_at ? ` · ${t.updated_at}` : ""}
                    </span>
                  )}
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <button type="button" className="btn sm" onClick={() => setEditor({ mode: "edit", row: t })}>Edit</button>
                  {t.hidden
                    ? <button type="button" className="btn sm" onClick={() => unhide(t)}>Unhide</button>
                    : <button type="button" className="btn sm" onClick={() => hide(t)}>Hide</button>}
                  {!t.builtin && <button type="button" className="btn sm" onClick={() => remove(t)}>Delete</button>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
      {editor?.mode === "new" && (
        <TemplateEditor onClose={() => setEditor(null)} onSaved={() => { setEditor(null); list.reload(); }} />
      )}
      {editor?.mode === "edit" && (
        <TemplateEditor initial={editor.row} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); list.reload(); }} />
      )}
    </>
  );
}

export default function Maintenance({ persona, go }) {
  const [tab, setTab] = useState("jobs"); // jobs | templates
  if (!canCap(persona, "readMaintenance")) {
    return (
      <EmptyState
        title="Maintenance is restricted"
        body="Platform source is for Dan · SME or Platform Admin."
        action={<button type="button" className="btn primary" onClick={() => go?.("guide")}>Open the product guide</button>}
      />
    );
  }
  return (
    <>
      <PageHeader
        eyebrow="Govern"
        title="Maintenance"
        sub="Jobs the platform team can run."
        primary={<button type="button" className="btn" onClick={() => go?.("guide")}>Product guide</button>}
      />
      <div className="row" style={{ gap: 6, marginBottom: 16 }}>
        {[["jobs", "Jobs & code"], ["templates", "Rule templates"]].map(([id, label]) => (
          <button key={id} type="button" className={`btn ${tab === id ? "primary" : ""}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {tab === "jobs" ? <JobsPane go={go} /> : <TemplatesPane />}
    </>
  );
}
