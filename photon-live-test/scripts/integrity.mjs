import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (process.getuid() === 0) throw new Error("ROOT_EXECUTION_DENIED");
const manifestPath = path.join(root, "MANIFEST.sha256");
const skip = new Set(["MANIFEST.sha256"]);
const records = [];
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a,b) => a.name.localeCompare(b.name))) {
    const full = path.join(dir, entry.name);
    const rel = path.relative(root, full);
    if (skip.has(rel) || rel === "dist" || rel.startsWith(`dist${path.sep}`)) continue;
    const stat = fs.lstatSync(full);
    if (stat.isDirectory()) { walk(full); continue; }
    if (stat.isSymbolicLink()) {
      const target = fs.readlinkSync(full);
      const resolved = path.resolve(path.dirname(full), target);
      if (path.isAbsolute(target) || !resolved.startsWith(`${root}${path.sep}`) || !fs.existsSync(resolved)) {
        throw new Error("INVALID_SYMLINK");
      }
      records.push(`L ${createHash("sha256").update(target).digest("hex")} ${rel}`);
    } else if (stat.isFile()) {
      records.push(`F ${createHash("sha256").update(fs.readFileSync(full)).digest("hex")} ${rel}`);
    } else {
      throw new Error("UNEXPECTED_FILE_TYPE");
    }
  }
}
walk(root);
const value = `${records.sort().join("\n")}\n`;
if (process.argv[2] === "--write") {
  fs.writeFileSync(manifestPath, value, { mode: 0o644 });
  process.stdout.write(`WROTE ${records.length} entries\n`);
} else if (process.argv[2] === "--verify") {
  if (fs.readFileSync(manifestPath, "utf8") !== value) throw new Error("MANIFEST_MISMATCH");
  process.stdout.write(`PASS ${records.length} manifest entries\n`);
} else {
  throw new Error("USE_WRITE_OR_VERIFY");
}
