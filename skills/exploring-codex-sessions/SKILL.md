---
name: exploring-codex-sessions
description: Finds and explores OpenAI Codex CLI conversation history stored locally as JSONL rollout files. Use when the user asks to find, search, read, export, or resume a Codex CLI session, rollout, thread, or transcript.
compatibility: Requires jq; sqlite3 and ripgrep recommended. Paths are macOS/Linux.
allowed-tools: Bash(jq *) Bash(sqlite3 *) Bash(rg *) Bash(find *) Bash(zstdcat *) Bash(zstdgrep *) Bash(head *) Bash(sort *) Bash(tail *) Bash(ls *) Bash(cut *) Bash(codex *)
metadata:
  author: jlreyes
---

# Exploring Codex Sessions

Set `CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"` and `CODEX_DB_ROOT="${CODEX_SQLITE_HOME:-$CODEX_ROOT}"`. Codex CLI stores sessions as JSONL rollouts under `$CODEX_ROOT`; rollouts are canonical and SQLite is rebuildable. Writers are mixed; persistent exec is the proven paginated-default path.

## Storage locations

| Path | What it holds |
|------|---------------|
| `$CODEX_ROOT/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` | Full session transcripts. Date dirs use **local** time |
| `$CODEX_ROOT/archived_sessions/rollout-*.jsonl` | Archived sessions (flat, no date dirs, via `codex archive`) |
| `$CODEX_DB_ROOT/state_5.sqlite` | `threads` table: metadata index (cwd, preview, first_user_message, title, name, git info, `history_mode`, archived flag). Treat as cache — rebuilt from rollouts |
| `$CODEX_DB_ROOT/thread_history_1.sqlite` | Rebuildable transcript-item projection; contains item JSON but is not canonical |
| `$CODEX_DB_ROOT/queue_1.sqlite` | Pending user submissions; writing to it changes queue state |
| `$CODEX_ROOT/history.jsonl` | User-typed prompts: `{"session_id", "ts" (unix sec), "text"}`. **Check its mtime first** — it can silently stop being appended (see pitfall) |
| `$CODEX_ROOT/session_index.jsonl` | Thread names: `{"id", "thread_name", "updated_at"}`, last entry wins |
| `$CODEX_ROOT/config.toml` | `[history] persistence = "save-all"\|"none"` |

Sessions are **never auto-deleted** (`codex archive` / `codex delete` are manual). Rollouts may be zstd-compressed to `.jsonl.zst`; search them when `zstdgrep` or `zstdcat` is available. The SQLite root follows `CODEX_SQLITE_HOME`, then `CODEX_HOME`; do not assume `CODEX_HOME` relocates every store. `session_index.jsonl` is an append-only compatibility index; prefer SQLite where available.

## Rollout schema (quick reference)

Every wrapped line is a rollout envelope, optionally carrying sequential `ordinal` in current paginated files (legacy readers accept no ordinal). The eleven source variants are documented in [data-model.md](data-model.md):

- `session_meta` — line 1: `id`/`session_id`, `cwd`, `cli_version`, `source` (`cli`, `vscode`, `exec`, `mcp`, subagent objects), `git{branch, commit_hash, repository_url}`, `history_mode`, `context_window`, `forked_from_id`
- `response_item` — model-visible conversation: `message` (roles `user`/`assistant`/`developer`), `function_call`(+`_output`), `custom_tool_call`(+`_output`, e.g. `apply_patch`), `tool_search_call`/`tool_search_output`, `agent_message` (cross-agent delivery), `reasoning` (encrypted), `web_search_call`
- `event_msg` — legacy UI events `user_message` / `agent_message`; paginated `item_completed` carries `UserMessage` / `AgentMessage` TurnItems. Exclude commentary.
- `turn_context` — per-turn snapshot: `model`, `cwd`, `approval_policy`, `sandbox_policy`, `permission_profile`, `collaboration_mode`
- `world_state` — model-visible world snapshot (`{full, state}`: skills, environments, permissions); not conversation — skip when building transcripts
- `compacted` — compaction marker; `replacement_history[]` substitutes prior history on replay
- `inter_agent_communication` / `_metadata` — multi-agent only

**Injected-context pitfall**: `response_item` `user` and `developer` messages carry harness injections. In legacy format prefer `event_msg/user_message`; in paginated format prefer `item_completed/UserMessage`. Do not treat bare-era files as covered by these envelope recipes.

**Format and integrity pitfall**: current paginated files use `item_completed`; legacy files use `user_message`/`agent_message`. Desktop alpha corpora include malformed split records: raw `jq` can stop or truncate. Preflight before export and use the current projection/migration or an explicitly documented tolerant repair; do not silently hide failures with `fromjson?`.

## Recipes

### List recent sessions (fast path, via the index)

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_DB_ROOT="${CODEX_SQLITE_HOME:-$CODEX_ROOT}"
sqlite3 -separator ' | ' "$CODEX_DB_ROOT/state_5.sqlite" \
  "SELECT datetime(updated_at,'unixepoch','localtime'), substr(id,1,13), cwd,
          substr(replace(first_user_message,char(10),' '),1,60)
   FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 20;"
```

Use 13 id chars, not 8 — UUIDv7 prefixes collide for sessions started in the same instant. Add `AND thread_source='user'` to drop subagent/guardian threads, whose `first_user_message` is an injected block rather than human text.

### List recent sessions (filesystem only — works on every version)

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
find "$CODEX_ROOT/sessions" "$CODEX_ROOT/archived_sessions" \( -name 'rollout-*.jsonl' -o -name 'rollout-*.jsonl.zst' \) -print 2>/dev/null |
  while IFS= read -r f; do printf '%s\t%s\n' "${f##*/}" "$f"; done |
  sort | tail -20 | cut -f2-
# Wrapped legacy cwd/prompt probes (use the dump recipe for paginated files; see the era doc for bare files):
# For a compressed FILE, pipe `zstdcat FILE` into the jq probes instead of reading it directly.
head -1 FILE | jq -r '.payload.cwd // .cwd // "?"'
jq -r 'select(.type=="event_msg" and .payload.type=="user_message") | .payload.message' FILE | head -1
```

