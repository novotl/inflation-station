---
name: review-pr
description: Review a pull request, post a COMMENT review, and squash-merge it when CI is green and nothing is blocking.
argument-hint: "[pr-number]"
disable-model-invocation: true
---

# Review a PR

`<n>` below is the PR number: `$ARGUMENTS` when run as `/review-pr <n>`, otherwise the number in the user's message.

You are the **review agent**. You run under the reviewer profile (`docs/agents/branch-protection.md`). The author and you share one GitHub identity, so GitHub rejects approve/request-changes: every review you post is a `--comment` review, and your verdict lives in its text.

## 1. Gather

```sh
gh pr view <n> --json number,title,body,baseRefName,headRefName,files,statusCheckRollup
git fetch origin <base> pull/<n>/head:refs/pr/<n>
```

- The **spec** is the issue referenced as `#N` (e.g. `Closes #N`) in the PR body or commit messages: read it with `gh issue view <N> --comments`. No referenced issue: the PR body is the spec.
- The **standards** are `CLAUDE.md`, `docs/agents/*.md`, `CONTEXT.md` and `docs/adr/` (when present), and the quality gate in `.pre-commit-config.yaml` / `pyproject.toml`.

Done when `refs/pr/<n>` exists and you have the spec and the list of standards files.

## 2. Review

Run the `mattpocock-skills:code-review` skill with these inputs, so it never has to ask:

- **Fixed point**: `origin/<base>`.
- **Tip**: `refs/pr/<n>` wherever the skill says `HEAD`. The diff is `git diff origin/<base>...refs/pr/<n>`, commits `git log origin/<base>..refs/pr/<n> --oneline`. Don't check out the PR branch.
- **Spec**: the issue or PR body from step 1.
- **Standards**: the files from step 1.

Its Standards and Spec reports cover only part of what blocks a merge. Then read the diff yourself for correctness bugs, missing tests and security problems.

Sort every finding, from the skill and your own pass, into one of two buckets.

**Blocking** (any one stops the merge):

- The change misses or contradicts the spec, or does work the spec didn't ask for.
- A correctness bug: wrong result, unhandled error path, data loss, broken edge case.
- Missing tests for new behaviour, or tests that don't exercise the behaviour they name.
- A security problem: secrets, credentials or files from `data/` committed, unsafe input handling.
- A documented standard or ADR violated without the PR saying why.

**Non-blocking**: naming, style the linters don't enforce, small refactors, follow-up ideas, and the skill's baseline smells (they are judgement calls). Report them; they never stop a merge.

Done when every changed file has been checked against both buckets.

## 3. Post the review

Post one review: a summary body plus a line comment for every finding that points at a line in the diff. The repo is hardcoded on purpose: the reviewer profile allows `gh api` only for this repo's reviews endpoint.

```sh
gh api repos/novotl/inflation-station/pulls/<n>/reviews --input - <<'EOF'
{
  "commit_id": "<git rev-parse refs/pr/<n>>",
  "event": "COMMENT",
  "body": "<summary>",
  "comments": [
    {"path": "src/inflation_station/foo.py", "line": 42, "side": "RIGHT", "body": "**blocking** (Spec): <finding and concrete fix>"},
    {"path": "src/inflation_station/foo.py", "start_line": 10, "line": 14, "side": "RIGHT", "body": "**non-blocking** (Standards): <finding and concrete fix>"}
  ]
}
EOF
```

- `event` is always `COMMENT`.
- The **summary** starts with one verdict line: `Verdict: ready to merge`, `Verdict: blocking issues`, or `Verdict: needs human merge`. Then the skill's `## Standards` and `## Spec` sections, plus `## Correctness` for your own pass. Keep the axes separate and list every finding there, marked **blocking** or **non-blocking**, with `file:line`.
- **Line comments** repeat a finding at its line, tagged with its bucket and axis, with the concrete fix. `line` is the line number in the PR's version of the file, and it must be inside a diff hunk. Use `start_line` for a range.
- A finding with no line in the diff (a missing test, a missing spec requirement) goes only in the summary.
- If GitHub answers `422`, a comment points outside the diff. Move that finding into the summary only and post again.
- Don't write `/merge` followed by a space in review text (e.g. an API merge path). The merge denies match a path ending in `/merge` anywhere in the command, heredoc included, and block the post. `docs/agents/branch-protection.md` repeats this caveat; keep the two in sync.

## 4. Decide

Check in this order; the first match wins.

1. **Fundamentally wrong** (solves the wrong problem, superseded, or the approach can't be fixed by revision): `gh pr close <n> --comment "<why, and what to do instead>"`. Reserve this for PRs no revision can save; everything else is blocking findings.
2. **Blocking findings**: stop. The review from step 3 is the hand-off to the author.
3. **Guardrail path touched**: any changed file matches `.claude/**`, `.github/**`, `CLAUDE.md`, `.pre-commit-config.yaml`, or the PR changes `uv.lock` (any change) or `dependencies`, `dependency-groups`, `build-system` in `pyproject.toml`. This list mirrors "Guardrail paths" in `docs/agents/branch-protection.md`, which is canonical. Check with `gh pr view <n> --json files --jq '.files[].path'`. Comment `A human must merge this PR: it touches guardrail files (<list>).` and stop.
4. **CI not green**: `gh pr checks <n>`. Pending: wait with `gh pr checks <n> --watch`, then re-check. Failing: comment with the failing check and stop.
5. **Otherwise merge**: `gh pr merge <n> --squash --delete-branch`. Squash is the only merge method; the server-side ruleset is the authority on whether the merge may happen, so when it refuses, comment the error and stop.

Finish by reporting the verdict, the action taken (merged / closed / left for author / left for human), and the review URL.
