# Claude Code Session Storage — Data Model

Verified against Claude Code 2.1.197 / on 2026-07-01 by inspecting real transcripts and the official docs (code.claude.com/docs).

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
│   └── -Users-me-repos-Foo/              # cwd with "/" → "-"
│       ├── <session-id>.jsonl            # main transcript
│       ├── <session-id>/
│       │   └── subagents/
│       │       ├── agent-<id>.jsonl      # subagent transcript (same schema)
│       │       └── agent-<id>.meta.json  # {agentType, description, toolUseId, spawnDepth}
│       ├── .session-aliases              # name=uuid lines (set via /rename, -n)
│       └── memory/                       # per-project auto-memory (markdown)
├── sessions/<pid>.json                   # live process registry (one per running session)
├── session-env/<session-id>/            # per-session env/state scratch
├── shell-snapshots/snapshot-*.sh         # captured shell env for Bash tool
├── history.jsonl                         # global prompt history (never auto-cleaned)
├── file-history/<session-id>/<hash>@v<N> # checkpoint/undo file snapshots
├── downloads/, backups/                  # file downloads; config backups
├── .last-cleanup                         # ISO timestamp of last retention sweep
└── settings.json                         # cleanupPeriodDays lives here
```

Not every dir exists on every machine. `sessions/<pid>.json`, `session-env/`, and `shell-snapshots/` are created at session start; `history.jsonl` and `file-history/` are only written by interactive/typed use (a headless or `claude-code-github-action` run may leave both absent). `sessions/<pid>.json` example: `{"pid","sessionId","cwd","startedAt","version","kind":"interactive","entrypoint","name","nameSource"}`.

## Transcript entry types

Each line is a standalone JSON object discriminated by `.type`.

### `user`

```json
{
  "type": "user",
  "uuid": "6c8e477c-…",
  "parentUuid": null,
  "sessionId": "82f80a36-…",
  "promptId": "e3271e4d-…",
  "message": { "role": "user", "content": "string OR array of blocks" },
  "timestamp": "2026-06-11T19:51:52.420Z",
  "cwd": "/Users/me/repos/Foo",
  "gitBranch": "master",
  "permissionMode": "default",
  "promptSource": "typed",
  "userType": "external",
  "entrypoint": "cli",
  "version": "2.1.197",
  "isSidechain": false
}
```

- `message.content` as array holds blocks: `{type:"text", text|content}`, `{type:"tool_result", tool_use_id, content}`, images.
- `promptSource`: `typed`, `clipboard`, `skill`, `agent-started`, `resumed`, `sdk`. Present only on true human/turn-initiating prompts; tool-result `user` lines omit it.
- `permissionMode`: `default`, `auto`, `plan`, `acceptEdits`, `dontAsk`, `bypassPermissions` (matches `--permission-mode` choices: `acceptEdits`, `auto`, `bypassPermissions`, `default`, `plan`).
- `promptId`: groups all entries produced by one user turn (present on `user`/`assistant` lines).
- Tool-result `user` entries (role user, `tool_result` block) also carry a top-level **`toolUseResult`** with the structured result and a `sourceToolAssistantUUID` pointing at the `assistant` entry whose `tool_use` they answer. `toolUseResult` shape varies by tool — e.g. Bash: `{stdout, stderr, interrupted, isImage, noOutputExpected}`; Read: `{type, file:{filePath, content, numLines, startLine, totalLines}}`; or a plain string. Not every `user` line is a human prompt.
- `agentId`: short hex id of the agent that wrote the line (present on sidechain/subagent entries; matches the `agent-<id>` filename).

### `assistant`

```json
{
  "type": "assistant",
  "uuid": "cac7af46-…",
  "parentUuid": "caeba134-…",
  "sessionId": "82f80a36-…",
  "message": {
    "model": "claude-…",
    "id": "msg_01…",
    "role": "assistant",
    "content": [
      { "type": "text", "text": "…" },
      { "type": "thinking", "thinking": "…" },
      { "type": "tool_use", "id": "toolu_01…", "name": "Bash", "input": { "command": "…" } }
    ],
    "stop_reason": "tool_use",
    "stop_details": null,
    "diagnostics": null,
    "usage": { "input_tokens": 2, "output_tokens": 2352,
               "cache_creation_input_tokens": 1831, "cache_read_input_tokens": 36329,
               "cache_creation": { "ephemeral_5m_input_tokens": 1831, "ephemeral_1h_input_tokens": 0 },
               "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
               "service_tier": "standard", "inference_geo": "global", "speed": "standard" }
  },
  "requestId": "req_011…",
  "timestamp": "2026-06-11T20:00:24.123Z",
  "cwd": "…", "gitBranch": "…", "version": "…", "isSidechain": false
}
```

- `message.usage` is the full API usage object: besides the four `*_tokens` counts it carries `cache_creation` (5m/1h ephemeral breakdown), `server_tool_use`, `service_tier`, `inference_geo`, `speed`, and sometimes an `iterations[]` array. `message` also carries `stop_details` and `diagnostics` (usually `null`).
- Subagent/sidechain `assistant` lines additionally carry `agentId` and `attributionAgent` (the agent type, e.g. `general-purpose`).

### Bookkeeping entries

| `.type` | Fields | Purpose |
|---------|--------|---------|
| `ai-title` | `aiTitle`, `sessionId` | Generated session title (shown in `/resume` picker) |
| `last-prompt` | `lastPrompt`, `leafUuid`, `sessionId` | Last user prompt, for picker preview |
| `attachment` | `attachment.type` (`deferred_tools_delta`, `skill_listing`, `agent_listing_delta`, `command_permissions`, `task_reminder`), plus the common turn fields (`parentUuid`, `uuid`, `cwd`, `agentId`, …) | Harness metadata attached to a turn (available tools/skills/agents, permission prompts, reminders) |
| `queue-operation` | `operation` (`enqueue`/`dequeue`), `timestamp`, `sessionId` | Message-queue bookkeeping when prompts are queued/pulled |
| `file-history-snapshot` | `messageId`, `snapshot.trackedFileBackups` (path → `hash@vN`) | Checkpoint/undo bookkeeping |
| `mode` / `permission-mode` | `mode` / `permissionMode` | Mode changes mid-session |
| `system` | `subtype` (e.g. `turn_duration` with `durationMs`), `message` | Turn boundaries, internal events |
| `summary` | `summary`, `leafUuid` | Compaction summary linking to the pre-compaction leaf |

Not every type appears in every transcript — short or headless sessions may contain only `user`/`assistant`/`attachment`/`ai-title`/`last-prompt`/`queue-operation`. `mode`, `permission-mode`, `system`, `summary`, and `file-history-snapshot` are emitted only when the corresponding event occurs.

## Common fields

| Field | Where | Notes |
|-------|-------|-------|
| `uuid` / `parentUuid` | user, assistant, attachment | Conversation DAG; `parentUuid: null` starts a chain |
| `sessionId` | all | Same for every entry in a file; equals the filename stem |
| `promptId` | user, assistant | Groups all lines produced by one user turn |
| `timestamp` | most | ISO 8601 UTC |
| `cwd`, `gitBranch` | user, assistant, attachment | Working dir and branch at that moment |
| `entrypoint` | user, assistant, attachment | `cli`, `vs-code`, `jetbrains`, `desktop`, `remote`, `sdk`, `claude-code-github-action` |
| `version` | user, assistant, attachment | Claude Code version that wrote the line |
| `isSidechain` | user, assistant, attachment | `true` on subagent/sidechain work |
| `userType` | user, assistant, attachment | `external` (observed value); distinguishes human vs agent origin |
| `agentId` | sidechain lines | Short hex id of the writing agent; matches `agent-<id>` filename |
| `attributionAgent` | assistant (sidechain) | Agent type that produced the message (e.g. `general-purpose`) |
| `toolUseResult` | user (tool results) | Structured result of the answered tool call (shape varies by tool) |
| `sourceToolAssistantUUID` | user (tool results) | `uuid` of the `assistant` entry whose `tool_use` this result answers |

## Subagent transcripts

- Live at `<project-slug>/<session-id>/subagents/agent-<id>.jsonl`, same schema as main transcripts.
- `agent-<id>.meta.json`: `{ "agentType": "general-purpose", "description": "…", "toolUseId": "toolu_…", "spawnDepth": 1 }` — `toolUseId` matches the `tool_use` block (`name: "Agent"`/`"Task"`) in the parent transcript; `spawnDepth` is the nesting level (subagents may spawn their own subagents up to 5 levels deep, restored on resume).
- Inside a subagent transcript, lines carry `isSidechain: true`, an `agentId` matching the `agent-<id>` filename, and (on `assistant` lines) `attributionAgent` = the agent type.
- Older versions wrote sidechains inline in the main transcript with `isSidechain: true`; current versions write separate files. Handle both when walking history.

## Global history.jsonl

One line per prompt typed, across all projects:

```json
{ "display": "fix the failing auth test", "pastedContents": {}, "timestamp": 1758995854832, "project": "/Users/me/repos/Foo" }
```

`timestamp` is epoch **milliseconds**; `project` is the real path (not the slug). Useful as a fast cross-project index of what the user asked for.

## Retention and lifecycle

- Transcripts auto-clean after `cleanupPeriodDays` (default 30) — recoverable history is bounded; `history.jsonl` persists indefinitely. Last sweep time is in `~/.claude/.last-cleanup`.
- `claude --resume <id|name>` / `--continue` / `--from-pr <n>` reopen sessions; `--fork-session` (with `--resume`/`--continue`) reopens under a new session ID; `--session-id <uuid>` pins a chosen ID for a new session; `/compact` writes a `summary` entry; `/export <file>` dumps readable text; `/rewind` can resume from before a `/clear`.
- `claude project purge [path]` deletes all state for a project (transcripts, tasks, file history, config entry).
- Settings are now edited directly (or via the in-session `/config key=value`); there is no `claude config` CLI subcommand.
- Deprecated: `~/.claude/__store.db` (pre-JSONL SQLite store) — ignore. Note `~/.claude/sessions/<pid>.json` is NOT deprecated: it is the live process registry for running sessions (one file per PID), distinct from transcripts.
- Desktop-app and claude.ai/code (web) sessions are not stored under `~/.claude/projects/`; only CLI/IDE-terminal sessions appear there.
