# Branch protection and agent roles

Two layers keep `main` safe: a GitHub ruleset that nobody can bypass, and Claude Code permission profiles that split agents into an **author** and a **reviewer**.

## Server side (GitHub)

Ruleset on `main`, no bypass actors:

- Changes land only through a pull request, 0 approvals required.
- Squash merge only; linear history.
- Required status check `ci` (`.github/workflows/ci.yml`), branch must be up to date with `main`.
- No force-push, no deletion.

The repo is public, with interaction limits set to `collaborators_only`. The limit expires **2027-04-09**; renew it before then:

```sh
gh api -X PUT repos/novotl/inflation-station/interaction-limits -f limit=collaborators_only -f expiry=six_months
```

## Client side (Claude Code)

Both agents run under the owner's `gh` identity, so GitHub can't tell them apart. The role split lives in Claude Code permission rules.

| Role | Profile | May | Denied |
| --- | --- | --- | --- |
| Author | `.claude/settings.json` (loads automatically) | edit, commit, push feature branches, open PRs | `gh pr merge`, merge via `gh api`, push to `main`, force-push, `push --all/--mirror` |
| Reviewer | `.claude/reviewer-settings.json` | read PRs/issues/CI, COMMENT reviews with line comments (`gh api .../pulls/<n>/reviews`), close, `gh pr merge <n> --squash` | file edits, commits, any push, `--admin`, merge via `gh api` |

Launch the reviewer from the repo root:

```sh
claude --setting-sources user,local --settings .claude/reviewer-settings.json "Read .claude/skills/review-pr/SKILL.md and follow it for PR <n>"
```

Why this shape:

- Permission rules from every loaded settings file merge, and deny beats allow. With `--settings` alone, the author profile's `gh pr merge` deny still loads and blocks the reviewer. `--setting-sources user,local` skips the project `.claude/settings.json`.
- Skipping project settings also skips project skills, so `/review-pr` isn't available in that session. The prompt points the reviewer at the skill file instead.

Rules match command text, so they stop the forms an agent normally writes, not every possible spelling (`git -C . push origin main`, `bash -c '...'`). The ruleset is the hard boundary. A plain `git push` while checked out on `main` is also not caught client-side; the ruleset rejects it.

## Guardrail paths

The reviewer leaves these PRs for a human to merge, with a comment saying so:

- `.claude/**`, `.github/**`, `CLAUDE.md`, `.pre-commit-config.yaml`
- dependency changes in `pyproject.toml` or `uv.lock`

A PR that touches these can weaken the guardrails themselves, so the owner reviews and merges it.

## Future

Issue #3 proposes running the reviewer in GitHub Actions as `github-actions[bot]`. A separate identity allows a server-side "1 approval required" rule, so the author agent can't merge even past the client-side rules.
