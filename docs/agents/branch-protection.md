# Branch protection and agent roles

Two layers keep `main` safe: a GitHub ruleset with no bypass actors, and Claude Code permission profiles that split agents into an **author** and a **reviewer**. The agents run as the repo owner, and that identity could still edit or delete the ruleset, so both profiles deny changing it (or branch protection) through `gh api`.

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
| Author | `.claude/settings.json` (loads automatically) | edit, commit, push feature branches, open PRs | `gh pr merge`, merge via `gh api`, push to `main`, force-push, `push --all/--mirror`, rulesets and branch protection via `gh api` |
| Reviewer | `.claude/reviewer-settings.json` | read PRs/issues/CI, COMMENT reviews with line comments (`gh api .../pulls/<n>/reviews`), close, `gh pr merge <n> --squash` | file edits, commits, any push, `--admin`, `--auto`, approve/request-changes (`gh pr review --approve/-a`, `--request-changes/-r`, `gh api` with `APPROVE`/`REQUEST_CHANGES`), merge via `gh api`, rulesets and branch protection via `gh api` |

Launch the reviewer from the repo root:

```sh
claude --setting-sources user,local --settings .claude/reviewer-settings.json "Read .claude/skills/review-pr/SKILL.md and follow it for PR <n>"
```

Why this shape:

- Permission rules from every loaded settings file merge, and deny beats allow. With `--settings` alone, the author profile's `gh pr merge` deny still loads and blocks the reviewer. `--setting-sources user,local` skips the project `.claude/settings.json`.
- Skipping project settings also skips project skills, so `/review-pr` isn't available in that session. The prompt points the reviewer at the skill file instead.
- The merge-via-`gh api` denies and the ruleset denies appear in both profiles because the reviewer session doesn't load `.claude/settings.json`. Keep the two blocks in sync.
- The `gh api` allow rule and the skill hardcode `novotl/inflation-station` on purpose: it scopes the allow rule to this repo's reviews endpoint.

Rules match command text, so they stop the forms an agent normally writes, not every possible spelling (`git -C . push origin main`, `bash -c '...'`). The ruleset is the hard boundary. A plain `git push` while checked out on `main` is also not caught client-side; the ruleset rejects it. The reviewer also denies `gh api *APPROVE*` and `gh api *REQUEST_CHANGES*`, so a `gh api .../reviews` call can't request either event. The trade-off: a review whose text contains either word is denied too, and the reviewer must reword it. The deny is the first line; GitHub's rejection of self-approval is the fallback for spellings the rules miss: matching is case-sensitive (checked headlessly), so a lowercase event value is not caught, and neither is an event passed in a `--input` file. The merge-via-`gh api` denies are anchored to a path that ends in `/merge` (`gh api *pulls/*/merge` and `gh api *pulls/*/merge *`), because rules match the whole command text, heredoc included. A review that mentions `src/merge.py` or a `merge-x` branch posts fine, but one whose text contains `/merge` followed by a space (e.g. quoting an API merge path) is denied. The ruleset denies (`gh api *repos/*/rulesets*`, `gh api *branches/*/protection*`) are anchored to API paths for the same reason: a review post always contains `repos/`, so its text must not contain `/rulesets`, or `/protection` after a `branches/`. A review that mentions `branch-protection.md` or the word rulesets posts fine. `SKILL.md` repeats these caveats; keep the two in sync.

## Guardrail paths

The reviewer leaves these PRs for a human to merge, with a comment saying so:

- `.claude/**`, `.github/**`, `CLAUDE.md`, `.pre-commit-config.yaml`
- any `uv.lock` change
- changes to `dependencies`, `dependency-groups` or `build-system` in `pyproject.toml`

A PR that touches these can weaken the guardrails themselves, so the owner reviews and merges it. This list is canonical; `.claude/skills/review-pr/SKILL.md` repeats it and must match.

## Future

Issue #3 proposes running the reviewer in GitHub Actions as `github-actions[bot]`. A separate identity allows a server-side "1 approval required" rule, so the author agent can't merge even past the client-side rules.
