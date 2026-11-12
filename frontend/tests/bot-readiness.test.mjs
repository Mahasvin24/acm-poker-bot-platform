import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { chooseAction } from "../../examples/bots/javascript/strategy.mjs";

const exported = {};
vm.runInNewContext(ts.transpileModule(
  fs.readFileSync("src/features/account/bot-readiness.ts", "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } },
).outputText, { exports: exported });
const { botReadiness, botSetupError } = exported;
const entrant = { id: "bot", verified_at: null };
const report = {
  passed: true,
  checks: ["Health", "Authentication", "Check or raise", "Facing a bet", "Short-stack call", "Short all-in raise"].map((name) => ({ name, passed: true })),
};
const detail = (steps, label) => steps.find((step) => step.label === label).detail;

test("registration and connection do not imply a running bot or passing decisions", () => {
  const steps = botReadiness({ ...entrant, verified_at: "saved-verification" }, true, null);
  assert.equal(steps.length, 5);
  assert.match(detail(steps, "Bot running"), /Not checked/);
  assert.match(detail(steps, "Connection verified"), /Verified for the saved endpoint/);
  assert.match(detail(steps, "Tests passed"), /Not checked/);
});

test("successful test observations do not save connection verification", () => {
  const steps = botReadiness(entrant, true, report);
  assert.match(detail(steps, "Bot running"), /during the last test/);
  assert.match(detail(steps, "Connection verified"), /Not verified/);
  assert.match(detail(steps, "Tests passed"), /All four decision checks passed/);
});

test("failed health and decision checks are shown separately", () => {
  const failed = { ...report, passed: false, checks: report.checks.map((check, index) => ({ ...check, passed: index !== 0 && index !== 3 })) };
  const steps = botReadiness(entrant, true, failed);
  assert.match(detail(steps, "Bot running"), /Not reached/);
  assert.match(detail(steps, "Tests passed"), /Some decision checks failed/);
  assert.match(detail(botReadiness(entrant, false, report), "Connection verified"), /Status unavailable/);
});

test("organizer progress comes from match status, never test success", () => {
  for (const [status, expected] of [["lobby", /Waiting for the organizer/], ["running", /in progress/], ["completed", /finished/], [null, /Join a match/]]) {
    const steps = botReadiness(entrant, true, report, status);
    assert.match(detail(steps, "Waiting for organizer"), expected);
  }
});

test("common setup errors suggest a next step and preserve other errors", () => {
  assert.match(botSetupError("bot verification failed: connection"), /terminal.*Wi-Fi.*firewall/);
  assert.match(botSetupError("bot verification failed: timeout"), /try Verify Bot Connection again/);
  assert.match(botSetupError("bot verification failed: http_status"), /Restart.*token/);
  assert.match(botSetupError("bot IP is outside the participant subnet"), /numeric Wi-Fi IP/);
  assert.equal(botSetupError("Tournament registration is closed"), "Tournament registration is closed");
});

test("JavaScript strategy chooses check, call, and fold without changing response IDs", () => {
  for (const [legal, expected] of [[["check", "raise"], "check"], [["fold", "call", "raise"], "call"], [["fold"], "fold"]]) {
    const decision = chooseAction({ legal_actions: legal.map((action) => ({ action })) });
    assert.deepEqual(decision, { action: expected, amount_to: null });
  }
});
