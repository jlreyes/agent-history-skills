---
name: exploring-claude-sessions
description: Finds and explores Claude Code session history stored locally as JSONL transcripts. Use when the user asks to find, search, read, export, or resume a past Claude Code session, conversation, or transcript, or to see what a previous Claude Code session did.
compatibility: Requires jq. Paths are macOS/Linux (~/.claude).
allowed-tools: Bash(jq *) Bash(ls *) Bash(grep *)
metadata:
  author: jlreyes
---

# Exploring Claude Code Sessions

Claude Code stores every session as a JSONL transcript (one JSON object per line) under `~/.claude/projects/`.

## Storage locations

| Path | What it holds |
|------|---------------|
| `~/.claude/projects/<project-slug>/<session-id>.jsonl` | Main session transcripts |
| `~/.claude/projects/<project-slug>/<session-id>/subagents/agent-*.jsonl` | Subagent transcripts (same schema), with `agent-*.meta.json` (agent type, description) |
| `~/.claude/projects/<project-slug>/.session-aliases` | User-set session names → session IDs |
| `~/.claude/projects/<project-slug>/memory/` | Per-project auto-memory (markdown) |
| `~/.claude/history.jsonl` | Global prompt history: `{display, timestamp(ms), project}` per line |
| `~/.claude/file-history/<session-id>/` | File snapshots backing checkpoint/undo |

**Project slug encoding**: the session's working directory with `/` replaced by `-`. `/Users/me/repos/Foo` → `-Users-me-repos-Foo`.

**Retention**: transcripts are auto-cleaned after 30 days by default (`cleanupPeriodDays` in `~/.claude/settings.json`). `history.jsonl` is never auto-cleaned.

## Transcript schema (quick reference)

Entry types per line: `user`, `assistant`, `attachment`, `ai-title`, `last-prompt`, `queue-operation`, `file-history-snapshot`, `mode`, `permission-mode`, `system`, `summary`. Full field tables and examples: [data-model.md](data-model.md).

The fields needed for most exploration:

- `user` / `assistant` entries: `.timestamp` (ISO 8601), `.sessionId`, `.cwd`, `.gitBranch`, `.message.content` (string **or** array of blocks: `text`, `thinking`, `tool_use`, `tool_result`), `.uuid` / `.parentUuid` (conversation chain), `.isSidechain` (subagent work)
- `ai-title` entries: `.aiTitle` — the generated session title
- `assistant` entries: `.message.model`, `.message.usage` (token counts)
- tool-result `user` entries: `.toolUseResult` (structured result, often richer than the `tool_result` block) and `.sourceToolAssistantUUID` (the `assistant` uuid it answers)

## Recipes

### List sessions for a project, newest first

```bash
PROJ=~/.claude/projects/-Users-me-repos-Foo   # slug for the project
for f in "$PROJ"/*.jsonl; do
  jq -rs --arg id "$(basename "$f" .jsonl)" '
    (map(select(.type=="ai-title")) | .[0].aiTitle // "") as $title |
    (map(select(.type=="user")) | .[0]) as $first |
    select($first != null) |
    "\($first.timestamp[:16])  \($id[:8])  \($first.gitBranch // "?")  \($title) — \(
      $first.message.content | if type=="string" then . else ([.[]? | select(.type=="text") | (.text // .content)] | join(" ")) end | .[:60])"
  ' "$f" 2>/dev/null
done | sort -r
```

### Search all sessions for a keyword (all projects)

Fast path — grep raw lines first, then inspect hits:

```bash
grep -rl "KEYWORD" ~/.claude/projects/*/*.jsonl 2>/dev/null
```

Or search only what the *user* said, via `~/.claude/history.jsonl`:

```bash
jq -r 'select(.display | test("KEYWORD"; "i")) |
  "\(.timestamp/1000 | todate)  \(.project)  \(.display[:80])"' ~/.claude/history.jsonl | tail -30
```

### Dump a session as readable markdown

```bash
jq -r '
  def text: .message.content |
    if type=="string" then .
    else [.[]? | select(type=="object" and .type=="text") | (.text // .content)] | join("\n") end;
  def tools: [.message.content | arrays | .[]? | select(.type=="tool_use") |
    "\(.name)(\(.input | tostring | .[:120]))"] | join("\n  ");
  if .type=="user" and (.message.content | type=="string" or (type=="array" and any(.[]?; .type=="text"))) then
    "\n## USER (\(.timestamp[:16]))\n\(text)"
  elif .type=="assistant" then
    (tools) as $t |
    "\n### ASSISTANT (\(.timestamp[:16]))\n\(text)" + (if $t != "" then "\n  [tools] \($t)" else "" end)
  else empty end
' "$PROJ/<session-id>.jsonl"
```

### Find which session touched a file

```bash
grep -l '"file_path":"[^"]*FILENAME' ~/.claude/projects/*/*.jsonl 2>/dev/null
```

Then confirm by extracting the matching `tool_use` blocks from the hit (see dump recipe).

### Resolve a partial session ID

```bash
ls ~/.claude/projects/*/SESSION_PREFIX*.jsonl 2>/dev/null
```

### Resume a found session

```bash
claude --resume <session-id>     # by ID (or saved name)
claude --continue                # most recent session in current directory
```

In-session: `/resume <id-or-name>`. Export a live session with `/export <file>`.

## Tips

- Skip `agent-*.jsonl` and `<session-id>/` subdirectories when listing top-level sessions; those are subagent transcripts.
- `tool_result` content can be huge — always truncate (`.[:200]`) when printing.
- The first `user` line of a transcript may be an injected context block rather than the human's prompt; the `last-prompt` entry and `history.jsonl` reflect what was actually typed.
- Sessions started headless (`claude -p`) are stored too but don't appear in the `/resume` picker.
- Old `~/.claude/__store.db` (SQLite) is deprecated and no longer written; everything current is JSONL.
