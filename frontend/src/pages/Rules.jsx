import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { canCap } from "../roles.js";
import { useApi, useAction, Panel, Status, Loading, ago, fmt, human, Modal, ReasonModal, Field } from "../ui.jsx";

const STAGES = [
  { id: "author", label: "Draft", desc: "Build the check with fields and options", states: ["draft"] },
  { id: "review", label: "Review", desc: "Peer sign-off; Compliance if regulatory", states: ["in_review", "approved"] },
  { id: "deploy", label: "Try safely", desc: "Run quietly or on a share of loans", states: ["shadow", "canary"] },
  { id: "monitor", label: "Live", desc: "On for all loans", states: ["active"] },
  { id: "retire", label: "Off", desc: "Stopped; history kept", states: ["retired"] },
];
const NEXT = { draft: ["in_review"], in_review: ["approved", "draft"], approved: ["shadow", "canary", "active"], shadow: ["canary", "active", "retired"], canary: ["active", "shadow", "retired"], active: ["retired"], rejected: ["draft"], retired: [] };
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
  draft: "Not submitted",
  in_review: "Waiting for a peer",
  approved: "Ready to try safely",
  shadow: "Running quietly",
  canary: "Trying on a slice",
  active: "Live on all loans",
  retired: "Off; history kept",
  rejected: "Sent back",
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
const blankLeaf = () => ({ shape: "required", field: "loan_number" });
const SHAPE_OPTS = [
  { id: "required", label: "Must be filled" },
  { id: "between", label: "Between two numbers" },
  { id: "compare_num", label: "Compare to a number" },
  { id: "compare_field", label: "Compare to another field" },
  { id: "one_of", label: "Must be one of" },
  { id: "equals", label: "Equals a value" },
  { id: "digits", label: "Exactly N digits" },
  { id: "date_order", label: "Date before / after another" },
  { id: "if_then", label: "If … then …" },
  { id: "all_present", label: "All fields filled" },
];

function FieldSelect({ id, label, fields, value, onChange, filter }) {
  const list = (fields || []).filter((f) => !filter || filter(f));
  return (
    <Field id={id} label={label}>
      <select id={id} className="input" value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a field…</option>
        {list.map((f) => (
          <option key={f.name} value={f.name}>{f.name} · {f.module} ({f.dtype})</option>
        ))}
      </select>
    </Field>
  );
}

