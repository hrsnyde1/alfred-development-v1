import net from "node:net";

// Future OS acceptance only. The standalone probe never loads Photon or credentials.
export function classifyNetworkResult(expected, result) {
  if (expected === "allow" && result === "connected") return "PASS";
  if (expected === "deny" && ["EACCES", "EPERM"].includes(result)) return "PASS";
  if (["timeout", "ECONNREFUSED", "ENETUNREACH", "EHOSTUNREACH"].includes(result)) return "INCONCLUSIVE";
  return "FAIL";
}

if (process.argv[1]?.endsWith("/os-network-probe.mjs")) {
  const [expected, host, rawPort] = process.argv.slice(2);
  const port = Number(rawPort);
  if (process.argv.length !== 5 || !["allow", "deny"].includes(expected) || net.isIP(host) === 0 ||
      !Number.isInteger(port) || port < 1 || port > 65535) {
    process.stderr.write("FAIL: probe arguments\n");
    process.exit(2);
  }
  const result = await new Promise((resolve) => {
    const socket = net.connect({ host, port, timeout: 3000 });
    socket.once("connect", () => { socket.destroy(); resolve("connected"); });
    socket.once("error", (error) => resolve(error.code || "error"));
    socket.once("timeout", () => { socket.destroy(); resolve("timeout"); });
  });
  const status = classifyNetworkResult(expected, result);
  process.stdout.write(`${status}: ${expected} ${result}\n`);
  process.exitCode = status === "PASS" ? 0 : status === "INCONCLUSIVE" ? 3 : 1;
}
