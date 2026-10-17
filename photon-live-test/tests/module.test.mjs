import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const hash = (p) => createHash("sha256").update(fs.readFileSync(p)).digest("hex");

test("exact pinned copies and corrected module hash", () => {
  const versions = [
    ["spectrum-ts", "12.7.0"],
    ["@spectrum-ts/imessage", "12.7.0"],
    ["@photon-ai/advanced-imessage", "2.1.0"],
  ];
  for (const [name, wanted] of versions) {
    const pkg = JSON.parse(fs.readFileSync(path.join(root, "vendor/node_modules", name, "package.json"), "utf8"));
    assert.equal(pkg.version, wanted);
  }
  assert.equal(hash(path.join(root, "vendor/node_modules/@spectrum-ts/imessage/dist/index.js")),
    "9faf0be1530dde1e2f80b580d12377a1fa6b0995c3595794648237a2c8f241ee");
  assert.equal(hash(path.join(root, "patches/spectrum-native-reply-provenance.proposed.patch")),
    "62d280e45e66b6880bf4e37d46aafbbf7cd4340368c5f85e6821f62c3cc62552");
});

test("full patched module imports locally and exposes both native fields", async () => {
  const url = new URL("../vendor/node_modules/@spectrum-ts/imessage/dist/index.js", import.meta.url);
  const module = await import(url.href);
  assert.equal(typeof module.imessage.config, "function");
  const source = fs.readFileSync(fileURLToPath(url), "utf8");
  assert.match(source, /nativeReplyTargetGuid: native\.replyTargetGuid/);
  assert.match(source, /nativeThreadOriginatorGuid: native\.threadOriginatorGuid/);
  assert.match(source, /nativeIsForward: native\.isForward/);
  assert.ok(fs.realpathSync(fileURLToPath(url)).startsWith(root + path.sep));
});
