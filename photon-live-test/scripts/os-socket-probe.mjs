import fs from "node:fs";
import { createControlServer } from "../src/control-server.mjs";

const phase = process.argv[2];
if (phase !== "local") throw new Error("PROBE_PHASE_INVALID");
const socket = "/run/photon-reply-probe-local/control.sock";
let server;
try {
  server = await createControlServer(socket, async () => "DENIED");
  if ((fs.statSync(socket).mode & 0o777) !== 0o600) throw new Error("SOCKET_MODE_INVALID");
  process.stdout.write("PASS: AF_UNIX control socket bound under SocketBindDeny\n");
} catch {
  process.stderr.write("FAIL: AF_UNIX control socket bind\n");
  process.exitCode = 1;
} finally {
  if (server) await new Promise((resolve) => server.close(resolve));
  try { fs.unlinkSync(socket); } catch { /* systemd removes runtime directory on stop */ }
}
