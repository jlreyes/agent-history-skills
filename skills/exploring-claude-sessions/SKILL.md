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
| `~/.claude/projects/<project-slug>/<session-id>/subagents/agent-<agent-id>.jsonl` | Subagent transcripts (same schema), with `agent-<agent-id>.meta.json` (agent type, description, spawn depth) |
| `~/.claude/projects/<project-slug>/<session-id>/tool-results/<id>.txt` | Large tool outputs spilled to their own files, pointed at by `toolUseResult.persistedOutputPath` |
| `~/.claude/projects/<project-slug>/<session-id>/workflows/wf_*.json` | Per-session workflow run records |
| `~/.claude/projects/<project-slug>/memory/` | Per-project auto-memory (markdown) |
| `~/.claude/projects/<project-slug>/.session-aliases` | Pointers to *sibling project directories* for the same working dir — one absolute `~/.claude/projects/<slug>` path per line. **Not** session names |
| `~/.claude/history.jsonl` | Global prompt history: `{display, timestamp(ms), project, sessionId}` per line |
| `~/.claude/file-history/<session-id>/<hash>@v<N>` | File snapshots backing checkpoint/undo |
| `~/.claude/sessions/<pid>.json` | Live registry of *running* sessions: `{pid, sessionId, cwd, version, kind, entrypoint, name, status, …}` |

**Project slug encoding**: the session's working directory with `/` replaced by `-`. `/Users/me/repos/Foo` → `-Users-me-repos-Foo`.

**Retention**: transcripts are auto-cleaned after 30 days by default (`cleanupPeriodDays` in `~/.claude/settings.json`; minimum 1). A session's `subagents/` and `tool-results/` age out with it. `history.jsonl` is never auto-cleaned. `claude project purge [path]` deletes one project's transcripts, memory, tasks, file-history and `history.jsonl` lines.

## Transcript schema (quick reference)

Entry types per line: `user`, `assistant`, `attachment`, `system`, `mode`, `permission-mode`, `ai-title`, `custom-title`, `last-prompt`, `queue-operation`, `file-history-snapshot`, `file-history-delta`, `pr-link`, `bridge-session`, `relocated`, `worktree-state`, `agent-name`, `agent-setting`, `frame-link`, `summary`. Full field tables and examples: [data-model.md](data-model.md).

The fields needed for most exploration:

- `user` / `assistant` entries: `.timestamp` (ISO 8601), `.sessionId`, `.cwd`, `.gitBranch`, `.message.content` (string **or** array of blocks: `text`, `thinking`, `tool_use`, `tool_result`, `image`), `.uuid` / `.parentUuid` (conversation chain), `.isSidechain` (subagent work), `.agentId` (which subagent)
- `user` entries carrying a tool result: `.toolUseResult` (structured result), `.sourceToolAssistantUUID` (the `assistant` entry that called the tool)
- `ai-title` / `custom-title` entries: `.aiTitle` / `.customTitle` — generated and user-set session titles
- `assistant` entries: `.message.model`, `.message.usage` (token counts), `.effort`

## Recipes

### List sessions for a project, newest first

```bash
PROJ=~/.claude/projects/-Users-me-repos-Foo   # slug for the project
for f in "$PROJ"/*.jsonl; do
  jq -rs --arg id "$(basename "$f" .jsonl)" '
    def flat: gsub("\\s+"; " ");
    def txt: .message.content
      | if type=="string" then . else [.[]? | select(.type=="text") | (.text // .content)] | join(" ") end;
    (map(select(.type=="ai-title" or .type=="custom-title")) | last) as $t |
    map(select(.type=="user")) as $u |
    (($u | map(select(.promptSource=="typed")) | first) // ($u | first)) as $p |
    select($p != null) |
    "\($p.timestamp[:16])  \($id[:8])  \($p.gitBranch // "?")  \($t.customTitle // $t.aiTitle // "-")  |  \($p | txt | flat | .[:70])"
  ' "$f" 2>/dev/null
done | sort -r
```

Preferring `promptSource=="typed"` skips injected first lines (`<local-command-caveat>`, `<command-name>/model`) that make previews useless; `flat` keeps one session per output line.

### Search all sessions for a keyword (all projects)

Fast path — grep raw lines first, then inspect hits. Include the subagent dirs; a lot of work happens there:

```bash
grep -rl "KEYWORD" ~/.claude/projects/*/*.jsonl ~/.claude/projects/*/*/subagents/*.jsonl 2>/dev/null
```

Or search only what the *user* typed, via `~/.claude/history.jsonl` — which now carries `sessionId`, so a hit points straight at a transcript:

```bash
jq -r 'select(.display | test("KEYWORD"; "i")) |
  "\(.timestamp/1000 | todate)  \(.sessionId // "-")  \(.project)  \(.display[:80])"' ~/.claude/history.jsonl | tail -30
```

### Dump a session as readable markdown

```bash
jq -r '
  def txt: [.message.content | if type=="string" then . else (.[]? | select(.type=="text") | (.text // .content)) end] | join("\n");
  def tools: [.message.content | arrays | .[]? | select(.type=="tool_use") | "\(.name)(\(.input|tostring|.[:120]))"] | join("\n  ");
  select(.type=="user" or .type=="assistant")
  | (txt) as $t | (tools) as $x
  | select($t != "" or $x != "")
  | if .type=="user" then "\n## USER \(.timestamp[:16])\n\($t)"
    else "\n### ASSISTANT \(.timestamp[:16])\n\($t)" + (if $x != "" then "\n  [tools] \($x)" else "" end) end
' "$PROJ/<session-id>.jsonl"
```

Same command works on `<session-id>/subagents/agent-*.jsonl`.

### Find which session touched a file

```bash
grep -l '"file_path":"[^"]*FILENAME' ~/.claude/projects/*/*.jsonl ~/.claude/projects/*/*/subagents/*.jsonl 2>/dev/null
```

Then confirm by extracting the matching `tool_use` blocks from the hit (see dump recipe).

### Resolve a partial session ID

```bash
ls ~/.claude/projects/*/SESSION_PREFIX*.jsonl 2>/dev/null
```

### Resume a found session

```bash
claude --resume <session-id|title>   # by ID, or by the session's title
claude --continue                    # most recent session in current directory
```

In-session: `/resume <id-or-title>`. Export a live session with `/export <file>`.

## Tips

- Skip `<session-id>/` subdirectories when listing top-level sessions; those hold subagent transcripts, spilled tool output, and workflow records.
- In a subagent transcript, `.sessionId` is the **parent** session's ID, not the filename stem — join back with `.agentId` (= the `agent-<id>` stem) and the `.meta.json` sidecar's `toolUseId`.
- `tool_result` content can be huge — always truncate (`.[:200]`) when printing. Very large Bash output is not inline at all: follow `toolUseResult.persistedOutputPath` to the `tool-results/` file.
- The first `user` line of a transcript may be an injected context block rather than the human's prompt; `promptSource:"typed"`, the `last-prompt` entry, and `history.jsonl` reflect what was actually typed.
- Sessions started headless or via the SDK are stored too, but `/resume` hides anything whose `entrypoint` is `sdk-cli`, `sdk-ts` or `sdk-py` (which is what `claude -p` writes), plus sidechains, `/loop` sessions, and `sessionKind` `daemon`/`daemon-worker`. Read those straight off disk.
- Legacy and no longer written: `~/.claude/todos/`, `statsig/`, `logs/`, and stray `<session-id>.jsonl.backup` files from pre-2.x versions. `~/.claude/sessions/` is *not* legacy — it is the live per-PID session registry.
