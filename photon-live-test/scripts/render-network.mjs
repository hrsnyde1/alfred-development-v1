import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const template = fs.readFileSync(path.join(root, "same-server/network-allowlist.nft.in"), "utf8");

function publicIPv4(value) {
  const [a, b, c] = value.split(".").map(Number);
  if (a === 0 || a === 10 || a === 127 || a >= 224 || a === 169 && b === 254 ||
      a === 172 && b >= 16 && b <= 31 || a === 192 && (b === 168 || b === 0 || b === 88 && c === 99) ||
      a === 100 && b >= 64 && b <= 127 || a === 198 && (b === 18 || b === 19 || b === 51 && c === 100) ||
      a === 203 && b === 0 && c === 113) return false;
  return true;
}

export function renderNetwork({ uid, ipv4 = [], ipv6 = [] }) {
  if (!Number.isSafeInteger(uid) || uid < 100 || uid > 4294967294) throw new Error("TEST_UID_INVALID");
  if (!Array.isArray(ipv4) || !Array.isArray(ipv6) || ipv4.length + ipv6.length < 1 ||
      ipv4.length + ipv6.length > 16) throw new Error("PROVIDER_IP_SET_INVALID");
  const unique4 = [...new Set(ipv4)].sort();
  const unique6 = [...new Set(ipv6.map((ip) => ip.toLowerCase()))].sort();
  if (unique4.some((ip) => net.isIP(ip) !== 4 || !publicIPv4(ip)) ||
      unique6.some((ip) => net.isIP(ip) !== 6 || !/^[23]/.test(ip) ||
        ip.startsWith("2001:db8:") || ip.startsWith("2001:0:"))) {
    throw new Error("PROVIDER_IP_NOT_PUBLIC_NUMERIC");
  }
  const rules = [];
  if (unique4.length) rules.push(`add rule inet alfred_photon_reply_test test_egress ip daddr { ${unique4.join(", ")} } tcp dport 443 counter accept`);
  if (unique6.length) rules.push(`add rule inet alfred_photon_reply_test test_egress ip6 daddr { ${unique6.join(", ")} } tcp dport 443 counter accept`);
  return template.replace("__TEST_UID__", String(uid)).replace("__ALLOW_RULES__", rules.join("\n"));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.getuid() === 0) throw new Error("RUN_RENDERER_AS_TEST_UID_ONLY");
  // Input is a nonsecret, operator-reviewed JSON file; output goes to stdout for redirection.
  if (process.argv.length !== 4) throw new Error("USE_POLICY_JSON_AND_ACTUAL_TEST_UID");
  const input = fs.readFileSync(process.argv[2], "utf8");
  if (input.length > 4096) throw new Error("POLICY_INPUT_TOO_LARGE");
  const policy = JSON.parse(input);
  if (String(policy.uid) !== process.argv[3]) throw new Error("TEST_UID_DOES_NOT_MATCH_SERVICE_ACCOUNT");
  process.stdout.write(renderNetwork(policy));
}
