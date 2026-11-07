/** Query helpers for the Monitor fleet page. */

export const LIVE_STATUSES = new Set(["queued", "running", "pausing", "paused"]);

export function buildBatchesPath({ days = 1, status = [], q = "", limit = 50 } = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (days) params.set("days", String(days));
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
