import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = fs.mkdtempSync(path.join(root, ".unit-verify-"));
try {
  const chroot = path.join(temp, "root");
  fs.mkdirSync(path.join(chroot, "app/bin"), { recursive: true });
  fs.linkSync(path.join(root, "bin/node"), path.join(chroot, "app/bin/node"));
  const units = [];
  for (const name of ["photon-reply-test@.service", "photon-reply-probe@.service",
    "photon-reply-control-initial@.service", "photon-reply-control-reconnect@.service",
    "photon-reply-results@.service"]) {
    let unit = fs.readFileSync(path.join(root, "same-server", name), "utf8");
    unit = unit.replaceAll("/srv/photon-reply-test/root", chroot);
    // systemd-analyze verify checks Exec paths in the host namespace even when
    // RootDirectory is set. Rebase only those paths for parser verification.
    unit = unit.replaceAll("ExecStartPre=/app/bin/node ", `ExecStartPre=${root}/bin/node `)
      .replace("ExecStart=/app/bin/node ", `ExecStart=${root}/bin/node `);
    const unitPath = path.join(temp, name);
    fs.writeFileSync(unitPath, unit);
    units.push(unitPath);
  }
  const result = spawnSync("systemd-analyze", ["verify", ...units], { encoding: "utf8" });
  if (result.status !== 0) throw new Error((result.stdout + result.stderr).trim() || "UNIT_VERIFY_FAILED");
  process.stdout.write("PASS: systemd-analyze syntax verify with rebased executables; chroot execution requires OS test\n");
} catch (error) {
  process.stderr.write(`FAIL: ${error.message}\n`);
  process.exitCode = 1;
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
