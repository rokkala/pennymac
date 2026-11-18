import { canCap, can } from "./roles.js";

/** The server enforces all of this; these helpers only decide which buttons to show. */
export const RESTORE_NOTE = "Restoring brings the feed back, but its schedules stay paused. Turn them back on from Delivery & schedule when you are ready.";

const archived = (f) => f?.status === "retired";

/** Live feeds need the reviewer; everything else any onboarding member. */
export const canArchive = (user, feed) => !!feed && !archived(feed) && canCap(user, "archiveFeed")
  && (feed.status !== "live" || can(user, "onboarding_reviewer"));

/** A feed archived from live also needs the reviewer to come back; the archive record does not say, so the server decides. */
export const canRestore = (user, feed) => !!feed && archived(feed) && canCap(user, "archiveFeed");

/** Admin only, and never when the row says the feed has history. The server refuses any feed that was used. */
export const canDelete = (user, feed) => !!feed && archived(feed) && !feed.has_history && canCap(user, "deleteFeed");

export const canDiscardMapping = (user, mapping, source) => !!mapping && ["draft", "rejected"].includes(mapping.status)
  && !archived(source) && canCap(user, "archiveFeed");

export const splitFeeds = (feeds) => ({ active: (feeds || []).filter((f) => !archived(f)), archived: (feeds || []).filter(archived) });

export const archivedLine = (f) => {
  const bits = [];
  if (f?.retired_reason) bits.push(f.retired_reason);
  if (f?.retired_by) bits.push(`by ${f.retired_by}`);
  if (f?.retired_at) bits.push(new Date(f.retired_at).toLocaleDateString());
  return bits.join(" · ");
};
