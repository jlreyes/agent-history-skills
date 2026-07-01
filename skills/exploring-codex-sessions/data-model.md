# Codex CLI Session Storage — Data Model

Verified against Codex CLI 0.142.5 / on 2026-07-01: a real `codex exec` rollout on this machine plus the `openai/codex` source at tag `rust-v0.142.5` (`protocol/src/{protocol.rs,models.rs}`, `message-history`, `config`). JSONL rollouts are ground truth; `state_5.sqlite` is a rebuildable cache. For reading pre-0.140 files see the archived [references/0.137.x.md](references/0.137.x.md).

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
│   └── …/rollout-*.jsonl.zst        # cold-compressed (feature flag; zstdcat to read)
├── archived_sessions/rollout-*.jsonl # flat; codex archive/unarchive moves files
├── history.jsonl                     # interactive (TUI) typed prompts, append-only, mode 0600
├── state_5.sqlite                    # thread metadata index (filename is schema-versioned)
├── goals_1.sqlite / memories_1.sqlite / logs_2.sqlite  # sibling caches (goals, memory, telemetry)
├── session_index.jsonl               # thread names: {id, thread_name, updated_at}
├── installation_id                   # opaque per-install id
├── config.toml                       # [history] persistence = "save-all" (default) | "none"
└── auth.json                         # credentials — never read or print
```

Sibling DBs (`goals_1`, `memories_1`, `logs_2`) and each `state_*` are all schema-versioned caches, WAL-mode, rebuildable — none are session ground truth. `history.jsonl`, `session_index.jsonl`, and the SQLite files only appear once the relevant feature has run; a fresh install / `codex exec`-only usage may have none of them (`exec` sessions write a rollout + `state_5.sqlite` row but do **not** append to `history.jsonl`).

- Date dirs and filename timestamps are **local time**; in-file timestamps are UTC RFC3339.
- Session IDs are UUIDv7 (time-ordered) since ~Oct 2025, UUIDv4 before.
- No automatic retention/deletion of sessions exists; archiving is manual.
- `CODEX_HOME` relocates everything; `CODEX_SQLITE_HOME` additionally splits the state DB.

## RolloutLine envelope

Every line: `{"timestamp": "<UTC RFC3339>", "type": T, "payload": {…}}` where `T` ∈ `session_meta | response_item | inter_agent_communication | compacted | turn_context | event_msg` (six `RolloutItem` variants as of 0.142; `inter_agent_communication` was added for multi-agent and replays as a synthetic `agent_message`).

## session_meta

Always line 1 of a fresh session (forked/subagent files replay parent lines, so mid-file `session_meta` occurs):

```json
{"timestamp":"2026-07-01T19:19:37.885Z","type":"session_meta","payload":{
  "session_id":"019f1f1f-607a-7642-9f69-59c37ab513e2",
  "id":"019f1f1f-607a-7642-9f69-59c37ab513e2",
  "timestamp":"2026-07-01T19:19:37.850Z",
  "cwd":"/tmp",
  "originator":"codex_exec",
  "cli_version":"0.142.5",
  "source":"exec",
  "thread_source":"user",
  "model_provider":"openai",
  "base_instructions":{"text":"You are Codex…"},
  "git":{"commit_hash":"9a3c93…","branch":"main","repository_url":"git@github.com:…"}}}
