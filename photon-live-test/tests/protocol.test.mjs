import test from "node:test";
import assert from "node:assert/strict";
import { ReplyTestProtocol } from "../src/policy.mjs";
import { extractNativeEvent } from "../src/observer-core.mjs";
import { sendPreview } from "../src/sender.mjs";

const meta = { testAccountId: "test-account", productionAccountId: "prod-account",
  testProjectId: "test-project", productionProjectId: "prod-project",
  testLineId: "test-line", productionLineId: "prod-line", lineMode: "shared",
  testSenderId: "+15550000001", productionSenderId: "+15550000002", routingEvidence: {
    senderLinePairBoundToTestProject: true, productionProjectExcludedForPair: true,
    reviewer: "operator", reference: "private-record-1" } };
const base = { direction: "inbound", senderId: meta.testSenderId,
  senderService: "iMessage", spaceType: "dm", spaceId: "chat-1",
  isForward: false, text: "reply" };
let seq = 0;
function ev(extra = {}) { return { ...base, messageId: `event-${++seq}`, ...extra }; }
function ready(phase = "initial") {
  const p = new ReplyTestProtocol(meta, { phase, nonce: "abcdef", delayMs: 10, expiryMs: 100 });
  assert.equal(p.observe(ev({ text: "LAB ROUTE abcdef" }), 0).kind, "preflight");
  p.confirmRouting();
  return p;
}
function preview(p, labels) { for (const label of labels) p.recordPreview(label, `out-${label}`, 0); }
function outcome(p, name, e, now = 1) { p.arm(name); return p.observe(ev(e), now); }

test("direct target equals exact outbound preview", () => {
  const p = ready(); preview(p, ["A"]);
  assert.equal(outcome(p, "direct", { replyTargetGuid: "out-A", threadOriginatorGuid: "other" }).outcome, "PASS");
});
test("thread fallback never becomes direct reply authority", () => {
  const p = ready(); preview(p, ["A"]);
  assert.equal(outcome(p, "direct", { threadOriginatorGuid: "out-A" }).outcome, "FAIL");
});
test("unthreaded reply is observed but cannot match preview", () => {
  const p = ready(); preview(p, ["A"]);
  assert.equal(outcome(p, "unthreaded", { threadOriginatorGuid: "old-thread" }).outcome, "PASS");
});
test("unrelated direct target is denied", () => {
  const p = ready(); preview(p, ["A", "B", "C"]);
  assert.equal(outcome(p, "unrelated", { replyTargetGuid: "unrelated-message" }).outcome, "PASS");
  const q = ready(); preview(q, ["A", "B", "C"]);
  assert.equal(outcome(q, "unrelated", { replyTargetGuid: "out-B" }).outcome, "FAIL");
});
test("overlapping previews retain individual IDs", () => {
  const p = ready(); preview(p, ["B", "C"]);
  assert.equal(outcome(p, "overlap-c", { replyTargetGuid: "out-C" }).outcome, "PASS");
  assert.equal(outcome(p, "overlap-b", { replyTargetGuid: "out-B" }).outcome, "PASS");
  const q = ready(); preview(q, ["B", "C"]);
  assert.equal(outcome(q, "overlap-c", { replyTargetGuid: "out-B" }).outcome, "FAIL");
});
test("delayed reply has bounded age", () => {
  const p = ready(); preview(p, ["D"]);
  assert.equal(outcome(p, "delayed", { replyTargetGuid: "out-D" }, 10).outcome, "PASS");
  const q = ready(); preview(q, ["D"]);
  assert.equal(outcome(q, "delayed", { replyTargetGuid: "out-D" }, 101).outcome, "FAIL");
});
test("reconnect requires fresh preflight and fresh preview", () => {
  const p = ready("reconnect"); preview(p, ["E"]);
  assert.equal(outcome(p, "reconnect", { replyTargetGuid: "out-E" }).outcome, "PASS");
  const q = ready("reconnect"); preview(q, ["E"]);
  assert.equal(outcome(q, "reconnect", { replyTargetGuid: "old-outbound" }).outcome, "FAIL");
});
test("sender forgery, wrong service, chat and duplicate are rejected", () => {
  const p = ready(); preview(p, ["A"]); p.arm("direct");
  assert.equal(p.observe(ev({ senderId: "attacker", replyTargetGuid: "out-A" }), 1).kind, "ignored");
  assert.equal(p.observe(ev({ senderService: "SMS", replyTargetGuid: "out-A" }), 1).kind, "ignored");
  assert.equal(p.observe(ev({ spaceId: "other-chat", replyTargetGuid: "out-A" }), 1).kind, "ignored");
  const good = ev({ replyTargetGuid: "out-A" });
  assert.equal(p.observe(good, 1).outcome, "PASS");
  assert.equal(p.observe(good, 2).code, "DUPLICATE");
});
test("routing evidence and preflight are mandatory", () => {
  assert.throws(() => new ReplyTestProtocol({ ...meta, routingEvidence: {} }, { nonce: "x" }));
  const p = new ReplyTestProtocol(meta, { nonce: "x" });
  assert.throws(() => p.confirmRouting());
  assert.equal(p.observe(ev({ text: "LAB ROUTE wrong" }), 0).code, "PREFLIGHT_MISMATCH");
});
test("wrong-phase and repeated preview commands reject before sending", () => {
  const initial = ready();
  assert.throws(() => initial.canPreview("E"), /WRONG_PHASE/);
  initial.recordPreview("A", "out-A", 0);
  assert.throws(() => initial.canPreview("A"), /PREVIEW_NOT_ARMED/);
  const reconnect = ready("reconnect");
  assert.throws(() => reconnect.canPreview("A"), /WRONG_PHASE/);
});
test("event cap prevents unbounded observation", () => {
  const p = new ReplyTestProtocol(meta, { nonce: "x", maxEvents: 1 });
  p.observe(ev(), 0);
  assert.throws(() => p.observe(ev(), 0), /EVENT_LIMIT/);
});
test("native extraction ignores fallback target", () => {
  const value = extractNativeEvent({ id: "chat", type: "dm" }, {
    id: "m", sender: { id: meta.testSenderId, service: "iMessage" },
    direction: "inbound", nativeThreadOriginatorGuid: "thread",
    content: { type: "reply", target: { id: "forged" } } });
  assert.equal(value.replyTargetGuid, undefined);
  assert.equal(value.threadOriginatorGuid, "thread");
  assert.equal(value.text, undefined);
});
test("controlled sender uses fixed content and requires SDK ID", async () => {
  let sent;
  const id = await sendPreview({ send: async (content) => { sent = content; return { id: "sdk-id" }; } },
    "A", (text) => ({ type: "text", text }));
  assert.equal(id, "sdk-id");
  assert.match(sent.text, /LAB REPLY TEST A/);
  await assert.rejects(sendPreview({ send: async () => ({}) }, "A", (x) => x));
});
