import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readPrivateJson } from "../src/secure-input.mjs";

test("private loader accepts 0600 regular file and rejects broad mode and symlink", () => {
  const testsDir = path.dirname(fileURLToPath(import.meta.url));
  const dir = fs.mkdtempSync(path.join(testsDir, ".private-test-"));
  try {
    const file = path.join(dir, "credentials.json");
    fs.writeFileSync(file, '{"projectId":"test"}', { mode: 0o600 });
    assert.equal(readPrivateJson(file).projectId, "test");
    fs.chmodSync(file, 0o400);
    assert.equal(readPrivateJson(file).projectId, "test");
    fs.chmodSync(file, 0o644);
    assert.throws(() => readPrivateJson(file), /PRIVATE_INPUT_PERMISSIONS_INVALID/);
    fs.chmodSync(file, 0o600);
    const link = path.join(dir, "link.json");
    fs.symlinkSync(file, link);
    assert.throws(() => readPrivateJson(link), /PRIVATE_INPUT_PERMISSIONS_INVALID/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
