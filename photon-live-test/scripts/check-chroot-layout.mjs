import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const unit = fs.readFileSync(path.join(root, "same-server/photon-reply-test@.service"), "utf8");
function run(program, args) {
  const result = spawnSync(program, args, { encoding: "utf8" });
  if (result.status !== 0) throw new Error(`${program.toUpperCase()}_FAILED`);
  return result.stdout;
}
try {
  if (!unit.includes("RootDirectory=/srv/photon-reply-test/root") ||
      !unit.includes("BindReadOnlyPaths=/usr:/usr /etc/ssl/certs:/etc/ssl/certs") ||
      !unit.includes("ExecStart=/app/bin/node /app/src/runtime.mjs --live")) {
    throw new Error("UNIT_LAYOUT_CHANGED");
  }
  if (fs.readlinkSync("/lib") !== "usr/lib" || fs.readlinkSync("/lib64") !== "usr/lib64") {
    throw new Error("HOST_LIBRARY_SYMLINK_LAYOUT_CHANGED");
  }
  const node = path.join(root, "bin/node");
  const elf = run("/usr/bin/readelf", ["-l", node]);
  if (!elf.includes("/lib64/ld-linux-x86-64.so.2")) throw new Error("ELF_INTERPRETER_CHANGED");
  const ldd = run("/usr/bin/ldd", [node]);
  if (ldd.includes("not found")) throw new Error("NODE_LIBRARY_MISSING");
  const absolutePaths = [...ldd.matchAll(/\s(\/(?:lib|usr\/lib)[^\s()]+)/g)].map((match) => match[1]);
  if (absolutePaths.length < 2 || absolutePaths.some((item) => !fs.realpathSync(item).startsWith("/usr/"))) {
    throw new Error("NODE_LIBRARY_OUTSIDE_READONLY_OS_BIND");
  }
  if (!fs.existsSync("/etc/ssl/certs/ca-certificates.crt")) throw new Error("CA_BUNDLE_MISSING");
  process.stdout.write(`PASS: Node ELF interpreter and ${absolutePaths.length} linked libraries resolve through reviewed /usr bind; chroot execution pending\n`);
} catch (error) {
  process.stderr.write(`FAIL: ${error.message}\n`);
  process.exitCode = 1;
}
