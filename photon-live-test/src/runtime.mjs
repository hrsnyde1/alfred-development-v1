import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import readline from "node:readline";
import { ReplyTestProtocol } from "./policy.mjs";
import { extractNativeEvent } from "./observer-core.mjs";
import { sendPreview } from "./sender.mjs";
import { readPrivateJson } from "./secure-input.mjs";
import { inputPaths } from "./runtime-paths.mjs";
import { createControlServer } from "./control-server.mjs";
import { checkStartup } from "../scripts/startup-gate.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const codes = new Set(["BOOT", "ROUTE_OBSERVED", "ROUTE_VERIFIED", "PREVIEW_SENT",
  "CASE_ARMED", "CASE_RESULT", "IGNORED", "STREAM_UNAVAILABLE", "SEND_FAILED",
  "STOP", "INPUT_REJECTED", "LIMIT_REACHED"]);

function importPathIsLocal(url) {
  const target = fileURLToPath(url);
  return target.startsWith(`${root}${path.sep}`);
}

async function loadSdk() {
  const coreUrl = import.meta.resolve("spectrum-ts");
  const providerUrl = import.meta.resolve("spectrum-ts/providers/imessage");
  if (!importPathIsLocal(coreUrl) || !importPathIsLocal(providerUrl)) throw new Error("NONLOCAL_SDK_IMPORT");
  const [core, provider] = await Promise.all([import(coreUrl), import(providerUrl)]);
  if (typeof core.Spectrum !== "function" || typeof core.text !== "function" ||
      typeof provider.imessage?.config !== "function") throw new Error("SDK_IMPORT_SHAPE");
  return { ...core, imessage: provider.imessage };
}

function assertIsolated() {
  if (process.env.PHOTON_TEST_ISOLATED !== "1" || root !== "/app" ||
      fs.existsSync("/home/alfred/.hermes") || fs.existsSync("/home/alfred/alfred-development-lab")) {
    throw new Error("ISOLATION_NOT_ESTABLISHED");
  }
}

function privateLog(resultDir) {
  const fd = fs.openSync(path.join(resultDir, "results.ndjson"),
    fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW,
    0o600);
  let count = 0;
  return (code, details = {}) => {
    if (!codes.has(code) || count >= 128) return;
    const safe = { at: new Date().toISOString(), code };
    for (const key of ["case", "outcome", "directMatch", "threadOriginPresent", "reason"]) {
      const val = details[key];
      if (typeof val === "boolean" || (typeof val === "string" && val.length <= 40 && /^[A-Z_a-z0-9-]+$/.test(val))) safe[key] = val;
    }
    fs.writeSync(fd, `${JSON.stringify(safe)}\n`);
    fs.fsyncSync(fd);
    count++;
  };
}

function privateControl(resultDir) {
  const fd = fs.openSync(path.join(resultDir, "control.txt"),
    fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW,
    0o600);
  let lines = 0;
  return (message) => {
    if (lines >= 80 || message.length > 260) return;
    fs.writeSync(fd, `${message}\n`);
    fs.fsyncSync(fd);
    lines++;
  };
}

