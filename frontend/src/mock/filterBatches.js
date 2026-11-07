/** Shared filter for demo GET /api/batches — kept in sync with backend import_status semantics. */

const ATTN = new Set(["failed", "blocked", "waiting", "paused", "out_of_order"]);
const RUNNING = new Set(["running", "queued"]);

export function filterBatches(rows, q) {
  const statuses = (q.get("status") || "").split(",").map((x) => x.trim()).filter(Boolean);
  const needle = (q.get("q") || "").trim().toLowerCase();
  const days = q.get("days") ? Number(q.get("days")) : null;
  const sinceMs = days && [1, 7, 30].includes(days) ? Date.now() - days * 86400000
    : q.get("since") ? Date.parse(q.get("since")) : null;
  const untilMs = q.get("until") ? Date.parse(q.get("until")) : null;

  const matchScope = (b) => {
    if (needle && !(String(b.filename || "").toLowerCase().includes(needle)
      || String(b.batch_id || "").toLowerCase().includes(needle))) return false;
    const t = Date.parse(b.created_at || b.started_at || 0);
    if (sinceMs && Number.isFinite(t) && t < sinceMs) return false;
    if (untilMs && Number.isFinite(t) && t > untilMs) return false;
    return true;
  };
  const match = (b) => {
    if (statuses.length && !statuses.includes(b.status)) return false;
    return matchScope(b);
  };

  const filtered = rows.filter(match);
  const attnStatuses = statuses.length ? statuses.filter((x) => ATTN.has(x)) : [...ATTN];
  const attention = rows.filter((b) => attnStatuses.includes(b.status) && matchScope(b)).length;
  const runStatuses = statuses.length ? statuses.filter((x) => RUNNING.has(x)) : [...RUNNING];
  const runRows = rows.filter((b) => runStatuses.includes(b.status) && matchScope(b));
  const limit = Math.min(200, Math.max(1, Number(q.get("limit") || 50)));
  return {
    batches: filtered.slice(0, limit),
    attention,
    running: runRows.length,
    current_throughput_lps: runRows.reduce((a, b) => a + (b.throughput_lps || 0), 0),
  };
}
