import path from "node:path";

// Pure layout contract for disposable bwrap and same-server systemd modes.
export function inputPaths(env) {
  const credentialsDirectory = env.CREDENTIALS_DIRECTORY;
  if (credentialsDirectory) {
    const phase = env.PHOTON_TEST_PHASE;
    if (phase !== "initial" && phase !== "reconnect") throw new Error("SYSTEMD_PHASE_INVALID");
    const resultDir = `/var/lib/photon-reply-test/${phase}`;
    const socket = `/run/photon-reply-test-${phase}/control.sock`;
    if (credentialsDirectory !== `/run/credentials/photon-reply-test@${phase}.service` ||
        env.PHOTON_TEST_RESULT_DIR !== resultDir ||
        env.PHOTON_TEST_COMMAND_SOCKET !== socket) {
      throw new Error("SYSTEMD_PATHS_INVALID");
    }
    return { credentials: path.join(credentialsDirectory, "credentials.json"),
      metadata: path.join(credentialsDirectory, "metadata.json"),
      results: resultDir };
  }
  if (env.PHOTON_TEST_RESULT_DIR || env.PHOTON_TEST_COMMAND_SOCKET) {
    throw new Error("MIXED_RUNTIME_MODE");
  }
  return { credentials: "/run/credentials.json", metadata: "/run/metadata.json",
    results: "/run/results" };
}