async function runLive(sdk) {
  assertIsolated();
  checkStartup(process.env);
  const paths = inputPaths(process.env);
  const allowRootOwner = Boolean(process.env.CREDENTIALS_DIRECTORY);
  const credentials = readPrivateJson(paths.credentials, { allowRootOwner });
  const meta = readPrivateJson(paths.metadata, { allowRootOwner });
  if (typeof credentials.projectId !== "string" || !credentials.projectId ||
      typeof credentials.projectSecret !== "string" || !credentials.projectSecret ||
      credentials.projectId !== meta.testProjectId) throw new Error("CREDENTIAL_PROJECT_MISMATCH");
  const phase = process.env.PHOTON_TEST_PHASE ?? "initial";
  if (phase !== "initial" && phase !== "reconnect") throw new Error("PHASE_INVALID");
  const resultsStat = fs.lstatSync(paths.results);
  if (!resultsStat.isDirectory() || resultsStat.isSymbolicLink() ||
      resultsStat.uid !== process.getuid() || (resultsStat.mode & 0o077) !== 0) {
    throw new Error("RESULT_DIRECTORY_INVALID");
  }
  const protocol = new ReplyTestProtocol(meta, { phase, nonce: randomBytes(10).toString("hex") });
  const log = privateLog(paths.results);
  const emit = privateControl(paths.results);
  let app;
  let testSpace;
  let stopping = false;
  let streamAvailable = true;
  let sends = 0;
  let commandServer;
  let handleCommand;
  let inputReader;
  let finish;
  const finished = new Promise((resolve) => { finish = resolve; });
  log("BOOT");
  emit(`Send exact preflight message from separate test sender to test line: LAB ROUTE ${protocol.nonce}`);
  emit("After test-project receipt and independent no-production-delivery check: route-ok");
  try {
    if (process.env.PHOTON_TEST_COMMAND_SOCKET) {
      commandServer = await createControlServer(process.env.PHOTON_TEST_COMMAND_SOCKET,
        (input) => handleCommand ? handleCommand(input) : "DENIED");
    }
    app = await sdk.Spectrum({ projectId: credentials.projectId,
      projectSecret: credentials.projectSecret, providers: [sdk.imessage.config()],
      options: { flattenGroups: true, logLevel: "silent" }, telemetry: false });
    // Credentials remain in local scope. Never print SDK errors; provider diagnostics
    // are suppressed by the outer launcher and not captured as evidence.
    const consume = async () => {
      try {
        for await (const [space, message] of app.messages) {
          if (stopping) break;
          const event = extractNativeEvent(space, message);
          const result = protocol.observe(event, Date.now());
          if (result.kind === "preflight") {
            testSpace = space;
            log("ROUTE_OBSERVED");
            emit("Preflight observed. Verify provider routing and production absence, then enter route-ok.");
          } else if (result.kind === "case") {
            log("CASE_RESULT", result);
            emit(`${result.case}: ${result.outcome}; direct match=${result.directMatch}; thread origin present=${result.threadOriginPresent}`);
          } else {
            log("IGNORED", { reason: result.code });
          }
        }
        if (!stopping) { streamAvailable = false; log("STREAM_UNAVAILABLE", { reason: "ENDED" }); }
      } catch {
        if (!stopping) { streamAvailable = false; log("STREAM_UNAVAILABLE", { reason: "ERROR" }); }
      }
    };
    void consume();
    const stop = async () => {
      if (stopping) return;
      stopping = true;
      inputReader?.close();
      commandServer?.close();
      log("STOP");
      await Promise.race([app.stop(), new Promise((_, reject) =>
        setTimeout(() => reject(new Error("STOP_TIMEOUT")), 5000))]);
      finish();
    };
    process.once("SIGINT", () => { void stop().then(() => process.exit(0), () => process.exit(1)); });
    process.once("SIGTERM", () => { void stop().then(() => process.exit(0), () => process.exit(1)); });
    handleCommand = async (input) => {
      const command = input.trim();
      try {
        if (!streamAvailable && command !== "quit" && command !== "status") {
          throw new Error("STREAM_UNAVAILABLE");
        }
        if (command === "quit") { await stop(); return "OK"; }
        if (command === "route-ok") {
          protocol.confirmRouting();
          log("ROUTE_VERIFIED");
          emit("Routing gate open for fixed benign previews.");
        } else if (/^preview [A-E]$/.test(command)) {
          if (sends >= 5 || !protocol.routeVerified || !testSpace) throw new Error("PREVIEW_LIMIT_OR_ROUTE");
          const label = command.slice(-1);
          protocol.canPreview(label);
          const messageId = await Promise.race([
            sendPreview(testSpace, label, sdk.text),
            new Promise((_, reject) => setTimeout(() => reject(new Error("SEND_TIMEOUT")), 15000)),
          ]);
          protocol.recordPreview(label, messageId, Date.now());
          sends++;
          log("PREVIEW_SENT", { reason: label });
          emit(`Preview ${label} sent; native outbound ID retained in memory only.`);
        } else if (/^expect (direct|unthreaded|unrelated|overlap-c|overlap-b|delayed|reconnect)$/.test(command)) {
          const caseName = command.slice(7);
          protocol.arm(caseName);
          log("CASE_ARMED", { case: caseName });
          emit(`Awaiting ${caseName} reply.`);
        } else if (command === "status") {
          emit(`phase=${phase}; route=${protocol.routeVerified ? "verified" : "pending"}; events=${protocol.eventCount}; cases=${protocol.finished.size}`);
        } else {
          throw new Error("INVALID_COMMAND");
        }
      } catch {
        if (command.startsWith("preview ")) {
          streamAvailable = false;
          log("SEND_FAILED");
          emit("Send uncertain or failed. Stop session; do not retry this preview.");
        } else {
          log("INPUT_REJECTED");
          emit("Command rejected; see privacy-safe result code.");
        }
        return "DENIED";
      }
      return "OK";
    };
    if (process.env.PHOTON_TEST_COMMAND_SOCKET) {
      await finished;
    } else {
      inputReader = readline.createInterface({ input: process.stdin, terminal: false });
      for await (const input of inputReader) await handleCommand(input);
      if (!stopping) await stop();
    }
  } catch {
    stopping = true;
    inputReader?.close();
    commandServer?.close();
    if (app) {
      await Promise.race([app.stop(), new Promise((_, reject) =>
        setTimeout(() => reject(new Error("STOP_TIMEOUT")), 5000))]).catch(() => {});
    }
    log("STREAM_UNAVAILABLE", { reason: "STARTUP" });
    throw new Error("LIVE_RUNTIME_FAILED");
  }
}

if (process.argv.length !== 3 || !["--dry-run", "--live"].includes(process.argv[2])) {
  process.stderr.write("Use --dry-run or --live.\n");
  process.exitCode = 2;
} else {
  try {
    const sdk = await loadSdk();
    if (process.argv[2] === "--dry-run") {
      process.stdout.write("PASS: copied SDK import, local path, no connection\n");
    } else {
      await runLive(sdk);
    }
  } catch {
    process.stderr.write("FAIL: isolated runtime validation or operation\n");
    process.exitCode = 1;
  }
}
