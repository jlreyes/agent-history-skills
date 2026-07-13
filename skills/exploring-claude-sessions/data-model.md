# Claude Code Session Storage — Data Model

Verified against Claude Code 2.1.207 on 2026-07-13 by inspecting real transcripts and the official docs (code.claude.com/docs).

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
├── history.jsonl                         # global prompt history (never auto-cleaned; only written for typed prompts)
├── file-history/<session-id>/<hash>@v<N> # checkpoint/undo file snapshots
├── sessions/<pid>.json                   # live per-process session registry (see below)
├── session-env/<session-id>/             # per-session env-var scratch dir (often empty)
└── settings.json                         # cleanupPeriodDays lives here
```

`sessions/<pid>.json` is a runtime registry of live/recent processes, e.g.
`{"pid":2652,"sessionId":"…","cwd":"…","startedAt":<ms>,"version":"2.1.207","kind":"interactive","entrypoint":"…","name":"…","nameSource":"derived","peerProtocol":1}`.
(Earlier docs described `sessions/` as holding empty per-session dirs; current builds write these PID-keyed JSON files instead.)

## Transcript entry types

Each line is a standalone JSON object discriminated by `.type`.

### `user`

```json
{
  "type": "user",
  "uuid": "6c8e477c-…",
  "parentUuid": null,
  "sessionId": "82f80a36-…",
  "message": { "role": "user", "content": "string OR array of blocks" },
  "timestamp": "2026-06-11T19:51:52.420Z",
  "cwd": "/Users/me/repos/Foo",
  "gitBranch": "master",
  "permissionMode": "auto",
  "promptSource": "typed",
  "promptId": "5709a709-…",
  "userType": "external",
  "entrypoint": "cli",
  "version": "2.1.207",
  "isSidechain": false
}
```

- `message.content` as array holds blocks: `{type:"text", text|content}`, `{type:"tool_result", tool_use_id, content}`, images.
- `promptSource`: `typed`, `clipboard`, `skill`, `agent-started`, `resumed`, `sdk` (headless/SDK/GitHub-action-driven turns).
- `permissionMode`: `auto`, `plan`, `acceptEdits`, `dontAsk`, `bypassPermissions`, `manual`, `default`.
- `promptId`: UUID grouping the entries produced by one user turn (only on human-prompt `user` entries, not tool-result ones).
- Tool results come back as `user`-typed entries (role user, `tool_result` block) — not every `user` line is a human prompt. These carry two extra fields: `toolUseResult` (the structured/parsed result, string **or** object — often richer than the `tool_result` block's text) and `sourceToolAssistantUUID` (the `uuid` of the `assistant` entry whose `tool_use` this answers). They omit `permissionMode`/`promptSource`.

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
    "stop_sequence": null,
    "stop_details": null,
    "diagnostics": null,
    "usage": { "input_tokens": 2, "output_tokens": 2352,
               "cache_creation_input_tokens": 1831, "cache_read_input_tokens": 36329 }
  },
  "requestId": "req_011…",
  "timestamp": "2026-06-11T20:00:24.123Z",
  "cwd": "…", "gitBranch": "…", "version": "…", "isSidechain": false
}
```

- `message` also carries `stop_sequence`, `stop_details`, and `diagnostics` (usually `null`) alongside `stop_reason`.
- In subagent transcripts, assistant entries add `attributionAgent` (the agent type that produced the turn, e.g. `general-purpose`).

### Bookkeeping entries

