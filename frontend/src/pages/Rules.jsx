import React, { useEffect, useState } from "react";
import { api, getPersona } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, Loading, ago, fmt, human, Modal, ReasonModal, Field } from "../ui.jsx";
import { blankLeaf, ensureTree, LeafEditor } from "../ruleTree.jsx";

function sameUser(a, b) {
  if (a == null || b == null || a === "" || b === "") return false;
  return String(a).trim().toLowerCase() === String(b).trim().toLowerCase();
}
function isRuleAuthor(persona, rule) {
  const me = persona?.id || persona?.name || getPersona()?.id;
  return sameUser(me, rule?.author) || sameUser(me, rule?.owner);
}
function isRuleSubmitter(persona, rule) {
  const me = persona?.id || persona?.name || getPersona()?.id;
  const submittedBy = [...(rule?.history || [])].reverse().find((h) => h.to === "in_review")?.actor;
  return sameUser(me, submittedBy);
}

const STAGES = [
  { id: "author", label: "Draft", desc: "Build the check", states: ["draft"] },
  { id: "review", label: "Review", desc: "Peer sign-off", states: ["in_review", "approved"] },
  { id: "deploy", label: "Try safely", desc: "Shadow or canary", states: ["shadow", "canary"] },
  { id: "monitor", label: "Live", desc: "On for all loans", states: ["active"] },
  { id: "retire", label: "Off", desc: "History kept", states: ["retired"] },
];
const NEXT = {
  draft: ["in_review"],
  in_review: ["approved", "draft"],
  approved: ["shadow", "canary", "active"],
  shadow: ["canary", "active", "retired"],
  canary: ["active", "shadow", "retired"],
  active: ["retired"],
  rejected: ["draft"],
  retired: [],
};
const ACTION_LABEL = {
  in_review: "Submit for review",
  approved: "Approve",
  draft: "Send back",
  shadow: "Run quietly (shadow)",
  canary: "Try on a %",
  active: "Turn on for all",
  retired: "Retire",
};
const STATUS_LABEL = {
  draft: "Draft — not submitted",
  in_review: "In review — waiting for a peer",
  approved: "Approved — ready to try safely",
  shadow: "Shadow — running quietly",
  canary: "Canary — trying on a slice",
  active: "Live on all loans",
  retired: "Retired",
  rejected: "Sent back",
};
const NEXT_HELP = {
  draft: "Save your checks, then submit for peer review. You cannot approve your own rule.",
  in_review: "Another SME must approve (not the author). Regulatory-tagged rules also need Compliance.",
  approved: "Try quietly (shadow), on a share of loans (canary), or turn on for everyone.",
  shadow: "Promote to canary or live, or retire.",
  canary: "Turn on for all loans, drop back to shadow, or retire.",
  active: "This version is live. To change the logic, create a new draft version, then submit it for review.",
  retired: "This version is off. Create a new draft from another version if you need changes.",
};
const TRANSITION_HELP = {
  in_review: "Sends the rule to a peer. Sample checks must pass first.",
  approved: "Non-regulatory rules need one peer. Regulatory-tagged rules also need Compliance. You cannot approve your own rule.",
  draft: "Returns the rule to its author with your comment.",
  shadow: "Runs on every loan but never blocks. Results are recorded for comparison. Live feed configs are republished.",
  canary: "Enforces on a share of loans. Live feed configs are republished.",
  active: "Turns this version on for all loans. Live feed configs are republished.",
  retired: "Stops the rule. History is kept. Live feed configs are republished.",
};
const AUTHOR_STEPS = [
  { id: "start", label: "Start" },
  { id: "build", label: "Build" },
  { id: "preview", label: "Preview & save" },
];

function Stepper({ steps, current }) {
  const idx = steps.findIndex((s) => s.id === current);
  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap" }} aria-label="Steps">
      {steps.map((s, i) => (
        <span key={s.id} className={`chip ${i === idx ? "" : "faint"}`} style={i === idx ? { fontWeight: 600 } : undefined}>
          {i + 1}. {s.label}
        </span>
      ))}
    </div>
  );
}

