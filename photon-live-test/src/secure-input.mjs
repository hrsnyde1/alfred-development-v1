import fs from "node:fs";

export function readPrivateJson(path, { maxBytes = 8192, allowRootOwner = false } = {}) {
  if (typeof path !== "string" || !path.startsWith("/") || path.length > 512) {
    throw new Error("PRIVATE_INPUT_PATH_INVALID");
  }
  const stat = fs.lstatSync(path);
  const ownerAllowed = (uid) => uid === process.getuid() || (allowRootOwner && uid === 0);
  if (!stat.isFile() || stat.isSymbolicLink() || !ownerAllowed(stat.uid) ||
      (stat.mode & 0o077) !== 0 || stat.size > maxBytes) {
    throw new Error("PRIVATE_INPUT_PERMISSIONS_INVALID");
  }
  const fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const current = fs.fstatSync(fd);
    if (current.ino !== stat.ino || current.dev !== stat.dev || current.size > maxBytes ||
        !ownerAllowed(current.uid) || (current.mode & 0o077) !== 0) {
      throw new Error("PRIVATE_INPUT_CHANGED");
    }
    return JSON.parse(fs.readFileSync(fd, { encoding: "utf8" }));
  } finally {
    fs.closeSync(fd);
  }
}
