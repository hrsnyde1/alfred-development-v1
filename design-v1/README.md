# Natural-language Option B staging approval package

**Design only, 2026-10-14.** This package is the revised candidate for human
review. It changes no accepted ADR, authoritative Task A spec, installed
Hermes/Photon/Gateway component, service, credential, permission, task status
or release archive. The earlier `milestone2/proposals/` package and Task A
v0.1.2/v0.1.3 archives/reviews remain untouched historical records.

| File | Review purpose |
| --- | --- |
| `NATURAL_LANGUAGE_INTAKE_ARCHITECTURE.md` | Functional flow, all conversation states, exact owner confirmation binding, failure policy and token budget. |
| `ADR_0003_AMENDMENT_PROPOSED.md` | Candidate Phase 4 Gateway Front amendment; preserves canonical Gateway filing and approval rules. |
| `ADR_0009_LINUX_EXCEPTION_PROPOSED.md` | Candidate whole-process Linux exception and non-grants. |
| `TASK_A_REVISED_STAGING_SPEC.md` | Replacement Task A *draft* scope, exclusions, tests and acceptance blockers. |
| `TOPOLOGY_AND_BOUNDARIES.md` | Candidate identities, IPC, credentials, inbox and OS measurements. |
| `CTO_PLANNING_HANDOFF.md` | Future, separately authorized plan-only trigger and autonomy gates. |
| `APPROVAL_CHECKLIST.md` | Exact human architecture, protected-work and later release decisions. |

## Differences from preceding design

- Ordinary owner language replaces mandatory `/dev` request/confirm syntax.
- Personal Alfred drafts, while a protected gate checks source events and the
  owner's **threaded natural-language reply to an exact protected preview**.
- Hermes holds no request-submission authority and a live event handle alone
  is insufficient. General messaging does not acquire all-chat reply handles.
- Detected uncertainty requires a fresh authenticated resend or confirmation;
  full Photon history replay and perfect automatic recovery are deferred.
- Automatic CTO planning is a future Gateway-owned, plan-only stage, never an
  intake side effect. Human approval/execution/publication gates remain.

The critical open technical question is whether the deployed provider and
installed SDK preserve a trustworthy direct `replyTargetGuid` for the owner's
reply to a protected preview while the sidecar runs under a separate identity
with ordinary messaging intact. The source types show the field; live
reliability and whole-process isolation are unverified. If either fails,
the natural-language authorization path must not be enabled.
