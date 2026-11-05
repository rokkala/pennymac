/** Overview boarding desk — health strip + attention rows from batches & deliveries. */

const BATCH_ATTENTION = new Set(["running", "paused", "blocked", "waiting", "out_of_order", "failed"]);
const DELIVERY_OPEN = new Set(["late", "missed", "expected"]);

const BATCH_SEV = {
  failed: 2,
  blocked: 3,
  out_of_order: 3,
  waiting: 4,
  paused: 4,
  running: 5,
};

const DELIVERY_SEV = { missed: 0, late: 1, expected: 6 };

export const DUE_SOON_MS = 4 * 3600 * 1000;

export function buildLoadHealth({ batches = [], deliveries = [], openExceptions = 0 } = {}) {
  const stuck = batches.filter((b) => ["blocked", "waiting", "out_of_order", "paused"].includes(b.status)).length;
  return {
    running: batches.filter((b) => b.status === "running").length,
    late: deliveries.filter((d) => d.status === "late").length,
    missed: deliveries.filter((d) => d.status === "missed").length,
    stuck,
    openExceptions: openExceptions || 0,
  };
}

function linkedBatchIds(d) {
  const fromEmbed = (d.batches || []).map((x) => x.batch_id).filter(Boolean);
  return [...new Set([...(d.batch_ids || []), ...fromEmbed])];
}

/**
 * Severity-sorted attention rows for the boarding desk.
 * @returns {{ id, kind, severity, status, title, subtitle, meta, batchId, deliveryId, delivery? }[]}
 */
export function buildAttentionRows({ batches = [], deliveries = [], now = Date.now(), dueSoonMs = DUE_SOON_MS } = {}) {
  const batchById = Object.fromEntries(batches.map((b) => [b.batch_id, b]));
  const covered = new Set();
  const rows = [];

  for (const b of batches) {
    if (!BATCH_ATTENTION.has(b.status)) continue;
    const progress = b.status === "running"
      ? `${b.progress_pct ?? 0}% · ${b.processed ?? 0} / ${b.total_rows ?? "—"}`
      : (b.error || null);
    rows.push({
      id: `batch:${b.batch_id}`,
      kind: "batch",
      severity: BATCH_SEV[b.status] ?? 9,
      status: b.status,
      title: b.filename || b.batch_id,
      subtitle: [b.vendor_name, b.source_name].filter(Boolean).join(" · "),
      meta: progress,
      batchId: b.batch_id,
      deliveryId: null,
      sortAt: b.started_at || "",
    });
    covered.add(b.batch_id);
  }

  for (const d of deliveries) {
    if (!DELIVERY_OPEN.has(d.status)) continue;
    if (d.status === "expected") {
      const due = new Date(d.due_at).getTime();
      if (Number.isFinite(due) && due > now && due - now > dueSoonMs) continue;
    }
    const linked = linkedBatchIds(d);
    const active = linked.find((id) => batchById[id] && BATCH_ATTENTION.has(batchById[id].status));
    if (active) continue; // batch row already covers the action

    rows.push({
      id: `delivery:${d.delivery_id}`,
      kind: "delivery",
      severity: DELIVERY_SEV[d.status] ?? 9,
      status: d.status,
      title: d.schedule_name || d.source_name || d.delivery_id,
      subtitle: [d.vendor_name, d.source_name].filter(Boolean).join(" · "),
      meta: d.local_label || d.due_at || "",
      batchId: linked.find((id) => batchById[id]) || linked[0] || null,
      deliveryId: d.delivery_id,
      delivery: d,
      sortAt: d.due_at || "",
    });
  }

  rows.sort((a, b) => a.severity - b.severity || String(a.sortAt).localeCompare(String(b.sortAt)) || a.id.localeCompare(b.id));
  return rows;
}
