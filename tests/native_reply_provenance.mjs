// Staging-only probe. It executes the installed Spectrum mapper after a patch
// is applied to a disposable copy; it never connects to Photon.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const [originalPath, patchedPath, corePath, sidecarPath] = process.argv.slice(2);
const original = readFileSync(originalPath, "utf8");
const patched = readFileSync(patchedPath, "utf8");
const core = readFileSync(corePath, "utf8");
const sidecar = readFileSync(sidecarPath, "utf8");

function mapper(source) {
  const match = source.match(/const toMessageMetadata = \(native\) => \(\{([\s\S]*?)\n\}\);/);
  assert.ok(match, "Spectrum mapper source changed");
  return new Function(
    "native", "toTextFormat", "toMention", "toAttachmentMetadata",
    "toAppliedReaction", "toPlacedSticker", "toReactionRecord",
    `return ({${match[1]}\n});`,
  );
}

const args = [x => x, x => x, x => x, x => x, x => x, () => null];
const fallbackSource = original.match(/const replyTargetGuid = (\(message\) => [^;]+);/);
assert.ok(fallbackSource, "Spectrum reply fallback source changed");
const normalizedTarget = new Function(`return ${fallbackSource[1]}`)();
const fixtures = [
  ["direct", "preview-A", "thread-origin", "preview-A"],
  ["thread fallback", undefined, "thread-origin", "thread-origin"],
  ["missing target", undefined, undefined, undefined],
  ["wrong target", "unrelated-message", "thread-origin", "unrelated-message"],
  ["concurrent preview A", "preview-A", "thread-origin", "preview-A"],
  ["concurrent preview B", "preview-B", "thread-origin", "preview-B"],
];
for (const [label, direct, origin, combined] of fixtures) {
  const native = {
    replyTargetGuid: direct,
    threadOriginatorGuid: origin,
    isForward: false,
    content: { text: "yes" },
  };
  const before = mapper(original)(native, ...args);
  const after = mapper(patched)(native, ...args);
  assert.equal(before.nativeReplyTargetGuid, undefined, label);
  assert.equal(before.nativeThreadOriginatorGuid, undefined, label);
  assert.equal(after.nativeReplyTargetGuid, direct, label);
  assert.equal(after.nativeThreadOriginatorGuid, origin, label);
  assert.equal(after.nativeIsForward, false, label);
  assert.equal(normalizedTarget(native), combined, label);
}
assert.match(core, /extras: extractExtras\(raw, ctx\.definition\)/);
assert.match(core, /\.\.\.params\.extras,/);
assert.match(sidecar, /targetMessageId: target\?\.id \?\? null/);
for (const key of ["nativeReplyTargetGuid", "nativeThreadOriginatorGuid", "nativeIsForward"]) {
  assert.match(patched, new RegExp(`${key}: z\\.`));
}
console.log("PASS: installed mapper drops direct provenance; patched mapper preserves native fields");
console.log("PASS: direct, fallback, missing, wrong and concurrent fixtures keep native fields separate");
