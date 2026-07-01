# Claude Code Session Storage — Data Model

Verified against Claude Code 2.1.197 by inspecting real transcripts (100+ sessions across many projects) and the official docs (code.claude.com/docs). Last verified 2026-07-01.

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
│   └── -Users-me-repos-Foo/              # cwd with "/" → "-" (worktrees are an exception, see below)
│       ├── <session-id>.jsonl            # main transcript
│       ├── <session-id>/
│       │   ├── subagents/
│       │   │   ├── agent-<id>.jsonl      # subagent transcript (same schema)
│       │   │   └── agent-<id>.meta.json  # {agentType, description, toolUseId, spawnDepth}
│       │   └── tool-results/<id>.txt     # large tool outputs offloaded out of the JSONL
│       ├── .session-aliases              # other project paths linked via /add-dir (not name=uuid)
│       └── memory/                       # per-project auto-memory (markdown)
├── history.jsonl                         # global prompt history (never auto-cleaned)
├── file-history/<session-id>/<hash>@v<N> # checkpoint/undo file snapshots
├── tasks/<session-id>/<n>.json           # structured per-session task list, + .lock/.highwatermark
├── todos/<session-id>-agent-<id>.json    # flat TodoWrite list per session/agent
├── sessions/<pid>.json                   # live process registry backing `claude agents` (not deprecated)
├── plans/<slug>.md                       # saved Plan Mode plans, cross-referenced by a session's `slug`
├── jobs/<id>/{state.json,timeline.jsonl} # background-agent dispatch bookkeeping (claude agents, --bg)
└── settings.json                         # cleanupPeriodDays lives here
```

Session display names (`-n`/`--name`, `/rename`) do **not** live in `.session-aliases` — they're
written into the transcript itself as `agent-name` entries (see below) and mirrored live in
`sessions/<pid>.json`.

**Worktree sessions**: a session started with `-w`/`--worktree` runs with `cwd` under
`<repo>/.claude/worktrees/<name>/`, but its transcript is filed under the *original* repo's
project-slug directory, not a slug derived from the worktree path. A `worktree-state` entry
(see "Transcript entry types") records both `originalCwd` and `worktreePath` so you can tell the
two apart. Don't assume a session's project-slug directory matches its current `cwd`.

## Transcript entry types

Each line is a standalone JSON object discriminated by `.type`.

### `user`

```json
{
  "type": "user",
  "uuid": "6c8e477c-…",
  "parentUuid": null,
  "promptId": "a05065bc-cf03-40ca-b739-8ef6d4928b84",
  "sessionId": "82f80a36-…",
  "message": { "role": "user", "content": "string OR array of blocks" },
  "timestamp": "2026-06-11T19:51:52.420Z",
  "cwd": "/Users/me/repos/Foo",
  "gitBranch": "master",
  "permissionMode": "auto",
  "promptSource": "typed",
  "origin": { "kind": "human" },
  "userType": "external",
  "entrypoint": "cli",
  "version": "2.1.173",
  "isSidechain": false
}
```

- `message.content` as array holds blocks: `{type:"text", text|content}`, `{type:"tool_result", tool_use_id, content}`, images.
- `promptSource` (observed values only — treat as non-exhaustive): `typed`, `system` (harness-injected, e.g. a hook-injected context block), `queued` (queued while busy, see `queue-operation`), `sdk` (Agent SDK / `entrypoint:"sdk-cli"`). Older docs/builds may have used `clipboard`/`skill`/`agent-started`/`resumed` — none of those appear anywhere in 100+ locally-inspected sessions on 2.1.197, so treat them as unconfirmed for current versions.
- `permissionMode`: `default`, `auto`, `plan`, `acceptEdits`, `dontAsk`, `bypassPermissions` (matches `claude --permission-mode`'s choice list).
- `origin.kind`: `"human"` for a real typed prompt; `"task-notification"` for a prompt-shaped injection from a background task/agent coming to rest (see `queue-operation`). The most reliable field for "did a human actually type this."
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
| `attachment` | `attachment.type`, `parentUuid` | Harness metadata attached to a turn. 20+ kinds observed (`command_permissions`, `task_reminder`, `deferred_tools_delta`, `skill_listing`, `output_style`, `queued_command`, `plan_mode`/`plan_mode_exit`, `edited_text_file`, `nested_memory`, …) — non-exhaustive |
| `file-history-snapshot` | `messageId`, `snapshot.trackedFileBackups` (path → `hash@vN`), `isSnapshotUpdate` | Checkpoint/undo bookkeeping |
| `mode` / `permission-mode` | `mode` / `permissionMode` | Mode changes mid-session |
| `system` | `subtype`, `message`/`content` | Turn boundaries, compaction, scheduled wakeups, internal events — subtypes below |
| `queue-operation` | `operation` (`enqueue`/`dequeue`), `content` | Delivers a background task/agent's completion (`<task-notification>` XML) via the message queue |
| `agent-name` | `agentName`, `sessionId` | Session display name — this is what `-n`/`--name`/`/rename` actually writes, **not** `.session-aliases` |
| `pr-link` | `prNumber`, `prUrl`, `prRepository` | Links a session to a PR; backs `claude --from-pr` |
| `worktree-state` | `worktreeSession.{originalCwd,worktreePath,worktreeName,worktreeBranch,originalBranch,originalHeadCommit}` | Written by `-w`/`--worktree`; explains cwd-vs-project-slug mismatches (see "Worktree sessions" under "Directory layout") |
| `agent-setting` | `agentSetting` | Which `--agent` persona the session is using |

**`system` subtypes observed**: `informational`, `turn_duration` (+`durationMs`), `api_error`, `away_summary`, `local_command`, `compact_boundary` (+`compactMetadata`: `trigger`, `preTokens`/`postTokens`, `durationMs`, `preservedMessages`), `scheduled_task_fire` (session woken by `/loop` or a scheduled/Desktop task), `stop_hook_summary`.

`compact_boundary` is the **current** compaction marker. A standalone `summary`-typed entry (`{"type":"summary","summary":"…","leafUuid":"…"}`, matching what older docs described) does not appear in any 2.1.197 transcript inspected here — it only turned up in year-old `*.jsonl.backup` files (an orphaned artifact from a past format migration, not something current versions write). Treat `summary` as a legacy/renamed type, not something to grep for today.

## Common fields

| Field | Where | Notes |
|-------|-------|-------|
| `uuid` / `parentUuid` | user, assistant, attachment | Conversation DAG; `parentUuid: null` starts a chain |
| `sessionId` | all | Same for every entry in a file; equals the filename stem |
| `timestamp` | most | ISO 8601 UTC |
| `cwd`, `gitBranch` | user, assistant | Working dir and branch at that moment |
| `entrypoint` | user, assistant | `cli` and `sdk-cli` confirmed locally; `vs-code`, `jetbrains`, `desktop`, `remote` are documented elsewhere but didn't appear in this (terminal/SDK-only) corpus — unconfirmed, not disproven |
| `version` | user, assistant | Claude Code version that wrote the line |
| `isSidechain` | user, assistant | `true` on subagent/sidechain work |
| `userType` | user | `external` (human) vs `agent` |
| `promptId` | user only | Stable per-turn id, distinct from `uuid` |
| `origin.kind` | user (when present) | `human` (real typed prompt) vs `task-notification` (injected background-task-completion prompt) — the most reliable signal for filtering out non-human `user` lines |
| `slug` | user, assistant, attachment, system (when present) | Ties the session to a saved plan at `~/.claude/plans/<slug>.md`; present only on sessions that used Plan Mode |

## Subagent transcripts

- Live at `<project-slug>/<session-id>/subagents/agent-<id>.jsonl`, same schema as main transcripts, plus an `agentId` field (matches the `<id>` in the filename) on every line.
- `agent-<id>.meta.json`: `{ "agentType": "general-purpose", "description": "…", "toolUseId": "toolu_…", "spawnDepth": 1 }` — `toolUseId` matches the `tool_use` block (`name: "Agent"`, historically `"Task"`) in the parent transcript; `spawnDepth` counts agent-spawning-agent nesting.
- Older versions wrote sidechains inline in the main transcript with `isSidechain: true`; current versions write separate files — confirmed across 100+ locally-inspected 2.1.197 transcripts, none had an inline `isSidechain: true` line. Handle both in case you encounter an old transcript.
- Large tool outputs (main or subagent transcript alike) can be offloaded to `<session-id>/tool-results/<id>.txt` instead of inlined in the JSONL — see "Directory layout."

## Global history.jsonl

One line per prompt typed, across all projects:

```json
{ "display": "fix the failing auth test", "pastedContents": {}, "timestamp": 1758995854832, "project": "/Users/me/repos/Foo", "sessionId": "82f80a36-…" }
```

`timestamp` is epoch **milliseconds**; `project` is the real path (not the slug); `sessionId` (confirmed present on current-version lines) lets you jump straight from a history hit to its transcript under `projects/<slug>/<sessionId>.jsonl`. Useful as a fast cross-project index of what the user asked for.

## Retention and lifecycle

- Transcripts auto-clean after `cleanupPeriodDays` (default 30) — recoverable history is bounded; `history.jsonl` persists indefinitely.
- `claude --resume <id|name>`/`-r` / `--continue`/`-c` / `--from-pr <n>` reopen sessions; `--fork-session` (with `--resume`/`--continue`) creates a new session ID instead of reusing the original, same as `/branch` mid-session; `/compact` writes a `system`/`compact_boundary` entry, **not** a `summary` entry (see "Transcript entry types"); `/export <file>` dumps readable text; `--no-session-persistence` (print mode only) skips saving to disk entirely.
- `claude project purge [path]` deletes a project's local state in one shot — transcripts, task lists, debug logs, file-edit history, prompt-history lines, and its `~/.claude.json` entry — with `--dry-run`, `-y`, and `--all` flags. The most direct built-in answer to "delete this project's history."
- `claude agents --json` lists currently-tracked sessions (running or recently supervised) straight from the `sessions/<pid>.json` registry — a live complement to grepping historical transcripts. `claude attach/logs/respawn/rm <id>` manage a background session found this way; per its own docs, `claude rm` drops it from that list without deleting its transcript.
- Deprecated: `~/.claude/__store.db` (pre-JSONL SQLite store; confirmed absent from a real `~/.claude/` in this pass) — ignore. `~/.claude/sessions/<pid>.json` is a **different, current, non-deprecated** thing (see "Directory layout") — don't confuse the two just because the names are similar.
- Desktop-app sessions on the same machine appear to land in the same `~/.claude/projects/` transcripts as CLI sessions (confirmed via a `jobs/<id>/state.json.linkScanPath` pointing at an ordinary project transcript for a computer-use-flagged background job) — don't assume Desktop usage is invisible here. claude.ai/code (web) sessions run on Anthropic's infrastructure and have no local transcript unless pulled down with `claude --teleport` (present in the official CLI reference; absent from `claude --help` on 2.1.197 — the docs note `--help` isn't exhaustive) or otherwise resumed locally.
- Routines (`/schedule`, cloud-scheduled) and Desktop scheduled tasks (local) both resume a session with a `system`/`scheduled_task_fire` entry (locally confirmed for a `/loop` wakeup; the same subtype is the general scheduled-resumption marker). The only Routines-specific local trace found is a `routineFiredWatermark` field in `~/.claude.json` — outside `~/.claude/` entirely, and no `routines/` directory exists anywhere. `--remote-control`/`--rc` and `--channels` (research preview) just flag an ordinary local session; the `claude remote-control` *subcommand* instead runs a server with no local interactive session of its own. None of Routines/Remote Control/Channels leave a dedicated `~/.claude/` directory the way transcripts or file-history do — there is no `channels/` or `remote-control/` dir, and no per-feature fields in `settings.json`.
