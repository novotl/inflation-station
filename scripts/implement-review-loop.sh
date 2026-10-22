#!/usr/bin/env bash
# Drive one issue or PR to a merge: implement, review, fix, review again, ...
#
# usage: scripts/implement-review-loop.sh <issue-or-pr-number>
#
# Each round looks at where the work is stuck and runs the one step that unblocks it:
#   implement  the issue has no open PR: a fresh `claude -p` with /mattpocock-skills:implement
#              on a new `<n>-<slug>` branch off origin/main opens one (`Closes #<n>`).
#   review     the PR head has no review yet, or its review said `Verdict: ready to merge`
#              but the PR is still open: the reviewer profile runs (as scripts/review-pr.sh
#              does), which merges it when it passes.
#   fix        the PR head's review said `Verdict: blocking issues`, or the PR is behind or
#              conflicts with main: the branch gets origin/main merged in, an implementer
#              fixes the blocking findings and any conflicts, and this script pushes.
# A step that dies mid-way (e.g. a usage limit) keeps its worktree, and a re-run resumes
# there: the new session gets the work so far and the cut-off transcript.
# A cycle is one review, plus the fix before it when there is one. It stops when the PR is
# merged, after $LOOP_CYCLES cycles, or when it needs a human
# (`Verdict: needs human merge`, a closed or draft PR, a failed step).
#
# Env:
#   LOOP_CYCLES=5              maximum number of cycles (reviews)
#   LOOP_PERMISSION_MODE=auto
#   LOOP_RETRIES=5             attempts for each GitHub/network call before giving up
#                              (backoff doubles from 5s)
set -euo pipefail

