---
name: exploring-codex-sessions
description: Finds and explores OpenAI Codex session history. Use native read-only thread APIs first when available; use local JSONL rollouts when native retrieval cannot reach the target, is incomplete, or raw storage is explicitly requested. Use when the user asks to find, search, read, export, or resume a Codex CLI session, rollout, thread, or transcript.
compatibility: Recipes require Bash and jq; compressed rollouts require zstd. sqlite3 and ripgrep are used where available. Paths are macOS/Linux.
allowed-tools: Bash(jq *) Bash(sqlite3 *) Bash(rg *) Bash(find *) Bash(zstd *) Bash(zstdcat *) Bash(zstdgrep *) Bash(cat *) Bash(head *) Bash(sort *) Bash(tail *) Bash(ls *) Bash(cut *) Bash(codex *)
metadata:
  author: jlreyes
---

# Exploring Codex Sessions

Use the narrowest read-only capability that answers the request. In Codex Desktop, `list_threads`, `read_thread`, and `list_archived_threads` can list current or archived threads and return recent status or bounded turn summaries. App-server clients can use `thread/list`, `thread/read`, `thread/turns/list`, and `thread/items/list` for metadata and history. Use these interfaces first for ordinary discovery and reading; inspect their available fields and pagination before relying on them. They do not necessarily expose the underlying rollout or every historical item.

Use raw storage when native history APIs cannot reach the target or do not contain the needed content, or when the user explicitly asks for raw storage-level detail. Do not use `resume` merely to inspect a thread. Set `CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"` and `CODEX_DB_ROOT="${CODEX_SQLITE_HOME:-$CODEX_ROOT}"`. Codex CLI stores sessions as JSONL rollouts under `$CODEX_ROOT`; rollouts are canonical and SQLite is rebuildable. Writers are mixed; persistent exec is the proven paginated-default path.

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

Every wrapped line is a rollout envelope, optionally carrying sequential `ordinal` in current paginated files (legacy readers accept no ordinal). The thirteen source variants are documented in [data-model.md](data-model.md):

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
sqlite3 -readonly -separator ' | ' "$CODEX_DB_ROOT/state_5.sqlite" \
  "SELECT datetime(updated_at,'unixepoch','localtime'), substr(id,1,13), cwd,
          substr(replace(first_user_message,char(10),' '),1,60)
   FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 20;"
```

Use 13 id chars, not 8 — UUIDv7 prefixes collide for sessions started in the same instant. Add `AND thread_source='user'` when the user wants only user-classified threads; it intentionally excludes NULL and other source classifications such as subagent and guardian threads.

### List recent sessions (filesystem only — works on every version)

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
find "$CODEX_ROOT/sessions" "$CODEX_ROOT/archived_sessions" \( -name 'rollout-*.jsonl' -o -name 'rollout-*.jsonl.zst' \) -print 2>/dev/null |
  while IFS= read -r f; do printf '%s\t%s\n' "${f##*/}" "$f"; done |
  sort | tail -20 | cut -f2-
# To inspect a first wrapped record, including a compressed rollout:
set -o pipefail
FILE=FILE
read_rollout() { case "$1" in *.jsonl.zst) zstd -dc -- "$1";; *) cat -- "$1";; esac; }
read_rollout "$FILE" | jq -r 'if input_line_number == 1 then (.payload.cwd // .cwd // "?") else empty end'
# Use the dump recipe for paginated files; see the era document for bare files.
```

### Search all sessions for a keyword

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
set -o pipefail
read_rollout() {
  case "$1" in
    *.jsonl.zst) zstd -dc -- "$1" ;;
    *) cat -- "$1" ;;
  esac
}
find "$CODEX_ROOT/sessions" "$CODEX_ROOT/archived_sessions" -type f \
  \( -name 'rollout-*.jsonl' -o -name 'rollout-*.jsonl.zst' \) -print0 |
  while IFS= read -r -d '' f; do
    if read_rollout "$f" | rg -- 'KEYWORD' >/dev/null; then
      printf '%s\n' "$f"
    else
      status=("${PIPESTATUS[@]}")
      if (( status[0] != 0 || status[1] > 1 )); then
        printf 'Could not search rollout: %s\n' "$f" >&2
        exit 2
      fi
    fi
  done || exit $?
