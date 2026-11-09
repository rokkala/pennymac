import React from "react";
import { Field } from "./ui.jsx";

const blankLeaf = () => ({ shape: "required", field: "loan_number" });
const SHAPE_OPTS = [
  { id: "required", label: "Must be filled" },
  { id: "between", label: "Between two numbers" },
  { id: "compare_num", label: "Compare to a number" },
  { id: "compare_field", label: "Compare to another field" },
  { id: "compare_scaled", label: "Compare to field × factor (e.g. UPB ≤ orig × 1.05)" },
  { id: "one_of", label: "Must be one of" },
  { id: "not_in", label: "Must not be one of" },
  { id: "equals", label: "Equals a value" },
  { id: "not_equals", label: "Does not equal" },
  { id: "digits", label: "Exactly N digits" },
  { id: "length_between", label: "Text length between" },
  { id: "pattern", label: "Matches a pattern (format)" },
  { id: "in_codes", label: "Must be a valid code for the field" },
  { id: "is_date", label: "Must be a valid date" },
  { id: "is_true", label: "Flag must be yes / true" },
  { id: "is_false", label: "Flag must be no / false" },
  { id: "date_order", label: "Date before / after another" },
  { id: "days_between", label: "Days between two dates in a range" },
  { id: "months_between", label: "Months between two dates in a range" },
  { id: "pmt_within", label: "Payment within % of amortized P&I" },
  { id: "blank_or", label: "Blank is OK, otherwise inner check" },
  { id: "if_flag_then", label: "If flag is yes, then check" },
  { id: "if_then", label: "If … then …" },
  { id: "all_present", label: "All fields filled" },
];
const PATTERN_PRESETS = [
  { id: "loan_number", label: "Loan number 6–20", pattern: "[A-Z0-9-]{6,20}", field: "loan_number", ok: "LN-100001", bad: "AB" },
  { id: "ssn", label: "SSN", pattern: "(?!000|666|9)\\d{3}(?!00)\\d{2}(?!0000)\\d{4}", field: "borrower_ssn", ok: "123456789", bad: "000121234" },
  { id: "zip", label: "ZIP 5 or 9", pattern: "\\d{5}(\\d{4})?", field: "property_zip", ok: "75024", bad: "750" },
  { id: "phone", label: "10-digit phone", pattern: "\\d{10}", field: "borrower_home_phone", ok: "2145550100", bad: "555" },
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
          else if (id === "if_flag_then") onChange({ shape: "if_flag_then", flag: "escrow_flag", then: { shape: "compare_num", field: "escrow_balance", op: ">=", number: 0 } });
          else if (id === "blank_or") onChange({ shape: "blank_or", inner: { shape: "between", field: "borrower_fico", min: 300, max: 850 } });
          else if (id === "all_present") onChange({ shape: "all_present", fields: ["loan_number"] });
          else if (id === "date_order") onChange({ shape: "date_order", field_a: "note_date", order: "before", field_b: "maturity_date" });
          else if (id === "days_between") onChange({ shape: "days_between", field_a: "note_date", field_b: "first_payment_date", min: 1, max: 125 });
          else if (id === "months_between") onChange({ shape: "months_between", field_a: "note_date", field_b: "maturity_date", min: 60, max: 480 });
          else if (id === "between") onChange({ shape: "between", field: "interest_rate", min: 0.5, max: 15 });
          else if (id === "compare_num") onChange({ shape: "compare_num", field: "borrower_fico", op: ">=", number: 580 });
          else if (id === "compare_scaled") onChange({ shape: "compare_scaled", field: "current_principal_balance", op: "<=", other: "original_loan_amount", factor: 1.05 });
          else if (id === "one_of") onChange({ shape: "one_of", field: "occupancy_type", values: ["P", "S", "I"] });
          else if (id === "not_in") onChange({ shape: "not_in", field: "loan_type", values: ["XX"] });
          else if (id === "pattern") onChange({ shape: "pattern", field: "loan_number", pattern: "[A-Z0-9-]{6,20}", ok_example: "LN-100001", bad_example: "AB" });
          else if (id === "in_codes") onChange({ shape: "in_codes", field: "property_state" });
          else if (id === "length_between") onChange({ shape: "length_between", field: "loan_number", min: 6, max: 20 });
          else if (id === "is_false") onChange({ shape: "is_false", field: "fraud_alert_flag" });
          else if (id === "is_true") onChange({ shape: "is_true", field: "escrow_flag" });
          else if (id === "is_date") onChange({ shape: "is_date", field: "note_date" });
          else if (id === "pmt_within") onChange({
            shape: "pmt_within", payment_field: "principal_interest_payment", rate_field: "interest_rate",
            term_field: "original_term_months", amount_field: "original_loan_amount", pct: 0.02,
            skip_when: { shape: "equals", field: "amortization_type", value: "ARM" },
          });
          else if (id === "not_equals") onChange({ shape: "not_equals", field: "ofac_check_status", value: "H" });
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
      ) : shape === "if_flag_then" ? (
        <>
          <FieldSelect id={`flg-${depth}`} label="Flag field" fields={fields} value={node.flag} onChange={(flag) => set({ flag })} filter={(f) => f.dtype === "bool"} />
          <span className="eyebrow">Then require</span>
          <LeafEditor node={node.then || blankLeaf()} fields={fields} onChange={(then) => set({ then })} depth={depth + 1} />
        </>
      ) : shape === "blank_or" ? (
        <>
          <p className="faint" style={{ fontSize: ".82rem", margin: 0 }}>If the field is blank, the loan passes. Otherwise the check below must pass.</p>
          <LeafEditor node={node.inner || blankLeaf()} fields={fields} onChange={(inner) => set({ inner })} depth={depth + 1} />
        </>
      ) : shape === "pmt_within" ? (
        <div className="stack">
          <div className="grid g2">
            <FieldSelect id={`pay-${depth}`} label="Payment field" fields={fields} value={node.payment_field} onChange={(payment_field) => set({ payment_field })} filter={(f) => f.dtype === "decimal" || f.dtype === "int"} />
            <Field id={`pct-${depth}`} label="Tolerance (e.g. 0.02 = 2%)">
              <input id={`pct-${depth}`} className="input" type="number" step="0.01" value={node.pct ?? 0.02} onChange={(e) => set({ pct: +e.target.value })} />
            </Field>
          </div>
          <div className="grid g2">
            <FieldSelect id={`rt-${depth}`} label="Rate field" fields={fields} value={node.rate_field} onChange={(rate_field) => set({ rate_field })} />
            <FieldSelect id={`tm-${depth}`} label="Term field" fields={fields} value={node.term_field} onChange={(term_field) => set({ term_field })} />
            <FieldSelect id={`am-${depth}`} label="Amount field" fields={fields} value={node.amount_field} onChange={(amount_field) => set({ amount_field })} />
          </div>
          <span className="eyebrow">Skip when (optional)</span>
          <LeafEditor node={node.skip_when || { shape: "equals", field: "amortization_type", value: "ARM" }} fields={fields}
            onChange={(skip_when) => set({ skip_when })} depth={depth + 1} />
        </div>
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
      ) : shape === "days_between" || shape === "months_between" ? (
        <div className="stack">
          <div className="grid g2">
            <FieldSelect id={`dba-${depth}`} label="From date" fields={fields} value={node.field_a} onChange={(field_a) => set({ field_a })} filter={(f) => f.dtype === "date"} />
            <FieldSelect id={`dbb-${depth}`} label="To date" fields={fields} value={node.field_b} onChange={(field_b) => set({ field_b })} filter={(f) => f.dtype === "date"} />
          </div>
          <div className="grid g2">
            <Field id={`dbmin-${depth}`} label={shape === "months_between" ? "Minimum months" : "Minimum days"}>
              <input id={`dbmin-${depth}`} className="input" type="number" value={node.min ?? ""} onChange={(e) => set({ min: +e.target.value })} />
            </Field>
            <Field id={`dbmax-${depth}`} label={shape === "months_between" ? "Maximum months" : "Maximum days"}>
              <input id={`dbmax-${depth}`} className="input" type="number" value={node.max ?? ""} onChange={(e) => set({ max: +e.target.value })} />
            </Field>
          </div>
        </div>
      ) : (
        <>
          {!["date_order", "days_between", "months_between", "pmt_within", "if_flag_then", "blank_or", "if_then", "all_present"].includes(shape) && (
            <FieldSelect id={`f-${depth}`} label="Field" fields={fields} value={node.field}
              filter={
                shape === "in_codes" ? (f) => f.dtype === "code" && (f.codes || []).length
                  : shape === "is_true" || shape === "is_false" ? (f) => f.dtype === "bool"
                    : undefined
              }
              onChange={(field) => {
              const a = (fields || []).find((x) => x.name === field);
              const patch = { field };
              if ((shape === "one_of" || shape === "not_in") && a?.codes?.length) patch.values = [...a.codes];
              set(patch);
            }} />
          )}
          {shape === "compare_scaled" && (
            <div className="grid g2">
              <Field id={`csop-${depth}`} label="Operator">
                <select id={`csop-${depth}`} className="input" value={node.op || "<="} onChange={(e) => set({ op: e.target.value })}>
                  {["<=", ">=", "<", ">"].map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </Field>
              <FieldSelect id={`csoth-${depth}`} label="Other field" fields={fields} value={node.other} onChange={(other) => set({ other })} />
              <Field id={`csf-${depth}`} label="Factor (e.g. 1.05)">
                <input id={`csf-${depth}`} className="input" type="number" step="0.01" value={node.factor ?? 1} onChange={(e) => set({ factor: +e.target.value })} />
              </Field>
            </div>
          )}
          {shape === "length_between" && (
            <div className="grid g2">
              <Field id={`lmin-${depth}`} label="Min length"><input id={`lmin-${depth}`} className="input" type="number" value={node.min ?? ""} onChange={(e) => set({ min: +e.target.value })} /></Field>
              <Field id={`lmax-${depth}`} label="Max length"><input id={`lmax-${depth}`} className="input" type="number" value={node.max ?? ""} onChange={(e) => set({ max: +e.target.value })} /></Field>
            </div>
          )}
          {(shape === "not_in") && (
            <Field id={`nivals-${depth}`} label="Disallowed values" hint="Comma-separated">
              <input id={`nivals-${depth}`} className="input" value={(node.values || []).join(", ")}
                onChange={(e) => set({ values: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
            </Field>
          )}
          {shape === "not_equals" && (
            <Field id={`neq-${depth}`} label="Value">
              <input id={`neq-${depth}`} className="input" value={node.value ?? ""} onChange={(e) => set({ value: e.target.value })} />
            </Field>
          )}
          {shape === "pattern" && (
            <>
              <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                {PATTERN_PRESETS.map((p) => (
                  <button key={p.id} type="button" className="chip btnchip" onClick={() => set({
                    field: p.field, pattern: p.pattern, ok_example: p.ok, bad_example: p.bad,
                  })}>{p.label}</button>
                ))}
              </div>
              <Field id={`pat-${depth}`} label="Pattern (full match)" hint="Letters, numbers, and dashes for loan IDs: [A-Z0-9-]{6,20}">
                <input id={`pat-${depth}`} className="input mono" value={node.pattern || ""} onChange={(e) => set({ pattern: e.target.value })} />
              </Field>
              <div className="grid g2">
                <Field id={`ok-${depth}`} label="Example that should pass">
                  <input id={`ok-${depth}`} className="input mono" value={node.ok_example || ""} onChange={(e) => set({ ok_example: e.target.value })} />
                </Field>
                <Field id={`bad-${depth}`} label="Example that should fail">
                  <input id={`bad-${depth}`} className="input mono" value={node.bad_example || ""} onChange={(e) => set({ bad_example: e.target.value })} />
                </Field>
              </div>
            </>
          )}
          {shape === "in_codes" && (
            <p className="faint" style={{ fontSize: ".82rem", margin: 0 }}>
              Uses the SSE code list for this field{attr?.codes?.length ? `: ${attr.codes.slice(0, 12).join(", ")}${attr.codes.length > 12 ? "…" : ""}` : ""}.
            </p>
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

export { blankLeaf, ensureTree, LeafEditor, GroupEditor, FieldSelect, SHAPE_OPTS, PATTERN_PRESETS };
