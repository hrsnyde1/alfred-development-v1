# handoff.32 host procedure: each specialist gets only its own team skills

## Why
Owner's instruction, 2026-10-19: "Yes lets build these out", after a review found that
every specialist on a task received the whole task's team skills. On a frontend and
integration task, the frontend developer also got the integration skills, and the
integration developer got the usability skill.

## What changes for the development team
The Central CTO plan still records every team skill the task needs, by id and SHA-256,
exactly as before, and your development approval still fixes that text. At development
time each specialist now receives only its share:

- a skill that names some of the task's specialists (`applies_to.specialists`) goes only
  to them;
- a general skill, or one matched by a word in the task's title or objective, goes to
  every specialist on the task;
- any other recorded skill goes to no one.

The split is worked out only from the approved plan, the approved request and the pinned
library commit the plan names, so nothing outside your approval decides it. Plans
approved before this install keep working unchanged.

The library side (hrsnyde1/alfred-team-skills) lists the core squad's `builder`, `qa` and
`code_reviewer` as specialists that skills can name; that is a library change, delivered
with the library's own deploy tool.

## What changes (two files, nothing restarts)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/team_skills.py` | Adds `for_specialists()`, the per-specialist split |
| `/opt/alfred-developer-v1/developer_v1/pipeline.py` | Hands each Developer worker its own share; checks the practices size per specialist |

The pipeline runs once per approved task, so the next task uses the new code. No service
restarts.

## Before installing
Nothing to prepare. The installer refuses unless both files and their ten dependencies
are exactly the bytes installed through handoff.31.

Team skills stay off until a CTO library snapshot is delivered (see the library README,
"Delivering approved skills"). Until then this release changes nothing a task does.

## Install
See [RELEASE.md](RELEASE.md): `sudo alfred-dev-ops pause`, `sudo alfred-dev-ops install 32`,
`sudo alfred-dev-ops resume`.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 32`. It restores both files.
