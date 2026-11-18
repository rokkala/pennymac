/** Query helpers for the Monitor fleet page. */

export const LIVE_STATUSES = new Set(["queued", "running", "pausing", "paused"]);

export function buildBatchesPath({
  days = 1, status = [], q = "", limit = 50, since = null, until = null,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (since || until) {
    if (since) params.set("since", since);
    if (until) params.set("until", until);
  } else if (days) {
    params.set("days", String(days));
  }
  if (status?.length) params.set("status", status.join(","));
  if (q?.trim()) params.set("q", q.trim());
  return `/api/batches?${params.toString()}`;
}

export function splitLiveAndHistory(batches = []) {
  const live = [];
  const history = [];
  for (const b of batches) {
    if (LIVE_STATUSES.has(b.status)) live.push(b);
    else history.push(b);
  }
  return { live, history };
}

/** Live rows first, then history — used for BatchModal prev/next. */
export function deskOrder(batches = []) {
  const { live, history } = splitLiveAndHistory(batches);
  return [...live, ...history];
}

const LOCAL_STEP = {
  queued: { label: "Queued", state: "running" },
  claimed: { label: "Claimed", state: "running" },
  blocked: { label: "Preflight", state: "failed" },
  waiting: { label: "Waiting", state: "running" },
  out_of_order: { label: "Out of order", state: "failed" },
  running: { label: "Processing", state: "running" },
  pausing: { label: "Pausing", state: "running" },
  paused: { label: "Paused", state: "running" },
  completed: { label: "Done", state: "succeeded" },
  failed: { label: "Failed", state: "failed" },
  discarded: { label: "Discarded", state: "failed" },
};

const SHORT_DETAIL = 28;

function splitDetail(raw) {
  if (!raw) return { detail: null, title: null };
  const text = String(raw);
  if (text.length <= SHORT_DETAIL) return { detail: text, title: text };
  return { detail: null, title: text };
}

function localDetail(batch) {
  const pct = batch.progress_pct;
  const live = batch.status === "running" || batch.status === "pausing" || batch.status === "paused";
  if (live && batch.micro_batches) return `cp ${batch.micro_batches}${pct != null ? ` · ${pct}%` : ""}`;
  if (live && pct != null) return `${pct}%`;
  return batch.error || null;
}

/** Current boarding step for Monitor: SF/local pipeline when present, else status phase. */
export function batchStep(batch = {}) {
  const cur = batch.pipeline?.current
    || (batch.pipeline?.steps || []).find((s) => s.state === "running")
    || (batch.pipeline?.steps || []).at(-1);
  if (cur?.label) {
    const { detail, title } = splitDetail(cur.summary);
    return { label: cur.label, state: cur.state || "running", detail, title };
  }
  const base = LOCAL_STEP[batch.status] || { label: batch.status || "—", state: "" };
  const { detail, title } = splitDetail(localDetail(batch));
  return { ...base, detail, title };
}
