# inflation-station

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on novotl/inflation-station, using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Branch protection

Agents run as an author (default) or reviewer profile; only the reviewer merges, never `main` pushes or force-pushes. Before merging, pushing, or touching `.claude/`, see `docs/agents/branch-protection.md`.
