# Claude Code Session Storage — Data Model

Verified against Claude Code 2.1.226 on 2026-08-09: a full enumeration of every `.type`, nested key, and enum value across 114,491 real transcript lines (167 main transcripts + 243 subagent transcripts, versions 2.1.201 → 2.1.226, plus 78 `1.0.x`-era `.jsonl.backup` files), a live `claude -p` run, the installed binary's own reader/writer code, and the official docs (code.claude.com/docs/en/claude-directory, /settings, /data-usage).

Everything documented here is additive over the older shape: `1.0.x` transcripts on disk still carry the same `user`/`assistant` + `message.content` + `uuid`/`parentUuid` core, so old transcripts remain a valid subset. There is no archived prior revision.

## Contents

- [Directory layout](#directory-layout)
- [Transcript entry types](#transcript-entry-types)
- [Common fields](#common-fields)
- [Subagent transcripts](#subagent-transcripts)
- [Global history.jsonl](#global-historyjsonl)
- [Retention and lifecycle](#retention-and-lifecycle)

## Directory layout

```
~/.claude/
├── projects/
│   └── -Users-me-repos-Foo/                  # cwd with "/" → "-"
│       ├── <session-id>.jsonl                # main transcript
│       ├── <session-id>/
│       │   ├── subagents/
│       │   │   ├── agent-<agent-id>.jsonl    # subagent transcript (same schema)
│       │   │   └── agent-<agent-id>.meta.json
│       │   ├── tool-results/<id>.txt         # large tool output spilled to file
│       │   └── workflows/wf_*.json           # workflow run records
│       ├── .session-aliases                  # sibling project-dir paths, one per line
│       └── memory/                           # per-project auto-memory (markdown)
├── history.jsonl                             # global prompt history (never auto-cleaned)
├── file-history/<session-id>/<hash>@v<N>     # checkpoint/undo file snapshots
├── sessions/<pid>.json                       # live registry of running sessions
├── session-env/<session-id>/                 # per-session environment metadata
├── tasks/<session-id>/                       # per-session task lists
└── settings.json                             # cleanupPeriodDays lives here
```

`.session-aliases` is **not** a name→session-ID map. It is an append-only, deduplicated list of absolute `~/.claude/projects/<slug>` directory paths, written by the CLI's `recordSessionAlias` when a directory's real path maps to a different project slug than the literal cwd does (symlinks, relocated checkouts). Use it to find sibling directories that may hold the transcript you want.

## Transcript entry types

Each line is a standalone JSON object discriminated by `.type`.

### `user`

```json
{
  "type": "user",
  "uuid": "67348d70-…",
  "parentUuid": "fdafa1b7-…",
  "sessionId": "a872a328-…",
  "promptId": "5a00c88c-…",
  "message": { "role": "user", "content": "string OR array of blocks" },
  "timestamp": "2026-08-09T18:02:42.528Z",
  "cwd": "/Users/me/repos/Foo",
  "gitBranch": "main",
  "permissionMode": "auto",
  "promptSource": "typed",
  "origin": { "kind": "human" },
  "userType": "external",
  "entrypoint": "cli",
  "version": "2.1.226",
  "isSidechain": false
}
```

- `message.content` as array holds blocks: `{type:"text", text|content}`, `{type:"tool_result", tool_use_id, content}`, `image`, `document`, `fallback`.
- `promptSource` (observed): `typed`, `system`, `queued`, `sdk`.
- `permissionMode` (observed): `auto`, `bypassPermissions`, `plan`, `acceptEdits`, `default`. The CLI's `--permission-mode` also accepts `manual` and `dontAsk`.
- `origin`: `{kind: "human" | "task-notification" | "coordinator"}`.
- Tool results come back as `user`-typed entries (role user, `tool_result` block) — not every `user` line is a human prompt. Those carry `toolUseResult` (structured result) and `sourceToolAssistantUUID` (the `assistant` entry that issued the call). Injected harness text carries `isMeta: true`.
- `toolUseResult` for Bash may replace inline output with `persistedOutputPath` + `persistedOutputSize`, pointing at `<session-id>/tool-results/<id>.txt`.

### `assistant`

```json
{
  "type": "assistant",
  "uuid": "c82d26bb-…",
  "parentUuid": "971eef46-…",
  "sessionId": "a872a328-…",
  "requestId": "req_011Cds…",
  "effort": "xhigh",
  "message": {
    "model": "claude-opus-5",
    "id": "msg_011Cds…",
    "role": "assistant",
    "content": [
      { "type": "text", "text": "…" },
      { "type": "thinking", "thinking": "…" },
      { "type": "tool_use", "id": "toolu_01…", "name": "Bash", "input": { "command": "…" } }
    ],
    "stop_reason": "tool_use",
    "stop_sequence": null,
    "stop_details": null,
    "diagnostics": null,
    "usage": { "input_tokens": 1, "output_tokens": 8057,
               "cache_creation_input_tokens": 2668, "cache_read_input_tokens": 93761,
               "cache_creation": { "ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 2668 },
               "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
               "service_tier": "standard", "inference_geo": "not_available",
               "iterations": [ … ], "speed": "standard" }
  },
  "timestamp": "2026-08-09T18:18:07.432Z",
  "cwd": "…", "gitBranch": "…", "version": "…", "isSidechain": false
}
```

- Locally-generated (non-API) assistant lines have `model: "<synthetic>"` and no `requestId`.
- Error turns add `isApiErrorMessage`, `error`, `apiErrorStatus`, `errorDetails`, `isAbortedMidStream`.
- Attribution of a turn: `attributionAgent`, `attributionSkill`, `attributionPlugin`, `attributionMcpServer`, `attributionMcpTool`.

### Bookkeeping entries

| `.type` | Fields | Purpose |
|---------|--------|---------|
| `ai-title` | `aiTitle`, `sessionId` | Generated session title (shown in `/resume` picker) |
| `custom-title` | `customTitle`, `sessionId` | User-set session title; `--resume` accepts a title in place of an ID |
| `last-prompt` | `lastPrompt`, `leafUuid`, `sessionId` | Last user prompt, for picker preview |
| `queue-operation` | `operation` (`enqueue`/…), `content`, `sessionId`, `timestamp` | Prompt queueing; written before the `user` entry, outside the uuid DAG |
| `attachment` | `attachment.type`, `parentUuid` | Harness metadata attached to a turn |
| `system` | `subtype`, plus subtype-specific fields | Turn boundaries and internal events |
| `mode` / `permission-mode` | `mode` / `permissionMode` | Mode changes mid-session (`mode` observed only as `normal`) |
| `file-history-snapshot` | `messageId`, `isSnapshotUpdate`, `snapshot.trackedFileBackups` (path → `hash@vN`) | Checkpoint/undo bookkeeping |
| `file-history-delta` | `messageId`, `snapshotMessageId`, `trackingPath`, `backup` | Incremental checkpoint entry; coexists with `file-history-snapshot` in the same session |
| `pr-link` | `prNumber`, `prUrl`, `prRepository` | Links the session to a PR (`--from-pr` resolves this) |
| `relocated` | `relocatedCwd` | The session's cwd moved (e.g. `/cd`, worktree) |
| `worktree-state` | `worktreeSession{originalCwd, worktreePath, worktreeName, worktreeBranch, …}` | `--worktree` session state |
| `agent-name` / `agent-setting` | `agentName` / `agentSetting` | Background-agent name; agent definition in use |
| `bridge-session` | `bridgeSessionId`, `lastSequenceNum` | Remote Control / cloud bridge linkage |
| `frame-link` | `path`, `frameUrl`, `title` | Published artifact linked to a local file |
| `summary` | `summary`, `leafUuid` | Compaction summary linking to the pre-compaction leaf |

Observed `attachment.type` values: `hook_success`, `task_reminder`, `queued_command`, `hook_additional_context`, `edited_text_file`, `deferred_tools_delta`, `skill_listing`, `mcp_instructions_delta`, `command_permissions`, `agent_listing_delta`, `nested_memory`, `hook_system_message`, `date_change`, `goal_status`, `plan_mode`, `plan_mode_exit`, `plan_mode_reentry`, `read_truncation_notice`, `auto_mode`, `hook_cancelled`, `async_hook_response`, `hook_non_blocking_error`, `hook_permission_decision`, `budget_usd`, `ultrathink_effort`, `max_turns_reached`.

Observed `system.subtype` values: `turn_duration` (`durationMs`, `messageCount`), `stop_hook_summary` (`hookCount`, `hookErrors`, `preventedContinuation`, …), `away_summary`, `local_command`, `model_refusal_fallback` (`originalModel`, `fallbackModel`, `apiRefusalCategory`), `informational`, `agents_killed`, `scheduled_task_fire`.

Rarer metadata line types the binary also writes and its reader skips (none present in this corpus): `ended-by-model`, `agent-color`, `isolation-latch`, `attribution-snapshot`, `content-replacement`, `fork-context-ref`, `observer-ref`, `marble-origami-commit|snapshot|reset`. Treat any unrecognized `.type` as skippable — the conversation lives entirely in `user`/`assistant`.

## Common fields

| Field | Where | Notes |
|-------|-------|-------|
| `uuid` / `parentUuid` | user, assistant, attachment, system | Conversation DAG; `parentUuid: null` starts a chain |
| `sessionId` | most | Equals the filename stem for main transcripts. In a `subagents/agent-*.jsonl` file it is the **parent** session's ID, not the stem |
| `session_id` | user, assistant, system | Snake-case duplicate of `sessionId` on newer lines |
| `timestamp` | most | ISO 8601 UTC |
| `cwd`, `gitBranch` | user, assistant, system | Working dir and branch at that moment |
| `entrypoint` | user, assistant, system | Observed: `cli`, `sdk-cli`. `claude -p` writes `sdk-cli`; the SDKs write `sdk-ts` / `sdk-py` |
| `version` | user, assistant, system | Claude Code version that wrote the line |
| `isSidechain` | user, assistant | `true` on subagent/sidechain work |
| `userType` | user, assistant, system | `external` on every entry observed |
| `promptId` | user, assistant | Groups every entry produced by one user prompt (including subagent entries) |
| `agentId` | user, assistant | Set on subagent entries; equals the `agent-<id>` filename stem |
| `slug` | user, assistant | Human-readable session slug derived from the first prompt |
| `sessionKind` | user, assistant | e.g. `bg` (background agent); `daemon`/`daemon-worker` are hidden from `/resume` |
| `isMeta` | user, system | `true` on injected/harness content rather than real conversation |
| `effort` | assistant | Reasoning effort (`low`…`max`), recorded per message since 2.1.212; absent on `<synthetic>` lines |
| `toolUseResult`, `sourceToolAssistantUUID`, `sourceToolUseID` | user | Structured tool result and back-pointer to the calling `assistant` entry |
| `toolDenialKind` | user | `user-rejected`, `permission-rule`, `automode-blocked`, `automode-unavailable`, `interrupted` |

## Subagent transcripts

- Live at `<project-slug>/<session-id>/subagents/agent-<agent-id>.jsonl`, same schema as main transcripts, every entry `isSidechain: true`.
- `agent-<agent-id>.meta.json`: `{ "agentType": "general-purpose", "description": "…", "toolUseId": "toolu_…", "spawnDepth": 1 }`, plus `parentAgentId` for nested subagents (`spawnDepth: 2`), and optionally `model` and `stoppedByUser`. `toolUseId` matches the `tool_use` block (`name: "Agent"`/`"Task"`) in the parent transcript.
- Nested subagents live in the same flat `subagents/` directory; use `parentAgentId` / `spawnDepth` to rebuild the tree.
- Older versions wrote sidechains inline in the main transcript with `isSidechain: true`; current versions write separate files. Handle both when walking history.

## Global history.jsonl

One line per prompt typed, across all projects:

```json
{ "display": "fix the failing auth test", "pastedContents": {}, "timestamp": 1758995854832,
  "project": "/Users/me/repos/Foo", "sessionId": "763a2310-…" }
```

`timestamp` is epoch **milliseconds**; `project` is the real path (not the slug). `sessionId` was added mid-2.1.x, so older lines lack it. Only prompts the user actually typed land here — SDK/headless prompts do not. Useful as a fast cross-project index that now links straight to a transcript.

## Retention and lifecycle

- Transcripts auto-clean after `cleanupPeriodDays` (default 30, minimum 1) — recoverable history is bounded; a session's `subagents/` and `tool-results/` age out with it. `history.jsonl`, `stats-cache.json` and other "kept until you delete them" paths persist indefinitely.
- `claude project purge [path]` deletes one project's transcripts, memory, `tasks/`, `debug/`, `file-history/`, its `history.jsonl` lines, and its `~/.claude.json` entry (`--dry-run`, `--yes`, `--all`, `-i`).
- `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` skips writing transcripts and prompt history entirely; `--no-session-persistence` does the same for a single `-p` run.
- `claude --resume <id|title>` / `--continue` / `--from-pr <n>` / `--fork-session` reopen sessions; `/compact` writes a `summary` entry; `/export <file>` dumps readable text.
- `/resume` hides sessions with `isSidechain: true`, a `teamName`, `sessionKind` of `daemon`/`daemon-worker`, `/loop` sessions, and any `entrypoint` in `sdk-cli`/`sdk-ts`/`sdk-py`. They are all still on disk — read them directly.
- Legacy, no longer written: `~/.claude/todos/`, `statsig/`, `logs/`, and stray `<session-id>.jsonl.backup` files (1.0.x era). `~/.claude/sessions/` is current: one `<pid>.json` per *running* session, removed on exit.
- Desktop-app and claude.ai/code (web) sessions are not stored under `~/.claude/projects/`; only CLI/IDE-terminal sessions appear there.
