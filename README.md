# agent-history-skills

[Agent skills](https://agentskills.io) for finding, searching, reading, and exporting the conversation history that AI coding agents store on your machine.

| Skill | Agent | Where the history lives |
|-------|-------|------------------------|
| [`exploring-claude-sessions`](skills/exploring-claude-sessions/SKILL.md) | Claude Code | JSONL transcripts in `~/.claude/projects/` |
| [`exploring-codex-sessions`](skills/exploring-codex-sessions/SKILL.md) | OpenAI Codex CLI | JSONL rollouts in `~/.codex/sessions/` |
| [`exploring-cursor-history`](skills/exploring-cursor-history/SKILL.md) | Cursor IDE | SQLite databases in `~/Library/Application Support/Cursor/` |

Each skill teaches an agent how to locate session files, decode the storage schema, and run verified recipes: list recent sessions, search across all history by keyword, dump a full transcript as readable markdown, and resume a found session.

Typical uses: "what did I ask Cursor to do in that session last week?", auditing an agent's past work, exporting a transcript for review, or building tooling on top of local agent history.

## Install

With [skills.sh](https://skills.sh) (works for Claude Code, Cursor, Codex, and 20+ other agents):

```bash
# user-level (all projects)
npx skills add jlreyes/agent-history-skills -g

# or project-level
npx skills add jlreyes/agent-history-skills
```

Or manually: copy any directory under `skills/` into `~/.claude/skills/` (Claude Code), `~/.agents/skills/` (open-standard agents), or your agent's equivalent.

## Staying current

A scheduled GitHub Action (`.github/workflows/check-upstream.yml`, weekly)
installs the current Claude Code, Codex, and Cursor CLIs fresh and diffs
their `--version` output against `.github/tracked-versions.json`, opening or
updating a tracking issue when something changed. It is deliberately dumb —
no LLM calls, no secrets, no auto-commits — and only tells you *that*
something shipped a new version.

**Coverage gap**: this only catches CLI drift. `exploring-cursor-history`
also documents the Cursor **IDE** app's on-disk schema (`composerData`/bubble
`_v` versions), and GitHub-hosted runners can't install or run a macOS
desktop GUI app — so an IDE-only schema change won't trip this check. That
skill still needs an occasional manual re-verification pass on a machine
with the Cursor app installed.

### Resolving drift

The open tracking issue is the signal to run a refresh. The refresh itself is
[`/refresh-history-skills`](.claude/commands/refresh-history-skills.md) — one
command, run on a real machine, that fans out one subagent per affected skill
against the installed CLIs and real on-disk history, then opens a single PR
updating whichever skills actually changed plus `tracked-versions.json`.

Each subagent works through a fixed ten-step checklist: read the current docs
in full, run the real CLI and every relevant `--help`, `ls` the real storage
dirs, enumerate *every* entry type and field present across the whole local
corpus (not spot-checks), re-run every recipe against real data, generate
fresh data with a live headless run, cross-check the tool's actual source and
release history, then decide archive-vs-fix-in-place before touching
`data-model.md`.

**Why this part isn't automated.** It was, for five weeks, and the job is
worth learning from rather than repeating. A GitHub runner is the wrong place
for it: there is no real history corpus to enumerate against — only the
handful of records the job generates for itself — and the Cursor desktop app
can't be installed there at all, which is most of `exploring-cursor-history`.
The execution held up worse than the premise. Four of five scheduled runs
produced nothing: the orchestrating agent spawned its subagents, narrated the
fan-out, and ended its turn while they were still running, killing them and
exiting green. The one run that did finish turned in claims a later local pass
disproved against real data — tables that don't exist, JSON keys that were
never there. Detection is cheap and reliable, so it stays; verification needs a
machine that actually uses these tools.

The `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `CURSOR_API_KEY` repo secrets
are no longer read by any workflow — live Codex and Cursor runs now happen
locally under your own credentials. They can be removed with `gh secret
delete`.

## Compatibility

- Verified on macOS. Storage locations are platform-specific; Linux and Windows equivalents are given where known (`exploring-cursor-history` documents all three).
- The skills teach the storage data models and compose queries from built-in tools (`jq`, `sqlite3`, `grep`) rather than bundling helper scripts — agents can adapt the recipes to any question.
- All database access is read-only.

## License

MIT
