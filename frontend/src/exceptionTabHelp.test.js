import assert from "node:assert/strict";
import { EXCEPTION_TAB_HELP, helpForExceptionTab } from "./exceptionTabHelp.js";

const IDS = ["open", "T1", "T2", "T3", "T4", "checker", "T5", "resolved"];

for (const id of IDS) {
  const h = helpForExceptionTab(id);
  assert.ok(h, `missing help for ${id}`);
  assert.ok(h.title?.trim(), `${id} needs title`);
  assert.ok(h.body?.trim(), `${id} needs body`);
  assert.ok(h.who?.trim(), `${id} needs who`);
}
assert.equal(helpForExceptionTab("nope"), null);
assert.equal(EXCEPTION_TAB_HELP.T2.title, "Suggest a fix");
assert.equal(EXCEPTION_TAB_HELP.T3.title, "Review");
assert.equal(EXCEPTION_TAB_HELP.T4.title, "Needs a second person");
assert.equal(EXCEPTION_TAB_HELP.checker.title, "Waiting for you");
assert.equal(EXCEPTION_TAB_HELP.T5.title, "Holds");
assert.equal(EXCEPTION_TAB_HELP.resolved.title, "Done");
assert.match(EXCEPTION_TAB_HELP.T2.body, /^T2\./);
assert.match(EXCEPTION_TAB_HELP.T4.body, /^T4\./);
assert.match(EXCEPTION_TAB_HELP.T5.body, /^T5\./);
assert.equal(Object.keys(EXCEPTION_TAB_HELP).sort().join(), IDS.slice().sort().join());
console.log("exceptionTabHelp ok");
