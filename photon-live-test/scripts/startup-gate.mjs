import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { inputPaths } from "../src/runtime-paths.mjs";
import { readPrivateJson } from "../src/secure-input.mjs";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export function checkStartup(env, uid = process.getuid()) {
  if (env.PHOTON_TEST_ISOLATED !== "1" || uid === 0 || appRoot !== "/app" ||
      fs.existsSync("/home/alfred/.hermes") || fs.existsSync("/home/alfred/alfred-development-lab")) {
    throw new Error("ISOLATION_OR_UID_INVALID");
  }
  const paths = inputPaths(env);
  return validateStartupMaterial(paths, env.PHOTON_TEST_COMMAND_SOCKET, uid,
    Boolean(env.CREDENTIALS_DIRECTORY));
}

export function validateStartupMaterial(paths, socket, uid, allowRootOwner = false) {
  const credentials = readPrivateJson(paths.credentials, { allowRootOwner });
  const metadata = readPrivateJson(paths.metadata, { allowRootOwner });
  if (typeof credentials.projectId !== "string" || !credentials.projectId ||
      typeof credentials.projectSecret !== "string" || !credentials.projectSecret ||
      credentials.projectId !== metadata.testProjectId) throw new Error("PROJECT_BINDING_INVALID");
  const result = fs.lstatSync(paths.results);
  if (!result.isDirectory() || result.isSymbolicLink() || result.uid !== uid ||
      (result.mode & 0o077) !== 0) throw new Error("RESULT_DIRECTORY_INVALID");
  if (socket) {
    const directory = fs.lstatSync(path.dirname(socket));
    if (!directory.isDirectory() || directory.isSymbolicLink() || directory.uid !== uid ||
        (directory.mode & 0o077) !== 0 || fs.existsSync(socket)) {
      throw new Error("COMMAND_SOCKET_DIRECTORY_INVALID");
    }
  }
  return true;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    checkStartup(process.env);
    process.stdout.write("PASS: test-only startup gate\n");
  } catch {
    process.stderr.write("FAIL: test-only startup gate\n");
    process.exitCode = 1;
  }
}
