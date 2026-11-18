/** Parse / build hash routes like `guide?step=mapping` (no leading #). */

export function parseHash(raw) {
  const s = String(raw || "").replace(/^#/, "");
  const q = s.indexOf("?");
  const id = q < 0 ? s : s.slice(0, q);
  const params = new URLSearchParams(q < 0 ? "" : s.slice(q + 1));
  return { id, params };
}

export function buildHash(id, params) {
  if (params == null || params === "") return id;
  if (typeof params === "string") return `${id}?${params.replace(/^\?/, "")}`;
  const qs = params instanceof URLSearchParams
    ? params.toString()
    : new URLSearchParams(params).toString();
  return qs ? `${id}?${qs}` : id;
}