```

`session_id` and `id` carry the same UUID; both are present in ≥0.140 files. Older files have only `id` (readers backfill `session_id` from it). Optional fields: `forked_from_id`, `parent_thread_id`, `agent_nickname`, `agent_role` (accepts alias `agent_type`), `agent_path`, `dynamic_tools`, `memory_mode`, `multi_agent_version`. `git` sits at the top level of `payload`, not inside `SessionMeta`. `originator` is `codex-tui` for the TUI, `codex_exec` for `codex exec`.

`source` values: `"cli"`, `"vscode"`, `"exec"`, `"mcp"`, `{"custom": …}`, `{"internal":"memory_consolidation"}`, or subagent objects like `{"subagent":{"thread_spawn":{"parent_thread_id":"…","depth":1,"agent_nickname":"…","agent_role":"…"}}}` (also `{"subagent":"review"}`, `{"subagent":"compact"}`, `{"subagent":"memory_consolidation"}`). Unknown strings deserialize to `"unknown"`. Everything lands in the same `sessions/` tree; the resume picker shows only interactive sources (`cli`, `vscode`) unless `--include-non-interactive`. `thread_source` values: `user`, `subagent`, `memory_consolidation`, or a feature string.

## response_item

The model-visible conversation. `payload.type` values:

| type | Key fields |
|------|-----------|
| `message` | `role` (`user` \| `assistant` \| `developer`), `content[]` of `{type: input_text \| output_text \| input_image, text}`, optional `phase` (`commentary` \| `final_answer`) |
| `reasoning` | `summary[]`, optional `content[]`, `encrypted_content` (opaque — not recoverable text) |
| `agent_message` | multi-agent inter-agent turn: `author`, `recipient`, `content[]` (distinct from the `event_msg` `agent_message`) |
| `function_call` | `name`, optional `namespace`, `arguments` (JSON **string**), `call_id` |
| `function_call_output` | `call_id`, `output` (string or `content_items[]`) |
| `custom_tool_call` / `_output` | `name` (e.g. `apply_patch`), `input` (patch text), `status` |
| `tool_search_call` / `tool_search_output` | deferred-tool search: `execution`, `arguments`/`tools[]`, `status` |
| `local_shell_call`, `web_search_call`, `image_generation_call` | tool-specific |

Every variant may carry `id` and `internal_chat_message_metadata_passthrough` (`{turn_id}`).

**Injected context warning**: `role:"user"` (and injected `role:"developer"`) messages include harness injections. Skip content starting with `<user_instructions>`, `<environment_context>`, `<permissions instructions>`, `<collaboration_mode>`, `<apps_instructions>`, `# AGENTS.md`. (The AGENTS.md fragment now renders as `# AGENTS.md instructions … <INSTRUCTIONS>…</INSTRUCTIONS>`; the permissions fragment as `<permissions instructions>…</permissions instructions>`.) In 2025-era files the human's text inside a wrapped message follows the marker line `## My request for Codex:`.

## event_msg

UI events; only an allowlisted subset is persisted. Common `payload.type` values:

```json
{"type":"user_message","message":"the actual typed prompt","images":[],"local_images":[],"text_elements":[]}
{"type":"agent_message","message":"…","phase":"commentary","memory_citation":null}
{"type":"task_started","turn_id":"…","started_at":1782933577,"model_context_window":258400,"collaboration_mode_kind":"default"}
{"type":"task_complete","turn_id":"…","last_agent_message":"…"|null,"completed_at":1782933579,"duration_ms":1970}
{"type":"token_count","info":{"total_token_usage":{"input_tokens":20570,"cached_input_tokens":3456,"output_tokens":531,"total_tokens":21101}},"rate_limits":{"plan_type":"pro"}}
{"type":"turn_aborted","turn_id":"…","reason":"interrupted","duration_ms":161964}
{"type":"thread_rolled_back","num_turns":1}
```

Also: `context_compacted`, `patch_apply_end`, `mcp_tool_call_end`, `web_search_end`, `item_completed`, `entered_review_mode`/`exited_review_mode`, `sub_agent_activity`.

- `user_message` events are the authoritative "what the human typed" record.
- `agent_message.phase`: `"commentary"` = streaming progress; keep only non-commentary (or `task_complete.last_agent_message`) for final answers. Absent in pre-2026 files.
- Serialized names are `task_started`/`task_complete`; readers should also accept aliases `turn_started`/`turn_complete`.

## turn_context and compacted

`turn_context` (one+ per turn; re-written after mid-turn compaction) — per-turn settings snapshot. Real 0.142 payload:

