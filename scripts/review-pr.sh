#!/usr/bin/env bash
# Launch the reviewer agent on a PR under the reviewer profile.
# See docs/agents/branch-protection.md.
set -euo pipefail

if [[ $# -ne 1 || ! $1 =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <pr-number>" >&2
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"
exec claude --setting-sources user,local --settings .claude/reviewer-settings.json \
  "Read .claude/skills/review-pr/SKILL.md and follow it for PR $1"
