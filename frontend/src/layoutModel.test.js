import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  emptyLayout, emptyReadiness, addDetail, validateLayoutForm, groupColumnsByRole, setStatusLabel, missingRoles,
  matchRateBadge, previewTrust, joinCodeText, filesToSend, ensureColumnIds, stripClientIds,
} from "./layoutModel.js";

const valid = () => {
  const l = addDetail(emptyLayout(), "details");
  l.files[0].name_pattern = "^master_(?P<date>\\d{8})\\.csv$";
  l.files[0].key = ["id"];
  l.files[1].name_pattern = "^details_(?P<date>\\d{8})\\.csv$";
  l.relations[0].on = [{ parent: "id", detail: "ref" }];
  return l;
};

describe("emptyLayout / addDetail", () => {
  it("starts with one master file and no relations", () => {
    const l = emptyLayout();
    assert.deepEqual(l.files.map((f) => f.role), ["master"]);
    assert.deepEqual(l.relations, []);
    assert.deepEqual(l.files[0].key, []);
  });
  it("adds a detail file plus a merge relation to the master, without mutating the input", () => {
    const base = emptyLayout();
    const l = addDetail(base, "details");
    assert.equal(base.files.length, 1);
    assert.deepEqual(l.files.map((f) => f.role), ["master", "details"]);
    assert.equal(l.relations.length, 1);
    assert.equal(l.relations[0].detail, "details");
    assert.equal(l.relations[0].to, "master");
    assert.equal(l.relations[0].mode, "merge");
    assert.equal(l.relations[0].cardinality, "one");
  });
  it("refuses an empty, reserved or repeated role", () => {
    assert.throws(() => addDetail(emptyLayout(), ""));
    assert.throws(() => addDetail(emptyLayout(), "master"));
    assert.throws(() => addDetail(addDetail(emptyLayout(), "a"), "a"));
  });
});

describe("validateLayoutForm", () => {
  it("accepts a complete layout", () => {
    assert.deepEqual(validateLayoutForm(valid(), emptyReadiness()), []);
  });
  it("rejects zero masters", () => {
    const l = valid();
    l.files = l.files.filter((f) => f.role !== "master");
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /exactly one master/.test(e)));
  });
  it("rejects two masters", () => {
    const l = valid();
    l.files.push({ role: "master", name_pattern: "x", key: ["id"] });
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /exactly one master/.test(e)));
  });
  it("needs a master key and a name pattern on every file", () => {
    const l = valid();
    l.files[0].key = [];
    l.files[1].name_pattern = "";
    const e = validateLayoutForm(l, emptyReadiness());
    assert.ok(e.some((x) => /key/.test(x)));
    assert.ok(e.some((x) => /name pattern/.test(x) && /details/.test(x)));
  });
  it("leaves regex syntax to the server: Python-only syntax passes", () => {
    const l = valid();
    l.files[0].name_pattern = "(?i)^loans_(?P<date>\\d{8})\\.csv$";
    l.files[1].name_pattern = "^details_(?P<date>\\d{8})\\.csv$";
    assert.deepEqual(validateLayoutForm(l, emptyReadiness()), []);
    l.files[1].name_pattern = "(?i)details_(?P<d>\\d+)";
    assert.deepEqual(validateLayoutForm(l, emptyReadiness()), []);
  });
  it("checks role names", () => {
    for (const bad of ["Details", "1a", "a.b", "layout", "readiness", "manifest", "files", "a-b"]) {
      const l = valid();
      l.files[1].role = bad;
      l.relations[0].detail = bad;
      assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /role name/.test(e)), bad);
    }
    const l = valid();
    l.files[1].role = "tax_2";
    l.relations[0].detail = "tax_2";
    assert.deepEqual(validateLayoutForm(l, emptyReadiness()), []);
  });
  it("merge needs cardinality one", () => {
    const l = valid();
    l.relations[0].cardinality = "many";
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /merge/.test(e) && /one/.test(e)));
  });
  it("supports merge and aggregate only", () => {
    const l = valid();
    l.relations[0].mode = "flatten";
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /not supported/.test(e)));
  });
  it("aggregate needs columns with unique names, a source column, and no clash with a master column", () => {
    const l = valid();
    Object.assign(l.relations[0], { mode: "aggregate", cardinality: "many", aggregate: { columns: [] } });
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /at least one/.test(e)));
    l.relations[0].aggregate.columns = [{ as: "total", op: "sum", col: "amt" }, { as: "total", op: "max", col: "amt" }];
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /total/.test(e) && /more than once/.test(e)));
    l.relations[0].aggregate.columns = [{ as: "id", op: "sum", col: "amt" }];
    assert.ok(validateLayoutForm(l, emptyReadiness(), { master: ["id", "name"] }).some((e) => /id/.test(e) && /master column/.test(e)));
    assert.deepEqual(validateLayoutForm(l, emptyReadiness()), []);
    l.relations[0].aggregate.columns = [{ as: "total", op: "sum", col: "" }];
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /source column/.test(e)));
    l.relations[0].aggregate.columns = [{ as: "n", op: "count" }];
    assert.deepEqual(validateLayoutForm(l, emptyReadiness()), []);
  });
  it("checks the match rate range and join key parts", () => {
    const l = valid();
    l.relations[0].min_match_rate = 1.5;
    l.relations[0].on = [];
    const e = validateLayoutForm(l, emptyReadiness());
    assert.ok(e.some((x) => /between 0% and 100%/.test(x)));
    assert.ok(e.some((x) => /join column/.test(x)));
  });
  it("checks readiness: named groups for pairing, window, and master-only timeout", () => {
    const l = valid();
    l.files[1].name_pattern = "^details\\.csv$";
    assert.ok(validateLayoutForm(l, emptyReadiness()).some((e) => /named group/.test(e)));
    assert.deepEqual(validateLayoutForm(l, { ...emptyReadiness(), pairing: "window_minutes", window_minutes: 30 }), []);
    assert.ok(validateLayoutForm(l, { ...emptyReadiness(), pairing: "window_minutes" }).some((e) => /window/.test(e)));
    assert.ok(validateLayoutForm(valid(), { ...emptyReadiness(), on_timeout: "load_master_only" }).some((e) => /master/.test(e) && /required/.test(e)));
  });
});

