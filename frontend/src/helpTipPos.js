/** Place a fixed help popup under an anchor without leaving the viewport. */
export function helpTipFixedPos(anchor, { popW = 280, popH = 160, gap = 8, pad = 8, vw = 0, vh = 0 } = {}) {
  if (!anchor) return null;
  const viewW = vw || (typeof window !== "undefined" ? window.innerWidth : 1024);
  const viewH = vh || (typeof window !== "undefined" ? window.innerHeight : 768);
  const left = Math.max(pad, Math.min(anchor.left, viewW - popW - pad));
  const spaceBelow = viewH - anchor.bottom - pad;
  const top = spaceBelow >= popH
    ? anchor.bottom + gap
    : Math.max(pad, anchor.top - gap - popH);
  return { top, left };
}
