#!/usr/bin/env bash
# Ralph loop: keep driving unblocked `ready-for-agent` issues and open PRs to a merge until
# none are left, running scripts/implement-review-loop.sh on each.
#
# Each round fills free slots, PRs first (a merge can unblock issues), then issues:
#   PRs     open, non-draft PRs against main whose head review isn't
#           `Verdict: needs human merge`: unreviewed, blocking, behind or conflicting, or
#           reviewed ready but still open. The loop reviews, fixes and re-reviews them.
#   issues  open, unassigned `ready-for-agent` issues with no open blockers (GitHub native
#           issue dependencies, see docs/agents/issue-tracker.md), lowest number first.
#           Each is claimed (assigned @me) before its loop starts, so no other round or
#           ralph picks it again. The loop implements it, then reviews and fixes the PR.
# Each target gets one loop per run, and a PR and the issue it closes (`Closes #<n>` or a
# `<n>-...` branch) count as one target. Whenever a loop finishes, ralph checks again. It
# stops when nothing is running and nothing is left to start.
#
# A failed loop (needs a human, out of cycles, a failed step) leaves its issue assigned, so
# it isn't retried; unassign it to put it back in the queue. Its PR is picked up again on
# the next run unless its head review says `Verdict: needs human merge` or it is a draft.
#
# usage: scripts/ralph.sh [--resume]
#   --resume  first re-run the loops a previous run left cut off (e.g. by a usage limit):
#             one per worktree left in .claude/worktrees/loop-<n> or loop-pr-<n>. Each
#             carries on from its worktree instead of starting over.
#
# Env:
#   RALPH_PARALLEL=1   how many loops to run at once
#   RALPH_CYCLES=5     review cycles per loop (LOOP_CYCLES)
#   RALPH_LABEL=ready-for-agent
#   RALPH_PERMISSION_MODE=auto
#   RALPH_RETRIES=5    attempts for each GitHub/network call before giving up
#                      (backoff doubles from 5s)
set -euo pipefail

PARALLEL=${RALPH_PARALLEL:-1}
LABEL=${RALPH_LABEL:-ready-for-agent}
RETRIES=${RALPH_RETRIES:-5}
export LOOP_CYCLES=${RALPH_CYCLES:-5}
export LOOP_PERMISSION_MODE=${RALPH_PERMISSION_MODE:-auto}
export LOOP_RETRIES=$RETRIES

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
LOOP="$ROOT/scripts/implement-review-loop.sh"

log() { printf '[ralph %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

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

# Open, unassigned, unblocked issues with $LABEL, one number per line, lowest first.
unblocked_issues() {
  gh api --paginate "repos/{owner}/{repo}/issues?state=open&labels=$LABEL&per_page=100" \
    --jq '.[]
      | select(.pull_request == null)
      | select((.assignees | length) == 0)
      | select((.issue_dependencies_summary.blocked_by // 0) == 0)
      | .number' |
    sort -n
}

# Matches a GitHub closing keyword in a PR body ("Closes #12"), capturing the issue as n.
# Same as in scripts/implement-review-loop.sh.
CLOSES_RE='(?i)\\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\\s+#(?<n>[0-9]+)\\b'

# Open, non-draft PRs against main that a loop can move forward: every one except those
# whose head review said `Verdict: needs human merge`. One "<pr> <issue>" per line, lowest
# first; <issue> is the issue it closes (body, else `<n>-...` branch), empty if none.
prs_to_drive() {
  gh pr list --state open --base main --limit 100 \
    --json number,headRefOid,headRefName,isDraft,body,reviews \
    --jq ".[]
      | select(.isDraft | not)
      | .headRefOid as \$head
      | ([.reviews[] | select(.commit.oid == \$head)] | last) as \$review
      | select((\$review.body // \"\" | split(\"\n\")[0]) != \"Verdict: needs human merge\")
      | ([(.body // \"\" | capture(\"$CLOSES_RE\"; \"g\").n), (.headRefName | capture(\"^(?<n>[0-9]+)-\").n)]
         | .[0] // \"\") as \$issue
      | \"\(.number) \(\$issue)\"" |
    sort -n
}

declare -A running=() # pid -> "#<n>", the loop's target
declare -A handled=() # "#<n>" -> 1, issues and PRs that got a loop this run
failed=()

# Targets of cut-off loops to resume: loop-<issue> or loop-pr-<pr> worktrees.
resume=()
if [[ ${1:-} == --resume ]]; then
  for wt in .claude/worktrees/loop-*; do
    [[ -d $wt && ${wt##*-} =~ ^[0-9]+$ ]] && resume+=("${wt##*-}")
  done
  log "resuming: ${resume[*]:-nothing left over}"
elif (($#)); then
  echo "usage: $0 [--resume]" >&2
  exit 1
fi

start_loop() {
  "$LOOP" "$1" &
  running[$!]="#$1"
}

while true; do
  # Cut-off loops before anything new. Their issues are already claimed.
  while ((${#resume[@]} && ${#running[@]} < PARALLEL)); do
    n=${resume[0]}
    resume=("${resume[@]:1}")
    [[ -z ${handled["#$n"]:-} ]] || continue
    handled["#$n"]=1
    start_loop "$n"
  done

  # Fill free slots with PRs first: a merge can unblock issues.
  if ((${#running[@]} < PARALLEL)); then
    prs=$(retry prs_to_drive) || prs=
    while read -r pr issue; do
      [[ -n $pr ]] || continue
      ((${#running[@]} < PARALLEL)) || break
      [[ -z ${handled["#$pr"]:-} ]] || continue
      # The issue's own loop drives this PR (or already did this run).
      [[ -z $issue || -z ${handled["#$issue"]:-} ]] || continue
      handled["#$pr"]=1
      [[ -z $issue ]] || handled["#$issue"]=1
      start_loop "$pr"
    done <<<"$prs"
  fi

  # Fill free slots with unblocked issues.
  if ((${#running[@]} < PARALLEL)); then
    # A failed lookup must not look like an empty queue, or the loop would stop early.
    if ! issues=$(retry unblocked_issues); then
      if ((${#running[@]} == 0)); then
        log "could not list issues and nothing running, giving up"
        exit 1
      fi
      issues=
    fi
    for n in $issues; do
      ((${#running[@]} < PARALLEL)) || break
      [[ -z ${handled["#$n"]:-} ]] || continue
      if ! retry gh issue edit "$n" --add-assignee @me >/dev/null; then
        log "#$n: could not claim, skipping for now"
        continue
      fi
      handled["#$n"]=1
      start_loop "$n"
    done
  fi

  if ((${#running[@]} == 0)); then
    log "no unblocked issues or open PRs left and nothing running, done"
    break
  fi

  log "running: $(IFS=,; echo "${running[*]}")"
  # Wait for any one loop to finish, then check again.
  pid=
  if wait -n -p pid "${!running[@]}"; then
    log "${running[$pid]}: done"
  else
    log "${running[$pid]}: stopped without a merge"
    failed+=("${running[$pid]}")
  fi
  unset "running[$pid]"
done

if ((${#failed[@]})); then
  log "not merged (issues stay assigned to you; see the [loop #<n>] lines above): ${failed[*]}"
  exit 1
fi
