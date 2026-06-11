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

## Compatibility

- macOS paths throughout (the storage locations are platform-specific; Linux equivalents are noted where known).
- The skills teach the storage data models and compose queries from built-in tools (`jq`, `sqlite3`, `grep`) rather than bundling helper scripts — agents can adapt the recipes to any question.
- All database access is read-only.

## License

MIT