if [[ $# -ne 1 || ! $1 =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <issue-or-pr-number>" >&2
  exit 1
fi
TARGET=$1
CYCLES=${LOOP_CYCLES:-5}
PERMISSION_MODE=${LOOP_PERMISSION_MODE:-auto}
RETRIES=${LOOP_RETRIES:-5}

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
# Logs live inside .git so they can never be committed.
LOG_DIR="$(git rev-parse --path-format=absolute --git-common-dir)/ralph-logs"
mkdir -p "$LOG_DIR"

log() { printf '[loop #%s %s] %s\n' "$TARGET" "$(date +%H:%M:%S)" "$*"; }
die() {
  log "$*"
  exit 1
}

# Runs "$@" up to $RETRIES times with doubling backoff, for flaky network calls.
# Prints only the successful attempt's stdout, so a half-finished --paginate can't leak.
retry() {
  local attempt=1 delay=5 out
  until out=$("$@"); do
    if ((attempt >= RETRIES)); then
      log "'$*' failed after $attempt attempts" >&2
      return 1
    fi
    log "'$*' failed (attempt $attempt/$RETRIES), retrying in ${delay}s" >&2
    sleep "$delay"
    ((attempt += 1, delay *= 2))
  done
  [[ -z $out ]] || printf '%s\n' "$out"
}

# Runs `claude -p "${@:2}"` and streams a readable transcript into log $1 as it works
# (assistant text, tool calls, final result), instead of only the final answer at exit.
claude_logged() {
  local log=$1
  shift
  claude -p --output-format stream-json --verbose "$@" 2>&1 |
    jq --unbuffered -rR '
      (fromjson? // {type: "raw", line: .}) as $e
      | if $e.type == "assistant" then
          $e.message.content[]
          | if .type == "text" then .text
            elif .type == "tool_use" then "> \(.name) \(.input | tostring | .[:300])"
            else empty end
        elif $e.type == "result" then
          "== \($e.subtype) after \($e.num_turns) turns, $\($e.total_cost_usd)\n\($e.result // "")"
        elif $e.type == "raw" then $e.line
        else empty end' >"$log"
}

slugify() {
  iconv -f utf-8 -t ascii//TRANSLIT <<<"$1" 2>/dev/null |
    tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//; s/-$//' | cut -c1-40 | sed 's/-$//'
}

# Matches a GitHub closing keyword in a PR body ("Closes #12"), capturing the issue as n.
CLOSES_RE='(?i)\\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\\s+#(?<n>[0-9]+)\\b'

# The open PR for issue $1: branch `<n>-...` or `Closes #<n>` in its body. Empty if none.
pr_for_issue() {
  gh pr list --state open --base main --limit 100 --json number,headRefName,body \
    --jq "[.[] | select((.headRefName | startswith(\"$1-\"))
                        or any(.body | capture(\"$CLOSES_RE\"; \"g\"); .n == \"$1\"))]
          | .[0].number // empty"
}

# The issue PR $1 implements, from `Closes #<n>` in its body or its `<n>-...` branch.
# Empty if neither.
issue_for_pr() {
  gh pr view "$1" --json headRefName,body \
    --jq "[(.body | capture(\"$CLOSES_RE\"; \"g\").n), (.headRefName | capture(\"^(?<n>[0-9]+)-\").n)]
          | .[0] // empty"
}

# One line "<step> <detail>" saying what PR $1 is waiting on: done, stop, review or fix.
pr_next_step() {
  gh pr view "$1" --json state,isDraft,headRefOid,mergeStateStatus,reviews --jq '
    .headRefOid as $head
    | ([.reviews[] | select(.commit.oid == $head)] | last) as $review
    | ($review.body // "" | split("\n")[0]) as $verdict
    | if .state == "MERGED" then "done merged"
      elif .state == "CLOSED" then "stop closed without merging"
      elif .isDraft then "stop draft PR"
      elif $verdict == "Verdict: needs human merge" then "stop needs a human merge"
      elif $verdict == "Verdict: blocking issues" then "fix blocking review"
      elif .mergeStateStatus == "DIRTY" then "fix conflicts with main"
      elif .mergeStateStatus == "BEHIND" then "fix behind main"
      else "review " + (if $review then "re-run, last review did not merge" else "head not reviewed" end)
      end'
}

# Numeric id of the blocking review on PR $1's head, for reading its line comments.
head_review_id() {
  local head
  head=$(gh pr view "$1" --json headRefOid --jq .headRefOid)
  gh api "repos/{owner}/{repo}/pulls/$1/reviews" --paginate \
    --jq "[.[] | select(.commit_id == \"$head\")] | last | .id // empty"
}

# Opens a PR for issue $1 from a fresh branch off origin/main.
implement_issue() {
  local n=$1 title slug branch wt resume= implement_log="$LOG_DIR/loop-$1-implement.log"
  wt="$ROOT/.claude/worktrees/loop-$n"
  if [[ -e $wt ]]; then
    # Left by an interrupted run (e.g. a usage limit): carry on with its work.
    branch=$(git -C "$wt" branch --show-current)
    [[ $branch == "$n-"* ]] || die "worktree $wt is not on a $n-... branch; remove it and re-run"
    resume="$LOG_DIR/loop-$n-implement.interrupted-$(date +%Y%m%d-%H%M%S).log"
    [[ ! -e $implement_log ]] || mv "$implement_log" "$resume"
  else
    title=$(retry gh issue view "$n" --json title --jq .title)
    slug=$(slugify "$title")
    branch="$n-${slug:-issue}"
    # Claim it, so scripts/ralph.sh doesn't pick it up too.
    retry gh issue edit "$n" --add-assignee @me >/dev/null
    retry git fetch --quiet origin main
    git worktree add --quiet -b "$branch" "$wt" origin/main
  fi

  log "${resume:+resuming, }implementing #$n on $branch (log: $implement_log)"
  (cd "$wt" && claude_logged "$implement_log" --permission-mode "$PERMISSION_MODE" --no-session-persistence \
    "/mattpocock-skills:implement GitHub issue #$n. Read it first with \`gh issue view $n --comments\`.
You are on branch \`$branch\`, created from origin/main for this issue; commit there.
When the work is committed, push the branch and open a PR against main with \`gh pr create\`.
The PR body must contain \`Closes #$n\`. Do not merge it.${resume:+
An earlier run on this issue was cut off before it finished. Its work is already in this worktree (see \`git status\`, \`git diff\` and \`git log origin/main..\`) and its transcript is in $resume. Pick up where it left off instead of starting over.}") ||
    die "implementer failed, see $implement_log (worktree kept at $wt)"
  git worktree remove --force "$wt"
}

# Merges origin/main into PR $1's branch, has an implementer fix the blocking review and
# any conflicts, and pushes. $2 says why.
fix_pr() {
  local pr=$1 why=$2 branch issue review_id wt fix_log task before resume= merged
  fix_log="$LOG_DIR/loop-$TARGET-pr-$pr-fix-$cycle.log"
  branch=$(retry gh pr view "$pr" --json headRefName --jq .headRefName)
  issue=$(retry issue_for_pr "$pr") || issue=
  wt="$ROOT/.claude/worktrees/loop-pr-$pr"

  retry git fetch --quiet origin main "$branch"
  before=$(git rev-parse "origin/$branch")
  if [[ -e $wt ]]; then
    # Left by an interrupted run (e.g. a usage limit): carry on with its work.
    local last
    last=$(ls -t "$LOG_DIR"/loop-*-pr-"$pr"-fix-[0-9]*.log 2>/dev/null | head -1) || last=
    resume="(no transcript found)"
    if [[ -n $last ]]; then
      # Out of the way, as this run's log may have the same name.
      resume="${last%.log}.interrupted-$(date +%Y%m%d-%H%M%S).log"
      mv "$last" "$resume"
    fi
    git -C "$wt" rev-parse -q --verify MERGE_HEAD >/dev/null && merged=conflicts || merged=ok
  else
    # Detached, so it works even when the branch is checked out elsewhere (e.g. the main checkout).
    git worktree add --quiet --detach "$wt" "origin/$branch"
    git -C "$wt" merge --quiet --no-edit origin/main >/dev/null 2>&1 && merged=ok || merged=conflicts
  fi

  task=
  if [[ $merged == conflicts ]]; then
    task+="- A merge of origin/main into this branch is in progress and has conflicts. Resolve them with /mattpocock-skills:resolving-merge-conflicts and commit the merge.
"
  fi
  if [[ $why == "blocking review" ]]; then
    review_id=$(retry head_review_id "$pr")
    task+="- The latest review of PR #$pr has blocking findings. Read it with \`gh pr view $pr --comments\` and its line comments with \`gh api repos/{owner}/{repo}/pulls/$pr/reviews/$review_id/comments\`. Fix every **blocking** finding; leave non-blocking ones unless a fix is trivial and in scope.
"
  fi

  if [[ -n $task ]]; then
    log "${resume:+resuming, }fixing PR #$pr ($why) (log: $fix_log)"
    (cd "$wt" && claude_logged "$fix_log" --permission-mode "$PERMISSION_MODE" --no-session-persistence \
      "/mattpocock-skills:implement Revise PR #$pr (branch \`$branch\`${issue:+, implementing GitHub issue #$issue: read it with \`gh issue view $issue --comments\`}).
You are in a worktree on a detached HEAD at the PR's head. Commit your changes here; do not push, do not open a PR, do not merge.
$task${resume:+
An earlier run of this fix was cut off before it finished. Its work is already in this worktree (see \`git status\`, \`git diff\` and \`git log origin/$branch..\`) and its transcript is in $resume. Pick up where it left off instead of starting over.}") ||
      die "fixer failed, see $fix_log (worktree kept at $wt)"
  else
    log "merged origin/main into PR #$pr ($why)"
  fi

  [[ -z $(git -C "$wt" status --porcelain) ]] ||
    die "fixer left uncommitted changes, see $fix_log (worktree kept at $wt)"
  [[ $(git -C "$wt" rev-parse HEAD) != "$before" ]] ||
    die "fix produced no new commits, see $fix_log (worktree kept at $wt)"
  retry git -C "$wt" push --quiet origin "HEAD:refs/heads/$branch"
  git worktree remove --force "$wt"
  log "pushed fixes to PR #$pr"
}

# Runs the reviewer profile on PR $1. Same invocation as scripts/review-pr.sh, headless.
# See docs/agents/branch-protection.md.
review_pr() {
  local pr=$1 review_log="$LOG_DIR/loop-$TARGET-pr-$1-review-$cycle.log"
  log "reviewing PR #$pr, cycle $cycle/$CYCLES (log: $review_log)"
  claude_logged "$review_log" --setting-sources user,local --settings .claude/reviewer-settings.json \
    --permission-mode "$PERMISSION_MODE" --no-session-persistence \
    "Read .claude/skills/review-pr/SKILL.md and follow it for PR $pr" ||
    log "reviewer exited non-zero, see $review_log"
}

# Is the target an issue or a PR? The issues endpoint answers for both.
kind_state=$(retry gh api "repos/{owner}/{repo}/issues/$TARGET" \
  --jq '(if .pull_request then "pr" else "issue" end) + " " + .state') ||
  die "could not look up #$TARGET"
read -r kind state <<<"$kind_state"
issue= pr=
if [[ $kind == pr ]]; then
  pr=$TARGET
else
  issue=$TARGET
  [[ $state == open ]] || {
    log "issue #$issue is already closed"
    exit 0
  }
fi

cycle=0
while true; do
  if [[ -z $pr ]]; then
    pr=$(retry pr_for_issue "$issue")
    if [[ -z $pr ]]; then
      implement_issue "$issue"
      pr=$(retry pr_for_issue "$issue")
      [[ -n $pr ]] || die "implementer finished but opened no PR, see $LOG_DIR/loop-$issue-implement.log"
      log "PR #$pr opened"
      continue
    fi
    log "issue #$issue has PR #$pr"
  fi

  next=$(retry pr_next_step "$pr") || die "could not read PR #$pr"
  read -r step detail <<<"$next"
  case $step in
  done)
    log "PR #$pr merged after $cycle review(s)"
    exit 0
    ;;
  stop) die "PR #$pr: $detail, stopping" ;;
  esac

  # A fix is always followed by a review, so both need a cycle left.
  ((cycle < CYCLES)) || die "PR #$pr not merged after $CYCLES reviews ($step next: $detail), leaving it to you"
  ((cycle += 1))
  # Straight on to the review after a fix: right after a push GitHub may still report the
  # old merge state.
  [[ $step != fix ]] || fix_pr "$pr" "$detail"
  review_pr "$pr"
done
