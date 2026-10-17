# Alfred Development V1 intake correction

This is a staged install candidate. The current session made no production
changes, started no Photon connection, and filed no real task. The older
`OPERATOR_MINIMAL_MIGRATION.md` manual `run-once` step is superseded for V1 by
the timer below. Its source, identity, registry, and single-connection gates
still apply.

## Corrections and boundaries

| Issue | Cause and correction |
| --- | --- |
| Delayed owner event | `IntakeGate._observe` retired every earlier observation when another owner message arrived. It now retains up to 16 exact SDK IDs and text digests for five minutes, retiring expired or capacity-evicted entries. A Hermes draft can ask for a preview only; a fresh native direct owner reply still controls filing. |
| Hermes request consistency | The sidecar observation and Hermes turn binding both use the same original SDK `messageId` and SHA-256 of the unwrapped text. No model-supplied identity or text is accepted. Existing staged adapter and binding tests cover ordinary and reply turns. |
| Socket traversal | The runtime directory's named client ACL entries had no effective traverse because its access mask was `---`. The unit now sets the access mask to `--x` on every start while retaining named `--x` entries and default socket ACL entries. `SO_PEERCRED` remains authoritative. |
| Nine-field draft | The Gateway envelope validator requires the nine exact keys, strict strings, an allowed task type, a single-line 5–120-character title, valid nonempty sections, and a checkbox in acceptance criteria. The Hermes tool schema now describes these constraints; the gate still validates the exact envelope and rejects invalid values. |
| Native confirmation | The gate stores `/send`'s outbound `messageId` and requires exact equality with the later original SDK `nativeReplyTargetGuid`, authorized sender, same DM, explicit `nativeIsForward=false`, affirmative text, fresh event ID, and five-minute window. The host must prove the SDK provides this equality for a real native Reply. |
| Gateway pickup | The existing `.dev/bin/gateway.py run-once` dispatcher had no automatic trigger. A systemd oneshot and five-second timer invoke that same dispatcher against the bound Hermes inbox. They do not start execution or introduce another Gateway. |
| Canonical ID | Only a `filed` record in the protected Gateway journal yields `task_id`; pending and rejected outcomes contain no invented ID. The dispatcher CLI test checks the canonical `T-0001` in a disposable repository and no second filing. |

## Staged files

- `../v1_1b/trusted_intake.py`: bounded event retention and expiry.
- `../v1_1b/plugin/__init__.py`: nine-field tool schema guidance.
- `units/alfred-development-intake.service`: access ACL mask correction.
- `units/alfred-development-gateway.service` and `.timer`: automatic existing dispatcher pickup.
- `../v1_1b/tests/test_intake.py`, `test_tool.py`, `test_patch.py`, `tests/test_intake_runtime_units.py`, and `../tests/test_native_reply_target_feasibility.py`: behavior and pinned-source tests.

## Operator installation

Perform the previously reviewed V1.1a/V1.1b single-connection migration and
protected registry binding first. Confirm the exact `dev-001` lab checkout,
Gateway patch, Hermes patch, native Spectrum patch, dedicated UIDs, and an empty
Hermes inbox. The approved operator must lift the existing `run-once` hold for
this isolated lab before enabling the timer. Do not run these commands against
the live host merely to exercise the staging candidate.

From this Development Lab root, after protected backups and source-hash review:

```sh
sudo install -d -m 0700 /var/backups/alfred-v1-intake-fix
sudo cp -a /usr/local/lib/alfred-v1.1/trusted_intake.py /var/backups/alfred-v1-intake-fix/trusted_intake.py
sudo cp -a /etc/systemd/system/alfred-development-intake.service /var/backups/alfred-v1-intake-fix/alfred-development-intake.service
if test -f /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/__init__.py; then sudo cp -a /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/__init__.py /var/backups/alfred-v1-intake-fix/plugin-init.py; fi
sudo install -o root -g root -m 0444 v1_1b/trusted_intake.py /usr/local/lib/alfred-v1.1/trusted_intake.py
sudo install -o root -g root -m 0644 v1_1_activation/units/alfred-development-intake.service /etc/systemd/system/alfred-development-intake.service
sudo install -o alfredmsg -g alfredmsg -m 0644 v1_1b/plugin/__init__.py /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/__init__.py
sudo install -o root -g root -m 0644 v1_1_activation/units/alfred-development-gateway.service /etc/systemd/system/alfred-development-gateway.service
sudo install -o root -g root -m 0644 v1_1_activation/units/alfred-development-gateway.timer /etc/systemd/system/alfred-development-gateway.timer
sudo systemd-analyze verify /etc/systemd/system/alfred-development-intake.service /etc/systemd/system/alfred-development-gateway.service /etc/systemd/system/alfred-development-gateway.timer
sudo systemctl daemon-reload
sudo systemctl restart alfred-development-intake.service
sudo systemctl restart alfred-hermes.service
```