function AuthorModal({ persona, onCreated, onClose }) {
  const { data: fieldData } = useApi("/api/rules/fields");
  const { data: tplData } = useApi("/api/rules/templates");
  const [step, setStep] = useState("start");
  const [tree, setTree] = useState(() => ensureTree(null));
  const [name, setName] = useState("");
  const [severity, setSeverity] = useState("FAIL");
  const [tag, setTag] = useState("");
  const [preview, setPreview] = useState(null);
  const [text, setText] = useState("Interest rate must be between 0.5 and 15");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const canSave = canCap(persona, "editRules");
  const fields = fieldData?.fields || [];

  const compose = async (t = tree) => {
    setErr("");
    const res = await act(() => api("/api/rules/compose", { method: "POST", body: { tree: t, name: name || undefined, severity, regulatory_tag: tag || null } }));
    if (res) setPreview(res);
    else setPreview(null);
    return res;
  };

  useEffect(() => { setPreview(null); }, [tree, severity, tag]);

  const goPreview = async () => {
    setBusy(true);
    const res = await compose();
    setBusy(false);
    if (!res?.draft) { setErr(res?.problems?.join(" ") || "Fix the rule before previewing."); return; }
    setStep("preview");
  };

  const save = async () => {
    setBusy(true);
    const res = preview || await compose();
    if (!res?.draft) { setBusy(false); setErr(res?.problems?.join(" ") || "Fix the rule before saving."); return; }
    if (res.problems?.length) { setBusy(false); setErr(res.problems.join(" ")); return; }
    const body = {
      name: name || res.draft.name || res.summary,
      description: res.summary,
      tree,
      severity,
      regulatory_tag: tag || null,
    };
    const r = await act(() => api("/api/rules", { method: "POST", body }), (x) => `Draft ${x.rule_id} created — submit it for review next`);
    setBusy(false);
    if (r) onCreated(r.rule_id);
  };

  const fromAi = async () => {
    setErr("");
    setBusy(true);
    const res = await act(() => api("/api/rules/author", { method: "POST", body: { text } }));
    setBusy(false);
    if (res?.draft?.tree) {
      setTree(ensureTree(res.draft.tree));
      setName(res.draft.name || text);
      setPreview({ draft: res.draft, test_results: res.test_results, problems: res.problems, summary: res.draft.summary || res.draft.description });
      setStep("build");
    } else setErr((res?.problems || ["Could not turn that into a guided rule."]).join(" "));
  };

  const startBlank = () => {
    setTree(ensureTree(null));
    setName("");
    setPreview(null);
    setErr("");
    setStep("build");
  };

  const footer = step === "start" ? (
    <button type="button" className="btn" onClick={onClose}>Cancel</button>
  ) : step === "build" ? (
    <>
      <button type="button" className="btn" onClick={() => setStep("start")} disabled={busy}>Back</button>
      <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
      <button type="button" className="btn primary" onClick={goPreview} disabled={busy}>{busy ? "Checking…" : "Preview checks"}</button>
    </>
  ) : (
    <>
      <button type="button" className="btn" onClick={() => setStep("build")} disabled={busy}>Back to build</button>
      <button type="button" className="btn" onClick={() => compose()} disabled={busy}>Re-check</button>
      {canSave && <button type="button" className="btn primary" onClick={save} disabled={busy || preview?.problems?.length}>{busy ? "Saving…" : "Save draft"}</button>}
    </>
  );

  return (
    <Modal title="New rule" sub="Three steps: choose a start, build the check, preview and save a draft." size="xl" onClose={onClose} busy={busy} footer={footer}>
      <div className="stack">
        <Stepper steps={AUTHOR_STEPS} current={step} />
        {!canSave && <div className="callout t4" style={{ fontSize: ".84rem" }}>You can build a preview. Switch to <b>Dan · SME</b> or <b>Ana · Compliance</b> to save.</div>}
        {err && <div className="callout t5" style={{ fontSize: ".84rem" }}>{err}</div>}

        {step === "start" && (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>How do you want to start?</p>
            <div className="grid g2">
              <button type="button" className="btn primary" style={{ textAlign: "left", height: "auto", padding: "14px 16px" }} onClick={startBlank}>
                <b>Blank rule</b>
                <div className="faint" style={{ fontSize: ".82rem", marginTop: 4, color: "inherit", opacity: 0.9 }}>Guided form — pick fields and options yourself</div>
              </button>
              {(tplData?.templates || []).map((t) => (
                <button key={t.id} type="button" className="btn" style={{ textAlign: "left", height: "auto", padding: "14px 16px" }}
                  onClick={() => { setTree(ensureTree(t.tree)); setName(t.name); setPreview(null); setErr(""); setStep("build"); }}>
                  <b>{t.name}</b>
                  <div className="faint" style={{ fontSize: ".82rem", marginTop: 4 }}>{t.description}</div>
                </button>
              ))}
            </div>
            {!tplData?.templates?.length && <p className="faint" style={{ margin: 0 }}>No catalog templates — use Blank rule, or add starters under Maintenance → Rule templates.</p>}
            <div className="stack" style={{ marginTop: 8, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
              <span className="eyebrow">Or describe it (AI assist)</span>
              <Field id="ai-text" label="Plain English">
                <textarea id="ai-text" className="input" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
              </Field>
              <button type="button" className="btn" disabled={!text.trim() || busy} onClick={fromAi}>Fill builder from this text</button>
              <p className="faint" style={{ fontSize: ".82rem", margin: 0 }}>Always review the Build step — AI can pick the wrong field.</p>
            </div>
          </div>
        )}

        {step === "build" && (
          <div className="stack">
            <div className="grid g2">
              <Field id="rn" label="Name"><input id="rn" className="input" data-autofocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Interest rate range" /></Field>
              <Field id="sev" label="When it fails">
                <select id="sev" className="input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  <option value="FAIL">Block the loan (FAIL)</option>
                  <option value="WARN">Flag only (WARN)</option>
                </select>
              </Field>
            </div>
            <Field id="tag" label="Regulatory tag (optional)" hint="If set, Compliance must also approve.">
              <input id="tag" className="input" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="e.g. HMDA, ECOA" />
            </Field>
            <div className="row" style={{ gap: 6 }}>
              <button type="button" className="btn sm" onClick={() => setTree({ op: "and", children: [blankLeaf()] })}>Start group (All must pass)</button>
              <button type="button" className="btn sm" onClick={() => setTree(blankLeaf())}>Single check</button>
            </div>
            <LeafEditor node={tree} fields={fields} onChange={setTree} />
          </div>
        )}

        {step === "preview" && preview?.draft && (
          <div className="stack">
            <div className="callout" style={{ fontSize: ".9rem" }}>
              After you save, open the draft and use <b>Submit for review</b> — that starts peer sign-off.
            </div>
            <span className="eyebrow">In plain English</span>
            <p style={{ margin: 0 }}>{preview.summary || preview.draft.summary || preview.draft.description}</p>
            <span className="eyebrow">Sample checks</span>
            {(preview.draft.tests || []).map((t, i) => (
              <span key={i} className="row" style={{ fontSize: ".82rem", gap: 8 }}>
                <span className={`pill ${preview.test_results?.[i]?.passed ? "pass" : "fail"}`}>
                  {preview.test_results?.[i]?.passed ? "ok" : "broken"}
                </span>
                expect {String(t.expect)} · <span className="mono faint">{Object.entries(t.record || {}).filter(([k]) => (preview.draft.fields || []).includes(k)).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")}</span>
              </span>
            ))}
            {preview.problems?.length > 0 && <div className="callout t4">{preview.problems.join(" ")}</div>}
          </div>
        )}
      </div>
    </Modal>
  );
}

function EditRuleModal({ rule, onClose, onSaved }) {
  const { data: fieldData } = useApi("/api/rules/fields");
  const [tree, setTree] = useState(() => ensureTree(rule.tree));
  const [name, setName] = useState(rule.name || "");
  const [severity, setSeverity] = useState(rule.severity || "FAIL");
  const [tag, setTag] = useState(rule.regulatory_tag || "");
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const fields = fieldData?.fields || [];
  const noTree = !rule.tree;

  const compose = async () => {
    setErr("");
    const res = await act(() => api("/api/rules/compose", { method: "POST", body: { tree, name, severity, regulatory_tag: tag || null } }));
    if (res) setPreview(res);
    return res;
  };

  const save = async () => {
    setBusy(true); setErr("");
    const res = preview || await compose();
    if (!res?.draft) { setBusy(false); setErr("Could not compile this rule."); return; }
    const r = await act(() => api(`/api/rules/${rule.rule_id}/${rule.version}`, {
      method: "PUT",
      body: { name, severity, regulatory_tag: tag || null, tree, description: res.summary },
    }), "Draft updated — submit for review when ready");
    setBusy(false);
    if (r) onSaved(r);
  };

  return (
    <Modal title={`Edit draft · ${rule.rule_id} v${rule.version}`} sub="Change the guided checks, then return to the rule to submit for review." size="xl" onClose={onClose} busy={busy}
      footer={<>
        <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="btn" disabled={busy} onClick={compose}>Preview</button>
        <button type="button" className="btn primary" disabled={busy || !name.trim()} onClick={save}>{busy ? "Saving…" : "Save draft"}</button>
      </>}>
      <div className="stack">
        {noTree && <div className="callout t4" style={{ fontSize: ".84rem" }}>This draft had no guided tree. Rebuild with the form below (replaces the old expression).</div>}
        {err && <div className="callout t5" style={{ fontSize: ".84rem" }}>{err}</div>}
        <div className="grid g2">
          <Field id="en" label="Name"><input id="en" className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field id="es" label="When it fails">
            <select id="es" className="input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="FAIL">Block the loan (FAIL)</option>
              <option value="WARN">Flag only (WARN)</option>
            </select>
          </Field>
        </div>
        <Field id="et" label="Regulatory tag (optional)">
          <input id="et" className="input" value={tag} onChange={(e) => setTag(e.target.value)} />
        </Field>
        <LeafEditor node={tree} fields={fields} onChange={(t) => { setTree(t); setPreview(null); }} />
        {preview?.summary && <p className="muted">{preview.summary}</p>}
      </div>
    </Modal>
  );
}

function primaryTransition(status) {
  const next = NEXT[status] || [];
  if (!next.length) return null;
  if (status === "draft") return "in_review";
  if (status === "in_review") return "approved";
  if (status === "approved") return "active";
  if (status === "shadow" || status === "canary") return "active";
  if (status === "active") return "retired";
  return next[0];
}

function RuleModal({ ruleId, persona, onChanged, onClose, onDeleted, nav, editIntent, onEditIntentHandled }) {
  const { data, reload } = useApi(`/api/rules/${ruleId}`, [ruleId]);
  const [ver, setVer] = useState(null);
  const [to, setTo] = useState(null);
  const [pct, setPct] = useState(10);
  const [editing, setEditing] = useState(false);
  const [editSnapshot, setEditSnapshot] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const act = useAction();
  const canEdit = canCap(persona, "editRules");

  const openEditor = (rule) => {
    setVer(rule.version);
    setEditSnapshot(rule);
    setEditing(true);
  };

  const newVersionFrom = async (src, { openEdit = false } = {}) => {
    const body = src.tree
      ? { rule_id: ruleId, name: src.name, description: src.description, tree: src.tree, severity: src.severity, category: src.category, regulatory_tag: src.regulatory_tag }
      : {
        rule_id: ruleId, name: src.name, description: src.description, field: src.field, severity: src.severity,
        category: src.category, regulatory_tag: src.regulatory_tag, expression: src.expression, tests: src.tests || [], message: src.message,
      };
    const res = await act(() => api("/api/rules", { method: "POST", body }), (x) => `Draft v${x.version} ready — edit if needed, then submit for review`);
    if (res) {
      setVer(res.version);
      await reload();
      onChanged();
      if (openEdit) openEditor(res);
    }
    return res;
  };

  useEffect(() => {
    if (!editIntent || !data || data.rule_id !== ruleId || !canEdit) return;
    const vs = data.versions;
    const draft = vs.find((v) => v.status === "draft");
    if (editIntent === "draft" && draft) {
      openEditor(draft);
      onEditIntentHandled?.();
      return;
    }
    if (editIntent === "new-version") {
      const src = vs.find((v) => v.status === "canary" || v.status === "active" || v.status === "approved" || v.status === "shadow" || v.status === "in_review") || vs[vs.length - 1];
      onEditIntentHandled?.();
      if (src?.status === "draft") openEditor(src);
      else if (src && src.status !== "retired") newVersionFrom(src, { openEdit: false });
    }
  }, [editIntent, data, ruleId, canEdit]);

  if (!data || data.rule_id !== ruleId) return <Modal title="Loading…" size="lg" onClose={onClose} nav={nav}><Loading /></Modal>;
  const vs = data.versions;
  const r = vs.find((v) => v.version === ver) || vs.find((v) => v.status === "draft") || vs.find((v) => v.status === "in_review" || v.status === "canary") || vs.find((v) => v.status === "active") || vs[vs.length - 1];
  const stage = STAGES.find((s) => s.states.includes(r.status));
  const isAuthor = isRuleAuthor(persona, r);
  const isSubmitter = isRuleSubmitter(persona, r);
  const cannotApprove = isAuthor || isSubmitter;
  const nexts = (NEXT[r.status] || []).filter((t) => !(t === "approved" && cannotApprove));
  const primary = nexts.includes(primaryTransition(r.status)) ? primaryTransition(r.status) : (nexts.find((t) => t !== "draft") || nexts[0] || null);
  const sendBack = nexts.includes("draft") ? "draft" : null;

  const move = async (comment) => {
    if (to === "approved" && cannotApprove) {
      return null; // maker-checker: never call the API as author/submitter
    }
    const res = await act(() => api(`/api/rules/${ruleId}/${r.version}/transition`, { method: "POST", body: { to, comment: comment || `${human(to)} by ${persona.id}`, canary_pct: to === "canary" ? pct : undefined } }),
      (x) => (x.pending ? "Peer approval recorded. Compliance approval still required." : `${ruleId} v${r.version}: ${STATUS_LABEL[to] || human(to)}`));
    if (res) { reload(); onChanged(); }
    return res;
  };

  const doDelete = async (reason) => {
    const q = reason ? `?reason=${encodeURIComponent(reason)}` : "";
    const res = await act(() => api(`/api/rules/${ruleId}${q}`, { method: "DELETE" }), () => `${ruleId} deleted`);
    if (res) { onDeleted?.(); onClose(); }
    return res;
  };

  const startEdit = () => {
    if (r.status === "draft") openEditor(r);
    else if (r.status !== "retired") newVersionFrom(r, { openEdit: true });
  };

  const footer = (
    <>
      {canEdit && <button type="button" className="btn danger" onClick={() => setDeleting(true)}>Delete…</button>}
      {canEdit && r.status !== "retired" && (
        <button type="button" className="btn" onClick={startEdit}>{r.status === "draft" ? "Edit" : "Edit (new draft)"}</button>
      )}
      {!canEdit && <span className="lead faint">Switch to Dan · SME or Ana · Compliance to change this rule</span>}
      {canEdit && r.status === "in_review" && cannotApprove && (
        <span className="lead faint">Waiting for a peer — switch to Ana · Compliance to approve</span>
      )}
      {canEdit && sendBack && (
        <button type="button" className="btn" onClick={() => setTo(sendBack)}>{ACTION_LABEL[sendBack]}…</button>
      )}
      {canEdit && primary && primary !== sendBack && (
        <button type="button" className={`btn ${primary === "retired" ? "danger" : "primary"}`} onClick={() => setTo(primary)}>
          {ACTION_LABEL[primary]}…
        </button>
      )}
    </>
  );

  return (
    <Modal title={r.name || r.rule_id} sub={`${r.rule_id} · v${r.version}${r.regulatory_tag ? ` · ${r.regulatory_tag}` : ""}`} size="lg" onClose={onClose} nav={nav} footer={footer}>
      <div className="stack">
        <div className="callout" style={{ fontSize: ".9rem" }}>
          <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
            <b>{STATUS_LABEL[r.status] || human(r.status)}{r.status === "canary" ? ` (${r.canary_pct}%)` : ""}</b>
            <span className="row" style={{ gap: 6 }}>
              <span className="chip">Author {r.author}</span>
              {r.status === "in_review" && cannotApprove && <span className="chip">You authored / submitted this</span>}
              {r.status === "in_review" && !cannotApprove && canEdit && <span className="chip">Your review needed</span>}
            </span>
          </div>
          <p style={{ margin: "8px 0 0", fontSize: ".86rem" }}>
            {r.status === "in_review" && cannotApprove
              ? "Submitted. Switch to Ana · Compliance (or another SME) in the rail to approve — the same user cannot author and approve."
              : NEXT_HELP[r.status]}
          </p>
        </div>

        <div className="lifecycle">
          {STAGES.map((s) => (
            <div key={s.id} className={`st ${stage?.id === s.id ? "on" : ""}`}>
              <b>{s.label}</b>
              <span>{s.desc}</span>
            </div>
          ))}
        </div>

        {vs.length > 1 && (
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <span className="eyebrow" style={{ marginRight: 4 }}>Versions</span>
            {vs.map((v) => (
              <button key={v.version} type="button" className={`btn sm ${v.version === r.version ? "primary" : ""}`} onClick={() => setVer(v.version)}>
                v{v.version} · {STATUS_LABEL[v.status]?.split("—")[0]?.trim() || human(v.status)}
              </button>
            ))}
          </div>
        )}

        <p className="muted" style={{ margin: 0 }}>{r.summary || r.description}</p>
        <dl className="kv">
          <dt>Field</dt><dd className="mono">{r.field || "—"}</dd>
          <dt>Severity</dt><dd><span className={`pill ${r.severity === "FAIL" ? "fail" : "warn"}`}>{r.severity}</span></dd>
          <dt>Category</dt><dd>{r.category}</dd>
          <dt>Author</dt><dd>{r.author}</dd>
        </dl>

        {r.tree ? (
          <p className="faint" style={{ fontSize: ".84rem", margin: 0 }}>Guided rule — use <b>Edit</b> to change it (creates a new draft if this version is already past Draft).</p>
        ) : (
          <pre className="code">{JSON.stringify(r.expression, null, 2)}</pre>
        )}

        <span className="eyebrow">Sample checks ({(r.tests || []).length})</span>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          {(r.tests || []).map((t, i) => (
            <span key={i} className={`pill ${t.expect ? "pass" : "fail"}`}>case {i + 1}: expect {t.expect ? "pass" : "fail"}</span>
          ))}
        </div>

        {r.history?.length > 0 && (
          <div className="timeline">
            {r.history.slice().reverse().map((h, i) => (
              <div key={i}>
                <b>{STATUS_LABEL[h.to]?.split("—")[0]?.trim() || human(h.to)}</b> · {h.actor}
                {h.comment ? ` · ${h.comment}` : ""} · <span className="faint">{ago(h.ts)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {to && (
        <ReasonModal title={`${ACTION_LABEL[to]}: ${r.rule_id} v${r.version}`} help={TRANSITION_HELP[to]} label="Comment (audited)" confirmLabel={ACTION_LABEL[to]}
          danger={to === "retired"} required={["draft", "retired"].includes(to)} onClose={() => setTo(null)} onSubmit={move}
          presets={to === "approved" ? ["Checks look right; matches the procedure"] : to === "draft" ? ["Please fix the sample checks"] : []}>
          {to === "canary" && (
            <Field id="cn-pct" label="Share of loans on the new version">
              <select id="cn-pct" className="input" value={pct} onChange={(e) => setPct(+e.target.value)}>
                {[5, 10, 25, 50].map((x) => <option key={x} value={x}>{x}%</option>)}
              </select>
            </Field>
          )}
          {(to === "shadow" || to === "canary" || to === "active" || to === "retired") && (
            <p className="faint" style={{ fontSize: ".82rem" }}>This updates every live feed’s signed config.</p>
          )}
        </ReasonModal>
      )}

      {deleting && (
        <ReasonModal title={`Delete ${r.rule_id}?`} help="Removes every version of this rule. If it was live, feed configs are republished." label="Reason (audited)"
          confirmLabel="Delete rule" danger required onClose={() => setDeleting(false)} onSubmit={doDelete}
          presets={["Created by mistake", "Superseded", "No longer needed"]} />
      )}

      {editing && (editSnapshot || r.status === "draft") && (
        <EditRuleModal
          rule={editSnapshot || r}
          onClose={() => { setEditing(false); setEditSnapshot(null); }}
          onSaved={() => { setEditing(false); setEditSnapshot(null); reload(); onChanged(); }}
        />
      )}
    </Modal>
  );
}

function queueFromHash() {
  const raw = (window.location.hash || "").replace(/^#/, "");
  const qs = raw.includes("?") ? raw.slice(raw.indexOf("?") + 1) : "";
  return new URLSearchParams(qs).get("queue") || "";
}

export default function Rules({ persona }) {
  const [queue, setQueue] = useState(() => queueFromHash()); // "" | awaiting_review | my_drafts
  const path = queue === "awaiting_review" || queue === "my_drafts" ? `/api/rules?queue=${queue}` : "/api/rules";
  const { data, error, reload } = useApi(path, [queue, persona.id]);
  const [sel, setSel] = useState(null);
  const [editIntent, setEditIntent] = useState(null);
  const [authoring, setAuthoring] = useState(false);
  const [deleteId, setDeleteId] = useState(null);
  const act = useAction();
  const { data: ntfData, reload: reloadNtf } = useApi("/api/notifications", [persona.id], { poll: 20000 });

  useEffect(() => {
    const sync = () => setQueue(queueFromHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  if (!data) return <Loading error={error} />;
  const idx = data.rules.findIndex((r) => r.rule_id === sel);
  const canAuthor = canCap(persona, "authorRules");
  const canEdit = canCap(persona, "editRules");

  const setQueueNav = (q) => {
    setQueue(q);
    window.location.hash = q ? `rules?queue=${q}` : "rules";
  };

  const closeRule = () => { setSel(null); setEditIntent(null); reloadNtf(); };

  const deleteRule = async (ruleId, reason) => {
    const q = reason ? `?reason=${encodeURIComponent(reason)}` : "";
    const res = await act(() => api(`/api/rules/${ruleId}${q}`, { method: "DELETE" }), () => `${ruleId} deleted`);
    if (res) {
      setDeleteId(null);
      if (sel === ruleId) setSel(null);
      reload();
    }
    return res;
  };

  const unread = ntfData?.notifications?.filter((n) => !n.read_at).slice(0, 5) || [];
  const markAllRead = async () => {
    await api("/api/notifications/read-all", { method: "POST" });
    reloadNtf();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Pillar 3.A · rules</span>
          <h1>Rule Engine</h1>
          <p className="sub">New rule → submit → peer approves → live. Click a row to open. Same person cannot author and approve.</p>
          {!canEdit && (
            <p className="faint" style={{ fontSize: ".84rem", marginTop: 6 }}>
              Switch to <b>Dan · SME</b> or <b>Ana · Compliance</b> to add or move rules.
            </p>
          )}
        </div>
        {canAuthor && <button type="button" className="btn primary" onClick={() => setAuthoring(true)}>New rule</button>}
      </div>

      {unread.length > 0 && (
        <div className="callout" style={{ marginBottom: 12, fontSize: ".88rem" }}>
          <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
            <b>Notifications</b>
            <button type="button" className="btn sm" onClick={markAllRead}>Mark all read</button>
          </div>
          <div className="stack" style={{ gap: 6, marginTop: 8 }}>
            {unread.map((n) => (
              <button key={n.id} type="button" className="btn" style={{ textAlign: "left", height: "auto", padding: "8px 10px" }}
                onClick={async () => {
                  await api(`/api/notifications/${n.id}/read`, { method: "POST" });
                  reloadNtf();
                  if (n.entity_id) { setQueueNav("awaiting_review"); setSel(n.entity_id); }
                }}>
                <b>{n.title}</b>
                <div className="faint" style={{ fontSize: ".8rem", marginTop: 2 }}>{n.body}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {authoring && canAuthor && (
        <AuthorModal
          persona={persona}
          onClose={() => setAuthoring(false)}
          onCreated={(id) => { reload(); setAuthoring(false); setEditIntent(null); setSel(id); }}
        />
      )}

      <div className="row" style={{ gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          ["", "All rules"],
          ["awaiting_review", "Needs my review"],
          ["my_drafts", "My drafts"],
        ].map(([id, label]) => (
          <button key={id || "all"} type="button" className={`btn sm ${queue === id ? "primary" : ""}`} onClick={() => setQueueNav(id)}>{label}</button>
        ))}
      </div>

      <Panel
        pad={false}
        title={`${data.rules.length} rules${queue === "awaiting_review" ? " awaiting your review" : queue === "my_drafts" ? " you drafted" : ""}`}
        sub="Open a row for the next step. Delete removes the rule entirely."
      >
        {!data.rules.length ? (
          <div className="empty stack" style={{ gap: 12, padding: 24, alignItems: "flex-start" }}>
            <span>No rules yet.</span>
            {canAuthor && <button type="button" className="btn primary" onClick={() => setAuthoring(true)}>New rule</button>}
          </div>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Rule</th><th>Field</th><th>Severity</th><th>Tag</th><th>Versions</th>
                  <th className="r">Exceptions</th>
                  {canEdit && <th></th>}
                </tr>
              </thead>
              <tbody>
                {data.rules.map((r) => (
                  <tr key={r.rule_id} className={`click ${sel === r.rule_id ? "sel" : ""}`} onClick={() => { setEditIntent(null); setSel(r.rule_id); }}>
                    <td><span className="mono">{r.rule_id}</span> {r.name}</td>
                    <td className="mono">{r.field}</td>
                    <td><span className={`pill ${r.severity === "FAIL" ? "fail" : "warn"}`}>{r.severity}</span></td>
                    <td>{r.regulatory_tag || <span className="faint">—</span>}</td>
                    <td><span className="row" style={{ gap: 4 }}>{r.versions.map(([v, s]) => <Status key={v} s={s} />)}</span></td>
                    <td className="r num">{fmt(r.exception_count)}</td>
                    {canEdit && (
                      <td onClick={(e) => e.stopPropagation()}>
                        <button type="button" className="btn sm danger" onClick={() => setDeleteId(r.rule_id)}>Delete</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {deleteId && (
        <ReasonModal title={`Delete ${deleteId}?`} help="Removes every version. Live rules trigger a config republish." label="Reason (audited)"
          confirmLabel="Delete rule" danger required onClose={() => setDeleteId(null)}
          onSubmit={(reason) => deleteRule(deleteId, reason)}
          presets={["Created by mistake", "Superseded", "No longer needed"]} />
      )}

      {sel && (
        <RuleModal
          ruleId={sel}
          persona={persona}
          onChanged={reload}
          onClose={closeRule}
          onDeleted={reload}
          editIntent={editIntent}
          onEditIntentHandled={() => setEditIntent(null)}
          nav={{
            label: idx >= 0 ? `${idx + 1} of ${data.rules.length}` : "",
            onPrev: idx > 0 ? () => { setEditIntent(null); setSel(data.rules[idx - 1].rule_id); } : null,
            onNext: idx >= 0 && idx < data.rules.length - 1 ? () => { setEditIntent(null); setSel(data.rules[idx + 1].rule_id); } : null,
          }}
        />
      )}
    </>
  );
}
