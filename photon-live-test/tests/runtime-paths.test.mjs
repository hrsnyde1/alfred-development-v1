import test from "node:test";
import assert from "node:assert/strict";
import { inputPaths } from "../src/runtime-paths.mjs";

test("systemd instance paths bind phase, credential directory, result and socket", () => {
  const env = { CREDENTIALS_DIRECTORY: "/run/credentials/photon-reply-test@initial.service",
    PHOTON_TEST_PHASE: "initial", PHOTON_TEST_RESULT_DIR: "/var/lib/photon-reply-test/initial",
    PHOTON_TEST_COMMAND_SOCKET: "/run/photon-reply-test-initial/control.sock" };
  assert.equal(inputPaths(env).credentials,
    "/run/credentials/photon-reply-test@initial.service/credentials.json");
  assert.throws(() => inputPaths({ ...env, PHOTON_TEST_RESULT_DIR: "/var/lib/other" }));
  assert.throws(() => inputPaths({ ...env, PHOTON_TEST_PHASE: "live" }));
  assert.throws(() => inputPaths({ ...env, CREDENTIALS_DIRECTORY: "/run/credentials/../other" }));
});
test("bwrap input layout remains fixed and mixed modes are rejected", () => {
  assert.equal(inputPaths({}).credentials, "/run/credentials.json");
  assert.throws(() => inputPaths({ PHOTON_TEST_COMMAND_SOCKET: "/tmp/control.sock" }));
});
