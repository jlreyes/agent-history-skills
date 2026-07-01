# Codex CLI Session Storage — Data Model

Verified against codex-cli 0.137.x (2026-06) and re-verified against 0.142.4 (2026-07-01): real rollout files spanning Sept 2025 → Jul 2026, the `openai/codex` source (rollout crate, protocol types), and `openai/codex` release/PR history. JSONL rollouts are ground truth; `state_5.sqlite` is a rebuildable cache.

> Rollouts already on disk were written by whatever version was current at
> the time — they don't retroactively upgrade. If a rollout looks like it
> doesn't match the schema below, it may predate this verification; see
> [references/codex-cli-0.137.x.md](references/codex-cli-0.137.x.md) for
> the schema as it stood before the 2026-07-01 refresh (also see "Format
> eras" below, which covers drift within a single reference's lifetime).

## Contents

- [Directory layout](#directory-layout)
- [RolloutLine envelope](#rolloutline-envelope)
- [session_meta](#session_meta)
- [response_item](#response_item)
- [event_msg](#event_msg)
- [turn_context and compacted](#turn_context-and-compacted)
- [history.jsonl](#historyjsonl)
- [state_5.sqlite](#state_5sqlite)
- [Format eras](#format-eras-2025-2026)

## Directory layout

```
$CODEX_HOME (default ~/.codex)
├── sessions/YYYY/MM/DD/rollout-YYYY-MM-DDThh-mm-ss-<uuid>.jsonl   # transcripts
│   └── …/rollout-*.jsonl.zst        # cold-compressed (feature flag `local_thread_store_compression`, off by default as of 0.142.4; zstdcat to read)
├── archived_sessions/rollout-*.jsonl # flat; codex archive/unarchive moves files
├── history.jsonl                     # all user prompts, append-only, mode 0600
├── state_5.sqlite                    # thread metadata index (filename is schema-versioned)
├── session_index.jsonl               # thread names: {id, thread_name, updated_at}
├── external_agent_session_imports.json # 0.142.x+: manifest of rollouts transcoded from another agent's history (seen: Claude Code) — see Format eras
├── config.toml                       # [history] persistence = "save-all" | "none"; 0.142.x config.toml also holds unrelated plugins/hooks/marketplaces/desktop config
└── auth.json                         # credentials — never read or print
```

- Date dirs and filename timestamps are **local time**; in-file timestamps are UTC RFC3339.
- Session IDs are UUIDv7 (time-ordered) since ~Oct 2025, UUIDv4 before.
- No automatic retention/deletion of sessions exists; archiving (`codex archive`/`unarchive`) and permanent removal (`codex delete`) are both manual-only actions.
- `CODEX_HOME` relocates everything; `CODEX_SQLITE_HOME` additionally splits the state DB.
- 0.142.x's `$CODEX_HOME` also hosts unrelated subsystems (memories, goals, logs, hooks, plugins, skills, computer-use) with their own files/dirs — out of scope here.

## RolloutLine envelope

Every line: `{"timestamp": "<UTC RFC3339>", "type": T, "payload": {…}}` where `T` ∈ `session_meta | response_item | compacted | turn_context | event_msg`.

## session_meta

Always line 1 of a fresh session (forked/subagent files replay parent lines, so mid-file `session_meta` occurs):

```json
{"timestamp":"2026-06-30T22:13:22.488Z","type":"session_meta","payload":{
  "id":"019f1a6d-ef70-7671-aab4-a58659f559a5",
  "session_id":"019f1a6d-ef70-7671-aab4-a58659f559a5",
  "timestamp":"2026-06-30T22:13:20.529Z",
  "cwd":"/Users/me/repos/proj",
  "originator":"codex-tui",
  "cli_version":"0.142.4",
  "source":"cli",
  "thread_source":"user",
  "model_provider":"openai",
  "base_instructions":{"text":"You are Codex…"},
  "git":{"commit_hash":"9a3c93…","branch":"main","repository_url":"git@github.com:…"}}}
```

`session_id` duplicates `id` — present by 0.142.2 (Jun 2026), absent in 0.139.0; identical to `id` in every sample observed so far.

Optional fields: `forked_from_id`, `parent_thread_id`, `agent_nickname`, `agent_role`, `agent_path`, `dynamic_tools`, `memory_mode`, `multi_agent_version`.

`source` values: `"cli"`, `"vscode"`, `"exec"`, `"mcp"`, `{"custom": …}`, `{"internal": …}`, or subagent objects like `{"subagent":{"thread_spawn":{"parent_thread_id":"…","depth":1,"agent_nickname":"…","agent_role":"…"}}}` (also `review`, `compact`). Everything lands in the same `sessions/` tree; the resume picker shows only interactive sources (`cli`, `vscode`, `atlas`, `chatgpt`) unless `--include-non-interactive`.

`originator` values seen: `"codex-tui"` (CLI/TUI) and `"Codex Desktop"` (the desktop app, `codex app`) — both write into the same `sessions/` tree and are indexed in the same `state_5.sqlite`.

## response_item

The model-visible conversation. `payload.type` values:

| type | Key fields |
|------|-----------|
| `message` | `role` (`user` \| `assistant` \| `developer`), `content[]` of `{type: input_text \| output_text \| input_image, text}` |
| `reasoning` | `summary[]`, `encrypted_content` (opaque — not recoverable text) |
| `function_call` | `name`, `arguments` (JSON **string**), `call_id` |
| `function_call_output` | `call_id`, `output` |
| `custom_tool_call` / `_output` | `name` (e.g. `apply_patch`), `input` (patch text), `status` |
| `local_shell_call`, `web_search_call`, `image_generation_call` | tool-specific |
| `tool_search_call` / `tool_search_output` | 0.142.x+: on-demand MCP tool discovery. Call: `id`, `call_id`, `arguments:{query, limit}`. Output: `call_id`, `tools[]` (namespace/function defs, each with `name`/`description`/`parameters`) |

**Injected context warning**: `response_item` messages (`role:"user"` or `"developer"`) include harness injections. Skip content starting with `<user_instructions>`, `<environment_context>`, `<permissions`, `<collaboration_mode>`, `<apps_instructions>`, `<plugins_instructions>`, `<skills_instructions>`, `<environment>`, `<environment-change>`, `<app-context>` (Codex Desktop only), `# AGENTS.md`. In 2025-era files the human's text inside a wrapped message follows the marker line `## My request for Codex:`.

## event_msg

UI events; only an allowlisted subset is persisted. Common `payload.type` values:

```json
{"type":"user_message","message":"the actual typed prompt","images":[],"local_images":[],"text_elements":[]}
{"type":"agent_message","message":"…","phase":"commentary","memory_citation":null}
{"type":"task_started","turn_id":"…","started_at":1780680620,"model_context_window":258400}
{"type":"task_complete","turn_id":"…","last_agent_message":"…","completed_at":1780681472,"duration_ms":689496}
{"type":"token_count","info":{"total_token_usage":{"input_tokens":20570,"cached_input_tokens":3456,"output_tokens":531,"total_tokens":21101}},"rate_limits":{"plan_type":"pro"}}
{"type":"turn_aborted","turn_id":"…","reason":"interrupted","duration_ms":161964}
{"type":"thread_rolled_back","num_turns":1}
```

Also: `context_compacted`, `patch_apply_end`, `mcp_tool_call_end`, `web_search_end`, `item_completed`, `entered_review_mode`/`exited_review_mode`, `sub_agent_activity`.

- `user_message` events are the authoritative "what the human typed" record.
- `agent_message.phase`: `"commentary"` = streaming progress; keep only non-commentary (or `task_complete.last_agent_message`) for final answers. Absent in pre-2026 files.
- Serialized names are `task_started`/`task_complete`; readers should also accept aliases `turn_started`/`turn_complete`.

## turn_context and compacted

`turn_context` (one+ per turn; re-written after mid-turn compaction): `{turn_id?, cwd, workspace_roots, approval_policy, sandbox_policy, file_system_sandbox_policy, permission_profile, model, effort?, personality?, collaboration_mode?, multi_agent_version, current_date, timezone, realtime_active, comp_hash, summary, …}` — per-turn settings snapshot. The field set grew steadily from 0.45.0 through 0.137.0 (see Format eras); `truncation_policy` and `user_instructions` briefly lived here (~0.105.0–0.118.0) but are both gone by 0.137.0 — user instructions are no longer surfaced as a turn_context field at all, only as injected `response_item` text (see Injected context warning above).

`compacted`: `{"message":"…","replacement_history":[<ResponseItem>…]}`, plus a window-lineage set added by 0.142.x — `window_id`, `window_number`, `previous_window_id`, `first_window_id` — chaining successive compactions. On replay, `replacement_history` substitutes everything before it.

## history.jsonl

```json
{"session_id":"019e98d5-…","ts":1780680560,"text":"the typed prompt"}
```

Only user prompts, all sessions interleaved, append-only, `ts` in unix **seconds**. `session_id` matches the rollout filename UUID, so this doubles as a reverse index. `[history] persistence = "none"` disables it; `max_bytes` trims oldest to 80% of cap.

## state_5.sqlite

`threads` table columns: `id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at, git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname, agent_role, memory_mode, model, reasoning_effort, agent_path, created_at_ms, updated_at_ms, thread_source, preview, recency_at, recency_at_ms`. The last two (0.142.x+) are a separate "last opened" sort key from `updated_at`, used by the desktop app's thread list.

`thread_spawn_edges` maps parent/child subagent threads; `thread_dynamic_tools` (0.142.x+) caches per-thread tool-search results (pairs with `tool_search_call`/`_output`, above). The DB also picks up tables for unrelated subsystems by 0.142.x (`agent_jobs`/`agent_job_items` for background automations, `external_agent_config_imports`, `remote_control_enrollments`) — out of scope here. The DB is backfilled from rollout files on upgrade — always recoverable, never authoritative.

## Format eras (2025–2026)

Readers that walk old history must handle all of these:

1. **Bare era (≤ early Sept 2025)**: line 1 is raw `{"id","timestamp","instructions","git"}` — no `cwd`, no envelope, no per-line timestamps; bare response items; `{"record_type":"state"}` lines. Recover cwd from `<environment_context>` in the first user message.
2. **Wrapped era (Sept 2025 →)**: `{timestamp,type,payload}` envelope; meta gains `cwd`, `originator`, `cli_version`; `source` appears ~Oct 2025. Both formats coexist in Sept 2025 directories.
3. **Meta drift (Feb 2026 →)**: `instructions: string|null` → `base_instructions: {text}`; `model_provider` added; multi-agent fields (`agent_nickname`, `forked_from_id`, `parent_thread_id`) ~Mar 2026; `thread_source` by Jun 2026. `originator` renamed `codex_cli_rs` → `codex-tui`.
4. **Event drift**: `user_message` `{kind:"plain"}` → `{images, local_images, text_elements}`; `agent_reasoning` events persisted 2025–early 2026, since replaced by encrypted `response_item` reasoning; `exec_command_end` no longer persisted.
5. **Terminology**: "sessions"/"conversations" → "threads" in source and CLI; on-disk dirs remain `sessions/` and `archived_sessions/`.
6. **turn_context growth, then user_instructions removal (0.45.0 → 0.137.0)**: fields accreted steadily (`turn_id`, `personality`, `collaboration_mode` by 0.105.0; `current_date`/`timezone`/`realtime_active` by 0.117.0; `workspace_roots`/`permission_profile`/`file_system_sandbox_policy`/`multi_agent_version` by 0.137.0). `truncation_policy` and `user_instructions` — present 0.105.0–0.118.0 — are both gone from turn_context by 0.137.0.
7. **Tool search, session_id, window lineage (0.142.x, Jun 2026 →)**: `session_meta.payload.session_id` (duplicates `id`) and default-on `response_item` types `tool_search_call`/`tool_search_output` (on-demand MCP tool discovery) both landed ~0.142.0–0.142.2. `compacted` gained a window-lineage scheme (`window_id`, `window_number`, `previous_window_id`, `first_window_id`) around the same point ("context window lineage IDs"). New injected-context prefixes appear in `response_item` messages: `<plugins_instructions>`, `<skills_instructions>`, `<environment>` (ambient Wi-Fi/power/display/time orientation, `role:"developer"`), `<environment-change>` (mid-session environment-change notice, `role:"developer"`); Codex Desktop sessions (`originator:"Codex Desktop"`) additionally get a `<app-context>` block. `state_5.sqlite.threads` gained `recency_at`/`recency_at_ms`; a new `thread_dynamic_tools` table caches tool-search results per thread.
8. **External-agent session import (~0.140, Jun 2026 →)**: Codex can transcode another agent's local history into native-looking rollouts (observed: Claude Code, from `~/.claude/projects/**/*.jsonl`). Imported files carry a normal envelope and session_meta — no in-rollout marker distinguishes them from native sessions. Cross-reference `~/.codex/external_agent_session_imports.json` (`records[].source_path`, `.imported_thread_id`, `.imported_at`) to identify them.
