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
gh pr view <n> --json number,title,body,baseRefName,headRefName,files,closingIssuesReferences,statusCheckRollup
gh pr diff <n>
```

- The **spec** is the linked issue (`closingIssuesReferences`, or `#N` in the body): read it with `gh issue view <issue> --comments`. No linked issue: the PR body is the spec.
- The **standards** are `CLAUDE.md`, `docs/agents/*.md`, `CONTEXT.md` and `docs/adr/` (when present), and the quality gate in `.pre-commit-config.yaml` / `pyproject.toml`.

Done when you have read the whole diff, the spec, and the standards that touch the changed files.

## 2. Review

Sort every finding into one of two buckets.

**Blocking** (any one stops the merge):

- The change misses or contradicts the spec, or does work the spec didn't ask for.
- A correctness bug: wrong result, unhandled error path, data loss, broken edge case.
- Missing tests for new behaviour, or tests that don't exercise the behaviour they name.
- A security problem: secrets, credentials or files from `data/` committed, unsafe input handling.
- A documented standard or ADR violated without the PR saying why.

**Non-blocking**: naming, style the linters don't enforce, small refactors, follow-up ideas. Report them; they never stop a merge.

Done when every changed file has been checked against both buckets.

## 3. Post the review

```sh
gh pr review <n> --comment --body "<review>"
```

Start the body with one verdict line: `Verdict: ready to merge`, `Verdict: blocking issues`, or `Verdict: needs human merge`. Then list blocking findings, then non-blocking ones, each with `file:line` and a concrete fix.

## 4. Decide

Check in this order; the first match wins.

1. **Fundamentally wrong** (solves the wrong problem, superseded, or the approach can't be fixed by revision): `gh pr close <n> --comment "<why, and what to do instead>"`. Reserve this for PRs no revision can save; everything else is blocking findings.
2. **Blocking findings**: stop. The review from step 3 is the hand-off to the author.
3. **Guardrail path touched**: any changed file matches `.claude/**`, `.github/**`, `CLAUDE.md`, `.pre-commit-config.yaml`, or the PR changes dependencies in `pyproject.toml` or `uv.lock` (any `uv.lock` change, or a change to `dependencies`, `dependency-groups`, `build-system` in `pyproject.toml`). Check with `gh pr view <n> --json files --jq '.files[].path'`. Comment `A human must merge this PR: it touches guardrail files (<list>).` and stop.
4. **CI not green**: `gh pr checks <n>`. Pending: wait with `gh pr checks <n> --watch`, then re-check. Failing: comment with the failing check and stop.
5. **Otherwise merge**: `gh pr merge <n> --squash --delete-branch`. Squash is the only merge method; the server-side ruleset is the authority on whether the merge may happen, so when it refuses, comment the error and stop.

Finish by reporting the verdict, the action taken (merged / closed / left for author / left for human), and the review URL.
