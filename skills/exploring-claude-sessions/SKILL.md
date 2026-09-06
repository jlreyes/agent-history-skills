---
name: exploring-claude-sessions
description: Finds and explores Claude Code session history stored locally as JSONL transcripts. Use when the user asks to find, search, read, export, or resume a past Claude Code session, conversation, or transcript, or to see what a previous Claude Code session did.
compatibility: Requires jq. Paths are macOS/Linux.
allowed-tools: Bash(jq *) Bash(ls *) Bash(grep *) Bash(find *) Bash(basename *) Bash(sort *) Bash(tail *) Bash(claude *)
metadata:
  author: jlreyes
---

# Exploring Claude Code Sessions

Set `CLAUDE_ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"`. Claude Code stores each session as JSONL under `$CLAUDE_ROOT/projects/`. The usual project slug is the cwd with `/` changed to `-`; if `CLAUDE_CODE_PROJECT_DIR_NAME` is set or uncertain, list/search `$CLAUDE_ROOT/projects` instead—it cannot be derived before finding the transcript.

## Storage locations

| Path | What it holds |
|------|---------------|
| `$CLAUDE_ROOT/projects/<project-slug>/<session-id>.jsonl` | Main session transcripts |
| `$CLAUDE_ROOT/projects/<project-slug>/<session-id>/subagents/agent-<agent-id>.jsonl` | Subagent transcripts (same schema), with `agent-<agent-id>.meta.json` (agent type, description, spawn depth) |
| `$CLAUDE_ROOT/projects/<project-slug>/<session-id>/subagents/journal.jsonl` | Subagent lifecycle records: `started` / `result`; not a conversation transcript |
| `$CLAUDE_ROOT/projects/<project-slug>/<session-id>/tool-results/<id>.txt` | Large tool outputs spilled to their own files, pointed at by `toolUseResult.persistedOutputPath` |
| `$CLAUDE_ROOT/projects/<project-slug>/<session-id>/workflows/wf_*.json` | Per-session workflow run records |
| `$CLAUDE_ROOT/projects/<project-slug>/memory/` | Per-project auto-memory (markdown) |
| `$CLAUDE_ROOT/projects/<project-slug>/.session-aliases` | Pointers to *sibling project directories* for the same working dir — one absolute `$CLAUDE_ROOT/projects/<slug>` path per line. **Not** session names |
| `$CLAUDE_ROOT/history.jsonl` | Global prompt history: `{display, timestamp(ms), project, sessionId}` per line |
| `$CLAUDE_ROOT/file-history/<session-id>/<hash>@v<N>` | File snapshots backing checkpoint/undo |
| `$CLAUDE_ROOT/sessions/<pid>.json` | Live registry of *running* sessions: `{pid, sessionId, cwd, version, kind, entrypoint, name, status, …}` |

**Project slug encoding**: the session's working directory with `/` replaced by `-`. `/Users/me/repos/Foo` → `-Users-me-repos-Foo`.

**Retention**: CLI transcripts are auto-cleaned after 30 days by default (`cleanupPeriodDays` in `$CLAUDE_ROOT/settings.json`; minimum 1). A session's `subagents/` and `tool-results/` age out with it. `history.jsonl` is never auto-cleaned. Claude Desktop has a separate retention exemption since 2.1.248, controlled by `desktopSessionCleanupPeriodDays`; this skill remains CLI-scoped. `claude project purge [path]` deletes one project's transcripts, memory, tasks, file-history and `history.jsonl` lines.

## Transcript schema (quick reference)

Entry types per line: `user`, `assistant`, `attachment`, `system`, `mode`, `permission-mode`, `ai-title`, `custom-title`, `last-prompt`, `queue-operation`, `file-history-snapshot`, `file-history-delta`, `pr-link`, `bridge-session`, `relocated`, `worktree-state`, `agent-name`, `agent-setting`, `frame-link`, `summary`, `atis-latch`, `history-suppression`, `artifact-autoreact-ledger`, `artifact-comment-monitor`. Full field tables and examples: [data-model.md](data-model.md). `started` and `result` are journal-only lifecycle records.

The fields needed for most exploration:

- `user` / `assistant` entries: `.timestamp` (ISO 8601), `.sessionId`, `.cwd`, `.gitBranch`, `.message.content` (string **or** array of blocks: `text`, `thinking`, `tool_use`, `tool_result`, `image`), `.uuid` / `.parentUuid` (conversation chain), `.isSidechain` (subagent work), `.agentId` (which subagent)
- `user` entries carrying a tool result: `.toolUseResult` (structured result), `.sourceToolAssistantUUID` (the `assistant` entry that called the tool)
- `agent-name` entries: `.agentName` is the current session name. `ai-title` and `custom-title` remain reader-compatible generated/user-set titles.
- `assistant` entries: `.message.model`, `.message.usage` (token counts), `.effort`

## Recipes

### List sessions for a project, newest first

