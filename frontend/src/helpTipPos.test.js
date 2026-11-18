import assert from "node:assert/strict";
import { helpTipFixedPos } from "./helpTipPos.js";

assert.equal(helpTipFixedPos(null), null);

const mid = helpTipFixedPos({ left: 100, top: 200, bottom: 220 }, { vw: 800, vh: 600 });
assert.deepEqual(mid, { top: 228, left: 100 });

const nearRight = helpTipFixedPos({ left: 750, top: 40, bottom: 60 }, { popW: 280, vw: 800, vh: 600 });
assert.equal(nearRight.left, 800 - 280 - 8);
assert.equal(nearRight.top, 68);

const nearBottom = helpTipFixedPos({ left: 40, top: 500, bottom: 520 }, { vw: 800, vh: 600, popH: 160 });
assert.ok(nearBottom.top < 500, "flips above when near bottom");

const roomBelow = helpTipFixedPos({ left: 40, top: 100, bottom: 120 }, { vw: 800, vh: 600, popH: 160 });
assert.equal(roomBelow.top, 128);

console.log("helpTipPos ok");