### Search all sessions for a keyword

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
rg -l --glob 'rollout-*.jsonl' 'KEYWORD' "$CODEX_ROOT/sessions" "$CODEX_ROOT/archived_sessions"
# or search only what the user typed, with session IDs — but check freshness first:
ls -l "$CODEX_ROOT/history.jsonl"
jq -r 'select(.text|test("KEYWORD";"i")) | "\(.session_id)  \(.ts|todate)  \(.text[0:80])"' "$CODEX_ROOT/history.jsonl"
```

This covers uncompressed active and archived files. For `.zst` rollouts, require zstd support and use `zstdgrep` or `zstdcat`; do not silently omit them.

`history.jsonl` can lag badly: on the verification host its last append was 2026-07-10 despite `persistence = "save-all"` and hundreds of later sessions, and `codex exec` never appends to it. If its mtime is older than the newest rollout, use the `rg` line or `state_5.threads.first_user_message` instead.

### Resolve a logical session to its current rollout

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_DB_ROOT="${CODEX_SQLITE_HOME:-$CODEX_ROOT}"
case "$ID" in (*[!0-9a-fA-F-]*|'') echo 'Invalid ID prefix' >&2; exit 2;; esac
sqlite3 -separator ' | ' "$CODEX_DB_ROOT/state_5.sqlite" \
  "SELECT id, rollout_path FROM threads WHERE id LIKE '${ID}%';"
```

### Dump a transcript as markdown

```bash
jq empty FILE >/dev/null || {
  echo 'Malformed rollout: use the current projection/migration or explicitly repair it first.' >&2; exit 1;
}
jq -r '
  if .type=="event_msg" then .payload |
    if .type=="user_message" then "## User\n\n\(.message)\n"
    elif .type=="agent_message" and ((.phase//"final")!="commentary") then "## Codex\n\n\(.message)\n"
    elif .type=="item_completed" and .item.type=="UserMessage" then "## User\n\n" + ([.item.content[]? | select(.type=="text") | .text] | join("\n")) + "\n"
    elif .type=="item_completed" and .item.type=="AgentMessage" and ((.item.phase//"final")!="commentary") then "## Codex\n\n" + ([.item.content[]? | select(.type=="Text") | .text] | join("\n")) + "\n"
    elif .type=="item_completed" and (.item.type=="CollabAgentToolCall" or .item.type=="CommandExecution" or .item.type=="DynamicToolCall" or .item.type=="FileChange" or .item.type=="ImageView" or .item.type=="McpToolCall" or .item.type=="WebSearch") then "  [tool] \(.item.type)\n"
    else empty end
  elif .type=="response_item" and (.payload.type=="function_call" or .payload.type=="custom_tool_call" or .payload.type=="tool_search_call") then
    "  [tool] \(.payload.name // .payload.type)\n"
  else empty end' FILE
```

Tool activity renders only its name or paginated category; arguments and results are intentionally omitted. This reader is current-first and also handles legacy events; see [data-model.md](data-model.md) for older bare rollouts.

### Resume, fork, and manage a found session

```bash
codex resume <SESSION_ID>            # interactive; also accepts a thread name
codex resume --last                  # most recent for current directory
codex resume --all                   # picker across all directories
codex exec resume <SESSION_ID> "prompt"   # headless continue (also --last / --all)
codex exec fork <SESSION_ID_OR_NAME> "prompt"
codex fork <SESSION_ID>              # branch into a new thread (also --last / --all)
codex archive <SESSION>              # move to archived_sessions/
codex unarchive <SESSION>            # move back
codex delete <SESSION> --force       # permanently remove (--force requires a UUID)
```

The `codex resume` picker filters to the **current cwd** and interactive sources by default; add `--all` and `--include-non-interactive` to see everything (exec/MCP/subagent sessions). `codex exec resume --all` selects across threads. `codex agents` lists agent work. Queue commands mutate pending submissions; do not use them merely to inspect history.

## Tips

- Revert can create a new rollout generation whose filename UUID differs from logical `session_meta.id`; `state_5.threads.rollout_path` resolves the current generation. Paginated forks use `history_base` lineage/cutoff rather than replaying the parent. Archive/delete/unarchive operate across logical generations and descendants.
- Filename timestamps are local time; in-file timestamps are UTC — a late-evening session can sit in the "wrong" date directory.
- Subagent/review/compact threads have object-valued `source` in `session_meta`; filter on it (or on `thread_source`) to separate human sessions from automation. On a multi-agent host they can outnumber human sessions.
- `originator` is a free-form host string, not an enum: `Codex Desktop`, `codex-tui`, `codex_cli_rs`, `codex_exec`, `codex_work_desktop` all occur.
- `codex exec --ephemeral` runs with no persisted rollout at all — such runs leave nothing under `sessions/`.
- `codex migrate-rollouts` is dry-run by default. It rewrites canonical JSONL only with `--apply`; there is no `--dry-run` flag. There is no `codex history` subcommand.

Verified against codex-cli **0.153.4** on **2026-09-06**. A live persistent run wrote 15 ordinalled lines (0–14), including paginated `UserMessage`/`AgentMessage` and `token_usage_record`; Studio and laptop corpora were exhaustively checked. See [data-model.md](data-model.md) and the [0.146.0 historical snapshot](references/data-model-0.146.0.md).
