import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { renderNetwork } from "../scripts/render-network.mjs";
import { checkStartup, validateStartupMaterial } from "../scripts/startup-gate.mjs";
import { auditRuntimeCopy } from "../scripts/audit-runtime-copy.mjs";
import { installTransaction, rollbackTransaction } from "../scripts/firewall-transaction.mjs";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const unit = fs.readFileSync(path.join(root, "same-server/photon-reply-test@.service"), "utf8");

test("required inputs use failed assertions, not silently skipped conditions", () => {
  assert.doesNotMatch(unit, /^ConditionPathExists=/m);
  for (const name of ["MANIFEST.sha256", "bin/node", "credentials.json", "metadata.json", "os-acceptance.ok"]) {
    assert.match(unit, new RegExp(`^AssertPathExists=.*${name.replace(".", "\\.")}$`, "m"));
  }
  assert.match(unit, /^ExecStartPre=\/app\/bin\/node \/app\/scripts\/integrity\.mjs --verify$/m);
  assert.match(unit, /^ExecStartPre=\/app\/bin\/node \/app\/scripts\/startup-gate\.mjs$/m);
  assert.match(unit, /^SocketBindDeny=any$/m);
  assert.match(unit, /^RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6$/m);
  assert.match(unit, /^Restart=no$/m);
});

test("nft rendering covers IPv4 only, IPv6 only and dual stack without empty sets", () => {
  for (const policy of [
    { uid: 997, ipv4: ["1.1.1.1"] },
    { uid: 997, ipv6: ["2606:4700:4700::1111"] },
    { uid: 997, ipv4: ["1.1.1.1"], ipv6: ["2606:4700:4700::1111"] },
  ]) {
    const nft = renderNetwork(policy);
    assert.match(nft, /create table inet alfred_photon_reply_test/);
    assert.match(nft, /meta skuid 997 jump test_egress/);
    assert.match(nft, /test_egress counter drop/);
    assert.doesNotMatch(nft, /__|\{\s*\}/);
    assert.doesNotMatch(nft, /flush ruleset|flush table|delete table/);
    assert.equal((nft.match(/tcp dport 443 counter accept/g) ?? []).length,
      Number(Boolean(policy.ipv4)) + Number(Boolean(policy.ipv6)));
  }
});

test("nft renderer rejects test identity confusion and local or placeholder destinations", () => {
  for (const policy of [
    { uid: 0, ipv4: ["1.1.1.1"] }, { uid: 997 },
    { uid: 997, ipv4: ["127.0.0.1"] }, { uid: 997, ipv4: ["10.1.1.1"] },
    { uid: 997, ipv4: ["198.51.100.1"] }, { uid: 997, ipv6: ["::1"] },
    { uid: 997, ipv6: ["fd00::1"] }, { uid: 997, ipv6: ["2001:db8::1"] },
    { uid: 997, ipv4: ["1.1.1.1; flush ruleset"] },
  ]) assert.throws(() => renderNetwork(policy));
});

test("startup gate rejects absent, mismatched and broadly readable test credentials", () => {
  const dir = fs.mkdtempSync(path.join(root, "tests/.startup-gate-"));
  try {
    const creds = path.join(dir, "credentials.json");
    const meta = path.join(dir, "metadata.json");
    const results = path.join(dir, "results");
    const socketDir = path.join(dir, "socket");
    fs.mkdirSync(results, { mode: 0o700 });
    fs.mkdirSync(socketDir, { mode: 0o700 });
    const paths = { credentials: creds, metadata: meta, results };
    const socket = path.join(socketDir, "control.sock");
    const uid = process.getuid();
    assert.throws(() => validateStartupMaterial(paths, socket, uid));
    fs.writeFileSync(creds, '{"projectId":"test","projectSecret":"fixture"}', { mode: 0o600 });
    fs.writeFileSync(meta, '{"testProjectId":"wrong"}', { mode: 0o600 });
    assert.throws(() => validateStartupMaterial(paths, socket, uid), /PROJECT_BINDING_INVALID/);
    fs.writeFileSync(meta, '{"testProjectId":"test"}');
    fs.chmodSync(meta, 0o600);
    assert.equal(validateStartupMaterial(paths, socket, uid), true);
    fs.chmodSync(creds, 0o644);
    assert.throws(() => validateStartupMaterial(paths, socket, uid), /PRIVATE_INPUT_PERMISSIONS_INVALID/);
    fs.chmodSync(creds, 0o600);
    fs.chmodSync(socketDir, 0o755);
    assert.throws(() => validateStartupMaterial(paths, socket, uid), /COMMAND_SOCKET_DIRECTORY_INVALID/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("runtime-copy audit fails closed on user-owned staging and missing copy", () => {
  assert.throws(() => auditRuntimeCopy(root), /RUNTIME_COPY_NOT_ROOT_IMMUTABLE/);
  assert.throws(() => auditRuntimeCopy(path.join(os.tmpdir(), "missing-photon-test-copy")));
});

test("missing integrity manifest produces a failed pre-start check", () => {
  const dir = fs.mkdtempSync(path.join(root, "tests/.missing-manifest-"));
  try {
    fs.mkdirSync(path.join(dir, "scripts"));
    fs.copyFileSync(path.join(root, "scripts/integrity.mjs"), path.join(dir, "scripts/integrity.mjs"));
    const result = spawnSync(path.join(root, "bin/node"),
      [path.join(dir, "scripts/integrity.mjs"), "--verify"], { encoding: "utf8" });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /ENOENT/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test("startup gate refuses a direct staging launch before any SDK connection", () => {
  assert.throws(() => checkStartup({ PHOTON_TEST_ISOLATED: "1" }), /ISOLATION_OR_UID_INVALID/);
});

function fakeFirewall(failAt = "") {
  let exists = false;
  let recorded = false;
  const calls = [];
  const ops = {
    tableExists: () => exists,
    syntaxCheck: () => { calls.push("check"); if (failAt === "check") throw new Error("check"); },
    apply: () => { calls.push("apply"); exists = true; },
    onApplied: () => { if (failAt === "interrupt") throw new Error("interrupt"); },
    record: () => { calls.push("record"); if (failAt === "record") throw new Error("record"); recorded = true; },
    remove: () => { calls.push("remove-test-table"); exists = false; },
    clearRecord: () => { calls.push("clear-record"); recorded = false; },
  };
  return { ops, calls, get exists() { return exists; }, get recorded() { return recorded; } };
}

test("atomic test-table install, interrupted cleanup and targeted rollback", () => {
  for (const stage of ["check", "interrupt", "record"]) {
    const mock = fakeFirewall(stage);
    assert.throws(() => installTransaction(mock.ops));
    assert.equal(mock.exists, false);
    assert.equal(mock.recorded, false);
    assert.equal(mock.calls.includes("remove-test-table"), stage !== "check");
  }
  const mock = fakeFirewall();
  installTransaction(mock.ops);
  assert.equal(mock.exists, true);
  assert.equal(mock.recorded, true);
  assert.throws(() => installTransaction(mock.ops), /TEST_TABLE_ALREADY_EXISTS/);
  rollbackTransaction(mock.ops);
  assert.equal(mock.exists, false);
  assert.equal(mock.recorded, false);
  assert.deepEqual(mock.calls.slice(-2), ["remove-test-table", "clear-record"]);
  assert.throws(() => rollbackTransaction(mock.ops), /TEST_TABLE_ABSENT_REVIEW_REQUIRED/);
});