describe("groupColumnsByRole", () => {
  it("puts plain names under master, then role groups in first-seen order", () => {
    assert.deepEqual(groupColumnsByRole(["loan_id", "details.fee", "details.type"]), [
      { role: "master", columns: ["loan_id"] },
      { role: "details", columns: ["details.fee", "details.type"] },
    ]);
  });
  it("keeps several roles apart and drops an empty master group", () => {
    assert.deepEqual(groupColumnsByRole(["a.x", "b.y", "a.z"]), [
      { role: "a", columns: ["a.x", "a.z"] }, { role: "b", columns: ["b.y"] }]);
    assert.deepEqual(groupColumnsByRole([]), []);
  });
});

describe("setStatusLabel / missingRoles", () => {
  const layout = { files: [{ role: "master", required: true }, { role: "borrowers", required: true }, { role: "notes", required: false }] };
  it("names the file a waiting set lacks", () => {
    const set = { status: "waiting", members: [{ role: "master" }] };
    assert.deepEqual(missingRoles(set, layout), ["borrowers"]);
    assert.equal(setStatusLabel({ ...set, missing_roles: ["borrowers"] }), "Waiting for borrowers file");
    assert.equal(setStatusLabel({ status: "waiting", missing_roles: ["a", "b"] }), "Waiting for a, b files");
    assert.equal(setStatusLabel({ status: "waiting" }), "Waiting for more files");
  });
  it("labels the other states in plain words", () => {
    assert.equal(setStatusLabel({ status: "ready" }), "Ready");
    assert.equal(setStatusLabel({ status: "consumed" }), "Loaded");
    assert.equal(setStatusLabel({ status: "expired" }), "Expired");
    assert.equal(setStatusLabel({ status: "discarded" }), "Discarded");
    assert.equal(setStatusLabel({ status: "overridden" }), "Accepted without all files");
  });
});

describe("matchRateBadge", () => {
  it("is ok at or above the threshold, block below it, warn when close or untuned", () => {
    assert.equal(matchRateBadge(0.99, 0.95), "ok");
    assert.equal(matchRateBadge(0.95, 0.95), "ok");
    assert.equal(matchRateBadge(0.9, 0.95), "block");
    assert.equal(matchRateBadge(0.97, 0), "ok");
    assert.equal(matchRateBadge(0.8, 0), "warn");
    assert.equal(matchRateBadge(1, 0), "ok");
    assert.equal(matchRateBadge(null, 0.5), "warn");
  });
});

describe("previewTrust", () => {
  it("trusts the rates of a whole-file preview", () => {
    const t = previewTrust({ sampled: false });
    assert.equal(t.reliable, true);
    assert.equal(t.note, "");
  });
  it("does not trust rates when the sample cut the master", () => {
    const t = previewTrust({ sampled: true });
    assert.equal(t.reliable, false);
    assert.match(t.note, /2,000/);
    assert.match(t.note, /orphan/i);
  });
  it("tolerates a missing preview", () => {
    assert.equal(previewTrust(null).reliable, true);
  });
});

describe("joinCodeText", () => {
  it("explains every JOIN code in plain words", () => {
    for (let i = 1; i <= 7; i++) assert.ok(joinCodeText(`JOIN0${i}`).length > 10);
    assert.equal(joinCodeText("X"), "");
  });
});

describe("filesToSend", () => {
  it("keeps only files of roles the layout still has", () => {
    const l = addDetail(emptyLayout(), "details");
    const m = { name: "m" }, d = { name: "d" }, gone = { name: "g" };
    assert.deepEqual(filesToSend(l, { master: m, details: d, removed: gone }), { master: m, details: d });
    assert.deepEqual(filesToSend(l, { master: m, details: null }), { master: m });
  });
});

describe("client column ids", () => {
  it("adds stable ids to aggregate columns and strips them again", () => {
    const l = valid();
    Object.assign(l.relations[0], { mode: "aggregate", aggregate: { columns: [{ as: "a", op: "sum", col: "x" }, { as: "b", op: "count" }] } });
    const withIds = ensureColumnIds(l);
    const ids = withIds.relations[0].aggregate.columns.map((c) => c._id);
    assert.equal(new Set(ids).size, 2);
    assert.ok(ids.every(Boolean));
    assert.deepEqual(ensureColumnIds(withIds).relations[0].aggregate.columns.map((c) => c._id), ids);
    assert.deepEqual(stripClientIds(withIds), l);
    assert.equal(l.relations[0].aggregate.columns[0]._id, undefined);
  });
});