```json
{"turn_id":"…","cwd":"/tmp","workspace_roots":["/tmp"],"current_date":"2026-07-01",
 "timezone":"Etc/UTC","approval_policy":"never","sandbox_policy":{"type":"read-only"},
 "permission_profile":{"type":"managed","file_system":{…},"network":"restricted"},
 "model":"gpt-5.5","personality":"pragmatic",
 "collaboration_mode":{"mode":"default","settings":{"model":"gpt-5.5","reasoning_effort":null,"developer_instructions":null}},
 "multi_agent_version":"v1","realtime_active":false,"summary":"auto"}
```

Other optional fields: `network` (`{allowed_domains,denied_domains}`), `file_system_sandbox_policy`, `comp_hash`, `multi_agent_mode`, `effort`. `summary` is a compat-only field still written with a default. Older files carry only the small subset (`cwd`, `approval_policy`, `sandbox_policy`, `model`, `effort?`).

`compacted`: `{"message":"…","replacement_history":[<ResponseItem>…]?}` plus context-window chain ids (`window_number`, `window_id`, `first_window_id`, `previous_window_id`) added in the 0.14x line. On replay, `replacement_history` substitutes everything before it.

## history.jsonl

```json
{"session_id":"019e98d5-…","ts":1780680560,"text":"the typed prompt"}
```

Only user prompts, append-only, `ts` in unix **seconds**. `session_id` matches the rollout filename UUID, so this doubles as a reverse index. **Written only for interactive (TUI) sessions** — `append_entry` is called from `tui/` only, so `codex exec` prompts never land here (use the rollout `event_msg`/`user_message` records for those). Default `[history] persistence = "save-all"`; `"none"` disables it; `max_bytes` trims oldest to 80% of cap.

## state_5.sqlite

`threads` table columns (0.142): `id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at, git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname, agent_role, memory_mode, model, reasoning_effort, agent_path, created_at_ms, updated_at_ms, thread_source, preview, recency_at, recency_at_ms` (`recency_at`/`recency_at_ms` were added in the 0.14x line and now back the resume picker's default ordering).

Other tables: `thread_spawn_edges` (parent/child subagent map), `thread_dynamic_tools`, `agent_jobs`/`agent_job_items`, `backfill_state`, `remote_control_enrollments`, `external_agent_config_imports`, `_sqlx_migrations`. The DB is backfilled from rollout files on upgrade — always recoverable, never authoritative.

## Format eras (2025–2026)

Readers that walk old history must handle all of these:

1. **Bare era (≤ early Sept 2025)**: line 1 is raw `{"id","timestamp","instructions","git"}` — no `cwd`, no envelope, no per-line timestamps; bare response items; `{"record_type":"state"}` lines. Recover cwd from `<environment_context>` in the first user message.
2. **Wrapped era (Sept 2025 →)**: `{timestamp,type,payload}` envelope; meta gains `cwd`, `originator`, `cli_version`; `source` appears ~Oct 2025. Both formats coexist in Sept 2025 directories.
3. **Meta drift (Feb 2026 →)**: `instructions: string|null` → `base_instructions: {text}`; `model_provider` added; multi-agent fields (`agent_nickname`, `forked_from_id`, `parent_thread_id`) ~Mar 2026; `thread_source` by Jun 2026. `originator` renamed `codex_cli_rs` → `codex-tui`.
4. **Event drift**: `user_message` `{kind:"plain"}` → `{images, local_images, text_elements}`; `agent_reasoning` events persisted 2025–early 2026, since replaced by encrypted `response_item` reasoning; `exec_command_end` no longer persisted.
5. **0.14x expansion (mid-2026)**: `session_meta` gains `session_id` (alongside `id`); `RolloutItem` gains the `inter_agent_communication` variant; `turn_context` grows from a 4-field snapshot to the full permission/collaboration/multi-agent payload above; `compacted` gains window-chain ids; `response_item` gains `agent_message`/`tool_search_call`/`tool_search_output`; injection wrappers renamed (`<permissions instructions>`, `# AGENTS.md instructions`). Reading pre-0.140 files: see archived [references/0.137.x.md](references/0.137.x.md).
6. **Terminology**: "sessions"/"conversations" → "threads" in source and CLI; on-disk dirs remain `sessions/` and `archived_sessions/`.
