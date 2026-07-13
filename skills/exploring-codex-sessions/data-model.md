# Codex CLI Session Storage — Data Model

Verified against codex-cli 0.144.3 on 2026-07-13: a freshly generated `codex exec` rollout plus the `openai/codex` source at tag `rust-v0.144.3` (rollout crate `policy.rs`/`recorder.rs`, protocol `RolloutItem`). JSONL rollouts are ground truth; `state_5.sqlite` is a rebuildable cache. For the older shape (world_state / history_mode absent), see [references/0.137.x.md](references/0.137.x.md).

## Contents

- [Directory layout](#directory-layout)
- [RolloutLine envelope](#rolloutline-envelope)
- [session_meta](#session_meta)
- [response_item](#response_item)
- [event_msg](#event_msg)
- [history_mode: legacy vs paginated](#history_mode-legacy-vs-paginated)
- [turn_context, world_state, compacted](#turn_context-world_state-compacted)
- [history.jsonl](#historyjsonl)
- [state_5.sqlite](#state_5sqlite)
- [Format eras](#format-eras-2025-2026)

## Directory layout

```
$CODEX_HOME (default ~/.codex)
├── sessions/YYYY/MM/DD/rollout-YYYY-MM-DDThh-mm-ss-<uuid>.jsonl   # transcripts
│   └── …/rollout-*.jsonl.zst        # cold-compressed (feature flag; zstdcat to read)
├── archived_sessions/rollout-*.jsonl # flat; codex archive/unarchive moves files
├── history.jsonl                     # user prompts (interactive TUI only — see note)
├── session_index.jsonl               # thread names: {id, thread_name, updated_at}
├── state_5.sqlite                    # thread metadata index (filename is schema-versioned)
├── memories_1.sqlite                 # long-term memory store (jobs, stage1_outputs)
├── goals_1.sqlite                    # per-thread goals (thread_goals)
├── logs_2.sqlite                     # structured client logs
├── installation_id                   # random UUID identifying this install
├── skills/                           # bundled + user skills (SKILL.md trees)
├── shell_snapshots/                  # captured shell env snapshots
├── config.toml                       # optional; absent by default
└── auth.json                         # credentials — never read or print
```

- Only `sessions/` (+ `state_5.sqlite`, and `history.jsonl`/`session_index.jsonl` for interactive use) matter for transcript exploration; the other DBs are separate subsystems.
- **`history.jsonl` and `session_index.jsonl` are written by interactive TUI sessions, not by `codex exec`.** Verified: two `codex exec` runs on a fresh `CODEX_HOME` created `state_5.sqlite` and the rollout but neither of those files. A fresh or exec-only home may lack them — fall back to `sessions/` + `state_5.sqlite`.
- Date dirs and filename timestamps are **local time**; in-file timestamps are UTC RFC3339.
- Session IDs are UUIDv7 (time-ordered) since ~Oct 2025, UUIDv4 before.
- No automatic retention/deletion of sessions; archiving (`codex archive`) is manual, and `codex delete` permanently removes one.
- `CODEX_HOME` relocates everything; `CODEX_SQLITE_HOME` additionally splits the state DB.

## RolloutLine envelope

Every line: `{"timestamp": "<UTC RFC3339>", "type": T, "payload": {…}}`. From `RolloutItem` (protocol.rs, `tag="type" content="payload"` snake_case), `T` ∈:

`session_meta | response_item | turn_context | world_state | compacted | event_msg`

Plus two multi-agent-only variants: `inter_agent_communication` (a delivered cross-agent message reconstructed as an `agent_message`) and `inter_agent_communication_metadata` (`{trigger_turn: bool}`). `world_state` and the `inter_agent_*` variants are **new since 0.137** (0.137 had only the first five, minus `world_state`).

## session_meta

Always line 1 of a fresh session (forked/subagent files replay parent lines, so mid-file `session_meta` occurs). Live 0.144.3 `codex exec` example (non-git cwd, so no `git` block):

```json
{"timestamp":"2026-07-13T16:41:30.145Z","type":"session_meta","payload":{
  "session_id":"019f5c5a-eb02-7ff0-90af-653b66eba9f4",
  "id":"019f5c5a-eb02-7ff0-90af-653b66eba9f4",
  "timestamp":"2026-07-13T16:41:30.114Z",
  "cwd":"/tmp",
  "originator":"codex_exec",
  "cli_version":"0.144.3",
  "source":"exec",
  "thread_source":"user",
  "model_provider":"openai",
  "base_instructions":{"text":"You are Codex…"},
  "history_mode":"legacy",
  "context_window":{"window_id":"019f5c5a-eb02-7ff0-90af-6543dd57b200"}}}
```

- New vs 0.137: `session_id` (duplicate of `id`), `history_mode` (`legacy`|`paginated`, default `legacy` — see below), `context_window.window_id`.
- `originator` is source-dependent: `codex-tui` (interactive), `codex_exec` (headless `exec`), etc.
- `git:{commit_hash, branch, repository_url}` present when cwd is a git repo.
- Optional: `forked_from_id`, `parent_thread_id`, `agent_nickname`, `agent_role`, `agent_path`, `dynamic_tools`, `memory_mode`, `multi_agent_version`.
- `source` values: `"cli"`, `"vscode"`, `"exec"`, `"mcp"`, `{"custom": …}`, `{"internal": …}`, or subagent objects like `{"subagent":{"thread_spawn":{"parent_thread_id":"…","depth":1,"agent_nickname":"…","agent_role":"…"}}}` (also `review`, `compact`). Everything lands in the same `sessions/` tree; the resume picker shows only interactive sources unless `--include-non-interactive`.

## response_item

The model-visible conversation. Persisted `payload.type` values (from `should_persist_response_item`):

| type | Key fields |
|------|-----------|
| `message` | `role` (`user` \| `assistant` \| `developer`), `content[]` of `{type: input_text \| output_text \| input_image, text}`. Assistant messages also carry `id` and `phase` (`commentary` \| `final_answer`). All messages carry `internal_chat_message_metadata_passthrough` |
| `reasoning` | `summary[]`, `encrypted_content` (opaque — not recoverable text) |
| `function_call` | `name`, `arguments` (JSON **string**), `call_id` |
| `function_call_output` | `call_id`, `output` |
| `custom_tool_call` / `_output` | `name` (e.g. `apply_patch`), `input` (patch text), `status` |
| `tool_search_call` / `_output` | skill/tool discovery calls (new) |
| `web_search_call`, `local_shell_call`, `image_generation_call` | tool-specific |
| `compaction`, `context_compaction` | compaction markers emitted as response items |

Not persisted: `additional_tools`, `compaction_trigger`, `other`.

**Injected context warning**: injected harness context arrives as `role:"user"` **and** `role:"developer"` messages. Skip content whose first line/marker is `<environment_context>`, `<user_instructions>`, `<permissions instructions>`, `<collaboration_mode>`, `<multi_agent_mode>`, `<apps_instructions>`, `# AGENTS.md`, or the multi-agent primary-agent block that opens ``You are `/root`, the primary agent…``. The real human turn is a plain `input_text` with no marker (e.g. `"print hello world in python"`). Prefer the `event_msg`/`user_message` record. In 2025-era files the human's text inside a wrapped message followed the marker line `## My request for Codex:`.

## event_msg

UI events; only an allowlisted subset is persisted, and **the allowlist depends on `history_mode`** (`should_persist_event_msg`). Live 0.144.3 legacy-mode payloads:

```json
{"type":"user_message","message":"the actual typed prompt","images":[],"local_images":[],"text_elements":[]}
{"type":"agent_message","message":"…","phase":"final_answer","memory_citation":null}
{"type":"task_started","turn_id":"…","started_at":1783960890,"model_context_window":353400,"collaboration_mode_kind":"default"}
{"type":"task_complete","turn_id":"…","last_agent_message":"…","completed_at":1783960893,"duration_ms":3166,"time_to_first_token_ms":2970}
{"type":"token_count","info":{"total_token_usage":{…},"last_token_usage":{"input_tokens":10776,"cached_input_tokens":0,"output_tokens":14,"reasoning_output_tokens":0,"total_tokens":10790},"model_context_window":353400},"rate_limits":null}
{"type":"turn_aborted","turn_id":"…","reason":"interrupted","duration_ms":161964}
{"type":"thread_rolled_back","num_turns":1}
```

- **Always persisted** (either mode): `token_count`, `task_started`/`turn_started`, `task_complete`/`turn_complete`, `turn_aborted`, `thread_rolled_back`, `thread_goal_updated`, `thread_settings_applied`.
- **Legacy-mode only**: `user_message`, `agent_message`, `agent_reasoning`, `agent_reasoning_raw_content`, `entered_review_mode`/`exited_review_mode`, `patch_apply_end`, `context_compacted`, `mcp_tool_call_end`, `web_search_end`, `image_generation_end`, `sub_agent_activity`.
- **Paginated-mode only**: `item_completed` wrapping a `TurnItem` (see next section). The legacy `user_message`/`agent_message` events are **not** written in paginated mode.
- `user_message` events are the authoritative "what the human typed" record (legacy mode).
- `agent_message.phase`: `"commentary"` = streaming progress; `"final_answer"` = the final turn answer. Keep only non-commentary (or `task_complete.last_agent_message`). New usage: 0.137-era docs described this as `commentary`/absent; the final value is now the explicit string `final_answer`.
- New fields since 0.137: `task_started.collaboration_mode_kind`, `task_complete.time_to_first_token_ms`, `token_count.info.last_token_usage`, `…reasoning_output_tokens`, `token_count.info.model_context_window`. `rate_limits` is `null` on API-key/exec runs.

## history_mode: legacy vs paginated

`ThreadHistoryMode` (serialized `legacy` | `paginated`, default `legacy`) is recorded in `session_meta.history_mode` and the `threads.history_mode` column, and it changes what a rollout contains:

- **legacy** (current default, and what a fresh `codex exec` writes): each user turn and agent reply is persisted as its own `event_msg` (`user_message`, `agent_message`, `agent_reasoning`, …). The transcript recipes in SKILL.md that read `event_msg`/`user_message` rely on this.
- **paginated**: those per-item `event_msg` records are dropped; instead the model-visible items are persisted as `item_completed` events carrying a `TurnItem` (variants include `UserMessage`, `AgentMessage`, `Reasoning`, `FileChange`, `McpToolCall`, `WebSearch`, `ImageGeneration`, `ContextCompaction`, `Plan`, `Sleep`, …). To read a paginated rollout, walk `select(.type=="event_msg" and .payload.type=="item_completed") | .payload.item` instead of `user_message`/`agent_message`.

Check `head -1 FILE | jq -r '.payload.history_mode'` before choosing a reader.

## turn_context, world_state, compacted

`turn_context` (one+ per turn; re-written after mid-turn compaction) — live 0.144.3:

```json
{"turn_id":"…","cwd":"/tmp","workspace_roots":["/tmp"],"current_date":"2026-07-13",
 "timezone":"Etc/UTC","approval_policy":"never","approvals_reviewer":"user",
 "sandbox_policy":{"type":"read-only"},
 "permission_profile":{"type":"managed","file_system":{…},"network":"restricted"},
 "model":"gpt-5.6-sol","comp_hash":"3000","personality":"pragmatic",
 "collaboration_mode":{"mode":"default","settings":{"model":"…","reasoning_effort":null,"developer_instructions":null}},
 "multi_agent_version":"v2","multi_agent_mode":"explicitRequestOnly","realtime_active":false,"summary":"auto"}
```

`sandbox_policy` and `permission_profile` are structured objects (already objects in 0.137). Fields new/expanded since 0.137 include `approvals_reviewer`, `comp_hash`, `collaboration_mode` (object with nested `settings`), `multi_agent_version`, `multi_agent_mode`, `realtime_active`, `summary`.

`world_state` (**new type**): persisted world-state snapshot used to resume model-visible diffing — `{"full": bool, "state": {…}}`. `full:true` establishes a baseline; the `state` object holds `agents_md`, `apps_instructions`, `environments{environments{<id>:{cwd,status,shell}}, current_date, timezone, filesystem}`, `plugins_instructions`, `skills`. Not part of the human conversation; skip it when building transcripts.

`compacted`: `{"message":"…","replacement_history":[<ResponseItem>…]}` — on replay, `replacement_history` substitutes everything before it.

## history.jsonl

```json
{"session_id":"019e98d5-…","ts":1780680560,"text":"the typed prompt"}
```

Only user prompts, all sessions interleaved, append-only, `ts` in unix **seconds**. `session_id` matches the rollout filename UUID, so this doubles as a reverse index. **Written by the interactive TUI, not by `codex exec`** — it can be entirely absent on an exec-only or fresh `CODEX_HOME`. `[history] persistence = "none"` disables it; `max_bytes` trims oldest to 80% of cap.

## state_5.sqlite

`threads` table columns: `id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at, git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname, agent_role, memory_mode, model, reasoning_effort, agent_path, created_at_ms, updated_at_ms, thread_source, preview, recency_at, recency_at_ms, history_mode`. (`recency_at`, `recency_at_ms`, `history_mode` are new since 0.137.) `sandbox_policy` is stored as the serialized `permission_profile` JSON, not a bare string.

`thread_spawn_edges(parent_thread_id, child_thread_id, status)` maps parent/child subagent threads. Other tables (`agent_jobs`, `agent_job_items`, `thread_dynamic_tools`, `backfill_state`, `external_agent_config_imports`, `remote_control_enrollments`, `_sqlx_migrations`) support unrelated subsystems. The DB is backfilled from rollout files on upgrade — always recoverable, never authoritative.

## Format eras (2025–2026)

Readers that walk old history must handle all of these:

1. **Bare era (≤ early Sept 2025)**: line 1 is raw `{"id","timestamp","instructions","git"}` — no `cwd`, no envelope, no per-line timestamps; bare response items; `{"record_type":"state"}` lines. Recover cwd from `<environment_context>` in the first user message.
2. **Wrapped era (Sept 2025 →)**: `{timestamp,type,payload}` envelope; meta gains `cwd`, `originator`, `cli_version`; `source` appears ~Oct 2025. Both formats coexist in Sept 2025 directories.
3. **Meta drift (Feb 2026 →)**: `instructions: string|null` → `base_instructions: {text}`; `model_provider` added; multi-agent fields (`agent_nickname`, `forked_from_id`, `parent_thread_id`) ~Mar 2026; `thread_source` by Jun 2026. `originator` renamed `codex_cli_rs` → `codex-tui` (interactive) / `codex_exec` (exec).
4. **Event drift**: `user_message` `{kind:"plain"}` → `{images, local_images, text_elements}`; `agent_reasoning` events persisted 2025–early 2026, since replaced by encrypted `response_item` reasoning; `exec_command_end` no longer persisted. `agent_message.phase` final value is `final_answer`.
5. **0.14x era (mid-2026, ≥ this doc's baseline)**: `world_state` and `inter_agent_communication`(`_metadata`) rollout line types added; `history_mode` (`legacy`|`paginated`) added to `session_meta` and `state_5.threads`, gating which `event_msg`/item records persist (paginated uses `item_completed`+`TurnItem`); `session_id` and `context_window` added to `session_meta`; new sibling DBs (`memories_1`, `goals_1`, `logs_2`) and `skills/`. See [references/0.137.x.md](references/0.137.x.md) for the prior shape.
6. **Terminology**: "sessions"/"conversations" → "threads" in source and CLI; on-disk dirs remain `sessions/` and `archived_sessions/`.
