# Isolated Photon native reply test runtime

Preparation only. This directory is a standalone Node observer with copied pinned SDK packages. It is not a Hermes gateway, has no Gateway code or credentials, and does not submit development requests. Nothing in this package starts a connection unless a human later runs `scripts/live-start.sh` after separate authorization.

For a separately approved test **on Alfred's existing Ubuntu server**, use [SAME_SERVER_TEST_PLAN.md](SAME_SERVER_TEST_PLAN.md), the [test-only operator candidate](same-server/OPERATOR_CANDIDATE.md), the [filesystem manifest](same-server/FILESYSTEM_PERMISSIONS.md), and the staged systemd/nft templates. The `live-start.sh` launcher remains reserved for a disposable host and intentionally refuses to run beside Personal Alfred.

The same-server installer requires an independently approved payload, manifest and gate digest held outside this writable staging tree. The current candidate is `dist/photon-reply-payload-v2.tar.gz`; `dist/PROPOSED_DIGESTS_v2.txt` is review evidence only. The historical payload and digest record remain unchanged. No copied Node binary or staging JavaScript is run as root. See [installer remediation](same-server/INSTALLER_REMEDIATION.md) and [network acceptance](same-server/NETWORK_ACCEPTANCE.md).

## Pinned contents and boundaries

- Copied Node 26.7.0; `spectrum-ts` 12.7.0, `@spectrum-ts/imessage` 12.7.0, and `@photon-ai/advanced-imessage` 2.1.0 with their pinned transitive `node_modules` and package lock.
- `patches/spectrum-native-reply-provenance.proposed.patch` is a copy of the corrected Task A patch. It has been applied only to the copied `vendor/node_modules/@spectrum-ts/imessage/dist/index.js` and declaration file. The installed original is not modified.
- The observer uses one SDK `app.messages` iterator and the test project credentials. It never starts Hermes, never imports from the installed sidecar, and never uses a second connection to Personal Alfred's project.
- `nativeReplyTargetGuid`, `nativeThreadOriginatorGuid`, and `nativeIsForward` remain separate. The fallback `content.target` cannot count as a direct reply.
- The launch namespace mounts `/app` read only, minimal system libraries and CA/DNS data, two operator supplied private input files, and a private result directory. It does not mount host home, production Hermes/Photon, Gateway, or repositories. If `bwrap` cannot create the namespace, the launch fails closed. Network isolation additionally requires a disposable host or VM with independently reviewed egress policy: `bwrap --share-net` shares that host's network, and the copied Node permission model does not provide a tested destination allowlist.

## Offline preparation and checks

From this directory:

```bash
./scripts/dry-run.sh
./scripts/isolation-probe.sh
```

The first command verifies every manifest entry, parses the full patched module, imports the copied SDK without credentials or a connection, and runs synthetic tests. The second requires a host that permits `bwrap` user namespaces; it verifies the actual mount view without credentials or network activity. **The current Codex sandbox denies nested namespace creation, so the host probe remains a separate acceptance gate.** Do not replace `bwrap` with an unrestricted launch to make the test work.

## Operator prerequisites for separately authorized live test

1. Use a disposable Photon account/project, its own project ID and project secret, and the separate test iMessage line. Do not reuse Personal Alfred credentials. Verify test account, project and line identifiers differ from production using provider configuration metadata; do not read production secrets.
2. Use a separate test sender identity from the production sender. Record it privately in metadata. Obtain provider evidence that the exact `(test line, test sender)` pair routes to the test project and is excluded from the production project. Project/account separation alone is insufficient for a shared line. If this mapping or the separate sender cannot be established, stop.
3. Have an independent way for the human operator to verify that the preflight message did not reach production. Do not use production credentials or ask this runtime to inspect production. If absence cannot be checked, stop before `route-ok`.
4. A **disposable host or VM without Personal Alfred installed** must pass `scripts/isolation-probe.sh`. It needs `bwrap` unprivileged user namespaces, the copied Node binary's architecture, `/usr`, `/lib`, `/lib64`, `/etc/ssl/certs`, `/etc/resolv.conf`, `/etc/hosts`, and network access to Photon. Its network boundary must deny access to production host/local services and protected internal networks while allowing only the provider endpoints needed by this test. Independently review and record that boundary before setting `PHOTON_TEST_NETWORK_BOUNDARY_CONFIRMED=1`. This environment is not established in the current sandbox. No Hermes installation, Gateway access, repository access, production service change or elevated permissions is needed.
5. Use private local files **outside this repository**. Create an owner-only directory in `$XDG_RUNTIME_DIR`; copy the two `.example.json` schemas there and fill them in using a local editor. Never put a secret in shell arguments, environment variables, command history, output capture, or a Codex prompt. `credentials.json` has only `projectId` and `projectSecret`; `metadata.json` has non-secret identifiers and private sender addresses. Both must be regular files owned by the operator with mode `0600`. The test project's `projectId` must match both files. Set routing evidence flags to `true` only after reviewing the provider record. No placeholders may remain.
6. Disable any test project webhook, automation, auto reply or delivery to a production endpoint in provider configuration. This runtime itself sends nothing automatically.