```bash
CLAUDE_ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
PROJ="$CLAUDE_ROOT/projects/-Users-me-repos-Foo"   # usual cwd-derived slug
for f in "$PROJ"/*.jsonl; do
  jq -rs --arg id "$(basename "$f" .jsonl)" '
    def flat: gsub("\\s+"; " ");
    def txt: if .type=="last-prompt" then .lastPrompt else .message.content
      | if type=="string" then . else [.[]? | select(.type=="text") | (.text // .content)] | join(" ") end end;
    (map(select(.type=="agent-name")) | last | .agentName) as $agentName |
    (map(select(.type=="custom-title")) | last | .customTitle) as $customTitle |
    (map(select(.type=="ai-title")) | last | .aiTitle) as $aiTitle |
    map(select(.type=="user")) as $u |
    (($u | map(select(.promptSource=="typed")) | first)
      // (map(select(.type=="last-prompt")) | last)
      // ($u | map(select((.isMeta != true) and (.toolUseResult == null) and (.message.content | tostring | startswith("<") | not))) | first)) as $p |
    select($p != null) |
    "\($p.timestamp[:16])  \($id[:8])  \($p.gitBranch // "?")  \($agentName // $customTitle // $aiTitle // "-")  |  \($p | txt | flat | .[:70])"
  ' "$f" 2>/dev/null
done | sort -r
```

Preferring `promptSource=="typed"` skips injected first lines (`<local-command-caveat>`, `<command-name>/model`) that make previews useless; `flat` keeps one session per output line.

### Search all sessions for a keyword (all projects)

Fast path — grep raw lines first, then inspect hits. Include the subagent dirs; a lot of work happens there:

```bash
grep -rl "KEYWORD" "$CLAUDE_ROOT"/projects/*/*.jsonl "$CLAUDE_ROOT"/projects/*/*/subagents/*.jsonl 2>/dev/null
```

Or search only what the *user* typed, via `$CLAUDE_ROOT/history.jsonl` — which now carries `sessionId`, so a hit points straight at a transcript:

```bash
jq -r 'select(.display | test("KEYWORD"; "i")) |
  "\(.timestamp/1000 | todate)  \(.sessionId // "-")  \(.project)  \(.display[:80])"' "$CLAUDE_ROOT/history.jsonl" | tail -30
```

### Dump a session as readable markdown

```bash
jq -r '
  def txt: [.message.content | if type=="string" then . else (.[]? | select(.type=="text") | (.text // .content)) end] | join("\n");
  def tools: [.message.content | arrays | .[]? | select(.type=="tool_use") | .name] | join("\n  ");
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
grep -l '"file_path":"[^"]*FILENAME' "$CLAUDE_ROOT"/projects/*/*.jsonl "$CLAUDE_ROOT"/projects/*/*/subagents/*.jsonl 2>/dev/null
```

Then confirm by extracting the matching `tool_use` blocks from the hit (see dump recipe).

### Resolve a partial session ID

```bash
ls "$CLAUDE_ROOT"/projects/*/SESSION_PREFIX*.jsonl 2>/dev/null
```

### Resume a found session

```bash
claude --resume <session-id|title>   # by ID, or a reader-compatible title
claude --continue                    # most recent session in current directory
claude attach <id>                   # short background ID, not a transcript UUID
claude logs <id>
claude stop <id>
claude respawn <id>
claude respawn --all
claude rm <id>
```

In-session: `/resume <id-or-title>`. `/export` is interactive: it copies to the clipboard or accepts a filename. `-p`/SDK sessions are hidden from the picker but remain directly resumable by ID.

## Tips

- Skip `<session-id>/` subdirectories when listing top-level sessions; those hold subagent transcripts, spilled tool output, and workflow records.
- In a subagent transcript, `.sessionId` is the **parent** session's ID, not the filename stem — join back with `.agentId` (= the `agent-<id>` stem) and the `.meta.json` sidecar's `toolUseId`.
- `tool_result` content can be huge — always truncate (`.[:200]`) when printing. Very large Bash output is not inline at all: follow `toolUseResult.persistedOutputPath` to the `tool-results/` file.
- The first `user` line of a transcript may be an injected context block rather than the human's prompt; `promptSource:"typed"`, the `last-prompt` entry, and `history.jsonl` reflect what was actually typed.
- Sessions started headless or via the SDK are stored too, but `/resume` hides anything whose `entrypoint` is `sdk-cli`, `sdk-ts` or `sdk-py` (which is what `claude -p` writes), plus sidechains, `/loop` sessions, and `sessionKind` `daemon`/`daemon-worker`. Read those straight off disk.
- Legacy and no longer written: `$CLAUDE_ROOT/todos/`, `statsig/`, `logs/`, and stray `<session-id>.jsonl.backup` files from pre-2.x versions. `$CLAUDE_ROOT/sessions/` is *not* legacy — it is the live per-PID session registry.
