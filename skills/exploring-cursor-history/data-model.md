# Cursor Conversation Storage — Data Model

Verified against Cursor CLI 2026.06.29-2ad2186 (binary `agent`, aliased `cursor-agent`) / on 2026-07-01, on Linux, by running a real headless prompt (`agent -p … --output-format json --force`) and querying the resulting databases. The IDE (VS Code fork) global-DB model was previously verified on macOS against Cursor 3.7.x (June 2026); it is unchanged here and left as-is (no IDE is installed on this Linux machine to re-verify against, but nothing contradicts it). Cursor 3.0 (April 2026) moved IDE conversation metadata from workspace DBs into the global DB; the legacy model is documented at the bottom because old conversations still use it.

Two distinct stores exist: (1) the **IDE / desktop app** store (`state.vscdb` SQLite, VS Code global storage) and (2) the **CLI `agent`** store (per-session `store.db` under the CLI config dir). They do **not** share files.

## Contents

- [Locations](#locations)
- [Global DB: composerData](#global-db-composerdata)
- [Global DB: bubbles](#global-db-bubbles)
- [Other global key families](#other-global-key-families)
- [The ~/.cursor tree](#the-cursor-tree)
- [CLI agent store (store.db)](#cli-agent-store-storedb)
- [Legacy model (pre-3.0)](#legacy-model-pre-30)
- [Caveats](#caveats)

## Locations

Two path roots matter. The **IDE app data root** is VS Code global storage; the **CLI config root** follows XDG.

IDE app data root (`state.vscdb` lives here):
- macOS: `~/Library/Application Support/Cursor`
- Linux: `~/.config/Cursor` (capital C — VS Code fork global storage)
- Windows: `%APPDATA%\Cursor`

CLI config root (`agent`/`cursor-agent` chats, `cli-config.json`, `auth.json` live here) — resolved via `XDG_CONFIG_HOME` per the [CLI config docs](https://cursor.com/docs/cli/reference/configuration):
- Linux (XDG default, `XDG_CONFIG_HOME` unset): `~/.config/cursor` (lowercase c) — **verified on this machine**
- macOS / when XDG is unset in a way that falls back: `~/.cursor`
- override: `$XDG_CONFIG_HOME/cursor` or `$CURSOR_CONFIG_DIR`

- **Global DB (IDE)**: `<IDE root>/User/globalStorage/state.vscdb` — tables `ItemTable` and `cursorDiskKV`, both `(key TEXT UNIQUE, value BLOB)`. All IDE conversation content lives here. A `state.vscdb.backup` sibling usually exists.
- **Workspace DBs (IDE)**: `<IDE root>/User/workspaceStorage/<hash>/state.vscdb` + `workspace.json` sibling: `{"folder": "file:///path"}` — or `{"workspace": "..."}` for multi-root `.code-workspace` setups. Workspace `cursorDiskKV` is empty; only legacy `ItemTable` keys matter.
- **CLI agent chats**: `<CLI config root>/chats/<md5(workspacePath)>/<sessionId>/store.db` (+ `meta.json` sidecar). Session-scoped SQLite; see [CLI agent store](#cli-agent-store-storedb).
- **`~/.cursor/`**: plaintext transcript mirrors and newer artifacts (see below). This tree is `~/.cursor` on all platforms — it is NOT the XDG config dir.

Always open read-only: `sqlite3 "file:$DB?mode=ro"` — this also sees WAL'd recent writes while Cursor runs.

## Global DB: composerData

`cursorDiskKV` key `composerData:<composerId>` — one JSON blob per conversation, schema-versioned by `_v` (current ~16). Conversation metadata and message order:

```json
{
  "composerId": "uuid",
  "_v": 16,
  "name": "User-visible title",
  "subtitle": "Files touched or 'New chat'",
  "unifiedMode": "agent | chat | plan | edit",
  "createdAt": 1765735715351,
  "lastUpdatedAt": 1765817972879,
  "workspaceIdentifier": { "id": "<workspaceStorage hash>", "uri": { "fsPath": "/Users/me/repos/proj" } },
  "gitWorktree": { "worktreePath": "…", "commitHash": "…", "branchName": "…" },
  "modelConfig": { "modelName": "…", "maxMode": false },
  "contextUsagePercent": 39.1,
  "totalLinesAdded": 685, "totalLinesRemoved": 175, "filesChangedCount": 12,
  "isArchived": false, "isWorktree": false, "isSpec": false,
  "subComposerIds": [], "subagentComposerIds": [],
  "todos": [],
  "context": { "fileSelections": [], "mentions": {}, "…": "19 sub-keys total" },
  "fullConversationHeadersOnly": [
    { "bubbleId": "uuid", "type": 1, "serverBubbleId": "…", "grouping": { "hasText": true, "toolFormerTool": null } },
    { "bubbleId": "uuid", "type": 2 }
  ]
}
```

- `fullConversationHeadersOnly[]` is the **ordered** message list; `type: 1` = user, `type: 2` = assistant.
- `workspaceIdentifier` exists on newer rows only; older rows need the legacy workspace lookup (or the `~/.cursor/projects` directory match) for project attribution.
- `lastUpdatedAt` often ≈ `createdAt` — for true recency use the last bubble's `createdAt`.
- Rows with an empty `fullConversationHeadersOnly` are drafts/empty tabs.
- Global `ItemTable` key `composer.composerHeaders` holds only the ~10 recently-open tabs, **not** the full index — enumerate `composerData:%` rows instead.

## Global DB: bubbles

`cursorDiskKV` key `bubbleId:<composerId>:<bubbleId>` — one JSON blob per message:

```json
{
  "_v": 3,
  "type": 1,
  "text": "message content (only on text turns)",
  "createdAt": "2026-06-09T02:44:14.296Z",
  "unifiedMode": 2,
  "tokenCount": { "inputTokens": 0, "outputTokens": 0 },
  "toolFormerData": {
    "tool": 21, "name": "read_file_v2", "params": "…", "rawArgs": "…",
    "result": "<JSON string>", "status": "completed", "toolCallId": "…"
  },
  "thinking": { "text": "reasoning content", "signature": "…" },
  "codeBlocks": [], "richText": "<ProseMirror JSON of user input>",
  "checkpointId": "…", "isAgentic": true, "context": { "…": "…" }
}
```

- `text` is present on only ~25–40% of bubbles; tool-call turns carry `toolFormerData` instead (~68% of bubbles). The pre-3.0 fields `toolResults`, `suggestedCodeBlocks`, `assistantSuggestedDiffs` **no longer exist**.
- `thinking.text` (~40% of assistant bubbles) stores reasoning — it is searchable via `LIKE` on the raw value.
- Bubble `unifiedMode` is an **integer** (chat=1, agent=2, plan=5), unlike the string in composerData.
- `createdAt` is an ISO string; absent on the oldest (`_v: 2`) bubbles; adjacent bubbles often share identical timestamps.
- Orphan bubbles (no header reference) exist from regenerated/deleted turns — bubble rows outnumber header refs; iterate headers.

## Other global key families

| `cursorDiskKV` prefix | Content |
|---|---|
| `checkpointId:<cid>:<checkpointId>` | Per-checkpoint file state (`files[]`, inline diffs, created folders) |
| `codeBlockDiff:<cid>:<blockId>` | Code block diffs (`newModelDiffWrtV0`, `originalModelDiffWrtV0`) |
| `messageRequestContext:<cid>:<bid>` | Per-request context sidecar (`projectLayouts`, `cursorRules`, `knowledgeItems`) |
| `agentKv:blob:<sha256>` | Hex-encoded protobuf blobs (worktree/agent state, content-addressed; can dominate DB size) |
| `agentKv:checkpoint:<cid>`, `agentKv:bubbleCheckpoint:<cid>:<bid>` | SHA-256 pointers into the blob store |
| `ofsContent:<uuid>:<file-uri>`, `composer.content.<sha256>` | Raw original-file snapshots (full text) |

Background/cloud agents: global `ItemTable` `workbench.backgroundComposer.persistentData` holds only `bc-<uuid>` ID lists; transcripts are server-side (shareable via cursor.com, not exportable locally).

## The ~/.cursor tree

`~/.cursor` on all platforms (distinct from the XDG CLI config dir). Both the IDE and the CLI `agent` write here.

| Path | Content |
|---|---|
| `projects/<path-slug>/agent-transcripts/<id>/<id>.jsonl` | **Plaintext JSONL mirror** of agent conversations — written by both IDE agent and CLI `agent`. `<id>` = composerId (IDE) or `session_id` (CLI, matches the CLI `store.db` dir and the `session_id` in `--output-format json`). Records: `{"role":"user"\|"assistant","message":{"content":[{"type":"text","text":"…"}]}}`, plus a trailing control record `{"type":"turn_ended","status":"success"}` per completed turn. Sidecars under `projects/<slug>/`: `agent-tools/`, `terminals/`, `canvases/`, and (CLI) `repo.json`, `worker.log`, `worker.sock`. |
| `plans/*.plan.md` | Plan-mode artifacts; indexed by global `ItemTable` `composer.planRegistry` |
| `ai-tracking/ai-code-tracking.db` | AI attribution; `conversation_summaries` table (`conversationId`, `title`, `tldr`, `overview`) when populated |
| `prompt_history.json` | Rolling plain-string array of recent prompts |
| `worktrees/<name>/` | Agent worktree checkouts (`agent -w`, under `~/.cursor/worktrees/<reponame>/<name>`) |
| `skills-cursor/<skill>/SKILL.md` | Installed CLI agent skills |
| `agent-cli-state.json` | Small CLI state flags (e.g. `version`, `hasClearedLegacyStatsigFields`) |

Note: CLI **chats** are NOT under `~/.cursor` — they are under the XDG CLI config dir (`~/.config/cursor/chats/…` on Linux). Only the JSONL transcript mirror lands in `~/.cursor/projects/…`.

## CLI agent store (store.db)

Written by the CLI `agent` binary at `<CLI config root>/chats/<md5(workspaceAbsPath)>/<sessionId>/store.db` (Linux: `~/.config/cursor/chats/…`). The `<md5>` segment is `md5(workspace absolute path)`; the `<sessionId>` matches the `session_id` returned by `agent -p … --output-format json` and the JSONL transcript dir. A `meta.json` sidecar sits next to `store.db`:

```json
{ "schemaVersion": 1, "createdAtMs": 1782933608208, "hasConversation": true, "updatedAtMs": 1782933613317 }
```

`store.db` (SQLite `user_version = 1`) has exactly two tables:

```sql
CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB);
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT);
```

- **`meta`** — a single row, `key = '0'`, `value` = a **hex-encoded** JSON string (decode with `xxd -r -p`). Fields: `agentId` (= sessionId), `latestRootBlobId` (SHA-256 of the head `blobs` entry), `name` (e.g. `"New Agent"`), `mode` (e.g. `"default"`), `isRunEverything` (bool), `createdAt` (epoch ms). This replaces the older documented `meta` shape (JSON row per key).
- **`blobs`** — a **content-addressed store**; `id` = SHA-256 of `data`. Two kinds of blob:
  - **JSON message blobs** (start with `0x7B` = `{`): `{"role":"system"|"user"|"assistant","content":…}`. `content` is either a plain string (system/user boilerplate) or an array of parts with `type` in {`text`, `redacted-reasoning`}. Assistant blobs may carry `providerOptions.cursor.modelName` (e.g. `composer-2.5-fast`); user blobs may carry `providerOptions.cursor.requestId`.
  - **Protobuf tree/index blobs** (start with `0x0A`): undecoded binary that chains the conversation and its sections (readable `strings`: `system_prompt`, `tools`, `rules`, `skills`, `MCP`, `subagents`, `summarized_conversation`, `conversation`, plus the workspace `file://` URI and git branch). `meta.latestRootBlobId` points at the root of this tree.

The `blobs` store is **not chronologically ordered** and message order is only recoverable by walking the protobuf tree — for reading a CLI transcript, prefer the JSONL mirror in `~/.cursor/projects/…/agent-transcripts/<sessionId>/`. `agent ls` / `agent resume` are the built-in ways to list/resume, but both are interactive Ink TUIs that need a real TTY (they error with "Raw mode is not supported" under `--print`/piped stdin).

## Legacy model (pre-3.0)

Conversations created before Cursor 3.0 (April 2026) additionally have metadata in **workspace** DBs, `ItemTable` key `composer.composerData`:

```json
{ "allComposers": [ {
  "composerId": "uuid", "name": "…", "subtitle": "…",
  "unifiedMode": "agent | chat | plan | edit",
  "createdAt": 0, "lastUpdatedAt": 0,
  "createdOnBranch": "…", "committedToBranch": "…",
  "totalLinesAdded": 0, "totalLinesRemoved": 0, "filesChangedCount": 0,
  "contextUsagePercent": 0, "isArchived": false
} ] }
```

After 3.0 this key shrinks to `{"selectedComposerIds": [...], "hasMigratedComposerData": false}` and `allComposers` is no longer written — **tools that only read workspace DBs see nothing newer than the 3.0 cutover**. Bubble/composerData rows in the global DB cover both eras; use legacy `allComposers` only to enrich old rows (title, workspace, branch).

Even older history: workspace `ItemTable` keys `aiService.prompts` / `aiService.generations` (pre-composer chat pane).

## Caveats

- IDE global-DB schema (`_v: 16` composerData / `_v: 3` bubbles) verified on macOS Cursor 3.7.x; not re-verifiable here (no IDE installed on this Linux box) but unchanged and left as documented. IDE app-data root differs per platform: macOS `~/Library/Application Support/Cursor`, Linux `~/.config/Cursor`, Windows `%APPDATA%\Cursor`.
- CLI `agent` store (`store.db`, `meta.json`, JSONL mirror, config dir) verified live against CLI 2026.06.29-2ad2186 on Linux (config root `~/.config/cursor`).
- `agentKv:blob` protobufs are undecoded; readable fragments only.
- "Chat Too Old" / "corrupted data" in the UI means the server `conversationState` token was lost in an upgrade — local text remains fully readable.
- Deleting the global `state.vscdb` is unrecoverable (conversations are not in workspace DBs); treat it as the canonical store and never open it read-write.
