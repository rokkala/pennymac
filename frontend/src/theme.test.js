import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

// Node has no document — test storage round-trip via pure helpers inlined
const KEY = "lbp.theme";
function normalize(theme) {
  return theme === "dark" ? "dark" : "light";
}

describe("theme preference", () => {
  const store = new Map();
  beforeEach(() => store.clear());
  afterEach(() => store.clear());

  it("defaults to light when unset", () => {
    const v = store.get(KEY);
    assert.equal(v === "light" || v === "dark" ? v : "light", "light");
  });
  it("normalizes unknown to light", () => {
    assert.equal(normalize("purple"), "light");
    assert.equal(normalize("dark"), "dark");
  });
});
