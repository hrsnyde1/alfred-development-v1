// Parse and import a disposable patched copy with pinned, read-only dependencies.
// Importing the provider definition does not instantiate Spectrum or connect.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { SourceTextModule } from "node:vm";

const modulePath = process.argv[2];
assert.ok(modulePath, "patched module path required");
const source = readFileSync(modulePath, "utf8");
new SourceTextModule(source);

// Prove this gate detects the exact prior missing-comma defect.
const corrected = "nativeIsForward: z.boolean().optional(),";
assert.equal(source.split(corrected).length, 2);
const broken = source.replace(corrected, "nativeIsForward: z.boolean().optional()");
assert.throws(() => new SourceTextModule(broken), SyntaxError);
console.log("PASS: complete module parses; prior missing-comma defect is rejected");

const { imessage } = await import(pathToFileURL(modulePath).href);
const schema = imessage?.config()?.__definition?.message?.schema;
assert.ok(schema?.shape, "imported provider message schema missing");
for (const key of ["nativeReplyTargetGuid", "nativeThreadOriginatorGuid"]) {
  assert.equal(schema.shape[key].safeParse("message-guid").success, true);
  assert.equal(schema.shape[key].safeParse(42).success, false);
}
assert.equal(schema.shape.nativeIsForward.safeParse(false).success, true);
assert.equal(schema.shape.nativeIsForward.safeParse("false").success, false);
console.log("PASS: pinned dependency import exposes separate native provenance schema fields");
