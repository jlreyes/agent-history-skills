# Cursor Conversation Storage — Data Model

Official current releases on 2026-09-06 are Desktop **3.19** and CLI **2026.09.02-c22c1a3**. Storage evidence is Desktop **3.15.6** and CLI **2026.08.04-aaa8809**; current CLI help/version was verified, but current live generation did not complete. Cursor 3.0 moved conversation metadata from workspace DBs into the global DB; Cursor 3.11 added `conversation-search.db` FTS.

## Contents

- [Locations](#locations)
- [Global DB: composerData](#global-db-composerdata)
- [Global DB: bubbles](#global-db-bubbles)
- [Global DB: composerHeaders table](#global-db-composerheaders-table)
- [conversation-search.db (FTS index)](#conversation-searchdb-fts-index)
- [Other global key families](#other-global-key-families)
- [The ~/.cursor tree](#the-cursor-tree)
- [CLI agent store (store.db)](#cli-agent-store-storedb)
- [Legacy model (pre-3.0)](#legacy-model-pre-30)
- [Caveats](#caveats)

## Locations

Two roots. The **IDE data root** is VS Code global storage: macOS `~/Library/Application Support/Cursor`, Linux `~/.config/Cursor`, Windows `%APPDATA%\Cursor`. The **CLI root** defaults to `~/.cursor` — per the [CLI config docs](https://cursor.com/docs/cli/reference/configuration), Linux/BSD use `$XDG_CONFIG_HOME/cursor` when that variable is set, and `$CURSOR_CONFIG_DIR` overrides everywhere. The default root also holds IDE-written artifacts (plans, transcripts, prompt history), so both products can share it.

- **Global DB**: `<IDE root>/User/globalStorage/state.vscdb` — tables `ItemTable` and `cursorDiskKV`, both `(key TEXT UNIQUE, value BLOB)`, plus a `composerHeaders` table. All conversation content lives here. Siblings: `state.vscdb.backup`, `state.vscdb.options.json` (`{"useWAL": true}`), `conversation-search.db`.
- **Workspace DBs**: `<IDE root>/User/workspaceStorage/<hash>/state.vscdb` + `workspace.json`: 174 folder mappings, 4 workspace mappings, and one unmapped. Nine are `ItemTable` only; 166 also have empty `cursorDiskKV`; four additionally have empty `composerHeaders`. Only legacy `ItemTable` keys matter.
- **`~/.cursor/`**: plaintext transcripts, CLI session stores, and newer artifacts (see below).

Always open read-only: `sqlite3 "file:$DB?mode=ro"` — this also sees WAL'd recent writes while Cursor runs.

## Global DB: composerData

`cursorDiskKV` key `composerData:<composerId>` — one JSON blob per conversation, schema-versioned by `_v`. Versions present on disk: absent, 1, 3, 6, 8, 9, 10, 11, 14, 16, **17** (current). All eras expose the same core fields, so one reader handles them all.

```json
{
  "composerId": "uuid",
  "_v": 17,
  "name": "User-visible title",
  "subtitle": "Files touched or 'New chat'",
  "unifiedMode": "agent | chat | plan | edit",
  "createdAt": 1765735715351,
  "lastUpdatedAt": 1765817972879,
  "modelConfig": { "modelName": "…", "maxMode": false },
  "contextUsagePercent": 39.1,
  "totalLinesAdded": 685, "totalLinesRemoved": 175,
  "isArchived": false, "isWorktree": false, "isSpec": false, "isDraft": false,
  "subComposerIds": [], "subagentComposerIds": [],
  "todos": [], "queueItems": [], "trackedGitRepos": [],
  "context": { "fileSelections": [], "mentions": {}, "…": "30 sub-keys total" },
  "fullConversationHeadersOnly": [
    { "bubbleId": "uuid", "type": 1, "serverBubbleId": "…" },
    { "bubbleId": "uuid", "type": 2 }
  ]
}
```

- `fullConversationHeadersOnly[]` is the **ordered** message list; `type: 1` = user, `type: 2` = assistant. Element keys seen: `bubbleId`/`type` (always), `serverBubbleId` (37%), `grouping`, `createdAt`, `contentHeightHint` (all rare).
- `name` on 73% of rows, `lastUpdatedAt` on 73%, `unifiedMode` on 68%, `subtitle` on 25%. Values: `agent` 1182, `chat` 474, `plan` 16, `edit` 7.
- **`workspaceIdentifier` is effectively absent** — 4 of 2,473 rows. Use the [`composerHeaders` table](#global-db-composerheaders-table), the [legacy workspace lookup](#legacy-model-pre-30), or the `~/.cursor/projects` slug for project attribution.
- `gitWorktree` (7 rows), `activeCustomMode` / `pendingExitedCustomMode` (`_v: 17` only), `filesChangedCount` / `agentBackend` (`_v: 16` and older) are all optional.
- For recency, use the last bubble's `createdAt` when present; otherwise fall back to `lastUpdatedAt`/`createdAt`. `composerHeaders.recency` is available for 26 rows.
- Composer versions: no `_v` 943; v1 13; v3 104; v6 240; v8 19; v9 334; v10 744; v11 20; v14 35; v16 14; v17 7; plus 80 `NULL` tombstones.
- `composerData` has 2,553 keys: 2,473 objects and 80 `NULL` tombstones. Rows with an empty `fullConversationHeadersOnly` are drafts/empty tabs; do not conflate absent-version rows with tombstones.
- Sub-agent threads are ordinary `composerData` rows, referenced from the parent's `subagentComposerIds`; they appear in any naive listing.
- Global `ItemTable` key `composer.composerHeaders` holds only the ~16 recently-open tabs (`{"allComposers":[…]}` with `type:"head"` entries), **not** the full index — enumerate `composerData:%` rows instead.

## Global DB: bubbles

`cursorDiskKV` key `bubbleId:<composerId>:<bubbleId>` — one JSON blob per message. `bubbles` has 56,085 versioned objects (v2 1,118; v3 54,967), 2 unversioned tokenCount-only objects, and 562 `NULL` tombstones. Do not conflate absent-version records with tombstones.

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
    "result": "<JSON string>", "status": "completed", "toolCallId": "…",
    "additionalData": { "…": "…" }
  },
  "thinking": { "text": "reasoning content", "signature": "…" },
  "codeBlocks": [], "richText": "<Lexical editor-state JSON of user input>",
  "checkpointId": "…", "isAgentic": true, "context": { "…": "…" }
}
```

- Population over the whole corpus: non-empty `text` 12,837 (23%); `toolFormerData` 36,479 (64%); non-empty `thinking.text` 18,803 (35% of the 53,643 assistant bubbles); `codeBlocks` 44,749; `richText` 2,452.
- Message split: `type: 2` (assistant) 53,643, `type: 1` (user) 2,442; no other values.
- The pre-3.0 fields `toolResults`, `suggestedCodeBlocks`, `assistantSuggestedDiffs` (and `allThinkingBlocks`) still exist on the 56,085 versioned objects but are always empty arrays. Don't read them.
- `toolFormerData.params` is a JSON string. `result` has 22,036 strings plus five structured `todo_write` objects; render neither by default. `status` ∈ {`completed`, `error`, `cancelled`, `loading`}.
- **13,284 `toolFormerData` objects carry no `name`** — they are the degenerate `{"additionalData":{"status":"error"}}` form. Guard with `coalesce(...)` when rendering.
- `thinking` sub-keys: `text`, `signature` (19,110 each), plus `redactedThinking`/`isLastThinkingChunk` on 75.
- Bubble `unifiedMode` is an **integer** (chat=1 ×299, agent=2 ×55,556, plan=5 ×230), unlike the string in composerData.
- `createdAt` is an ISO string and is **often missing**: absent on all `_v: 2`/unversioned rows and on 19,049 of 54,967 `_v: 3` rows. Adjacent bubbles often share identical timestamps.
- `richText` is **Lexical** editor state (`{"root":{"children":[…]}}`, 2,358 rows), not ProseMirror; 94 rows store plain text instead.
- Orphan bubbles from regenerated/deleted turns exist; iterate headers rather than raw bubble rows.

## Global DB: composerHeaders table

New in the 3.9-era schema (gated by `ItemTable` keys `composer.composerHeaders.tableGateEnabled` / `.version` / `.migratedToTable`):

```sql
CREATE TABLE composerHeaders (composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER,
  lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER, recency INTEGER,
  checkpointAt INTEGER, value TEXT);
CREATE INDEX idx_composerHeaders_0 ON composerHeaders (workspaceId, isSubagent, isArchived, recency);
CREATE INDEX idx_composerHeaders_1 ON composerHeaders (recency, composerId);
```

- `value` is the same `type:"head"` JSON as `ItemTable composer.composerHeaders` — keys: `composerId`, `createdAt`, `lastUpdatedAt`, `unifiedMode`, `forceMode`, `workspaceIdentifier`, `draftTarget`, `isArchived`, `isDraft`, `isSpec`, `isProject`, `isWorktree`, `isBestOfNSubcomposer`, `numSubComposers`, `referencedPlans`, `trackedGitRepos`, `hasUnreadMessages`, `hasPendingPlan`, `hasBlockingPendingActions`, `hasBeenInSidebar`, `totalLinesAdded`, `totalLinesRemoved`, `worktreeStartedReadOnly`, `type`.
- **Forward-only, not backfilled**: 26 rows here, all created 2026-06-07 or later — matching the 23 `composerData` rows created after the migration. It is not a full index of history.
- It is nonetheless the only place with a precomputed `recency` and reliable workspace attribution. `workspaceId` is either a `workspaceStorage` hash, a numeric window id for untitled windows, or `empty-window`.

## conversation-search.db (FTS index)

`<IDE root>/User/globalStorage/conversation-search.db` — the local index behind Cursor 3.11's transcript search (`PRAGMA user_version=7`).

```sql
CREATE TABLE conversations (fts_rowid INTEGER PRIMARY KEY,
  source TEXT CHECK (source IN ('local','cloud-cache')), scope TEXT, id TEXT,
  title TEXT, updated_at INTEGER, is_archived INTEGER,
  root_fingerprint TEXT, cache_fingerprint TEXT, UNIQUE(source,scope,id));
CREATE VIRTUAL TABLE conversation_fts USING fts5(title, body,
  tokenize='unicode61 remove_diacritics 2', prefix='2 3');
CREATE TABLE conversation_search_candidates (id TEXT PRIMARY KEY, updated_at INTEGER);
CREATE TABLE conversation_search_reconciliation (id INTEGER PRIMARY KEY CHECK (id=1), cursor TEXT, in_progress INTEGER);
CREATE TABLE conversation_search_settings (id INTEGER PRIMARY KEY CHECK (id=1), effective_conversation_cap INTEGER);
```

- Join on `conversations.fts_rowid = conversation_fts.rowid`. `conversations.id` is the composerId for `source='local'`, and the `bc-<uuid>` id for `source='cloud-cache'`.
- 1,491 local rows + 1 cloud-cache row here; `effective_conversation_cap = 10000`.
- **Partial**: 505 of 1,492 indexed rows have an empty `body` (title-only), including every cloud-cache row. Treat it as a fast first pass, not ground truth — the exhaustive search is a `LIKE` scan of `cursorDiskKV` (~0.9 s on a 932 MB DB).

## Other global key families

`cursorDiskKV` prefix counts on this machine: `bubbleId` 56,649 · `checkpointId` 10,556 · `agentKv` 8,829 · `codeBlockDiff` 6,972 · `messageRequestContext` 2,880 · `composerData` 2,553 · `codeBlockPartialInlineDiffFates` 516 · `inlineDiffs-<hash>` 176 · `ofsContent` 154 · `inlineDiff` 12 · `composerVirtualRowHeights` 4.

| `cursorDiskKV` key | Content |
|---|---|
| `checkpointId:<cid>:<checkpointId>` | Per-checkpoint file state — `files`, `activeInlineDiffs`, `inlineDiffNewlyCreatedResources`, `newlyCreatedFolders`, `nonExistentFiles` |
| `codeBlockDiff:<cid>:<blockId>` | `{newModelDiffWrtV0, originalModelDiffWrtV0}` |
| `messageRequestContext:<cid>:<bid>` | Per-request context sidecar — `projectLayouts`, `cursorRules`, `knowledgeItems`, `summarizedComposers`, `attachedFoldersListDirResults`, `terminalFiles` |
| `agentKv:blob:<sha256>` | Hex-encoded protobuf blobs (worktree/agent state, content-addressed; 8,818 rows — can dominate DB size) |
| `agentKv:checkpoint:<cid>`, `agentKv:bubbleCheckpoint:<cid>:<bid>` | SHA-256 pointers into the blob store |
| `codeBlockPartialInlineDiffFates:<cid>:<bid>` | `{fates: …}` — accept/reject state of partially applied inline diffs |
| `inlineDiff:<workspaceHash>:<diffId>` | `{diffId, generationUUID, uri, originalTextLines, composerMetadata, hideDecorations}` |
| `inlineDiffs-<workspaceHash>`, `inlineDiffsData` | Per-workspace inline-diff lists (empty arrays here) |
| `composerVirtualRowHeights:<cid>`, `:_recentIds` | UI scroll-height cache |
| `ofsContent:<uuid>:<file-uri>`, `composer.content.<sha256>` | Raw original-file snapshots (full text, not JSON) |

Other useful global `ItemTable` keys: `composer.planRegistry` (array of plan slugs matching `~/.cursor/plans/<slug>.plan.md`), `composer.planRedirects`, `glass.localAgentProjects.v1` / `glass.localAgentProjectMembership.v1` (the "Projects" grouping: `{id, name, workspace:{id, uri}, createdAt, isArchived}` and composerId → projectId), `glass.cloudAgentProjects.v1`, `workbench.backgroundComposer.persistentData` (`bc-<uuid>` id lists only — cloud transcripts are server-side), `aiService.prompts` / `aiService.generations` (also present per workspace).

## The ~/.cursor tree

| Path | Content |
|---|---|
| `projects/<path-slug>/agent-transcripts/<id>/<id>.jsonl` | Top-level role messages (`user`/`assistant`) and `turn_ended` controls (`success`, or `aborted` with `error`); 35 files observed (22 IDE-matched, 13 CLI-only) |
| `projects/<slug>/agent-transcripts/<id>/subagents/<subagentId>.jsonl` | Sub-agent transcripts, same record shape; 11 IDE-matched files observed; ids match the parent's `subagentComposerIds` |
| `projects/<slug>/{agent-tools,terminals,canvases,mcps}/` | Sidecars: overflowed tool output (`.txt`), terminal state, canvas scratch files, MCP tool descriptors |
| `projects/<slug>/{repo.json,mcp-auth.json,worker.log,worker.sock,.workspace-trusted}` | CLI per-workspace state; `.workspace-trusted` is written by `--trust` |
| `chats/<md5>/<sessionId>/store.db` (+ `meta.json`) | CLI session store — see below |
| `plans/<slug>.plan.md` | Plan-mode artifacts; indexed by global `ItemTable composer.planRegistry` |
| `ai-tracking/ai-code-tracking.db` | AI attribution — `ai_code_hashes` (including `createdAt`), `ai_deleted_files`, `tracked_file_content`, `scored_commits`, `tracking_state`, and `conversation_summaries` (including `model`, `mode`, `updatedAt`) |
| `prompt_history.json` | Rolling plain-string array of recent typed prompts — small and stale (9 entries here); not a history surface |
| `cli-config.json` | CLI settings and optional `authInfo`; `agent-cli-state.json` holds version flags |
| `hooks.json`, `ide_state.json`, `mcp.json`, `argv.json`, `statsig-cache.json` | Hook definitions, `recentlyViewedFiles`, MCP config, Electron argv, feature-flag cache |
| `skills/`, `skills-cursor/`, `plugins/`, `agents/`, `workers/` | User skills, bundled Cursor skills, plugins, agent/worker definitions |
| `worktrees/<repo>/<name>/` | Agent worktree checkouts (`agent -w`) |
| `.gitignore` | Cursor-managed; un-ignores `projects/*/agent-transcripts/` and `projects/*/mcps/` so transcripts stay citable |

Across both transcript paths: 46 files/1,183 records (1,166 messages: 1,066 assistant/100 user; 15 success/2 aborted; 936 text/673 tool-use parts). Observed display tools: `AwaitShell`, `Delete`, `GetMcpTools`, `Glob`, `Grep`, `Read`, `ReadLints`, `Shell`, `StrReplace`, `TodoWrite`, `WebFetch`, `WebSearch`, `Write`. No `tool_result` part was observed.

## CLI agent store (store.db)

Previously live-verified on CLI 2026.08.04: `agent -p` writes both the JSONL transcript above and `~/.cursor/chats/<md5(workspaceAbsPath)>/<sessionId>/store.db` + `meta.json`.

```json
// meta.json
{"schemaVersion":1,"createdAtMs":1786300050097,"hasConversation":true,
 "updatedAtMs":1786300056274,"cwd":"/abs/workspace/path"}
```

```sql
-- store.db, PRAGMA user_version = 1
CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB);
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT);
```

- **`meta.json` sidecar** — 16 observed, all schemaVersion 1. `cwd` is optional (absent 3/16), as is `title`.
- **`meta` table** — one row, `key='0'`, whose value is hex-encoded JSON. Optional keys include `agentId`, `approvalMode`, `blobEncryptionKey`, `createdAt`, `isRunEverything`, `lastUsedModel`, `latestRootBlobId`, `mode`, and `name`; observed modes are `default`, `search`, and `auto-run`.
- **`blobs`** — content-addressed, `id` = SHA-256 of `data`. JSON message blobs have roles `system`/`user`/`assistant`/`tool`, content as string or array, and parts `reasoning`, `redacted-reasoning`, `text`, `tool-call`, or `tool-result`. Three structured non-message JSON blobs also occur. Non-JSON protobuf/binary blobs have observed first bytes `0A`, `12`, `1A`, `23`, `2D`, `2F`, `46`, `6E`.
- Blobs are **not chronologically ordered** — order is only recoverable by walking the protobuf tree. Non-JSON blobs are protobuf/binary; their first byte is not universally `0x0A`. Read the JSONL mirror instead. Only 13/16 CLI store IDs had JSONL mirrors.
- `--continue` (= `--resume=-1`) and `--resume <chatId>` reuse the same `sessionId`, update `store.db`/`meta.json` in place, and **rewrite** the JSONL with the whole conversation plus a single trailing `turn_ended` (IDE threads instead accumulate one `turn_ended` per turn).
- Older session dirs may have `store.db` with no `meta.json`, and may carry `-wal`/`-shm` siblings.
- Current help visibly lists `create-chat`, `ls`, `resume`, and `persist list|attach|stop`; persist manages detached processes. The raw-mode hang was observed only on 2026.08.04. There is no export/history/sessions subcommand.

## Legacy model (pre-3.0)

Conversations created before Cursor 3.0 additionally have metadata in **workspace** DBs, `ItemTable` key `composer.composerData`:

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

164 of 179 workspace DBs still carry `allComposers`, but the newest entry anywhere is **2026-04-01** — the cutover. After it the key shrinks to `{"selectedComposerIds":[],"lastFocusedComposerIds":[],"hasMigratedComposerData":true,"hasMigratedMultipleComposers":true}` and `allComposers` is no longer written — **tools that only read workspace DBs see nothing newer than the 3.0 cutover**. Bubble/composerData rows in the global DB cover both eras; use legacy `allComposers` only to enrich old rows (title, workspace, branch).

Even older history: workspace `ItemTable` keys `aiService.prompts` / `aiService.generations` (pre-composer chat pane).

## Caveats

- Storage was verified on macOS with IDE 3.15.6 and CLI `2026.08.04-aaa8809`; current 3.19 / 2026.09.02 help/version was checked, not current live storage. The CLI root defaults to `~/.cursor`, with Linux/BSD `$XDG_CONFIG_HOME/cursor` and `$CURSOR_CONFIG_DIR` overrides.
- `agentKv:blob` and CLI `store.db` protobufs are undecoded; readable fragments only.
- "Chat Too Old" / "corrupted data" in the UI means the server `conversationState` token was lost in an upgrade — local text remains fully readable.
- Cloud/background agents (`bc-*`) store only a cached title locally (`conversation-search.db`, `source='cloud-cache'`); the body is server-side.
- Deleting the global `state.vscdb` is unrecoverable (conversations are not in workspace DBs); treat it as the canonical store and never open it read-write.
