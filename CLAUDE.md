# inflation-station

When reporting information to me, be extremely concise and sacrifice grammar for the sake of concision.

## Before opening a PR

Run `make check` (lint, tests, and diff coverage vs `origin/main`: every changed line covered) and fix what fails. CI runs the same targets.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on novotl/inflation-station, using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Branch protection

Agents run as an author (default) or reviewer profile; only the reviewer merges (the owner merges PRs that touch guardrail paths), never `main` pushes or force-pushes. Before merging, pushing, or touching `.claude/`, see `docs/agents/branch-protection.md`.