Back up an existing Hermes plugin file separately if one exists. Restart only
the dedicated external-sidecar Hermes unit after confirming the original user
service is stopped and the single Photon connection remains the only one.
The gate restart clears any pending preview; the owner must send a fresh request.

## Targeted rollback

Stop automatic pickup first. Preserve the Gateway journal and any canonical task
for audit. Restore only the files replaced above, then restart the dedicated
services under the reviewed single-connection procedure:

```sh
sudo systemctl disable --now alfred-development-gateway.timer
sudo systemctl stop alfred-development-gateway.service
sudo install -o root -g root -m 0444 /var/backups/alfred-v1-intake-fix/trusted_intake.py /usr/local/lib/alfred-v1.1/trusted_intake.py
sudo install -o root -g root -m 0644 /var/backups/alfred-v1-intake-fix/alfred-development-intake.service /etc/systemd/system/alfred-development-intake.service
if test -f /var/backups/alfred-v1-intake-fix/plugin-init.py; then sudo install -o alfredmsg -g alfredmsg -m 0644 /var/backups/alfred-v1-intake-fix/plugin-init.py /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/__init__.py; else sudo unlink /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/__init__.py; fi
sudo unlink /etc/systemd/system/alfred-development-gateway.timer
sudo unlink /etc/systemd/system/alfred-development-gateway.service
sudo systemctl daemon-reload
sudo systemctl restart alfred-development-intake.service
sudo systemctl restart alfred-hermes.service
```

Remove the two new Gateway unit files only after the timer is disabled and stopped. Do not delete
the inbox envelope, journal, or task to hide a partially filed request.

## One live acceptance

1. With the timer disabled, restart the Intake gate twice. After each start,
   check `getfacl -cp /run/alfred-development-intake`: both named clients must
   have effective `--x`, the access `mask::--x`, and the socket must grant the
   two client UIDs connect access. Confirm `alfredmsg` and `alfredphoton` can
   connect and an unrelated UID cannot submit an observation or draft. Confirm
   ordinary iMessage text still works through the single Photon connection.
2. In the approved lab, run `sudo systemctl enable --now alfred-development-gateway.timer`
   with an empty inbox. The owner sends
   one natural-language `dev-001` software request. Verify the sidecar's
   original SDK event ID and text digest match the Hermes tool's turn binding.
   The gate sends a complete nine-field preview to that same DM; no envelope
   or task exists yet.
3. Send one unlinked or wrong-target `Yes, go ahead` and verify no envelope.
   Then use the iMessage **Reply** action on the exact preview within five
   minutes. Privately record the equality of `/send`'s outbound `messageId`
   and the new event's native `replyTargetGuid`; require explicit non-forwarded
   state. Stop if the provider does not expose this equality.
4. Verify exactly one `alfred.devreq/1` envelope appears; the timer invokes
   the existing Gateway `run-once` automatically and the journal records one
   `filed` outcome. Check one canonical `proposed` `T-NNNN` spec in the
   approved `dev-001` lab repository, `source: hermes`, no approval or
   execution state. Ask Alfred for status and compare its `task_id` to the
   filename and journal. Repeat the same confirmation and wait through another
   timer interval; no second task may appear. Do not run CTO, developer, QA,
   reviewer, or GitHub work.

The sandbox cannot validate live native Reply GUIDs, systemd activation, Unix
socket peer credentials, or named ACL application. Those are the exact host
checks above; no such pass is claimed from offline tests.
