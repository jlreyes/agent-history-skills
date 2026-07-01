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
updating a tracking issue when something changed (job: `check`). That part
is deliberately dumb — no LLM calls, no secrets, no auto-commits — it only
tells you *that* something shipped a new version.

**Coverage gap**: this only catches CLI drift. `exploring-cursor-history`
also documents the Cursor **IDE** app's on-disk schema (`composerData`/bubble
`_v` versions), and GitHub-hosted runners can't install or run a macOS
desktop GUI app — so an IDE-only schema change won't trip this check. That
skill still needs an occasional manual re-verification pass on a machine
with the Cursor app installed.

A second job (`propose-update`) runs only when drift is detected **and** an
`ANTHROPIC_API_KEY` repo secret is configured: it invokes
[`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action)
headlessly to re-verify the changed CLI(s) against real, freshly-installed
binaries (not memory) and open a PR updating the affected skill's
`SKILL.md`, `data-model.md`, and `tracked-versions.json` together — review
it before merging, same as any other PR. Without the secret, only the
tracking issue fires and resolving it stays manual.

Two more secrets unlock deeper verification for two of the three skills:

| Secret | Unlocks |
|---|---|
| `ANTHROPIC_API_KEY` | Required for the `propose-update` job to run at all |
| `OPENAI_API_KEY` | Lets the job log in and run a real `codex exec` prompt to verify `exploring-codex-sessions`, instead of relying on `--help` output alone |
| `CURSOR_API_KEY` | Lets the job run a real `agent -p` prompt to verify `exploring-cursor-history` the same way |

Without `OPENAI_API_KEY` / `CURSOR_API_KEY`, the corresponding skill still
gets re-verified from `--help`/`--version` output and official docs, just
not from a live, freshly-generated session — the PR description says which
mode it ran in for each tool.

**Setting a secret:** run this yourself, in your own terminal — not through
an agent session, so the key value never passes through anyone's context or
transcript:

```bash
gh secret set ANTHROPIC_API_KEY --repo jlreyes/agent-history-skills
gh secret set OPENAI_API_KEY --repo jlreyes/agent-history-skills
gh secret set CURSOR_API_KEY --repo jlreyes/agent-history-skills
# each pastes/prompts for the value interactively; nothing is echoed
```

This is standard CI-secret hygiene regardless of any agent-visibility policy
you run elsewhere — `gh secret set` with no `--body` flag reads from a
hidden prompt, and the value is never visible to anything running inside the
workflow's logs (GitHub masks it automatically).

## Compatibility

- macOS paths throughout (the storage locations are platform-specific; Linux equivalents are noted where known).
- The skills teach the storage data models and compose queries from built-in tools (`jq`, `sqlite3`, `grep`) rather than bundling helper scripts — agents can adapt the recipes to any question.
- All database access is read-only.

## License

MIT
