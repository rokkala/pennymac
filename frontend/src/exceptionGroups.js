/** Group open exceptions for the Loans-to-fix desk. */

export const PAGE_SIZE = 200;

export function loadDay(iso) {
  return (iso || "").slice(0, 10) || "—";
}

/** One section per filename (+ vendor + load day). Deep-link uses newest batch_id. */
export function groupExceptions(items) {
  const map = new Map();
  for (const e of items) {
    const day = loadDay(e.loaded_at || e.created_at);
    const filename = e.filename || e.batch_id || "Unknown file";
    const key = `${e.vendor_id || ""}|${filename}|${day}`;
    const ts = e.loaded_at || e.created_at || "";
    if (!map.has(key)) {
      map.set(key, {
        key,
        vendor_id: e.vendor_id,
        vendor_name: e.vendor_name || "Unknown vendor",
        batch_id: e.batch_id,
        filename,
        loaded_on: day,
        _ts: ts,
        items: [],
      });
    }
    const g = map.get(key);
    g.items.push(e);
    if (e.batch_id && ts >= (g._ts || "")) {
      g.batch_id = e.batch_id;
      g._ts = ts;
    }
  }
  return [...map.values()].map(({ _ts, ...g }) => g);
}

/** Apply #exceptions?batch_id=&loaded_on=&vendor_id= into desk filters. */
export function exceptionFiltersFromSearch(params) {
  const p = params instanceof URLSearchParams ? params : new URLSearchParams(params || "");
  return {
    batch_id: p.get("batch_id") || "",
    loaded_on: p.get("loaded_on") || "",
    vendor_id: p.get("vendor_id") || "",
  };
}

/** Unfiltered desk: one group per load from /api/exceptions/loads (counts, no loan rows). */
export function groupsFromLoads(loads = []) {
  return loads.map((L) => ({
    key: `load|${L.batch_id || L.filename}|${L.loaded_on || ""}`,
    vendor_id: L.vendor_id,
    vendor_name: L.vendor_name || "Unknown vendor",
    batch_id: L.batch_id,
    filename: L.filename || L.batch_id || "Unknown file",
    loaded_on: L.loaded_on || "—",
    open_count: L.open_count ?? 0,
    items: null,
  }));
}

/** Monitor deep-link / file filter: show every open loan for that batch (not one tier). */
export function fileScopedAllOpen({ batchId, tab } = {}) {
  if (!batchId) return false;
  return ["open", "T2", "T3", "T4"].includes(tab);
}

/** Tier query for /api/exceptions/loads browse counts (empty = all open for status). */
export function tierForLoads(tab) {
  return { T2: "T2", T3: "T3", T4: "T4", T5: "T5" }[tab] || "";
}

/** Next loan in the file queue after resolving/rejecting currentId. */
export function nextOpenId(items = [], currentId) {
  if (!items.length) return null;
  const i = items.findIndex((x) => x.exception_id === currentId);
  if (i < 0) return items[0].exception_id;
  if (i + 1 < items.length) return items[i + 1].exception_id;
  if (i > 0) return items[i - 1].exception_id;
  return null;
}

export function hasMoreExceptions(loaded, total) {
  return (loaded || 0) < (total || 0);
}
