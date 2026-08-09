# Cursor Conversation Storage — Data Model

Verified on **macOS** against the **Cursor IDE 3.13.21** and **Cursor CLI `2026.08.04-aaa8809`** on **2026-08-09**, by querying the real global/workspace databases read-only (2,553 `composerData` rows, 56,649 bubble rows) and by running live `agent -p` sessions. Cursor 3.0 (April 2026) moved conversation metadata from workspace DBs into the global DB; the legacy model is documented at the bottom because old conversations still use it. Cursor 3.11 (July 2026) added the `conversation-search.db` FTS index.

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

Two roots. The **IDE data root** is VS Code global storage: macOS `~/Library/Application Support/Cursor`, Linux `~/.config/Cursor`, Windows `%APPDATA%\Cursor`. The **CLI root** is `~/.cursor` on every platform — per the [CLI config docs](https://cursor.com/docs/cli/reference/configuration), Linux/BSD use `$XDG_CONFIG_HOME/cursor` when that variable is set, and `$CURSOR_CONFIG_DIR` overrides everywhere. `~/.cursor` also holds IDE-written artifacts (plans, transcripts, prompt history), so both products share it.

- **Global DB**: `<IDE root>/User/globalStorage/state.vscdb` — tables `ItemTable` and `cursorDiskKV`, both `(key TEXT UNIQUE, value BLOB)`, plus a `composerHeaders` table. All conversation content lives here. Siblings: `state.vscdb.backup`, `state.vscdb.options.json` (`{"useWAL": true}`), `conversation-search.db`.
- **Workspace DBs**: `<IDE root>/User/workspaceStorage/<hash>/state.vscdb` + `workspace.json` sibling: `{"folder": "file:///path"}` — or `{"workspace": "..."}` for multi-root `.code-workspace` setups (174 vs 4 here). Workspace `cursorDiskKV` is empty in all 179 dirs, and the `composerHeaders` table (created in 4 recently-opened workspaces) is empty too; only legacy `ItemTable` keys matter.
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
- `lastUpdatedAt` often ≈ `createdAt` — for true recency use the last bubble's `createdAt`, or `composerHeaders.recency`.
- Rows with an empty `fullConversationHeadersOnly` are drafts/empty tabs (1,483 of 2,473 here).
- Sub-agent threads are ordinary `composerData` rows, referenced from the parent's `subagentComposerIds`; they appear in any naive listing.
- Global `ItemTable` key `composer.composerHeaders` holds only the ~16 recently-open tabs (`{"allComposers":[…]}` with `type:"head"` entries), **not** the full index — enumerate `composerData:%` rows instead.

## Global DB: bubbles

`cursorDiskKV` key `bubbleId:<composerId>:<bubbleId>` — one JSON blob per message. `_v` distribution: `3` × 54,967 (current), `2` × 1,118, absent × 564. ~100 keys are present on nearly every row; the ones that carry content:

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
- The pre-3.0 fields `toolResults`, `suggestedCodeBlocks`, `assistantSuggestedDiffs` (and `allThinkingBlocks`) **still exist as keys on ~56,085 rows but are always empty arrays** — zero non-empty occurrences. Don't read them.
- `toolFormerData` keys by frequency: `additionalData` 35,677, `toolCallId`/`tool`/`status`/`name` 23,195, `toolIndex`/`modelCallId` 23,136, `params` 23,098, `rawArgs` 22,629, `result` 22,041, `userDecision` 7,586, `toolCallBinary` 2,041, `attachments` 1,155, `error` 541. `status` ∈ {`completed` 22,367, `error` 540, `cancelled` 221, `loading` 67}. `params` and `result` are JSON **strings**, not objects.
- **13,284 `toolFormerData` objects carry no `name`** — they are the degenerate `{"additionalData":{"status":"error"}}` form. Guard with `coalesce(...)` when rendering.
- `thinking` sub-keys: `text`, `signature` (19,110 each), plus `redactedThinking`/`isLastThinkingChunk` on 75.
- Bubble `unifiedMode` is an **integer** (chat=1 ×299, agent=2 ×55,556, plan=5 ×230), unlike the string in composerData.
- `createdAt` is an ISO string and is **often missing**: absent on all `_v: 2`/unversioned rows and on 19,049 of 54,967 `_v: 3` rows. Adjacent bubbles often share identical timestamps.
- `richText` is **Lexical** editor state (`{"root":{"children":[…]}}`, 2,358 rows), not ProseMirror; 94 rows store plain text instead.
- Orphan bubbles (no header reference) exist from regenerated/deleted turns — 56,649 bubble rows vs 51,732 header refs. Iterate headers.

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

`<IDE root>/User/globalStorage/conversation-search.db` — the local index behind Cursor 3.11's transcript search.

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
| `projects/<path-slug>/agent-transcripts/<id>/<id>.jsonl` | Plaintext JSONL transcript of agent conversations — **both** IDE agent threads and CLI `agent` sessions. `<path-slug>` = workspace absolute path, leading `/` dropped, remaining `/` → `-` (verified: `/private/tmp/…/scratchpad/cursorlive` → `private-tmp-…-scratchpad-cursorlive`); IDE windows without a folder use the numeric window id or `empty-window`. Records: `{"role":"user"\|"assistant","message":{"content":[…]}}` and `{"type":"turn_ended","status":"success"}` — no other top-level shapes across all 35 files here. Content blocks: `{"type":"text","text":…}` (848) and `{"type":"tool_use","name":…,"input":…}` (82); **tool results are never persisted**. Tool `name`s are display names (`Read`, `Grep`, `Shell`, `Glob`, `Write`, `StrReplace`, `TodoWrite`, `WebSearch`) that map 1:1 onto the DB's internal `toolFormerData.name`. **Coverage is partial** — 33 of 990 conversations with content, starting ~2026-04-01 |
| `projects/<slug>/agent-transcripts/<id>/subagents/<subagentId>.jsonl` | Sub-agent transcripts, same record shape; ids match the parent's `subagentComposerIds` |
| `projects/<slug>/{agent-tools,terminals,canvases,mcps}/` | Sidecars: overflowed tool output (`.txt`), terminal state, canvas scratch files, MCP tool descriptors |
| `projects/<slug>/{repo.json,mcp-auth.json,worker.log,worker.sock,.workspace-trusted}` | CLI per-workspace state; `.workspace-trusted` is written by `--trust` |
| `chats/<md5>/<sessionId>/store.db` (+ `meta.json`) | CLI session store — see below |
| `plans/<slug>.plan.md` | Plan-mode artifacts; indexed by global `ItemTable composer.planRegistry` |
| `ai-tracking/ai-code-tracking.db` | AI attribution — `ai_code_hashes` (`hash`, `source`, `fileName`, `requestId`, `conversationId`, `model`), `scored_commits`, `tracking_state`, `conversation_summaries` (`conversationId`, `title`, `tldr`, `overview`, `summaryBullets`; empty here) |
| `prompt_history.json` | Rolling plain-string array of recent typed prompts — small and stale (9 entries here); not a history surface |
| `cli-config.json` | CLI settings + `authInfo` (`email`, `displayName`, `userId`, `authId`); `agent-cli-state.json` holds version flags |
| `hooks.json`, `ide_state.json`, `mcp.json`, `argv.json`, `statsig-cache.json` | Hook definitions, `recentlyViewedFiles`, MCP config, Electron argv, feature-flag cache |
| `skills/`, `skills-cursor/`, `plugins/`, `agents/`, `workers/` | User skills, bundled Cursor skills, plugins, agent/worker definitions |
| `worktrees/<repo>/<name>/` | Agent worktree checkouts (`agent -w`) |
| `.gitignore` | Cursor-managed; un-ignores `projects/*/agent-transcripts/` and `projects/*/mcps/` so transcripts stay citable |

## CLI agent store (store.db)

Verified live: `agent -p "…" --output-format json --force` writes **both** the JSONL transcript above **and** `~/.cursor/chats/<md5(workspaceAbsPath)>/<sessionId>/store.db` + `meta.json`. (`md5 "/…/scratchpad/cursorlive"` = `1d7dc78584615d02d18005a0d64da6a8`, matching the directory name.) `<sessionId>` is the `session_id` in the `--output-format json` result object.

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

- **`meta`** — one row, `key='0'`, `value` = **hex-encoded** JSON (`xxd -r -p` to decode): `agentId` (= sessionId), `latestRootBlobId` (SHA-256 of the head blob), `name` (`"New Agent"`), `mode` (`"default"`), `isRunEverything`, `createdAt`, `blobEncryptionKey`.
- **`blobs`** — content-addressed, `id` = SHA-256 of `data`. Two kinds: JSON message blobs starting `0x7B` (`{"role":"system"|"user"|"assistant","content":…}`; `content` is a string for system turns or an array of `text`/`redacted-reasoning` parts; `providerOptions.cursor.requestId` on user turns), and protobuf tree/index blobs starting `0x0A` (undecoded; readable `strings`: `system_prompt`, `tools`, `rules`, `skills`, `MCP`, `subagents`, `summarized_conversation`, `conversation`).
- Blobs are **not chronologically ordered** — order is only recoverable by walking the protobuf tree. Read the JSONL mirror instead.
- `--continue` (= `--resume=-1`) and `--resume <chatId>` reuse the same `sessionId`, update `store.db`/`meta.json` in place, and **rewrite** the JSONL with the whole conversation plus a single trailing `turn_ended` (IDE threads instead accumulate one `turn_ended` per turn).
- Older session dirs may have `store.db` with no `meta.json`, and may carry `-wal`/`-shm` siblings.
- CLI subcommands `ls` ("Resume a chat session"), `resume`, and `create-chat` exist but are omitted from `agent --help`; `ls`/`resume` are Ink TUIs that hang under piped stdin with "Raw mode is not supported". `agent about --format json` and `agent status --format json` are the machine-readable surfaces.

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

- Verified on macOS with IDE 3.13.21 (`composerData _v: 17` current, bubbles `_v: 3`) and CLI `2026.08.04-aaa8809`. IDE data root differs by OS (macOS `~/Library/Application Support/Cursor`, Linux `~/.config/Cursor`, Windows `%APPDATA%\Cursor`); `~/.cursor` is the same everywhere unless `$XDG_CONFIG_HOME` (Linux/BSD) or `$CURSOR_CONFIG_DIR` is set.
- `agentKv:blob` and CLI `store.db` protobufs are undecoded; readable fragments only.
- "Chat Too Old" / "corrupted data" in the UI means the server `conversationState` token was lost in an upgrade — local text remains fully readable.
- Cloud/background agents (`bc-*`) store only a cached title locally (`conversation-search.db`, `source='cloud-cache'`); the body is server-side.
- Deleting the global `state.vscdb` is unrecoverable (conversations are not in workspace DBs); treat it as the canonical store and never open it read-write.