# or search only what the user typed, with session IDs — but check freshness first:
ls -l "$CODEX_ROOT/history.jsonl"
jq -r 'select(.text|test("KEYWORD";"i")) | "\(.session_id)  \(.ts|todate)  \(.text[0:80])"' "$CODEX_ROOT/history.jsonl"
```

This searches both compressed and uncompressed active and archived rollouts. `zstd -dc` fails on invalid compressed input; do not substitute `zstdcat` unless it is configured not to pass through invalid data. The search consumes every stream before checking `PIPESTATUS`, so a match cannot be mistaken for a decompression failure caused by an early-exiting reader.

`history.jsonl` can lag badly: on the verification host its last append was 2026-07-10 despite `persistence = "save-all"` and hundreds of later sessions, and `codex exec` never appends to it. If its mtime is older than the newest rollout, use the `rg` line or `state_5.threads.first_user_message` instead.

### Resolve a logical session to its current rollout

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_DB_ROOT="${CODEX_SQLITE_HOME:-$CODEX_ROOT}"
case "$ID" in (*[!0-9a-fA-F-]*|'') echo 'Invalid ID prefix' >&2; exit 2;; esac
sqlite3 -readonly -separator ' | ' "$CODEX_DB_ROOT/state_5.sqlite" \
  "SELECT id, rollout_path FROM threads WHERE id LIKE '${ID}%';"
```

### Dump a physical rollout as markdown

```bash
set -o pipefail
FILE=FILE
read_rollout() {
  case "$1" in
    *.jsonl.zst) zstd -dc -- "$1" ;;
    *) cat -- "$1" ;;
  esac
}
read_rollout "$FILE" | jq empty >/dev/null || {
  echo 'Malformed or unreadable rollout: inspect the reported error before exporting.' >&2; exit 1;
}
read_rollout "$FILE" | jq -r '
  if .type=="event_msg" then .payload |
    if .type=="user_message" then "## User\n\n\(.message)\n"
    elif .type=="agent_message" and ((.phase//"final")!="commentary") then "## Codex\n\n\(.message)\n"
    elif .type=="item_completed" and .item.type=="UserMessage" then "## User\n\n" + ([.item.content[]? | select(.type=="text") | .text] | join("\n")) + "\n"
    elif .type=="item_completed" and .item.type=="AgentMessage" and ((.item.phase//"final")!="commentary") then "## Codex\n\n" + ([.item.content[]? | select(.type=="Text") | .text] | join("\n")) + "\n"
    elif .type=="item_completed" and (.item.type=="CollabAgentToolCall" or .item.type=="CommandExecution" or .item.type=="DynamicToolCall" or .item.type=="FileChange" or .item.type=="ImageView" or .item.type=="McpToolCall" or .item.type=="WebSearch") then "  [tool] \(.item.type)\n"
    else empty end
  elif .type=="response_item" and (.payload.type=="function_call" or .payload.type=="custom_tool_call" or .payload.type=="tool_search_call") then
    "  [tool] \(.payload.name // .payload.type)\n"
  else empty end'
```

Tool activity renders only its name or paginated category; arguments and results are intentionally omitted. This reader renders one physical rollout; for inherited fork context, follow `history_base.{thread_id,end_ordinal_exclusive,end_byte_offset}` to its parent with the exclusive cutoff, or use a native API that returns sufficient history. It is current-first and also handles legacy events; see [data-model.md](data-model.md) for older bare rollouts.

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

Verified against codex-cli **0.166.0** on **2026-10-30**. A live persistent run wrote 18 ordinalled lines (0–17), including paginated `UserMessage`/`AgentMessage` and `token_usage_record`; 5,408 rollouts (1,705,091 lines) were checked without malformed or decompression failures. See [data-model.md](data-model.md), the [0.153.4 historical snapshot](references/data-model-0.153.4.md), and the [0.146.0 historical snapshot](references/data-model-0.146.0.md).
