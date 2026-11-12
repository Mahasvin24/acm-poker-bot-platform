import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(fs.readFileSync("src/features/table/presentation.ts", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const exported = {};
vm.runInNewContext(compiled, { exports: exported });
const { boardRevealSteps, newerTable, raisePresets } = exported;
const plain = (value) => JSON.parse(JSON.stringify(value));

test("all-in runout reveals streets within the server window, with polling margin", () => {
  assert.deepEqual(plain(boardRevealSteps(0, 5, 2500, false)), [
    { count: 3, delay: 360 }, { count: 4, delay: 720 }, { count: 5, delay: 1080 },
  ]);
  assert.deepEqual(plain(boardRevealSteps(3, 4, 2000, false)), [{count: 4, delay: 360}]);
});

test("live decisions, insufficient windows and unchanged boards never wait for reveals", () => {
  for (const args of [[0,5,2500,true],[0,5,1000,false],[5,5,2500,false],[5,0,2500,false]]) {
    assert.deepEqual(plain(boardRevealSteps(...args)), []);
  }
});

const state = (overrides = {}) => ({match_id:'match-a',hand_number:2,hand_id:'hand-2',table_version:8,match_status:'running',...overrides});
test("delayed polls cannot overwrite newer action responses or hands", () => {
  const current = state();
  assert.equal(newerTable(current,state({table_version:7})),current);
  assert.equal(newerTable(current,state({hand_number:1,table_version:100})),current);
  const next = state({hand_number:3,table_version:1});
  assert.equal(newerTable(current,next),next);
  assert.equal(newerTable(current,state({match_id:'other-match'})),current);
});

test("terminal metadata survives a late poll with the same hand version", () => {
  const done = state({match_status:'completed'});
  assert.equal(newerTable(done,state()),done);
  assert.equal(newerTable(state(),done),done);
});

test("raise presets include the call and prior street contribution, bounded by legal totals", () => {
  assert.deepEqual(plain(raisePresets(2200,600,400,1800,18800)),[1800,2400,3100,3800,18800]);
  assert.deepEqual(plain(raisePresets(10000,0,0,200,500)),[200,500,500,500,500]);
  assert.deepEqual(plain(raisePresets(100,0,0,200,2000)),[200,200,200,200,2000]);
});