function LeafEditor({ node, fields, onChange, depth = 0 }) {
  if (node?.op) {
    return <GroupEditor node={node} fields={fields} onChange={onChange} depth={depth} />;
  }
  const shape = node?.shape || "required";
  const set = (patch) => onChange({ ...node, ...patch });
  const attr = (fields || []).find((f) => f.name === node.field);
  return (
    <div className="stack" style={{ padding: "10px 12px", background: "var(--bg-elev, rgba(0,0,0,.03))", borderRadius: 8 }}>
      <Field id={`sh-${depth}`} label="Check type">
        <select id={`sh-${depth}`} className="input" value={shape} onChange={(e) => {
          const id = e.target.value;
          if (id === "if_then") onChange({ shape: "if_then", when: blankLeaf(), then: blankLeaf() });
          else if (id === "all_present") onChange({ shape: "all_present", fields: ["loan_number"] });
          else if (id === "date_order") onChange({ shape: "date_order", field_a: "note_date", order: "before", field_b: "maturity_date" });
          else if (id === "between") onChange({ shape: "between", field: "interest_rate", min: 0.5, max: 15 });
          else if (id === "compare_num") onChange({ shape: "compare_num", field: "borrower_fico", op: ">=", number: 580 });
          else if (id === "one_of") onChange({ shape: "one_of", field: "occupancy_type", values: ["P", "S", "I"] });
          else onChange({ shape: id, field: node.field || "loan_number" });
        }}>
          {SHAPE_OPTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </Field>
      {shape === "if_then" ? (
        <>
          <span className="eyebrow">When</span>
          <LeafEditor node={node.when || blankLeaf()} fields={fields} onChange={(when) => set({ when })} depth={depth + 1} />
          <span className="eyebrow">Then</span>
          <LeafEditor node={node.then || blankLeaf()} fields={fields} onChange={(then) => set({ then })} depth={depth + 1} />
        </>
      ) : shape === "all_present" ? (
        <Field id={`ap-${depth}`} label="Fields (comma-separated)">
          <input id={`ap-${depth}`} className="input mono" value={(node.fields || []).join(", ")}
            onChange={(e) => set({ fields: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
        </Field>
      ) : shape === "date_order" ? (
        <div className="grid g2">
          <FieldSelect id={`da-${depth}`} label="First date" fields={fields} value={node.field_a} onChange={(field_a) => set({ field_a })} filter={(f) => f.dtype === "date"} />
          <Field id={`ord-${depth}`} label="Order">
            <select id={`ord-${depth}`} className="input" value={node.order || "before"} onChange={(e) => set({ order: e.target.value })}>
              <option value="before">must be before</option>
              <option value="after">must be after</option>
            </select>
          </Field>
          <FieldSelect id={`db-${depth}`} label="Second date" fields={fields} value={node.field_b} onChange={(field_b) => set({ field_b })} filter={(f) => f.dtype === "date"} />
        </div>
      ) : (
        <>
          {shape !== "date_order" && (
            <FieldSelect id={`f-${depth}`} label="Field" fields={fields} value={node.field} onChange={(field) => {
              const a = (fields || []).find((x) => x.name === field);
              const patch = { field };
              if (shape === "one_of" && a?.codes?.length) patch.values = [...a.codes];
              set(patch);
            }} />
          )}
          {shape === "between" && (
            <div className="grid g2">
              <Field id={`mn-${depth}`} label="Minimum"><input id={`mn-${depth}`} className="input" type="number" value={node.min ?? ""} onChange={(e) => set({ min: +e.target.value })} /></Field>
              <Field id={`mx-${depth}`} label="Maximum"><input id={`mx-${depth}`} className="input" type="number" value={node.max ?? ""} onChange={(e) => set({ max: +e.target.value })} /></Field>
            </div>
          )}
          {shape === "compare_num" && (
            <div className="grid g2">
              <Field id={`op-${depth}`} label="Operator">
                <select id={`op-${depth}`} className="input" value={node.op || ">="} onChange={(e) => set({ op: e.target.value })}>
                  {[[">=", "at least"], ["<=", "at most"], [">", "greater than"], ["<", "less than"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </Field>
              <Field id={`num-${depth}`} label="Number"><input id={`num-${depth}`} className="input" type="number" value={node.number ?? ""} onChange={(e) => set({ number: +e.target.value })} /></Field>
            </div>
          )}
          {shape === "compare_field" && (
            <div className="grid g2">
              <Field id={`op2-${depth}`} label="Operator">
                <select id={`op2-${depth}`} className="input" value={node.op || "<="} onChange={(e) => set({ op: e.target.value })}>
                  {["<=", ">=", "<", ">", "==", "!="].map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </Field>
              <FieldSelect id={`oth-${depth}`} label="Other field" fields={fields} value={node.other} onChange={(other) => set({ other })} />
            </div>
          )}
          {shape === "one_of" && (
            <Field id={`vals-${depth}`} label="Allowed values" hint={attr?.codes?.length ? `Codes: ${attr.codes.join(", ")}` : "Comma-separated"}>
              <input id={`vals-${depth}`} className="input" value={(node.values || []).join(", ")}
                onChange={(e) => set({ values: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
            </Field>
          )}
          {shape === "equals" && (
            <Field id={`eq-${depth}`} label="Value">
              {attr?.codes?.length ? (
                <select id={`eq-${depth}`} className="input" value={node.value || ""} onChange={(e) => set({ value: e.target.value })}>
                  <option value="">Choose…</option>
                  {attr.codes.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input id={`eq-${depth}`} className="input" value={node.value ?? ""} onChange={(e) => set({ value: e.target.value })} />
              )}
            </Field>
          )}
          {shape === "digits" && (
            <Field id={`n-${depth}`} label="Number of digits">
              <input id={`n-${depth}`} className="input" type="number" min={1} value={node.n ?? 9} onChange={(e) => set({ n: +e.target.value })} />
            </Field>
          )}
        </>
      )}
    </div>
  );
}

function GroupEditor({ node, fields, onChange, depth = 0 }) {
  const kids = node.children || [];
  const setKid = (i, child) => onChange({ ...node, children: kids.map((c, j) => (j === i ? child : c)) });
  const add = () => onChange({ ...node, children: [...kids, blankLeaf()] });
  const remove = (i) => onChange({ ...node, children: kids.filter((_, j) => j !== i) });
  return (
    <div className="stack">
      <Field id={`grp-${depth}`} label="Combine checks">
        <select id={`grp-${depth}`} className="input" value={node.op} onChange={(e) => onChange({ ...node, op: e.target.value })}>
          <option value="and">All must pass</option>
          <option value="or">Any may pass</option>
          <option value="xor">Exactly one must pass</option>
        </select>
      </Field>
      {kids.map((c, i) => (
        <div key={i} className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="eyebrow">Check {i + 1}</span>
            {kids.length > 1 && <button type="button" className="btn sm" onClick={() => remove(i)}>Remove</button>}
          </div>
          <LeafEditor node={c} fields={fields} onChange={(n) => setKid(i, n)} depth={depth + 1} />
        </div>
      ))}
      {depth < 2 && <button type="button" className="btn" onClick={add}>Add check</button>}
    </div>
  );
}

function ensureTree(tree) {
  if (!tree) return { op: "and", children: [blankLeaf()] };
  if (tree.op || tree.shape) return tree;
  return { op: "and", children: [blankLeaf()] };
}

function AuthorModal({ persona, onCreated, onClose }) {
  const { data: fieldData } = useApi("/api/rules/fields");
  const { data: tplData } = useApi("/api/rules/templates");
  const [tab, setTab] = useState("templates"); // templates | build | ai
  const [tree, setTree] = useState(() => ensureTree(null));
  const [name, setName] = useState("");
  const [severity, setSeverity] = useState("FAIL");
  const [tag, setTag] = useState("");
  const [preview, setPreview] = useState(null);
  const [text, setText] = useState("Interest rate must be between 0.5 and 15");
  const [err, setErr] = useState("");
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

  const save = async () => {
    const res = preview || await compose();
    if (!res?.draft) { setErr(res?.problems?.join(" ") || "Fix the rule before saving."); return; }
    if (res.problems?.length) { setErr(res.problems.join(" ")); return; }
    const body = {
      name: name || res.draft.name || res.summary,
      description: res.summary,
      tree,
      severity,
      regulatory_tag: tag || null,
    };
    const r = await act(() => api("/api/rules", { method: "POST", body }), (x) => `Draft ${x.rule_id} created`);
    if (r) onCreated(r.rule_id);
  };

  const fromAi = async () => {
    setErr("");
    const res = await act(() => api("/api/rules/author", { method: "POST", body: { text } }));
    if (res?.draft?.tree) {
      setTree(ensureTree(res.draft.tree));
      setName(res.draft.name || text);
      setTab("build");
      setPreview({ draft: res.draft, test_results: res.test_results, problems: res.problems, summary: res.draft.summary || res.draft.description });
    } else setErr((res?.problems || ["Could not turn that into a guided rule."]).join(" "));
  };

  return (
    <Modal title="Author a rule" sub="Pick a template or build with fields and options. No JSON required. Preview sample checks, then save a draft." size="xl" onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn" onClick={() => compose()}>Preview checks</button>
        {canSave && <button className="btn primary" onClick={save}>Save as draft</button>}
      </>}>
      <div className="stack">
        {!canSave && <div className="callout t4" style={{ fontSize: ".84rem" }}>You can build a preview. Switch to <b>Dan · SME</b> or <b>Ana · Compliance</b> to save.</div>}
        <div className="row" style={{ gap: 6 }}>
          {[["templates", "Templates"], ["build", "Build"], ["ai", "AI assist"]].map(([id, label]) => (
            <button key={id} type="button" className={`btn sm ${tab === id ? "primary" : ""}`} onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        {tab === "templates" && (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>Start from a common mortgage check, then adjust on the Build tab.</p>
            <div className="grid g2">
              {(tplData?.templates || []).map((t) => (
                <button key={t.id} type="button" className="btn" style={{ textAlign: "left", height: "auto", padding: "12px 14px" }}
                  onClick={() => { setTree(ensureTree(t.tree)); setName(t.name); setTab("build"); setPreview(null); }}>
                  <b>{t.name}</b>
                  <div className="faint" style={{ fontSize: ".82rem", marginTop: 4 }}>{t.description}</div>
                </button>
              ))}
            </div>
          </div>
        )}
        {tab === "ai" && (
          <div className="stack">
            <Field id="ai-text" label="Describe the rule (optional shortcut)">
              <textarea id="ai-text" className="input" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            <button type="button" className="btn primary" disabled={!text.trim()} onClick={fromAi}>Fill the builder from this text</button>
            <p className="faint" style={{ fontSize: ".82rem", margin: 0 }}>Always review the Build tab before saving — AI can pick the wrong field.</p>
          </div>
        )}
        {tab === "build" && (
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
        {err && <div className="callout t5" style={{ fontSize: ".84rem" }}>{err}</div>}
        {preview?.draft && (
          <div className="stack">
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
          </div>
        )}
        {preview?.problems?.length > 0 && <div className="callout t4">{preview.problems.join(" ")}</div>}
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
    }), "Draft updated");
    setBusy(false);
    if (r) onSaved(r);
  };

  return (
    <Modal title={`Edit draft ${rule.rule_id} v${rule.version}`} sub="Change the guided checks. Live rules need a new version." size="xl" onClose={onClose} busy={busy}
      footer={<>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn" disabled={busy} onClick={compose}>Preview</button>
        <button className="btn primary" disabled={busy || !name.trim()} onClick={save}>{busy ? "Saving…" : "Save draft"}</button>
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

function RuleModal({ ruleId, persona, onChanged, onClose, nav }) {
  const { data, reload } = useApi(`/api/rules/${ruleId}`, [ruleId]);
  const [ver, setVer] = useState(null);
  const [to, setTo] = useState(null);
  const [pct, setPct] = useState(10);
  const [editing, setEditing] = useState(false);
  const act = useAction();
  if (!data || data.rule_id !== ruleId) return <Modal title="Loading…" size="lg" onClose={onClose} nav={nav}><Loading /></Modal>;
  const vs = data.versions;
  const r = vs.find((v) => v.version === ver) || vs.find((v) => v.status === "canary" || v.status === "in_review" || v.status === "draft") || vs.find((v) => v.status === "active") || vs[vs.length - 1];
  const stage = STAGES.find((s) => s.states.includes(r.status));
  const canEdit = canCap(persona, "editRules");
  const move = async (comment) => {
    const res = await act(() => api(`/api/rules/${ruleId}/${r.version}/transition`, { method: "POST", body: { to, comment: comment || `${human(to)} by ${persona.id}`, canary_pct: to === "canary" ? pct : undefined } }),
      (x) => (x.pending ? "Peer approval recorded. Compliance approval still required." : `${ruleId} v${r.version}: ${STATUS_LABEL[to] || human(to)}`));
    if (res) { reload(); onChanged(); }
    return res;
  };
  const newVersion = async () => {
    const body = r.tree
      ? { rule_id: ruleId, name: r.name, description: r.description, tree: r.tree, severity: r.severity, category: r.category, regulatory_tag: r.regulatory_tag }
      : {
        rule_id: ruleId, name: r.name, description: r.description, field: r.field, severity: r.severity,
        category: r.category, regulatory_tag: r.regulatory_tag, expression: r.expression, tests: r.tests || [], message: r.message,
      };
    const res = await act(() => api("/api/rules", { method: "POST", body }), (x) => `Draft v${x.version} created from v${r.version}`);
    if (res) { setVer(res.version); reload(); onChanged(); }
  };
  return (
    <Modal title={`${r.rule_id} · ${r.name}`} sub={`v${r.version} · ${STATUS_LABEL[r.status] || human(r.status)} · owner ${r.owner}${r.regulatory_tag ? ` · ${r.regulatory_tag}` : ""}`} size="lg" onClose={onClose} nav={nav}
      footer={<>
        {canEdit && r.status === "draft" && <button className="btn" onClick={() => setEditing(true)}>Edit draft…</button>}
        {canEdit && r.status !== "draft" && r.status !== "retired" && <button className="btn" onClick={newVersion}>Edit as new version…</button>}
        {(NEXT[r.status] || []).length && canEdit ? <><span className="lead faint">{STATUS_LABEL[r.status] || human(r.status)}{r.status === "canary" ? ` (${r.canary_pct}%)` : ""}</span>
          {(NEXT[r.status] || []).map((t) => <button key={t} className={`btn ${t === "active" || t === "approved" ? "primary" : t === "retired" ? "danger" : ""}`} onClick={() => setTo(t)}>{ACTION_LABEL[t]}…</button>)}</>
          : !canEdit ? <span className="lead faint">Switch to Dan · SME or Ana · Compliance to edit or move this rule</span> : null}
      </>}>
      <div className="stack">
        <div className="lifecycle">{STAGES.map((s) => <div key={s.id} className={`st ${stage?.id === s.id ? "on" : ""}`}><b>{s.label}</b><span>{s.desc}</span></div>)}</div>
        <div className="row">{vs.map((v) => <button key={v.version} className={`btn sm ${v.version === r.version ? "primary" : ""}`} onClick={() => setVer(v.version)}>v{v.version} · {STATUS_LABEL[v.status] || human(v.status)}{v.status === "canary" ? ` ${v.canary_pct}%` : ""}</button>)}</div>
        <p className="muted">{r.summary || r.description}</p>
        <dl className="kv"><dt>Field</dt><dd className="mono">{r.field}</dd><dt>Severity</dt><dd><span className={`pill ${r.severity === "FAIL" ? "fail" : "warn"}`}>{r.severity}</span></dd>
          <dt>Category</dt><dd>{r.category}</dd><dt>Author</dt><dd>{r.author}</dd></dl>
        {r.tree ? (
          <div className="callout" style={{ fontSize: ".88rem" }}>Guided rule — edit via the form. Runtime expression is kept for Glue.</div>
        ) : (
          <pre className="code">{JSON.stringify(r.expression, null, 2)}</pre>
        )}
        <span className="eyebrow">Sample checks ({(r.tests || []).length})</span>
        <div className="row">{(r.tests || []).map((t, i) => <span key={i} className={`pill ${t.expect ? "pass" : "fail"}`}>case {i + 1}: expect {t.expect ? "pass" : "fail"}</span>)}</div>
        {r.history?.length > 0 && <div className="timeline">{r.history.slice().reverse().map((h, i) => <div key={i}><b>{STATUS_LABEL[h.to] || human(h.to)}</b> · {h.actor}{h.comment ? ` · ${h.comment}` : ""} · <span className="faint">{ago(h.ts)}</span></div>)}</div>}
      </div>
      {to && <ReasonModal title={`${ACTION_LABEL[to]}: ${r.rule_id} v${r.version}`} help={TRANSITION_HELP[to]} label="Comment (audited)" confirmLabel={ACTION_LABEL[to]}
        danger={to === "retired"} required={["draft", "retired"].includes(to)} onClose={() => setTo(null)} onSubmit={move}
        presets={to === "approved" ? ["Checks look right; matches the procedure"] : to === "draft" ? ["Please fix the sample checks"] : []}>
        {to === "canary" && <Field id="cn-pct" label="Share of loans on the new version"><select id="cn-pct" className="input" value={pct} onChange={(e) => setPct(+e.target.value)}>
          {[5, 10, 25, 50].map((x) => <option key={x} value={x}>{x}%</option>)}</select></Field>}
        {(to === "shadow" || to === "canary" || to === "active" || to === "retired") && (
          <p className="faint" style={{ fontSize: ".82rem" }}>This updates every live feed’s signed config.</p>
        )}
      </ReasonModal>}
      {editing && <EditRuleModal rule={r} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); reload(); onChanged(); }} />}
    </Modal>
  );
}

export default function Rules({ persona }) {
  const { data, error, reload } = useApi("/api/rules");
  const [sel, setSel] = useState(null);
  const [authoring, setAuthoring] = useState(false);
  if (!data) return <Loading error={error} />;
  const idx = data.rules.findIndex((r) => r.rule_id === sel);
  const canAuthor = canCap(persona, "authorRules");
  const canEdit = canCap(persona, "editRules");
  return (
    <>
      <div className="page-head"><div><span className="eyebrow">Pillar 3.A · rules</span><h1>Rule Engine</h1>
        <p className="sub">Build checks with fields and options — templates, a guided form, or optional AI assist. Peers review; try quietly or on a slice before going live.</p>
        {!canEdit && <p className="faint" style={{ fontSize: ".84rem", marginTop: 6 }}>Signed in without SME/Compliance — switch to <b>Dan · SME</b> or <b>Ana · Compliance</b> in the rail to author or move rules.</p>}</div>
        {canAuthor && <button className="btn primary" onClick={() => setAuthoring(true)}>Author a rule</button>}</div>
      {authoring && canAuthor && <AuthorModal persona={persona} onClose={() => setAuthoring(false)} onCreated={(id) => { reload(); setAuthoring(false); setSel(id); }} />}
      <Panel pad={false} title={`${data.rules.length} rules`} sub="Open a rule to edit a draft, create a new version, or move it through review → try safely → live.">
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Rule</th><th>Field</th><th>Severity</th><th>Tag</th><th>Versions</th><th className="r">Exceptions</th></tr></thead>
            <tbody>{data.rules.map((r) => (
              <tr key={r.rule_id} className={`click ${sel === r.rule_id ? "sel" : ""}`} onClick={() => setSel(r.rule_id)}>
                <td><span className="mono">{r.rule_id}</span> {r.name}</td><td className="mono">{r.field}</td>
                <td><span className={`pill ${r.severity === "FAIL" ? "fail" : "warn"}`}>{r.severity}</span></td><td>{r.regulatory_tag || <span className="faint">—</span>}</td>
                <td><span className="row" style={{ gap: 4 }}>{r.versions.map(([v, s]) => <Status key={v} s={s} />)}</span></td>
                <td className="r num">{fmt(r.exception_count)}</td>
              </tr>))}</tbody>
          </table></div>
      </Panel>
      {sel && <RuleModal ruleId={sel} persona={persona} onChanged={reload} onClose={() => setSel(null)}
        nav={{ label: idx >= 0 ? `${idx + 1} of ${data.rules.length}` : "", onPrev: idx > 0 ? () => setSel(data.rules[idx - 1].rule_id) : null,
          onNext: idx >= 0 && idx < data.rules.length - 1 ? () => setSel(data.rules[idx + 1].rule_id) : null }} />}
    </>
  );
}
