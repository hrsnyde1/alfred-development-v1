import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fixedControl } from "../scripts/operator-control.mjs";
import { readFixedRecord, parseResultRecord } from "../scripts/read-results.mjs";
import { classifyNetworkResult } from "../scripts/os-network-probe.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("control wrapper exposes only fixed commands and phase sockets", () => {
  assert.deepEqual(fixedControl("initial", "preview-A"),
    { socket: "/run/photon-reply-test-initial/control.sock", command: "preview A" });
  assert.deepEqual(fixedControl("reconnect", "expect-reconnect"),
    { socket: "/run/photon-reply-test-reconnect/control.sock", command: "expect reconnect" });
  for (const [phase, token] of [["initial", "preview-Z"], ["initial", "preview-A;cat"],
    ["../initial", "quit"], ["initial", "send /etc/shadow"], ["initial", "preview A"]])
    assert.throws(() => fixedControl(phase, token), /INVALID_FIXED_COMMAND/);
  for (const phase of ["initial", "reconnect"]) {
    const unit = fs.readFileSync(path.join(root, `same-server/photon-reply-control-${phase}@.service`), "utf8");
    assert.match(unit, /^Requisite=photon-reply-test@.*\.service$/m);
    assert.match(unit, /^RootDirectory=\/srv\/photon-reply-test\/root$/m);
    assert.match(unit, new RegExp(`^BindPaths=/run/photon-reply-test-${phase}:/run/photon-reply-test-${phase}$`, "m"));
    assert.match(unit, /^PrivateNetwork=yes$/m);
    assert.match(unit, /^RestrictAddressFamilies=AF_UNIX$/m);
    assert.doesNotMatch(unit, /LoadCredential=|\/home\/alfred|BindPaths=\/run:/);
  }
});

test("confined results reader rejects symlinks, hardlinks, oversize and unsafe content", () => {
  const dir = fs.mkdtempSync(path.join(root, "tests/.results-reader-"));
  try {
    fs.chmodSync(dir, 0o700);
    const control = path.join(dir, "control.txt");
    const results = path.join(dir, "results.ndjson");
    fs.writeFileSync(control, "Send exact preflight message from separate test sender to test line: LAB ROUTE 0123456789abcdefabcd\n", { mode: 0o600 });
    fs.writeFileSync(results, `${JSON.stringify({ at: "2026-10-14T00:00:00.000Z", code: "BOOT" })}\n`, { mode: 0o600 });
    assert.equal(readFixedRecord(dir, "control.txt").length, 1);
    assert.equal(readFixedRecord(dir, "results.ndjson").length, 1);
    assert.throws(() => readFixedRecord(dir, "../../etc/shadow"), /INVALID_RESULT_NAME/);
    fs.unlinkSync(control);
    fs.symlinkSync(results, control);
    assert.throws(() => readFixedRecord(dir, "control.txt"), /RESULT_FILE_INVALID/);
    fs.unlinkSync(control);
    fs.linkSync(results, control);
    assert.throws(() => readFixedRecord(dir, "results.ndjson"), /RESULT_FILE_INVALID/);
    fs.unlinkSync(control);
    fs.writeFileSync(control, "secret=raw sdk diagnostic\n", { mode: 0o600 });
    assert.throws(() => readFixedRecord(dir, "control.txt"), /UNSAFE_CONTROL_RECORD/);
    fs.writeFileSync(control, "x".repeat(24 * 1024 + 1), { mode: 0o600 });
    assert.throws(() => readFixedRecord(dir, "control.txt"), /RESULT_FILE_INVALID/);
    fs.chmodSync(dir, 0o755);
    assert.throws(() => readFixedRecord(dir, "results.ndjson"), /RESULT_DIRECTORY_INVALID/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("result schema rejects secret and unbounded fields", () => {
  const base = { at: "2026-10-14T00:00:00.000Z", code: "CASE_RESULT", case: "direct" };
  assert.equal(parseResultRecord(JSON.stringify(base)).code, "CASE_RESULT");
  for (const extra of [{ credential: "secret" }, { reason: "raw message" },
    { case: "x".repeat(41) }, { directMatch: "yes" }])
    assert.throws(() => parseResultRecord(JSON.stringify({ ...base, ...extra })), /UNSAFE_RESULT_RECORD/);
  const unit = fs.readFileSync(path.join(root, "same-server/photon-reply-results@.service"), "utf8");
  assert.match(unit, /^BindReadOnlyPaths=.*\/var\/lib\/photon-reply-test\/%i:\/results$/m);
  assert.match(unit, /^RootDirectory=\/srv\/photon-reply-test\/root$/m);
  assert.doesNotMatch(unit, /LoadCredential=|BindPaths=|\/home\/alfred/);
});

test("network probe classifications never treat timeout or refusal as filtering proof", () => {
  assert.equal(classifyNetworkResult("allow", "connected"), "PASS");
  assert.equal(classifyNetworkResult("deny", "EPERM"), "PASS");
  assert.equal(classifyNetworkResult("deny", "EACCES"), "PASS");
  for (const result of ["timeout", "ECONNREFUSED", "ENETUNREACH", "EHOSTUNREACH"])
    assert.equal(classifyNetworkResult("deny", result), "INCONCLUSIVE");
  assert.equal(classifyNetworkResult("deny", "connected"), "FAIL");
  const probe = fs.readFileSync(path.join(root, "same-server/photon-reply-probe@.service"), "utf8");
  assert.match(probe, /^TimeoutStartSec=15s$/m);
  assert.doesNotMatch(probe, /^RuntimeMaxSec=/m);
});
