// Fixed-command client for the chrooted, test-UID systemd control units only.
import net from "node:net";

const [phase, token] = process.argv.slice(2);
const fixed = new Map([
  ["route-ok", "route-ok"], ["status", "status"], ["quit", "quit"],
  ...["A", "B", "C", "D", "E"].map((label) => [`preview-${label}`, `preview ${label}`]),
  ...["direct", "unthreaded", "unrelated", "overlap-c", "overlap-b", "delayed", "reconnect"]
    .map((name) => [`expect-${name}`, `expect ${name}`]),
]);

export function fixedControl(phaseName, commandToken) {
  if (!["initial", "reconnect"].includes(phaseName) || !fixed.has(commandToken))
    throw new Error("INVALID_FIXED_COMMAND");
  return { socket: `/run/photon-reply-test-${phaseName}/control.sock`, command: fixed.get(commandToken) };
}

if (process.argv[1]?.endsWith("/operator-control.mjs")) {
  if (process.getuid() === 0 || process.argv.length !== 4) {
    process.stderr.write("DENIED\n");
    process.exit(2);
  }
  let request;
  try { request = fixedControl(phase, token); }
  catch { process.stderr.write("DENIED\n"); process.exit(2); }
  const client = net.createConnection(request.socket);
  let finished = false;
  const finish = (ok) => {
    if (finished) return;
    finished = true;
    process.stdout.write(`${ok ? "OK" : "DENIED"}\n`);
    process.exitCode = ok ? 0 : 1;
    client.destroy();
  };
  client.setTimeout(5000, () => finish(false));
  client.once("connect", () => client.write(`${request.command}\n`));
  client.once("data", (data) => finish(data.toString("utf8").trim() === "OK"));
  client.once("error", () => finish(false));
}
