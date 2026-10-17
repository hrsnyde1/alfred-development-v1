// Confined, unprivileged view of the observer's fixed privacy-safe records.
import fs from "node:fs";
import path from "node:path";

const maximum = { "control.txt": 24 * 1024, "results.ndjson": 32 * 1024 };
const controlPatterns = [
  /^Send exact preflight message from separate test sender to test line: LAB ROUTE [0-9a-f]{20}$/,
  /^After test-project receipt and independent no-production-delivery check: route-ok$/,
  /^Preflight observed\. Verify provider routing and production absence, then enter route-ok\.$/,
  /^(direct|unthreaded|unrelated|overlap-c|overlap-b|delayed|reconnect): (PASS|FAIL); direct match=(true|false); thread origin present=(true|false)$/,
  /^Routing gate open for fixed benign previews\.$/,
  /^Preview [A-E] sent; native outbound ID retained in memory only\.$/,
  /^Awaiting (direct|unthreaded|unrelated|overlap-c|overlap-b|delayed|reconnect) reply\.$/,
  /^phase=(initial|reconnect); route=(verified|pending); events=[0-9]{1,3}; cases=[0-9]{1,2}$/,
  /^Send uncertain or failed\. Stop session; do not retry this preview\.$/,
  /^Command rejected; see privacy-safe result code\.$/,
];
const codes = new Set(["BOOT", "ROUTE_OBSERVED", "ROUTE_VERIFIED", "PREVIEW_SENT",
  "CASE_ARMED", "CASE_RESULT", "IGNORED", "STREAM_UNAVAILABLE", "SEND_FAILED",
  "STOP", "INPUT_REJECTED", "LIMIT_REACHED"]);
const caseNames = new Set(["direct", "unthreaded", "unrelated", "overlap-c", "overlap-b", "delayed", "reconnect"]);
const reasons = new Set(["IDENTITY_OR_SHAPE", "DUPLICATE", "PREFLIGHT_MISMATCH",
  "CONVERSATION_MISMATCH", "NO_ARMED_CASE", "ENDED", "ERROR", "STARTUP",
  "A", "B", "C", "D", "E"]);

export function parseResultRecord(line) {
  const item = JSON.parse(line);
  if (!item || Array.isArray(item) || typeof item !== "object" ||
      !codes.has(item.code) || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(item.at) ||
      Object.keys(item).some((key) => !["at", "code", "case", "outcome", "directMatch", "threadOriginPresent", "reason"].includes(key)))
    throw new Error("UNSAFE_RESULT_RECORD");
  if (("case" in item && !caseNames.has(item.case)) ||
      ("outcome" in item && !["PASS", "FAIL"].includes(item.outcome)) ||
      ("reason" in item && !reasons.has(item.reason))) throw new Error("UNSAFE_RESULT_RECORD");
  for (const key of ["directMatch", "threadOriginPresent"]) {
    if (key in item && typeof item[key] !== "boolean") throw new Error("UNSAFE_RESULT_RECORD");
  }
  return item;
}

export function readFixedRecord(directory, filename, uid = process.getuid()) {
  if (!(filename in maximum)) throw new Error("INVALID_RESULT_NAME");
  const parent = fs.lstatSync(directory);
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== uid ||
      (parent.mode & 0o777) !== 0o700) throw new Error("RESULT_DIRECTORY_INVALID");
  const name = path.join(directory, filename);
  const before = fs.lstatSync(name);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 ||
      before.uid !== uid || (before.mode & 0o777) !== 0o600 ||
      before.size > maximum[filename]) throw new Error("RESULT_FILE_INVALID");
  const fd = fs.openSync(name, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW |
    fs.constants.O_NONBLOCK | fs.constants.O_CLOEXEC);
  try {
    const now = fs.fstatSync(fd);
    if (!now.isFile() || now.dev !== before.dev || now.ino !== before.ino ||
        now.uid !== uid || now.nlink !== 1 || now.size > maximum[filename] ||
        (now.mode & 0o777) !== 0o600) throw new Error("RESULT_FILE_CHANGED");
    const content = Buffer.alloc(maximum[filename] + 1);
    let count = 0;
    while (count < content.length) {
      const bytes = fs.readSync(fd, content, count, content.length - count, null);
      if (bytes === 0) break;
      count += bytes;
    }
    if (count > maximum[filename]) throw new Error("RESULT_TOO_LARGE");
    const text = new TextDecoder("utf-8", { fatal: true }).decode(content.subarray(0, count));
    if (text && !text.endsWith("\n")) throw new Error("RESULT_PARTIAL_RECORD");
    const lines = text ? text.trimEnd().split("\n") : [];
    if (lines.length > (filename === "control.txt" ? 80 : 128)) throw new Error("TOO_MANY_RESULTS");
    if (filename === "control.txt") {
      if (lines.some((line) => !controlPatterns.some((pattern) => pattern.test(line))))
        throw new Error("UNSAFE_CONTROL_RECORD");
      return lines;
    }
    return lines.map((line) => JSON.stringify(parseResultRecord(line)));
  } finally { fs.closeSync(fd); }
}

if (process.argv[1]?.endsWith("/read-results.mjs")) {
  if (process.getuid() === 0 || process.argv.length !== 3 ||
      !["initial", "reconnect"].includes(process.argv[2])) {
    process.stderr.write("DENIED\n");
    process.exit(2);
  }
  try {
    for (const name of ["control.txt", "results.ndjson"])
      for (const line of readFixedRecord("/results", name)) process.stdout.write(`${line}\n`);
  } catch {
    process.stderr.write("RESULTS_UNAVAILABLE_OR_UNSAFE\n");
    process.exitCode = 1;
  }
}
