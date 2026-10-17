import assert from "node:assert/strict";
import test from "node:test";
import { developmentObservation } from "../staging/sidecar/development-observe.mjs";

test("preserves original SDK sender and message ID", () => {
  const input = { messageId: "sdk-1", direction: "inbound", sender: { id: "owner" },
    space: { id: "dm", type: "dm", phone: "fallback" },
    content: { type: "text", text: "Please build it" }, timestamp: "2026-10-14T12:00:00Z" };
  assert.deepEqual(developmentObservation(input), {
    messageId: "sdk-1", direction: "inbound", sender: { id: "owner" }, space: { id: "dm", type: "dm" },
    nativeReplyTargetGuid: null, nativeThreadOriginatorGuid: null, nativeIsForward: null,
    content: { type: "text", text: "Please build it" }, timestamp: input.timestamp,
  });
  assert.equal(developmentObservation({ ...input, sender: {}, content: input.content }).sender.id, null);
  assert.equal(developmentObservation({ ...input, content: { type: "attachment" } }), null);
  const threaded = { ...input, content: { type: "reply", targetMessageId: "preview",
    content: { type: "text", text: "Please build it" } } };
  assert.equal(developmentObservation(threaded).content.text, "Please build it");
  const native = { ...threaded, nativeReplyTargetGuid: "preview-A", nativeThreadOriginatorGuid: "thread-B", nativeIsForward: false };
  assert.equal(developmentObservation(native).nativeReplyTargetGuid, "preview-A");
  assert.equal(developmentObservation(native).nativeThreadOriginatorGuid, "thread-B");
  assert.equal(developmentObservation(native).nativeIsForward, false);
  const fallback = { ...threaded, nativeThreadOriginatorGuid: "preview-A" };
  assert.equal(developmentObservation(fallback).nativeReplyTargetGuid, null);
});
