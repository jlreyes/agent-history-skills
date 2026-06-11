---
name: exploring-codex-sessions
description: Finds and explores OpenAI Codex CLI conversation history stored locally as JSONL rollout files. Use when the user asks to find, search, read, export, or resume a Codex CLI session, rollout, thread, or transcript.
compatibility: Requires jq; sqlite3 and ripgrep recommended. Paths are macOS/Linux (~/.codex).
allowed-tools: Bash(jq *) Bash(sqlite3 *) Bash(rg *) Bash(find *)
metadata:
  author: jlreyes
---

# Exploring Codex Sessions

Codex CLI stores every session ("thread") as a JSONL rollout file under `$CODEX_HOME` (default `~/.codex`). The JSONL files are ground truth; a SQLite index caches metadata.

## Storage locations

| Path | What it holds |
|------|---------------|
| `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` | Full session transcripts. `<uuid>` is the session/thread ID (UUIDv7, time-sortable). Date dirs use **local** time |
| `~/.codex/archived_sessions/rollout-*.jsonl` | Archived sessions (flat, via `codex archive`) |
| `~/.codex/history.jsonl` | Every user-typed prompt across all sessions: `{"session_id", "ts" (unix sec), "text"}` |
| `~/.codex/state_5.sqlite` | `threads` table: metadata index (cwd, preview, title, git info, archived flag). Treat as cache — rebuilt from rollouts |
| `~/.codex/session_index.jsonl` | Thread names: `{"id", "thread_name", "updated_at"}`, last entry wins |
| `~/.codex/config.toml` | `[history] persistence = "save-all"\|"none"` |

Sessions are **never auto-deleted**. Cold rollouts may be zstd-compressed to `.jsonl.zst` (feature-flagged; read with `zstdcat`). `CODEX_HOME` env var relocates everything.

## Rollout schema (quick reference)

Every line: `{"timestamp": "<UTC RFC3339>", "type": "<tag>", "payload": {...}}` with five tags — full detail in [data-model.md](data-model.md):

- `session_meta` — line 1: `id`, `cwd`, `cli_version`, `source` (`cli`, `vscode`, `exec`, `mcp`, subagent objects), `git{branch, commit_hash, repository_url}`, `forked_from_id`
- `response_item` — model-visible conversation: `message` (roles `user`/`assistant`/`developer`), `function_call`(+`_output`), `custom_tool_call` (e.g. `apply_patch`), `reasoning` (encrypted), `web_search_call`
- `event_msg` — UI events: `user_message` (**authoritative record of what the user typed**), `agent_message` (`phase`: `"commentary"` stream vs final), `task_complete` (`last_agent_message`), `token_count`, `turn_aborted`
- `turn_context` — per-turn snapshot: `model`, `cwd`, `approval_policy`, `sandbox_policy`
- `compacted` — compaction marker; `replacement_history[]` substitutes prior history on replay

**Pitfall**: `response_item` user messages include injected context. Skip texts starting with `<user_instructions>`, `<environment_context>`, `<permissions`, `<collaboration_mode>`, `<apps_instructions>`, or `# AGENTS.md`. Prefer `event_msg`/`user_message` for the human's words.

## Recipes

### List recent sessions (fast path, via the index)

```bash
sqlite3 -separator ' | ' ~/.codex/state_5.sqlite \
  "SELECT datetime(updated_at,'unixepoch','localtime'), substr(id,1,8), cwd,
          substr(replace(preview,char(10),' '),1,60)
   FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 20;"
```

### List recent sessions (filesystem only — works on every version)

```bash
find ~/.codex/sessions -name 'rollout-*.jsonl*' | sort | tail -20
# cwd + first real prompt of one file:
head -1 FILE | jq -r '.payload.cwd // .cwd // "?"'
jq -r 'select(.type=="event_msg" and .payload.type=="user_message") | .payload.message' FILE | head -1
```

### Search all sessions for a keyword

```bash
rg -l --glob 'rollout-*.jsonl' 'KEYWORD' ~/.codex/sessions
# or search only what the user typed, with session IDs:
jq -r 'select(.text|test("KEYWORD";"i")) | "\(.session_id)  \(.ts|todate)  \(.text[0:80])"' ~/.codex/history.jsonl
```

### Map a session ID to its file

```bash
find ~/.codex/sessions ~/.codex/archived_sessions -name "rollout-*${ID}*.jsonl*" 2>/dev/null
```

### Dump a transcript as markdown

```bash
jq -r 'select(.type=="event_msg") | .payload |
  if .type=="user_message" then "## User\n\n\(.message)\n"
  elif .type=="agent_message" and ((.phase//"final")!="commentary") then "## Codex\n\n\(.message)\n"
  else empty end' FILE
```

For tool calls add: `select(.type=="response_item" and .payload.type=="function_call") | "  [tool] \(.payload.name)(\(.payload.arguments[:150]))"`. For pre-late-2025 files (no `event_msg` wrapper) see the era notes in [data-model.md](data-model.md).

### Resume a found session

```bash
codex resume <SESSION_ID>            # interactive; also accepts a thread name
codex resume --last                  # most recent for current directory
codex resume --all                   # picker across all directories
codex exec resume <SESSION_ID> "prompt"   # headless continue
codex fork <SESSION_ID>              # branch into a new thread
```

The `codex resume` picker filters to the **current cwd** and interactive sources by default; add `--all` and `--include-non-interactive` to see everything (exec/MCP/subagent sessions).

## Tips

- Resume appends to the same rollout file; fork creates a new file whose `session_meta` has `forked_from_id` and replays parent lines — so mid-file `session_meta` lines exist in forked files.
- Filename timestamps are local time; in-file timestamps are UTC — a late-evening session can sit in the "wrong" date directory.
- Subagent/review/compact threads have object-valued `source` in `session_meta`; filter on it to separate human sessions from automation.
- There is no `codex history` subcommand — `history.jsonl` plus the recipes above are the interface.
