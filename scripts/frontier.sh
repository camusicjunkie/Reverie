#!/bin/sh
# Lists open issues that are ready to work: no open blocker, no assignee.
#
#   scripts/frontier.sh                 every open issue, lowest number first
#   scripts/frontier.sh --label L       only issues labelled L (e.g. ready-for-agent)
#   scripts/frontier.sh --map N         only open sub-issues of map issue N, in map order
#   scripts/frontier.sh --all           also show blocked and assigned issues
#
# Output is tab-separated: number, title, labels, assignees, open blockers.
# Needs only gh (filtering uses gh's built-in --jq; jq itself is not installed).
set -e

label=""; map=""; all=""
while [ $# -gt 0 ]; do
    case "$1" in
        --label) label="$2"; shift 2 ;;
        --map) map="$2"; shift 2 ;;
        --all) all=1; shift ;;
        *) echo "usage: $0 [--label L] [--map N] [--all]" >&2; exit 2 ;;
    esac
done

filter='.[]
  | {n: .number, t: .title,
     l: ([.labels[].name] | join(",")),
     a: ([.assignees[].login] | join(",")),
     b: ([.blockedBy.nodes[] | select(.state == "OPEN") | "#\(.number)"] | join(","))}'
if [ -z "$all" ]; then
    filter="$filter | select(.a == \"\" and .b == \"\")"
fi
filter="$filter | [.n, .t, .l, .a, .b] | @tsv"

set -- issue list --state open --limit 500 --json number,title,labels,assignees,blockedBy
[ -n "$label" ] && set -- "$@" --label "$label"
rows=$(gh "$@" --jq "$filter")

if [ -z "$map" ]; then
    printf '%s\n' "$rows" | sort -n | sed '/^$/d'
    exit 0
fi

repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
for n in $(gh api "repos/$repo/issues/$map/sub_issues" --paginate --jq '.[] | select(.state == "open") | .number'); do
    printf '%s\n' "$rows" | grep "^$n	" || true
done
