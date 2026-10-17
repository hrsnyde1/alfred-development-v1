import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import net from "node:net";
import test from "node:test";
import { developmentObservation, observeDevelopmentEvent } from "../sidecar/development-observe.mjs";

const event = {
  messageId: "mock-owner-event", direction: "inbound", sender: { id: "mock-owner" },
  space: { id: "mock-dm", type: "dm" }, nativeReplyTargetGuid: "mock-challenge-native-id",
  nativeIsForward: false, content: { type: "text", text: "mock-owner-approval" },
  timestamp: "2026-10-16T12:00:03Z",
};

async function mocked(fn) {
  const original = net.createConnection;
  const socket = new EventEmitter();
  let clock = 0, expires, timeout;
  const requests = [];
  socket.setTimeout = (ms, callback) => { expires = ms; timeout = callback; };
  socket.write = (body) => requests.push(JSON.parse(body));
  socket.destroy = () => { socket.destroyed = true; };
  net.createConnection = (options) => {
    assert.deepEqual(options, { path: "/mock/intake.sock" });
    process.nextTick(() => socket.emit("connect"));
    return socket;
  };
  try {
    await fn(socket, requests, (ms) => {
      clock += ms;
      if (clock >= expires && !socket.destroyed) timeout();
    });
  } finally { net.createConnection = original; }
}

test("early genuine reply survives a 20-second queued development ACK", async () => {
  await mocked(async (socket, requests, advance) => {
    const pending = observeDevelopmentEvent("/mock/intake.sock", event);
    await new Promise(resolve => process.nextTick(resolve));
    advance(20000); // No real sleeping, connection, send, or SDK client.
    assert.equal(socket.destroyed, undefined);
    assert.deepEqual(requests, [{ op: "observe", event: developmentObservation(event) }]);
    socket.emit("data", Buffer.from('{"ok":true,"state":"development_approved"}\n'));
    assert.deepEqual(await pending, { state: "development_approved" });
    assert.equal(socket.destroyed, true);
  });
});

test("observation remains bounded and does not reconnect or invent approval", async () => {
  await mocked(async (socket, requests, advance) => {
    const pending = observeDevelopmentEvent("/mock/intake.sock", event);
    await new Promise(resolve => process.nextTick(resolve));
    advance(44999);
    assert.equal(socket.destroyed, undefined);
    advance(1);
    assert.deepEqual(await pending, { state: "unavailable" });
    assert.equal(requests.length, 1);
  });
});

test("a refusal stays unavailable and preserves native identity without fallbacks", async () => {
  await mocked(async (socket, requests) => {
    const forwarded = { ...event, nativeIsForward: true };
    const pending = observeDevelopmentEvent("/mock/intake.sock", forwarded);
    await new Promise(resolve => process.nextTick(resolve));
    assert.equal(requests[0].event.nativeIsForward, true);
    assert.equal(requests[0].event.nativeReplyTargetGuid, event.nativeReplyTargetGuid);
    socket.emit("data", Buffer.from('{"ok":false,"error":"development_approval_refused"}\n'));
    assert.deepEqual(await pending, { state: "unavailable" });
    assert.equal(requests.length, 1);
  });
});
