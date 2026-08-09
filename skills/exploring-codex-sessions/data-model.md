# Codex CLI Session Storage — Data Model

Verified against codex-cli 0.146.0 on 2026-08-09: a freshly generated `codex exec` rollout, a full enumeration of 1103 real rollout files spanning Sept 2025 → Aug 2026, and the `openai/codex` source at tags `rust-v0.137.0` vs `rust-v0.146.0` (`protocol/src/protocol.rs`, `rollout/src/policy.rs`, `rollout/src/recorder.rs`). JSONL rollouts are ground truth; `state_5.sqlite` is a rebuildable cache.

## Contents

- [Directory layout](#directory-layout)
- [RolloutLine envelope](#rolloutline-envelope)
- [session_meta](#session_meta)
- [response_item](#response_item)
- [event_msg](#event_msg)
- [history_mode](#history_mode)
- [turn_context, world_state, compacted](#turn_context-world_state-compacted)
- [history.jsonl](#historyjsonl)
- [state_5.sqlite](#state_5sqlite)
- [Format eras](#format-eras-2025-2026)

## Directory layout

```
$CODEX_HOME (default ~/.codex)
├── sessions/YYYY/MM/DD/rollout-YYYY-MM-DDThh-mm-ss-<uuid>.jsonl   # transcripts
│   └── …/rollout-*.jsonl.zst        # cold-compressed (zstdcat to read)
├── archived_sessions/rollout-*.jsonl # flat, no date dirs; codex archive/unarchive moves files
├── history.jsonl                     # typed prompts, append-only, mode 0600 — may be stale, see below
├── session_index.jsonl               # thread names: {id, thread_name, updated_at}
├── state_5.sqlite (+ -wal, -shm)     # thread metadata index (filename is schema-versioned)
├── config.toml                       # [history] persistence = "save-all" | "none"
└── auth.json                         # credentials — never read or print
```

Everything else in `$CODEX_HOME` belongs to other subsystems and holds no transcripts: `memories_1.sqlite`, `goals_1.sqlite`, `logs_2.sqlite` (+ legacy `logs_1.sqlite`), `sqlite/codex-dev.db` and `sqlite/codex-history-snapshots-dev.db` (app-server/desktop), `.codex-global-state.json` (Electron desktop UI state), `skills/`, `plugins/`, `hooks/`, `shell_snapshots/`, `attachments/`, `thread-writer-locks/`, `installation_id`.

- Date dirs and filename timestamps are **local time**; in-file timestamps are UTC RFC3339.
- Session IDs are UUIDv7 (time-ordered) since ~Oct 2025, UUIDv4 before.
- No automatic retention/deletion. `codex archive`/`unarchive` move files; `codex delete` removes one permanently.
- Compression is real but off by default: `rollout/src/compression.rs` uses suffix `.zst`, zstd level 3, and only considers rollouts older than `MIN_ROLLOUT_AGE = 7 days`. 0 of 1103 files were compressed on the verification host.
- `CODEX_HOME` relocates everything.

## RolloutLine envelope

Every line: `{"timestamp": "<UTC RFC3339>", "type": T, "payload": {…}}`, plus an optional `ordinal` (u64) that is `skip_serializing_if none` — absent from all 1103 files checked.

From `RolloutItem` (protocol.rs, `tag="type" content="payload"`, snake_case), `T` is one of **eight**:

`session_meta | response_item | turn_context | world_state | compacted | event_msg | inter_agent_communication | inter_agent_communication_metadata`

Observed frequency across the corpus: `event_msg` 220361, `response_item` 196356, `turn_context` 18018, `world_state` 3560, `session_meta` 2012, `inter_agent_communication_metadata` 1759, `compacted` 459. Plain `inter_agent_communication` did not appear — in practice the delivered cross-agent message is written as a `response_item` of type `agent_message` and only the `{"trigger_turn": bool}` metadata line accompanies it.

`world_state`, `inter_agent_communication` and `inter_agent_communication_metadata` are **new since 0.137** (which had exactly five variants). The five original variants are unchanged in name and payload, so older rollouts remain readable by a current reader.

## session_meta

Always line 1 of a fresh session. Forked and subagent files replay the parent's lines, so mid-file `session_meta` occurs — in a forked file line 1 is the *new* thread (carrying `forked_from_id`/`parent_thread_id`) and the later metas are the replayed parent's.

Live 0.146.0 `codex exec` example (non-git cwd, so no `git` block):

```json
{"timestamp":"2026-08-09T18:25:45.201Z","type":"session_meta","payload":{
  "session_id":"019fe7c6-10ee-75f2-aeb2-e17e16a59b29",
  "id":"019fe7c6-10ee-75f2-aeb2-e17e16a59b29",
  "timestamp":"2026-08-09T18:25:45.201Z",
  "cwd":"/private/tmp",
  "originator":"codex_exec",
  "cli_version":"0.146.0",
  "source":"exec",
  "thread_source":"user",
  "model_provider":"openai",
  "base_instructions":{"text":"You are Codex…"},
  "history_mode":"legacy",
  "context_window":{"window_id":"019fe7c6-10ee-75f2-aeb2-e188a46b1e48"}}}
```

- New vs 0.137, all defaulted or optional: `session_id` (duplicate of `id`), `history_mode`, `context_window.window_id`, `history_base`, `selected_capability_roots`, `subagent_history_start_ordinal`. **No field was removed or renamed.**
- `git:{commit_hash, branch, repository_url}` present when cwd is a git repo (1475 / 2013 metas).
- Other optional fields seen on disk: `forked_from_id`, `parent_thread_id`, `agent_nickname`, `agent_role`, `agent_path`, `dynamic_tools`, `memory_mode`, `multi_agent_version`. Pre-2026 files carry `instructions` instead of `base_instructions`.
- `source` (`SessionSource`): `"cli"`, `"vscode"` (the serde default), `"exec"`, `"mcp"`, `{"custom": …}`, `{"internal": …}`, `"unknown"`, or subagent objects `{"subagent":{"thread_spawn":{parent_thread_id, depth, agent_path, agent_nickname, agent_role}}}` — also `review`, `compact`, `memory_consolidation`, `{"other": …}`. Observed: `vscode` 972, `subagent/thread_spawn` 513, `subagent/other` 412, `cli` 109, `exec` 1.
- `thread_source` (`ThreadSource`): `user` | `subagent` | `{"feature": …}` | `memory_consolidation`.
- `originator` is a free string set by the host, **not** limited to CLI values. Observed: `Codex Desktop` 1879, `codex_cli_rs` 108, `codex-tui` 26, `codex_work_desktop` 3, `codex_exec` 1.
- Everything lands in the same `sessions/` tree; `codex resume`'s picker shows only interactive sources unless `--include-non-interactive`.

## response_item

The model-visible conversation. Persisted `payload.type` values (source: `should_persist_response_item`), with corpus counts:

| type | Key fields |
|------|-----------|
| `message` (37491) | `role` (`user` \| `assistant` \| `developer`), `content[]` |
| `reasoning` (55643) | `summary[]`, `encrypted_content` (opaque — not recoverable text) |
| `function_call` (29057) / `function_call_output` (29037) | `name`, `arguments` (JSON **string**), `call_id` / `call_id`, `output` |
| `custom_tool_call` (21255) / `custom_tool_call_output` (21251) | `name` (e.g. `apply_patch`), `input` (patch text), `status` |
| `agent_message` (1759) | multi-agent delivery: `id`, `author`, `recipient` (agent paths like `/root`), `content[]`, `internal_chat_message_metadata_passthrough` |
| `web_search_call` (608) | tool-specific |
| `tool_search_call` (198) / `tool_search_output` (198) | skill/tool discovery. Note the output tag is `tool_search_output`, not `…_call_output` |
| `local_shell_call`, `image_generation_call`, `compaction`, `context_compaction` | persisted by policy; not observed on this host |

Not persisted: `additional_tools`, `compaction_trigger`, `other`.

`content[]` block types actually present: `input_text` 118522, `output_text` 22996, `encrypted_content` 1261, `input_image` 83.

**Injected context warning**: harness context arrives as `role:"user"` *and* `role:"developer"` messages. Skipping only the classic markers is no longer enough. Markers seen on disk, by number of files containing them:

`<environment_context>` 1075, `<permissions instructions>` 1031, `# AGENTS.md` 1005, `<skills_instructions>` 575, `<apps_instructions>` 560, `<recommended_plugins>` 537, `<multi_agent_mode>` 536, `<collaboration_mode>` 524, `<app-context>` 519, `<environment>` 389, `## My request for Codex:` 230, `<skill>` 158, `<turn_aborted>` 148, `<environment-change>` 123, `<task-notification>` 93, `<user_instructions>` 77, `<heartbeat>` 10.

Two prose-prefixed injections are the single largest source of noise (4714 + 553 occurrences), both delivered as `role:"user"` inside guardian/approval sub-threads:

- `The following is the Codex agent history added since your last approval assessment…`
- `The following is the Codex agent history whose request action you are assessing…`

Non-tagged developer injections also open with `## Memory` or ``You are `/root`, the primary agent…``. The real human turn is a plain `input_text` with no marker. Prefer the `event_msg`/`user_message` record.

## event_msg

UI events; only an allowlisted subset is persisted, and **the allowlist depends on `history_mode`** (`should_persist_event_msg`). Payloads from the live 0.146.0 run:

```json
{"type":"user_message","message":"the actual typed prompt","images":[],"local_images":[],"audio":[],"local_audio":[],"text_elements":[]}
{"type":"agent_message","message":"…","phase":"final_answer","memory_citation":null}
{"type":"task_started","turn_id":"…","started_at":1786299949,"model_context_window":258400,"collaboration_mode_kind":"default"}
{"type":"task_complete","turn_id":"…","last_agent_message":"pong","started_at":1786299949,"completed_at":1786300045,"duration_ms":95411,"time_to_first_token_ms":94524}
{"type":"token_count","info":{"total_token_usage":{"input_tokens":24593,"cached_input_tokens":11008,"cache_write_input_tokens":0,"output_tokens":5,"reasoning_output_tokens":0,"total_tokens":24598},"last_token_usage":{…},"model_context_window":258400},"rate_limits":{"limit_id":…}}
{"type":"turn_aborted","turn_id":"…","reason":"interrupted","duration_ms":161964}
{"type":"thread_rolled_back","num_turns":1}
```

Persistence classes, from `rollout/src/policy.rs` at `rust-v0.146.0`:

- **Always persisted** (either mode): `token_count`, `task_started`/`turn_started`, `task_complete`/`turn_complete`, `turn_aborted`, `thread_rolled_back`, `thread_goal_updated`, `thread_settings_applied`.
- **Legacy mode only**: `user_message`, `agent_message`, `agent_reasoning`, `agent_reasoning_raw_content`, `entered_review_mode`/`exited_review_mode`, `patch_apply_end`, `context_compacted`, `mcp_tool_call_end`, `web_search_end`, `image_generation_end`, `sub_agent_activity`.
- **`item_completed`** is persisted in paginated mode **or**, in legacy mode, when the item is a `Plan` or `Extension(Sleep)`. All 46 `item_completed` events on this host are the legacy `Plan` case — do not read `item_completed` as proof of paginated mode.
- **Never persisted** (transient): `error`, `exec_command_end`, `guardian_assessment`, `mcp_tool_call_begin`, `exec_command_begin`, `session_configured`, the `realtime_*` family, and others.

Observed counts: `token_count` 91921, `agent_reasoning` 51739, `agent_message` 25673, `task_started` 8385, `user_message` 8082, `task_complete` 7657, `mcp_tool_call_end` 7325, `web_search_end` 6813, `thread_settings_applied` 5954, `sub_agent_activity` 3345, `patch_apply_end` 2382, `context_compacted` 459, `exec_command_end` 396 (all from ≤0.118 files), `turn_aborted` 240, `thread_rolled_back` 54, `item_completed` 46, `image_generation_end` 6, `collab_waiting_end`/`collab_close_end`/`collab_agent_spawn_end` 1–2 each.

- `user_message` events are the authoritative "what the human typed" record. New optional fields `audio`/`local_audio` alongside `images`/`local_images`/`text_elements`.
- `agent_message.phase`: `"commentary"` = streaming progress, `"final_answer"` = the final turn answer, absent in pre-2026 files. Corpus: absent 11109, `commentary` 7847, `final_answer` 6761. Keep non-commentary (or `task_complete.last_agent_message`).
- `thread_settings_applied` moved from never-persisted (0.137) to always-persisted (0.146).
- Serialized names are `task_started`/`task_complete`; readers should also accept aliases `turn_started`/`turn_complete`.

## history_mode

`ThreadHistoryMode` (serialized `legacy` | `paginated`, `#[serde(default)]` → `Legacy`) is recorded in `session_meta.history_mode` and the `threads.history_mode` column, and it selects which event records a rollout contains.

- **legacy** — current default and what a fresh 0.146.0 `codex exec` writes. Each user turn and agent reply is persisted as its own `event_msg`. The SKILL.md transcript recipes rely on this.
- **paginated** — the per-item `event_msg` records are dropped; model-visible items are persisted as `item_completed` events carrying a `TurnItem`. To read one, walk `select(.type=="event_msg" and .payload.type=="item_completed") | .payload.item`.

Corpus reality: 1838 metas say `legacy`, 175 (pre-0.14x) omit the field, **0 say `paginated`**. Paginated is documented from `policy.rs` only; it was not observed on disk and there is no `codex exec` flag to force it. Check `head -1 FILE | jq -r '.payload.history_mode'` before choosing a reader.

## turn_context, world_state, compacted

`turn_context` (one+ per turn; re-written after mid-turn compaction) — live 0.146.0:

```json
{"turn_id":"…","cwd":"/private/tmp","workspace_roots":["/private/tmp"],"current_date":"2026-08-09",
 "timezone":"America/New_York","approval_policy":"on-request","approvals_reviewer":"auto_review",
 "sandbox_policy":{"type":"read-only"},
 "permission_profile":{"type":"managed","file_system":{"type":"restricted","entries":[…]},"network":"restricted"},
 "model":"gpt-5.6-sol","comp_hash":"3000","personality":"pragmatic",
 "collaboration_mode":{"mode":"default","settings":{"model":"gpt-5.6-sol","reasoning_effort":"xhigh","developer_instructions":null}},
 "multi_agent_version":"v2","realtime_active":false,"effort":"xhigh","summary":"auto"}
```

`sandbox_policy` and `permission_profile` are structured objects (already objects in 0.137). Added since 0.137: `approvals_reviewer`, `comp_hash`, `multi_agent_mode`. Nothing was removed. User instructions live here in current versions, not in `session_meta`.

`world_state` (**new type**): `{"full": bool, "state": {…}}`. `full:true` establishes a baseline snapshot; `full:false` is a patch carrying only changed keys. Baseline `state` keys observed: `agents_md`, `apps_instructions`, `collaboration_mode`, `environments`, `environments_instructions`, `git_attribution`, `host_skills`, `model`, `multi_agent_mode`, `permissions`, `personality`, `plugins_instructions`, `realtime`, `skills`. Not part of the human conversation — skip it when building transcripts.

`compacted`: `{"message":"…","replacement_history":[<ResponseItem>…]}` — on replay, `replacement_history` substitutes everything before it. Added since 0.137: `window_number`, `window_id`, `first_window_id`, `previous_window_id`, which chain successive context windows.

`inter_agent_communication_metadata`: `{"trigger_turn": bool}`, paired with the `response_item`/`agent_message` that carries the actual cross-agent payload.

## history.jsonl

```json
{"session_id":"019e98d5-…","ts":1780680560,"text":"the typed prompt"}
```

Only user prompts, all sessions interleaved, append-only, `ts` in unix **seconds**. `session_id` matches the rollout filename UUID, so this doubles as a reverse index. `[history] persistence = "none"` disables it; `max_bytes` trims oldest to 80% of cap.

**Verify freshness before trusting it.** The writer still exists at 0.146.0 (`codex-rs/message-history/src/lib.rs`, `HISTORY_FILENAME = "history.jsonl"`), but on the verification host — with `persistence = "save-all"` set — the file's last append was **2026-07-10** while hundreds of sessions ran afterwards, and the live `codex exec` run did not append to it either. Check `ls -l ~/.codex/history.jsonl` against the newest rollout; when it lags, use `state_5.threads.first_user_message` or the rollouts themselves instead.

## state_5.sqlite

`threads` columns (37): `id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at, git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname, agent_role, memory_mode, model, reasoning_effort, agent_path, created_at_ms, updated_at_ms, thread_source, preview, recency_at, recency_at_ms, history_mode, name, is_pinned, thread_section_id, section_position, section_entered_at_ms`.

New since 0.137: `recency_at`, `recency_at_ms`, `history_mode`, `name` (thread name, also in `session_index.jsonl`), `is_pinned`, `thread_section_id`, `section_position`, `section_entered_at_ms`. `sandbox_policy` stores serialized JSON, not a bare string. `first_user_message`/`preview` may contain an injected block rather than human text for guardian and subagent threads.

Other tables: `thread_spawn_edges(parent_thread_id, child_thread_id, status)` maps parent/child subagent threads (`status` ∈ `open`/`closed`); `thread_sections(id, name)` is new; `thread_dynamic_tools`, `backfill_state`, `external_agent_config_imports`, `remote_control_enrollments`, `_sqlx_migrations` support unrelated subsystems. The DB is backfilled from rollout files on upgrade — always recoverable, never authoritative.

## Format eras (2025–2026)

Readers that walk old history must handle all of these. Verified against the oldest files on disk.

1. **Bare era (≤ mid Sept 2025)**: line 1 is raw `{"id","timestamp","instructions","git"}` — no `cwd`, no envelope, no per-line timestamps; bare response items (`{"type":"message","role","content"}` at top level); `{"record_type":"state"}` lines. Recover cwd from `<environment_context>` in the first user message. Confirmed on `sessions/2025/09/02/` and two `2025/09/16/` files; the `event_msg` transcript recipe correctly returns nothing for these.
2. **Wrapped era (Sept 2025 →)**: `{timestamp,type,payload}` envelope; meta gains `cwd`, `originator`, `cli_version`; `source` appears ~Oct 2025. Both formats coexist within `2025/09/16/` — the crossover file is the 10:02 session.
3. **Meta drift (Feb 2026 →)**: `instructions: string|null` → `base_instructions: {text}`; `model_provider` added; multi-agent fields (`agent_nickname`, `forked_from_id`, `parent_thread_id`) ~Mar 2026; `thread_source` by Jun 2026. `originator` moved off `codex_cli_rs` to `codex-tui` and, for desktop hosts, `Codex Desktop`.
4. **Event drift**: `user_message` `{kind:"plain"}` → `{images, local_images, audio, local_audio, text_elements}`; `agent_reasoning` events persisted 2025–early 2026, since replaced by encrypted `response_item` reasoning; `exec_command_end` no longer persisted (396 survivors, all from ≤0.118); `agent_message.phase` gains the explicit `final_answer` value.
5. **0.14x era (mid-2026 →)**: three new rollout line types (`world_state`, `inter_agent_communication`, `inter_agent_communication_metadata`); `history_mode` added to `session_meta` and `state_5.threads`; `session_id`, `context_window` added to `session_meta`; `agent_message` and `tool_search_call`/`tool_search_output` added to `response_item`; `thread_settings_applied` now persisted. **All of it is additive** — no field or variant from the 0.137 shape was renamed, removed, or restructured, so pre-0.14x rollouts are a valid subset of the current schema and need no separate reader.
6. **Terminology**: "sessions"/"conversations" → "threads" in source and CLI; on-disk dirs remain `sessions/` and `archived_sessions/`.
