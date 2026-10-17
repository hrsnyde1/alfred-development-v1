import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const forbidden = ["/home/alfred/.hermes", "/home/alfred/alfred-development-lab",
  "/home/alfred/.config", "/root", "/run/credentials.json"];
if (root !== "/app" || process.env.PHOTON_TEST_ISOLATED !== "1" ||
    forbidden.some((p) => fs.existsSync(p))) {
  process.stderr.write("FAIL: isolation probe\n");
  process.exit(1);
}
const core = import.meta.resolve("spectrum-ts");
const imessage = import.meta.resolve("spectrum-ts/providers/imessage");
if (![core, imessage].every((url) => fileURLToPath(url).startsWith("/app/"))) {
  process.stderr.write("FAIL: nonlocal SDK\n");
  process.exit(1);
}
process.stdout.write("PASS: isolated filesystem and copied SDK resolution; no connection\n");
