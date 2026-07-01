# Cursor IDE Conversation Storage — Data Model

Verified on macOS against Cursor IDE 3.8.23 and CLI 2026.06.29 (July 2026) by querying real databases. The IDE (semver, `Info.plist` `CFBundleShortVersionString`) and the CLI (date-based, `agent --version`) are versioned independently — "Cursor 3.x" below means the IDE; CLI-specific storage is under [The ~/.cursor tree](#the-cursor-tree). Cursor 3.0 (April 2026) moved conversation metadata from workspace DBs into the global DB; the legacy model is documented at the bottom because old conversations still use it.

## Contents

- [Locations](#locations)
- [Global DB: composerData](#global-db-composerdata)
- [Global DB: bubbles](#global-db-bubbles)
- [Other global key families](#other-global-key-families)
- [The ~/.cursor tree](#the-cursor-tree)
- [Legacy model (pre-3.0)](#legacy-model-pre-30)
- [Caveats](#caveats)

## Locations

- **Global DB**: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` — tables `ItemTable` and `cursorDiskKV`, both `(key TEXT UNIQUE, value BLOB)`. All conversation content lives here. A `state.vscdb.backup` sibling usually exists.
- **Workspace DBs**: `~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/state.vscdb` + `workspace.json` sibling: `{"folder": "file:///path"}` — or `{"workspace": "..."}` for multi-root `.code-workspace` setups. Workspace `cursorDiskKV` is empty; only legacy `ItemTable` keys matter.
- **`~/.cursor/`**: plaintext mirrors and newer artifacts (see below).

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
  "isArchived": false, "isSpec": false,
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
- There is no plain `isWorktree` field (checked 2,547 rows, 0 hits) — use the presence of `gitWorktree` instead; it's rare in practice (7/2,547 rows here).
- Global `ItemTable` key `composer.composerHeaders` holds only a couple dozen recently-open tabs (16 observed here), **not** the full index — enumerate `composerData:%` rows instead.

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

- `text` is present on only ~23% of bubbles (12,828/56,570 measured here); tool-call turns carry `toolFormerData` instead (~64%, 36,431/56,570). The pre-3.0 fields `toolResults`, `suggestedCodeBlocks`, `assistantSuggestedDiffs` are **not gone** — they're still serialized on ~99% of rows — but every single one measured here is an empty array; treat them as dead weight, not a data source.
- `thinking.text` (~35% of assistant bubbles, 18,781/53,567 measured here) stores reasoning — it is searchable via `LIKE` on the raw value.
- Bubble `unifiedMode` is an **integer** (chat=1, agent=2, plan=5), unlike the string in composerData.
- `createdAt` is an ISO string; absent on the oldest (`_v: 2`) bubbles; adjacent bubbles often share identical timestamps.
- Orphan bubbles (no header reference) exist from regenerated/deleted turns — bubble rows outnumber header refs; iterate headers.

## Other global key families

| `cursorDiskKV` prefix | Content |
|---|---|
| `checkpointId:<cid>:<checkpointId>` | Per-checkpoint file state (`files[]`, inline diffs, created folders) |
| `codeBlockDiff:<cid>:<blockId>` | Code block diffs (`newModelDiffWrtV0`, `originalModelDiffWrtV0`) |
| `messageRequestContext:<cid>:<bid>` | Per-request context sidecar (`projectLayouts`, `cursorRules`, `knowledgeItems`) |
| `agentKv:blob:<sha256>` | Hex-encoded, content-addressed blobs; can dominate DB size. A mix: ~1/4 (76/300 sampled) are plain JSON — full conversation messages, including verbatim system prompts; the rest are protobuf-framed worktree/agent state with embedded readable text after a short binary header |
| `agentKv:checkpoint:<cid>`, `agentKv:bubbleCheckpoint:<cid>:<bid>` | SHA-256 pointers into the blob store |
| `ofsContent:<uuid>:<file-uri>`, `composer.content.<sha256>` | Raw original-file snapshots (full text) |

Background/cloud agents: global `ItemTable` `workbench.backgroundComposer.persistentData` holds only `bc-<uuid>` ID lists; transcripts are server-side (shareable via cursor.com, not exportable locally).

## The ~/.cursor tree

| Path | Content |
|---|---|
| `projects/<path-slug>/agent-transcripts/<cid>/<cid>.jsonl` | Plaintext JSONL mirror of agent conversations from **both** the IDE and the CLI. One record per turn: `{"role":"user"\|"assistant","message":{"content":[{"type":"text","text":"…"}]}}`; content blocks can also be `{"type":"tool_use","name":"…","input":{...}}`, and files end with a trailing `{"type":"turn_ended","status":"success"}` line. ComposerIds match the global DB **only for IDE-originated conversations** — CLI-originated ones (below) have no `composerData`/`bubbleId` rows anywhere in the global DB. Sidecars: `agent-tools/`, `terminals/`, `canvases/` |
| `chats/<md5>/<agentId>/meta.json` | Lightweight index sidecar for a CLI session, written the moment the chat is created (e.g. by `create-chat`, before any message): `{schemaVersion, createdAtMs, updatedAtMs, hasConversation}`. `hasConversation:false` with no sibling `store.db` means the chat was registered but never actually used |
| `chats/<md5>/<agentId>/store.db` | Cursor CLI (`agent`/`cursor-agent`) session content — created alongside `meta.json` once a message is actually sent. `meta` table: one row (key `0`), a TEXT column whose content is a **hex-encoded JSON string** (not a BLOB), decoding to `{agentId, latestRootBlobId, name, mode, createdAt, isRunEverything, lastUsedModel}` — richer than `meta.json`, and the only place `name`/`mode` live. `blobs` table (`id` sha256, `data` BLOB) holds the actual transcript, same protobuf-framed encoding as `agentKv:blob` above |
| `plans/*.plan.md` | Plan-mode artifacts; indexed by global `ItemTable` `composer.planRegistry` |
| `ai-tracking/ai-code-tracking.db` | AI attribution; `conversation_summaries` table (`conversationId`, `title`, `tldr`, `overview`) when populated |
| `prompt_history.json` | Rolling plain-string array of recent prompts |
| `worktrees/<name>/` | Agent worktree checkouts |

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

After 3.0 this key shrinks to `{"selectedComposerIds": [...], "lastFocusedComposerIds": [...], "hasMigratedComposerData": true, "hasMigratedMultipleComposers": true}` and `allComposers` is no longer written — **tools that only read workspace DBs see nothing newer than the 3.0 cutover**. Bubble/composerData rows in the global DB cover both eras; use legacy `allComposers` only to enrich old rows (title, workspace, branch).

Even older history: workspace `ItemTable` keys `aiService.prompts` / `aiService.generations` (pre-composer chat pane).

## Caveats

- Verified 2026-07-01 on macOS, IDE 3.8.23 / CLI 2026.06.29, with `_v: 16` composerData / `_v: 3` bubbles unchanged since the last pass (Cursor 3.7.x, June 2026); Windows/Linux paths differ (`%APPDATA%/Cursor`, `~/.config/Cursor`).
- `agentKv:blob` (and the CLI's own `store.db` blobs) are a mix: plain JSON decodes fully, protobuf-framed ones give readable text fragments only — the leading tag/varint header bytes are undecoded.
- "Chat Too Old" / "corrupted data" in the UI means the server `conversationState` token was lost in an upgrade — local text remains fully readable.
- Deleting the global `state.vscdb` is unrecoverable (conversations are not in workspace DBs); treat it as the canonical store and never open it read-write.
