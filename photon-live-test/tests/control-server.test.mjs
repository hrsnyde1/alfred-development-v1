import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createControlServer } from "../src/control-server.mjs";

test("private control socket carries one bounded fixed command", async (t) => {
  const taskRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const dir = fs.mkdtempSync(path.join(taskRoot, ".control-test-"));
  let server;
  try {
    fs.chmodSync(dir, 0o700);
    const socketPath = path.join(dir, "s");
    try {
      server = await createControlServer(socketPath, async (command) => command === "status" ? "OK" : "DENIED");
    } catch (error) {
      if (error?.code === "EPERM") {
        t.skip("current sandbox denies AF_UNIX bind; run on separately authorized OS test host");
        return;
      }
      throw error;
    }
    assert.equal(fs.statSync(socketPath).mode & 0o777, 0o600);
    const result = await new Promise((resolve, reject) => {
      const socket = net.createConnection(socketPath);
      let data = "";
      socket.on("connect", () => socket.write("status\n"));
      socket.on("data", (chunk) => { data += chunk.toString(); });
      socket.on("end", () => resolve(data));
      socket.on("error", reject);
    });
    assert.equal(result, "OK\n");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
