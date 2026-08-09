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
| `~/.codex/archived_sessions/rollout-*.jsonl` | Archived sessions (flat, no date dirs, via `codex archive`) |
| `~/.codex/state_5.sqlite` | `threads` table: metadata index (cwd, preview, first_user_message, title, name, git info, `history_mode`, archived flag). Treat as cache — rebuilt from rollouts |
| `~/.codex/history.jsonl` | User-typed prompts: `{"session_id", "ts" (unix sec), "text"}`. **Check its mtime first** — it can silently stop being appended (see pitfall) |
| `~/.codex/session_index.jsonl` | Thread names: `{"id", "thread_name", "updated_at"}`, last entry wins |
| `~/.codex/config.toml` | `[history] persistence = "save-all"\|"none"` |

Sessions are **never auto-deleted** (`codex archive` / `codex delete` are manual). Rollouts older than 7 days may be zstd-compressed to `.jsonl.zst` (read with `zstdcat`). Everything else in `~/.codex` — `memories_1`/`goals_1`/`logs_2.sqlite`, `sqlite/`, `.codex-global-state.json`, `skills/`, `plugins/`, `shell_snapshots/` — belongs to other subsystems and holds no transcripts. `CODEX_HOME` relocates everything.

## Rollout schema (quick reference)

Every line: `{"timestamp": "<UTC RFC3339>", "type": "<tag>", "payload": {...}}` with eight tags — full detail in [data-model.md](data-model.md):

- `session_meta` — line 1: `id`/`session_id`, `cwd`, `cli_version`, `source` (`cli`, `vscode`, `exec`, `mcp`, subagent objects), `git{branch, commit_hash, repository_url}`, `history_mode`, `context_window`, `forked_from_id`
- `response_item` — model-visible conversation: `message` (roles `user`/`assistant`/`developer`), `function_call`(+`_output`), `custom_tool_call`(+`_output`, e.g. `apply_patch`), `tool_search_call`/`tool_search_output`, `agent_message` (cross-agent delivery), `reasoning` (encrypted), `web_search_call`
- `event_msg` — UI events: `user_message` (**authoritative record of what the user typed**), `agent_message` (`phase`: `"commentary"` stream vs `"final_answer"`), `task_complete` (`last_agent_message`), `token_count`, `turn_aborted`
- `turn_context` — per-turn snapshot: `model`, `cwd`, `approval_policy`, `sandbox_policy`, `permission_profile`, `collaboration_mode`
- `world_state` — model-visible world snapshot (`{full, state}`: skills, environments, permissions); not conversation — skip when building transcripts
- `compacted` — compaction marker; `replacement_history[]` substitutes prior history on replay
- `inter_agent_communication` / `_metadata` — multi-agent only

**Injected-context pitfall**: `response_item` `user` **and** `developer` messages carry harness injections. Skip texts starting with `<environment_context>`, `<permissions instructions>`, `# AGENTS.md`, `<skills_instructions>`, `<apps_instructions>`, `<recommended_plugins>`, `<multi_agent_mode>`, `<collaboration_mode>`, `<app-context>`, `<environment>`, `<skill>`, `<turn_aborted>`, `<environment-change>`, `<task-notification>`, `<user_instructions>`, `## Memory`, ``You are `/root`, the primary agent``, or `The following is the Codex agent history` (guardian threads). Prefer `event_msg`/`user_message` for the human's words.

**history_mode pitfall**: `head -1 FILE | jq -r '.payload.history_mode'`. In `legacy` (the default, and everything observed on disk) the recipes below work as written. In `paginated` there are **no** `user_message`/`agent_message` events — read `select(.type=="event_msg" and .payload.type=="item_completed") | .payload.item` instead. Note the reverse does not hold: `item_completed` also appears in legacy files for `Plan` items.

## Recipes

### List recent sessions (fast path, via the index)

```bash
sqlite3 -separator ' | ' ~/.codex/state_5.sqlite \
  "SELECT datetime(updated_at,'unixepoch','localtime'), substr(id,1,13), cwd,
          substr(replace(first_user_message,char(10),' '),1,60)
   FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 20;"
```

Use 13 id chars, not 8 — UUIDv7 prefixes collide for sessions started in the same instant. Add `AND thread_source='user'` to drop subagent/guardian threads, whose `first_user_message` is an injected block rather than human text.

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
# or search only what the user typed, with session IDs — but check freshness first:
ls -l ~/.codex/history.jsonl
jq -r 'select(.text|test("KEYWORD";"i")) | "\(.session_id)  \(.ts|todate)  \(.text[0:80])"' ~/.codex/history.jsonl
```

`history.jsonl` can lag badly: on the verification host its last append was 2026-07-10 despite `persistence = "save-all"` and hundreds of later sessions, and `codex exec` never appends to it. If its mtime is older than the newest rollout, use the `rg` line or `state_5.threads.first_user_message` instead.

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

For tool calls add: `select(.type=="response_item" and .payload.type=="function_call") | "  [tool] \(.payload.name)(\(.payload.arguments[:150]))"`. This covers `history_mode:"legacy"` files. For `paginated` files and pre-late-2025 files (no `event_msg` wrapper — the query above correctly returns nothing) see the era notes in [data-model.md](data-model.md).

### Resume, fork, and manage a found session

```bash
codex resume <SESSION_ID>            # interactive; also accepts a thread name
codex resume --last                  # most recent for current directory
codex resume --all                   # picker across all directories
codex exec resume <SESSION_ID> "prompt"   # headless continue (also --last / --all)
codex fork <SESSION_ID>              # branch into a new thread (also --last / --all)
codex archive <SESSION>              # move to archived_sessions/
codex unarchive <SESSION>            # move back
codex delete <SESSION> --force       # permanently remove (--force requires a UUID)
```

The `codex resume` picker filters to the **current cwd** and interactive sources by default; add `--all` and `--include-non-interactive` to see everything (exec/MCP/subagent sessions). `codex fork` takes `--all` but not `--include-non-interactive`.

## Tips

- Resume appends to the same rollout file; fork creates a new file whose line-1 `session_meta` has `forked_from_id`/`parent_thread_id` and then replays the parent's lines — so mid-file `session_meta` lines (carrying the *parent's* id) exist in forked files.
- Filename timestamps are local time; in-file timestamps are UTC — a late-evening session can sit in the "wrong" date directory.
- Subagent/review/compact threads have object-valued `source` in `session_meta`; filter on it (or on `thread_source`) to separate human sessions from automation. On a multi-agent host they can outnumber human sessions.
- `originator` is a free-form host string, not an enum: `Codex Desktop`, `codex-tui`, `codex_cli_rs`, `codex_exec`, `codex_work_desktop` all occur.
- `codex exec --ephemeral` runs with no persisted rollout at all — such runs leave nothing under `sessions/`.
- There is no `codex history` subcommand — `history.jsonl`, `state_5.sqlite`, and the recipes above are the interface.

Verified against codex-cli **0.146.0** on **2026-08-09**.