| `.type` | Fields | Purpose |
|---------|--------|---------|
| `ai-title` | `aiTitle`, `sessionId` | Generated session title (shown in `/resume` picker) |
| `last-prompt` | `lastPrompt`, `leafUuid`, `sessionId` | Last user prompt, for picker preview |
| `attachment` | `attachment.type` (`command_permissions`, `task_reminder`, `deferred_tools_delta`, `agent_listing_delta`, `skill_listing`), `parentUuid` | Harness metadata attached to a turn |
| `queue-operation` | `operation` (`enqueue` / `dequeue`), `timestamp`, `sessionId` | Prompt-queue bookkeeping (no `uuid`/`parentUuid`; not part of the conversation DAG) |
| `file-history-snapshot` | `messageId`, `snapshot.trackedFileBackups` (path → `hash@vN`) | Checkpoint/undo bookkeeping |
| `mode` / `permission-mode` | `mode` / `permissionMode` | Mode changes mid-session |
| `system` | `subtype` (e.g. `turn_duration` with `durationMs`), `message` | Turn boundaries, internal events |
| `summary` | `summary`, `leafUuid` | Compaction summary linking to the pre-compaction leaf |

## Common fields

| Field | Where | Notes |
|-------|-------|-------|
| `uuid` / `parentUuid` | user, assistant, attachment | Conversation DAG; `parentUuid: null` starts a chain |
| `sessionId` | all | Same for every entry in a file; equals the filename stem |
| `timestamp` | most | ISO 8601 UTC |
| `cwd`, `gitBranch` | user, assistant | Working dir and branch at that moment |
| `entrypoint` | user, assistant, attachment | `cli`, `vs-code`, `jetbrains`, `desktop`, `remote`, `claude-code-github-action` |
| `version` | user, assistant, attachment | Claude Code version that wrote the line |
| `isSidechain` | user, assistant, attachment | `true` on subagent/sidechain work |
| `userType` | user, assistant | `external` (human/normal) vs `agent` |
| `promptId` | user (human prompts) | UUID grouping entries from one user turn |
| `agentId` | subagent entries | Short ID of the subagent; matches the `agent-<id>.jsonl`/`.meta.json` filename |
| `attributionAgent` | assistant (subagents) | Agent type that produced the turn (e.g. `general-purpose`) |

## Subagent transcripts

- Live at `<project-slug>/<session-id>/subagents/agent-<id>.jsonl`, same schema as main transcripts.
- `agent-<id>.meta.json`: `{ "agentType": "general-purpose", "description": "…", "toolUseId": "toolu_…", "spawnDepth": 1 }` — `toolUseId` matches the `tool_use` block (`name: "Agent"`/`"Task"`) in the parent transcript; `spawnDepth` is the nesting level (1 = spawned by the main session).
- Inside a subagent transcript, `user`/`assistant`/`attachment` entries carry `agentId` (matches the `agent-<id>` filename) and `isSidechain: true`; assistant entries also carry `attributionAgent` (the agent type).
- Older versions wrote sidechains inline in the main transcript with `isSidechain: true`; current versions write separate files. Handle both when walking history.

## Global history.jsonl

One line per prompt typed, across all projects:

```json
{ "display": "fix the failing auth test", "pastedContents": {}, "timestamp": 1758995854832, "project": "/Users/me/repos/Foo" }
```

`timestamp` is epoch **milliseconds**; `project` is the real path (not the slug). Useful as a fast cross-project index of what the user asked for.

## Retention and lifecycle

- Transcripts auto-clean after `cleanupPeriodDays` (default 30) — recoverable history is bounded; `history.jsonl` persists indefinitely.
- `claude --resume <id|name>` / `--continue` / `--from-pr <n>` reopen sessions; `/branch` forks to a new session ID; `/compact` writes a `summary` entry; `/export <file>` dumps readable text.
- Deprecated: `~/.claude/__store.db` (pre-JSONL SQLite store) — ignore. `~/.claude/sessions/` now holds `<pid>.json` runtime-registry files (see [Directory layout](#directory-layout)), not transcript data — ignore for history exploration. `~/.claude/session-env/<session-id>/` is a per-session scratch dir, usually empty.
- Desktop-app and claude.ai/code (web) sessions are not stored under `~/.claude/projects/`; only CLI/IDE-terminal sessions appear there.
