# Cursor IDE Conversation Storage — Data Model

CLI transcript format re-verified on **Linux** against Cursor CLI `2026.07.09-a3815c0` on **2026-07-13** by running real `agent -p` sessions and inspecting the on-disk JSONL (see [The ~/.cursor tree](#the-cursor-tree)). The **editor** SQLite model (global/workspace `state.vscdb`, `composerData`, bubbles, legacy) below was verified on macOS against Cursor 3.7.x (June 2026) by querying real databases and is carried forward **unchanged** — it was **not** re-verified this pass (no Cursor editor / `state.vscdb` exists on this CLI-only host). Cursor 3.0 (April 2026) moved conversation metadata from workspace DBs into the global DB; the legacy model is documented at the bottom because old conversations still use it.

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

| Path | Content |
|---|---|
| `projects/<path-slug>/agent-transcripts/<sessionId>/<sessionId>.jsonl` (or flat `agent-transcripts/<sessionId>.jsonl`) | Plaintext JSONL transcript of agent conversations — **both** IDE agent threads and CLI `agent -p` sessions land here. `<path-slug>` = workspace absolute path with leading `/` dropped and remaining `/` → `-` (`/tmp/cursortest` → `tmp-cursortest`, verified). `<sessionId>` = the `session_id` in `--output-format json`; matches the global-DB composerId for IDE threads. **Verified record shapes (2026.07.09):** turn records `{"role":"user"\|"assistant","message":{"content":[…]}}`, plus one terminal `{"type":"turn_ended","status":"success"}` per `agent -p` run (has no `role`). Content blocks seen: `{"type":"text","text":"…"}` and `{"type":"tool_use","name":"<Tool>","input":{…}}` (e.g. `name:"Shell"`, `input:{command,description}`). User turns wrap the prompt: `<timestamp>…</timestamp>\n<user_query>\n…\n</user_query>`. **Tool _results_ are NOT persisted here** — only the `tool_use` call is (results appear in stream-json output, never the file). Possible sidecars `agent-tools/`, `terminals/`, `canvases/` were **not** created by plain CLI runs |
| `chats/<md5>/<agentId>/store.db` | Legacy CLI SQLite session store (`meta` JSON: `agentId`, `name`, `mode`, `createdAt`; + `blobs`). **Not created by `agent -p` on 2026.07.x** (headless CLI sessions persist only as the JSONL above, and `--continue`/`--resume` read that JSONL); appears only where older/IDE/interactive CLI sessions wrote it — unverified on this host |
| `agent-cli-state.json` | CLI global state, e.g. `{"version":1,"hasClearedLegacyStatsigFields":true}` (verified) |
| `projects/<path-slug>/repo.json` | `{"id":"<uuid>"}` — per-workspace repo id (verified) |
| `projects/<path-slug>/.workspace-trusted` | `{"trustedAt","workspacePath","trustMethod":"cli-flag"}` — written by `--trust` (verified) |
| `projects/<path-slug>/worker.log`, `worker.sock` | Local LSP/indexing worker log + unix socket started per workspace (verified) |
| `skills-cursor/<name>/SKILL.md` | Bundled Cursor CLI skills, synced (`.sync-manifest.json`) (verified) |
| `plans/*.plan.md` | Plan-mode artifacts; indexed by global `ItemTable` `composer.planRegistry` (editor; not present on CLI-only host) |
| `ai-tracking/ai-code-tracking.db` | AI attribution; `conversation_summaries` table (`conversationId`, `title`, `tldr`, `overview`) when populated (editor) |
| `prompt_history.json` | Rolling plain-string array of recent prompts (editor; not created by CLI runs here) |
| `worktrees/<name>/` | Agent worktree checkouts (`agent -w`; base `~/.cursor/worktrees/<repo>/<name>`) |

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

- Editor model verified on macOS Cursor 3.7.x with `_v: 16` composerData / `_v: 3` bubbles (not re-verified 2026.07.09); editor DB path differs by OS (macOS `~/Library/Application Support/Cursor`, Linux `~/.config/Cursor`, Windows `%APPDATA%/Cursor`). The `~/.cursor/` CLI tree is the same path on all platforms.
- `agent ls` and `agent resume` are interactive Ink TUIs that need a real TTY — piped/headless they abort with "Raw mode is not supported". For scripting, read the JSONL directly, or use `agent about --format json` / `agent status --format json` (both verified machine-readable).
- `agentKv:blob` protobufs are undecoded; readable fragments only.
- "Chat Too Old" / "corrupted data" in the UI means the server `conversationState` token was lost in an upgrade — local text remains fully readable.
- Deleting the global `state.vscdb` is unrecoverable (conversations are not in workspace DBs); treat it as the canonical store and never open it read-write.
