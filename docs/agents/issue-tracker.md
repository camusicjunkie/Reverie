# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Multi-line bodies** (issues, comments, edits): write the body with the Write tool into the session scratchpad, then pass `--body-file <path>`. Heredocs through Git Bash break on long bodies, and `/tmp` does not resolve to the same place for every tool on Windows.
- **Filtering JSON**: use `gh`'s built-in `--jq`. Standalone `jq` is not installed.
- **Create an issue**: `gh issue create --title "..." --body-file <path>`.
- **Read an issue**: `gh issue view <number> --comments --json title,body,labels,comments`.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue: `gh api --method POST repos/<owner>/<repo>/issues/<map>/sub_issues -F sub_issue_id=<child-db-id>` (`-F`, not `-f`: the id must go as an integer). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). A ticket is unblocked when every blocker is closed.

  **In this repo, every edge is written twice** — the native dependency *and* a `**Requires**: [Blocker name](url)` line at the top of the child body, one entry per blocker, comma-separated, optionally followed by ` — <why>`. The body line is not the fallback the stock template describes; it is the human-readable mirror of a native edge, and it exists because the map's standing preference is to refer to tickets by name rather than by bare number. Write both. Writing only the native edge leaves the body silent about what gates the ticket; writing only the body line leaves the frontier query blind.
- **Frontier query**: `scripts/frontier.sh --map <map>` lists the map's open children with no open blocker and no assignee, in map order; first wins. The native edge is the gate; the `**Requires**:` line mirrors it but is never queried. Outside a map, `scripts/frontier.sh --label ready-for-agent` gives the implementable queue; `--all` also shows blocked and assigned issues.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

## Repo conventions

- **Refer to issues by name, never by a bare number.** In anything a human reads —
  narration, the map's Decisions-so-far, a `**Requires**:` line, a resolution
  comment — write the ticket's title as a link: `[Datum as v1's engine](url)`.
  A wall of `#12, #13, #14` is illegible. The number rides inside the link; it
  never stands in for the name. This is a standing preference of the Reverie
  design-spec effort and applies to every skill that writes here, not just
  `/wayfinder`.
- **Plain, consistent terminology.** Fix a glossary and reuse the words. No
  letter-coded options in anything published to the tracker.
