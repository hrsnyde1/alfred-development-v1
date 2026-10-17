import fs from "node:fs";
import path from "node:path";

export function auditRuntimeCopy(root) {
  const base = fs.realpathSync(root);
  let files = 0;
  function inspect(item) {
    const st = fs.lstatSync(item);
    if (st.uid !== 0 || st.gid !== 0 || (!st.isSymbolicLink() && (st.mode & 0o022) !== 0)) {
      throw new Error("RUNTIME_COPY_NOT_ROOT_IMMUTABLE");
    }
    if (st.isSymbolicLink()) {
      const target = fs.readlinkSync(item);
      const resolved = fs.realpathSync(item);
      if (path.isAbsolute(target) || !resolved.startsWith(`${base}${path.sep}`)) {
        throw new Error("RUNTIME_COPY_SYMLINK_ESCAPE");
      }
    } else if (st.isDirectory()) {
      for (const child of fs.readdirSync(item)) inspect(path.join(item, child));
    } else if (st.isFile()) {
      if (st.nlink !== 1) throw new Error("RUNTIME_COPY_HARDLINK");
      files++;
    } else {
      throw new Error("RUNTIME_COPY_SPECIAL_FILE");
    }
  }
  inspect(base);
  return files;
}

if (process.argv[1] && path.resolve(process.argv[1]) === new URL(import.meta.url).pathname) {
  if (process.getuid() === 0) throw new Error("RUN_AUDIT_AS_TEST_UID_ONLY");
  if (process.argv.length !== 3) throw new Error("USE_ONE_RUNTIME_COPY_PATH");
  try {
    const count = auditRuntimeCopy(process.argv[2]);
    process.stdout.write(`PASS: root-owned runtime copy, ${count} regular files\n`);
  } catch {
    process.stderr.write("FAIL: runtime copy ownership or structure\n");
    process.exitCode = 1;
  }
}
