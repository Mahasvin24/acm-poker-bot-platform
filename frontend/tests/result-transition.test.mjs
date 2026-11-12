import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// Use the existing TypeScript dependency; no browser testing library is required
// for the pure transition rules used by the table container.
const compiled = ts.transpileModule(
  fs.readFileSync("src/features/table/result-transition.ts", "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } },
).outputText;
const exported = {};
vm.runInNewContext(compiled, { exports: exported });
const { resultTransitionDelay } = exported;

test("refresh can show durable results immediately without a live hand", () => {
  assert.equal(resultTransitionDelay(null, 0, 1000), 0);
});

test("a late final hand receives its full four-second presentation", () => {
  assert.equal(resultTransitionDelay({ completed: false }, 0, 0), 4000);
  assert.equal(resultTransitionDelay({ completed: true }, 4500, 500), 4000);
  assert.equal(resultTransitionDelay({ completed: true }, 4500, 1000), 3500);
  assert.equal(resultTransitionDelay({ completed: true }, 4500, 4499), 1);
  assert.equal(resultTransitionDelay({ completed: true }, 4500, 4500), 0);
});

test("reconnect after a finished presentation does not restart its clock", () => {
  assert.equal(resultTransitionDelay({ completed: true }, 4500, 8000), 0);
});
