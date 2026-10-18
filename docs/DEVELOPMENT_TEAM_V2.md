# Alfred Development Team v2: build plan

Owner's design (whiteboard, 2026-10-18) and decisions, and how the existing pipeline
grows into it. Each phase ships as pinned handoffs with tests, and is proven live on the
demo site before the next starts.

## The design

```
Hayden ──► Alfred ──► Dev CTO (Claude Opus) ──► squads (group chats) ──► QA ► Security* ► Review ──► live
   ▲          │                                                                                      │
   └── plan ◄─┘◄──────────────────────────────── "done" (+ link, reply "undo") ◄─────────────────────┘
```

**Owner sees exactly two messages:** the CTO's plan (reply "yes" to start) and "done"
(it is live; reply "undo" to revert). Nothing else.

| Squad | Members | Typical work |
| --- | --- | --- |
| Core Development | Builder, QA, Reviewer | Alfred's own gateway, bug fixes, small features (*later, with extra review*) |
| Web & Application | Frontend, Backend, Full Stack, QA | Websites, dashboards, internal apps |
| AI & Data | AI/ML, Data Scientist, Data Engineer | LLM features, agents, data pipelines, models |
| Integrations & Infrastructure | Integrations, Backend, QA, DevOps | Third-party APIs, infrastructure, deployment, monitoring |
| Security & Review | Security (lead), Reviewer, QA, DevOps | Code review, security testing, access control, deploy readiness |

| Agent | Model | Effort | Style |
| --- | --- | --- | --- |
| Dev CTO | Claude Opus | high | deliberate |
| Frontend | Claude Sonnet | medium | snappy |
| Backend | Claude Sonnet | high | balanced |
| Full Stack | Claude Sonnet | medium | balanced |
| Data Scientist | Claude Sonnet | high | deliberate |
| Data Engineer | Claude Sonnet | medium | balanced |
| AI/ML | Claude Opus | high | deliberate |
| DevOps | Claude Sonnet | high | balanced |
| Integrations | Claude Sonnet | medium | snappy |
| Builder | Claude Sonnet | medium | snappy |
| QA Engineer | Codex | medium | balanced |
| Security Engineer | Codex | high | deliberate |
| Code Reviewer | Codex | high | deliberate |

Every agent has `Soul.md`, `Role.md`, `Skills.md`, `Tools.md`, `Workflow.md`,
`Memory.md`, `Quality.md`, `Handoff.md`, drafted by Claude Code and reviewed by the owner
in the `hrsnyde1/alfred-team-skills` library (approved by merging, delivered as a pinned
snapshot, as team skills already are).

## Owner decisions (2026-10-18)
- Approve the plan, then "done" means live. Merge and deploy happen automatically
  after QA, Security (when required) and Review pass; "done" carries a one-tap undo.
- Claude runs through this server's Claude Code login (`claude -p`, headless, no tools;
  agents return structured edits, as Codex workers do today).
- Squad chats are internal and logged, mirrored read-only to Telegram groups.
- Security review is risk-based: always for auth, data, secrets, APIs, infrastructure or
  dependencies; skipped for purely visual changes.
- The team works on Alfred's own code later, with extra review.

## Phases

**1. Agents and models.**
- Claude provider in the developer runner, next to Codex. Each role gets the model, effort
  and style from the table.
- The 13 agents' identity files: drafted, owner-reviewed, then injected into each agent's
  instructions.
- A sandbox rule lets the Claude CLI keep its session state.
- *Proof:* the dark-mode task built by a Claude Sonnet frontend agent.

**2. The AI CTO and the plan message.**
- The CTO (Claude Opus) reads the repository and the request, then writes a structured plan:
  squads, tasks per agent, API/data contracts, milestones, acceptance criteria and risk.
- It also writes a short plain-language summary, which becomes your one approval text
  ("Here's the plan for … Reply yes"). That approval replaces today's preview step and the
  separate development step.
- *Proof:* the CTO correctly tells a frontend-only change from a full-stack one.

**3. Squads and chats.**
- One message board per task and squad. The CTO posts assignments and contracts, agents
  post progress, questions and handoffs, and the CTO answers and unblocks.
- Agents work in isolated worktrees, commit often, and push feature branches at milestones.
  The CTO integrates and resolves conflicts.
- A Telegram mirror (read-only, one group per squad) is added once you create the bot and
  groups.

**4. Security stage.**
- A risk-based Security Engineer (Codex, high), placed between QA and Review. Its findings
  feed the existing fix loop.

**5. Go live with undo.**
- After every check passes: merge to `main`, deploy (the local preview now, Vercel later),
  then "done" with the link.
- Reply "undo" to revert the merge and redeploy.
- The publication approval text goes away, per your decision. Your plan approval
  authorizes the whole job.

**6. Alfred's own repository (later).**
- The Core Development squad on Alfred's own code: Security review on every change, and
  your approval of each plan.

## Already working (handoffs 1 to 20)
Owner text → Alfred → canonical task → CTO plan → delegated approval → developers in
isolated worktrees → Independent QA → Reviewer → automatic fix loop (up to 3 rounds) →
draft PR → completion text, across multiple projects. Proven live with T-0009 (calculator)
and T-0003 (demo site: frontend build, Reviewer change request, fix round, approval).