Example setup commands (paths contain no credentials):

```bash
umask 077
mkdir -m 700 "$XDG_RUNTIME_DIR/photon-reply-test"
install -m 600 credentials.example.json "$XDG_RUNTIME_DIR/photon-reply-test/credentials.json"
install -m 600 metadata.example.json "$XDG_RUNTIME_DIR/photon-reply-test/metadata.json"
${EDITOR:-vi} "$XDG_RUNTIME_DIR/photon-reply-test/credentials.json"
${EDITOR:-vi} "$XDG_RUNTIME_DIR/photon-reply-test/metadata.json"
```

Use a private result directory that does not yet exist. The launcher creates it with mode `0700`. Its path can be passed in environment variables; the secret values are never passed that way.

## Human-operated session

Only after separate live authorization and the offline host probe passes:

```bash
export PHOTON_TEST_CREDENTIAL_FILE="$XDG_RUNTIME_DIR/photon-reply-test/credentials.json"
export PHOTON_TEST_METADATA_FILE="$XDG_RUNTIME_DIR/photon-reply-test/metadata.json"
export PHOTON_TEST_RESULTS_DIR="$XDG_RUNTIME_DIR/photon-reply-test/initial-results"
export PHOTON_TEST_NETWORK_BOUNDARY_CONFIRMED=1
./scripts/live-start.sh
```

The launcher discards SDK stdout/stderr. In another terminal, inspect only the private control channel:

```bash
tail -f "$XDG_RUNTIME_DIR/photon-reply-test/initial-results/control.txt"
```

Send the printed `LAB ROUTE <nonce>` from the separate test sender to the test line. The observer must report test-project receipt. Independently verify the provider sender-line routing record and absence of production delivery; then type `route-ok` in the launch terminal. If any check fails or is unavailable, type `quit`. The shared-mode SDK uses a generic phone sentinel, so the observer cannot prove the physical line from `space.phone` alone.

The only outbound command is `preview A` through `preview E`; it sends a fixed benign text and keeps the SDK returned message ID only in memory. `expect <case>` arms one reply at a time. The result log records case/outcome and boolean native direct-target equality and thread-origin presence, never raw IDs, addresses, body, credentials or SDK diagnostics. The private control file contains the preflight nonce, fixed commands and boolean outcomes. Both files are capped. No read receipt is sent by this observer.

| Case | Operator sequence | Expected native result |
|---|---|---|
| Direct | `preview A`, `expect direct`; directly reply to A | `nativeReplyTargetGuid` equals A's returned ID |
| Unthreaded | `expect unthreaded`; send ordinary unthreaded text | No native direct target; a thread origin alone never authorizes |
| Unrelated target | `preview B`, `preview C`, `expect unrelated`; directly reply to a separate unrelated message in the same test chat | Native direct target exists but matches no test preview |
| Overlap | `expect overlap-c`; reply to C, then `expect overlap-b`; reply to B | C and B each match their own outbound ID |
| Delayed | `preview D`, `expect delayed`; directly reply to D after 5 minutes and before 30 minutes | Native direct target equals D within time bound |
| Reconnect | Type `quit`. Start a **new** isolated session with `PHOTON_TEST_PHASE=reconnect` and a new empty result directory; repeat fresh route preflight, then `preview E`, `expect reconnect`, directly reply to E | Fresh direct target equals E; old ID is never reused |

For reconnect, use:

```bash
export PHOTON_TEST_PHASE=reconnect
export PHOTON_TEST_RESULTS_DIR="$XDG_RUNTIME_DIR/photon-reply-test/reconnect-results"
./scripts/live-start.sh
```

`status` writes a bounded status line to the control file. `quit` calls SDK `app.stop()`. `Ctrl-C` or `SIGTERM` attempts a bounded clean stop. If a send times out or fails, its outcome is uncertain: stop, do not retry the same preview, and discard that run. If the stream ends, the runtime refuses further sends. A failed/uncertain result never counts as PASS.

## Acceptance, retention and cleanup

Each case passes only on an authenticated inbound event from the configured test sender, service `iMessage`, same DM conversation as preflight, with the exact expected native direct target. Any wrong or missing native target, unexpected forward status, replay, sender/service/chat mismatch or timeout fails or is ignored. A pass in this experiment supports native field behavior on this disposable account only; it does not establish owner authorization, provider delivery durability or production readiness.

Keep only `results.ndjson` and a redacted operator record of the provider mapping and no-production-delivery check. Review the private control file locally, then delete its nonce-bearing contents, private credentials, metadata and results according to the approved retention period. After the session is stopped, the operator can remove the private directory with `rm -r -- "$XDG_RUNTIME_DIR/photon-reply-test"`. Do not remove or alter any production path. Revocation of the disposable project secret and provider route is a separate human/provider cleanup action.
