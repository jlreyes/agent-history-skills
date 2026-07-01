> **Archived reference — not the current schema.** This is the full
> `data-model.md` exactly as it stood for Claude Code 2.1.x, before the
> 2026-07-01 refresh. Kept so an agent reading an *old* transcript on disk
> (one written before that refresh) has an accurate schema to work from —
> old files don't retroactively change format when a tool updates. For
> anything current, see the live [data-model.md](../data-model.md).

---

# Claude Code Session Storage — Data Model

Verified against Claude Code 2.1.x by inspecting real transcripts and the official docs (code.claude.com/docs).

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
│       │       └── agent-<id>.meta.json  # {agentType, description, toolUseId}
│       ├── .session-aliases              # name=uuid lines (set via /rename, -n)
│       └── memory/                       # per-project auto-memory (markdown)
├── history.jsonl                         # global prompt history (never auto-cleaned)
├── file-history/<session-id>/<hash>@v<N> # checkpoint/undo file snapshots
└── settings.json                         # cleanupPeriodDays lives here
```

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
  "userType": "external",
  "entrypoint": "cli",
  "version": "2.1.173",
  "isSidechain": false
}
```

- `message.content` as array holds blocks: `{type:"text", text|content}`, `{type:"tool_result", tool_use_id, content}`, images.
- `promptSource`: `typed`, `clipboard`, `skill`, `agent-started`, `resumed`.
- `permissionMode`: `auto`, `plan`, `acceptEdits`, `dontAsk`, `bypassPermissions`.
- Tool results come back as `user`-typed entries (role user, `tool_result` block) — not every `user` line is a human prompt.

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
    "usage": { "input_tokens": 2, "output_tokens": 2352,
               "cache_creation_input_tokens": 1831, "cache_read_input_tokens": 36329 }
  },
  "requestId": "req_011…",
  "timestamp": "2026-06-11T20:00:24.123Z",
  "cwd": "…", "gitBranch": "…", "version": "…", "isSidechain": false
}
```

### Bookkeeping entries

| `.type` | Fields | Purpose |
|---------|--------|---------|
| `ai-title` | `aiTitle`, `sessionId` | Generated session title (shown in `/resume` picker) |
| `last-prompt` | `lastPrompt`, `leafUuid`, `sessionId` | Last user prompt, for picker preview |
| `attachment` | `attachment.type` (`command_permissions`, `task_reminder`, `deferred_tools_delta`), `parentUuid` | Harness metadata attached to a turn |
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
| `entrypoint` | user, assistant | `cli`, `vs-code`, `jetbrains`, `desktop`, `remote` |
| `version` | user, assistant | Claude Code version that wrote the line |
| `isSidechain` | user, assistant | `true` on subagent/sidechain work |
| `userType` | user | `external` (human) vs `agent` |

## Subagent transcripts

- Live at `<project-slug>/<session-id>/subagents/agent-<id>.jsonl`, same schema as main transcripts.
- `agent-<id>.meta.json`: `{ "agentType": "general-purpose", "description": "…", "toolUseId": "toolu_…" }` — `toolUseId` matches the `tool_use` block (`name: "Agent"`/`"Task"`) in the parent transcript.
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
- Deprecated: `~/.claude/__store.db` (pre-JSONL SQLite store), empty `~/.claude/sessions/<id>/` dirs — ignore both.
- Desktop-app and claude.ai/code (web) sessions are not stored under `~/.claude/projects/`; only CLI/IDE-terminal sessions appear there.
