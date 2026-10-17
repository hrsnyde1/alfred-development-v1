// Pure synthetic/live comparison policy. No SDK, filesystem, model or Gateway access.
export const PREVIEW_TEXT = Object.freeze({
  A: "LAB REPLY TEST A — no development request",
  B: "LAB REPLY TEST B — no development request",
  C: "LAB REPLY TEST C — no development request",
  D: "LAB REPLY TEST D — no development request",
  E: "LAB REPLY TEST E — no development request",
});

const CASES = new Set([
  "direct", "unthreaded", "unrelated", "overlap-c", "overlap-b",
  "delayed", "reconnect",
]);

function hasString(value) {
  return typeof value === "string" && value.length > 0 && value.length <= 256;
}

export function validateMetadata(meta) {
  const names = ["testAccountId", "productionAccountId", "testProjectId",
    "productionProjectId", "testLineId", "productionLineId", "testSenderId", "productionSenderId"];
  if (!meta || names.some((name) => !hasString(meta[name]))) throw new Error("INVALID_METADATA");
  if (meta.testAccountId === meta.productionAccountId ||
      meta.testProjectId === meta.productionProjectId ||
      meta.testLineId === meta.productionLineId ||
      meta.testSenderId === meta.productionSenderId || meta.lineMode !== "shared") {
    throw new Error("SEPARATION_NOT_ESTABLISHED");
  }
  const routing = meta.routingEvidence;
  if (routing?.senderLinePairBoundToTestProject !== true ||
      routing?.productionProjectExcludedForPair !== true ||
      !hasString(routing?.reviewer) || !hasString(routing?.reference)) {
    throw new Error("ROUTING_EVIDENCE_MISSING");
  }
  return meta;
}

export class ReplyTestProtocol {
  constructor(meta, { phase = "initial", nonce, delayMs = 300_000,
    expiryMs = 1_800_000, maxEvents = 128 } = {}) {
    validateMetadata(meta);
    if (!["initial", "reconnect"].includes(phase) || !hasString(nonce)) {
      throw new Error("INVALID_PROTOCOL_SETUP");
    }
    this.meta = meta;
    this.phase = phase;
    this.nonce = nonce;
    this.delayMs = delayMs;
    this.expiryMs = expiryMs;
    this.maxEvents = maxEvents;
    this.eventCount = 0;
    this.routeObserved = false;
    this.routeVerified = false;
    this.spaceId = null;
    this.previews = new Map();
    this.seen = new Set();
    this.expected = null;
    this.finished = new Set();
  }

  observe(event, now) {
    this.eventCount += 1;
    if (this.eventCount > this.maxEvents) throw new Error("EVENT_LIMIT");
    if (!event || event.direction !== "inbound" ||
        event.senderService !== "iMessage" ||
        event.senderId !== this.meta.testSenderId || event.spaceType !== "dm" ||
        !hasString(event.spaceId) || !hasString(event.messageId)) {
      return { kind: "ignored", code: "IDENTITY_OR_SHAPE" };
    }
    if (this.seen.has(event.messageId)) return { kind: "ignored", code: "DUPLICATE" };
    this.seen.add(event.messageId);
    if (!this.routeObserved) {
      if (event.text !== `LAB ROUTE ${this.nonce}`) return { kind: "ignored", code: "PREFLIGHT_MISMATCH" };
      this.routeObserved = true;
      this.spaceId = event.spaceId;
      return { kind: "preflight", code: "TEST_PROJECT_DELIVERY_OBSERVED" };
    }
    if (event.spaceId !== this.spaceId) return { kind: "ignored", code: "CONVERSATION_MISMATCH" };
    if (!this.routeVerified || !this.expected) return { kind: "ignored", code: "NO_ARMED_CASE" };
    const current = this.expected;
    this.expected = null;
    const result = this.#evaluate(current, event, now);
    if (result.pass) this.finished.add(current);
    return { kind: "case", case: current, outcome: result.pass ? "PASS" : "FAIL",
      directMatch: result.directMatch, threadOriginPresent: hasString(event.threadOriginatorGuid),
      code: result.code };
  }

  confirmRouting() {
    if (!this.routeObserved || this.routeVerified) throw new Error("ROUTE_PREFLIGHT_INCOMPLETE");
    // The operator must separately check the provider's sender+line routing
    // record and absence of production delivery before issuing route-ok.
    this.routeVerified = true;
  }

  canPreview(label) {
    if (!this.routeVerified || !Object.hasOwn(PREVIEW_TEXT, label) || this.previews.has(label)) {
      throw new Error("PREVIEW_NOT_ARMED");
    }
    if (this.phase === "reconnect" && label !== "E") throw new Error("WRONG_PHASE");
    if (this.phase === "initial" && label === "E") throw new Error("WRONG_PHASE");
  }

  recordPreview(label, messageId, now) {
    this.canPreview(label);
    if (!hasString(messageId) || [...this.previews.values()].some((p) => p.id === messageId)) {
      throw new Error("DUPLICATE_PREVIEW_ID");
    }
    this.previews.set(label, { id: messageId, sentAt: now });
  }

  arm(caseName) {
    if (!this.routeVerified || this.expected || !CASES.has(caseName) || this.finished.has(caseName)) {
      throw new Error("CASE_NOT_ARMED");
    }
    const required = {
      direct: ["A"], unthreaded: ["A"], unrelated: ["A", "B", "C"],
      "overlap-c": ["B", "C"], "overlap-b": ["B", "C"], delayed: ["D"],
      reconnect: ["E"],
    }[caseName];
    if (required.some((label) => !this.previews.has(label)) ||
        (this.phase === "reconnect") !== (caseName === "reconnect")) {
      throw new Error("CASE_PREREQUISITE_MISSING");
    }
    this.expected = caseName;
  }

  #evaluate(caseName, event, now) {
    const direct = event.replyTargetGuid;
    const target = (label) => this.previews.get(label)?.id;
    const match = (label) => hasString(direct) && direct === target(label);
    if (event.isForward !== false) return { pass: false, directMatch: false, code: "FORWARD_OR_UNKNOWN" };
    if (caseName === "direct") return { pass: match("A"), directMatch: match("A"), code: "DIRECT_A" };
    if (caseName === "unthreaded") {
      const pass = !hasString(direct);
      return { pass, directMatch: false, code: "UNTHREADED_DENIED" };
    }
    if (caseName === "unrelated") {
      const pass = hasString(direct) && !["A", "B", "C", "D", "E"].some(match);
      return { pass, directMatch: false, code: "UNRELATED_DENIED" };
    }
    if (caseName === "overlap-c" || caseName === "overlap-b") {
      const label = caseName === "overlap-c" ? "C" : "B";
      return { pass: match(label), directMatch: match(label), code: "OVERLAP_EXACT" };
    }
    if (caseName === "delayed") {
      const age = now - this.previews.get("D").sentAt;
      const pass = match("D") && age >= this.delayMs && age < this.expiryMs;
      return { pass, directMatch: match("D"), code: "DELAY_BOUND" };
    }
    return { pass: match("E"), directMatch: match("E"), code: "RECONNECT_FRESH" };
  }
}
