---
name: exploring-cursor-history
description: Finds and explores Cursor IDE conversation history stored locally in SQLite databases and plaintext agent transcripts. Use when the user asks to find, search, read, or export a Cursor chat session, agent conversation, composer thread, or transcript.
compatibility: Requires sqlite3 CLI and jq. IDE paths below are macOS; on Linux the IDE data root is ~/.config/Cursor, on Windows %APPDATA%\Cursor. The CLI tree is ~/.cursor on every platform (Linux/BSD honours $XDG_CONFIG_HOME/cursor; $CURSOR_CONFIG_DIR overrides everywhere).
allowed-tools: Bash(sqlite3 *) Bash(jq *)
metadata:
  author: jlreyes
---

# Exploring Cursor History

Cursor stores IDE conversations in SQLite (`state.vscdb`), with the **global DB as the single source of truth** — workspace DBs only hold legacy metadata (pre-3.0). The CLI (`agent`) stores its own sessions under `~/.cursor`. Query them directly with `sqlite3`; the recipes below are building blocks — swap the `json_extract` paths for any field in [data-model.md](data-model.md).

## Storage locations

IDE paths are shown for macOS (`~/Library/Application Support/Cursor` → `~/.config/Cursor` on Linux, `%APPDATA%\Cursor` on Windows). `~/.cursor` is the same on all platforms.

| Path | What it holds |
|------|---------------|
| `…/Cursor/User/globalStorage/state.vscdb` | (IDE) All conversation content + metadata — `cursorDiskKV` key/value table plus a `composerHeaders` index table. Can be ~1 GB |
| `…/Cursor/User/globalStorage/conversation-search.db` | (IDE) FTS5 full-text index over conversation titles + bodies, added in Cursor 3.11. Fastest search surface; best-effort, not exhaustive |
| `…/Cursor/User/workspaceStorage/<hash>/state.vscdb` | (IDE) Legacy per-workspace conversation metadata (stopped updating at Cursor 3.0); `workspace.json` sibling maps hash → folder (`folder` or `workspace` key) |
| `~/.cursor/projects/<path-slug>/agent-transcripts/<id>/<id>.jsonl` | **Plaintext JSONL transcript** of agent conversations — IDE agent threads *and* CLI `agent` sessions. Only exists for recent conversations (from ~Cursor 3.0); sub-agents live in a `subagents/<subagentId>.jsonl` sibling dir |
| `~/.cursor/chats/<md5>/<sessionId>/store.db` | CLI (`agent`) session store + `meta.json`. `<md5>` = md5 of the workspace absolute path |
| `~/.cursor/plans/*.plan.md` | Plan-mode artifacts (markdown) |
| `~/.cursor/prompt_history.json` | Rolling array of recent typed prompts (small; IDE only) |

## Schema (quick reference)

Global DB, `cursorDiskKV` table (key/value):

- `composerData:<composerId>` — one row per conversation: `name`, `subtitle`, `createdAt`/`lastUpdatedAt` (epoch ms; **lastUpdatedAt is unreliable** — the last bubble's `createdAt` is the true recency signal), `unifiedMode` (`agent`|`chat`|`plan`|`edit`), and `fullConversationHeadersOnly[]` — the ordered message list: `{bubbleId, type}` (1=user, 2=assistant). `workspaceIdentifier` is **almost never present** (4 of 2473 rows here) — attribute projects via the `composerHeaders` table, the legacy workspace lookup, or the `~/.cursor/projects` slug.
- `bubbleId:<composerId>:<bubbleId>` — one row per message: `text` (only on text turns), `type`, `createdAt` (ISO, often absent), `toolFormerData` (`{name, params, result, status}` — tool calls), `thinking.text` (reasoning), `codeBlocks`, `context` (file selections etc.)

Global DB, `composerHeaders` table (added ~Cursor 3.9): `(composerId, workspaceId, createdAt, lastUpdatedAt, isArchived, isSubagent, recency, checkpointAt, value)` — a forward-only index with a precomputed `recency` and real workspace attribution, but **only for conversations created after the migration** (26 rows vs 990 conversations with content here). Use it to filter/attribute recent chats; use `composerData:%` for the full history.

**Iterate via headers, not raw bubble rows** — orphan bubbles from regenerated/deleted turns exist (56,649 bubble rows vs 51,732 header refs here). Always open DBs read-only (`file:...?mode=ro`). In `sqlite3` shell arguments, escape JSON paths as `'\$.field'` so the shell doesn't mangle them.

All queries below assume:

```bash
GLOBAL_DB="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
SEARCH_DB="$HOME/Library/Application Support/Cursor/User/globalStorage/conversation-search.db"
```

## Resolve a partial composer ID

```bash
sqlite3 "file:$GLOBAL_DB?mode=ro" \
  "SELECT substr(key,14) FROM cursorDiskKV WHERE key LIKE 'composerData:1de03385%' LIMIT 1;"
```

## List recent conversations

```bash
sqlite3 -separator ' | ' "file:$GLOBAL_DB?mode=ro" "
  SELECT datetime(json_extract(value,'\$.createdAt')/1000,'unixepoch','localtime'),
         substr(key,14,12),
         json_extract(value,'\$.unifiedMode'),
         coalesce(nullif(json_extract(value,'\$.name'),''), json_extract(value,'\$.subtitle'), '?')
  FROM cursorDiskKV
  WHERE key LIKE 'composerData:%'
    AND json_array_length(value,'\$.fullConversationHeadersOnly') > 0
  ORDER BY 1 DESC LIMIT 30;"
```

To sort by true last activity instead of creation, order by the last bubble's timestamp (`[#-1]` = last array element):

```sql
(SELECT json_extract(b.value,'$.createdAt') FROM cursorDiskKV b
 WHERE b.key = 'bubbleId:' || substr(c.key,14) || ':' ||
       json_extract(c.value,'$.fullConversationHeadersOnly[#-1].bubbleId'))
```

For conversations created since the `composerHeaders` migration, that work is already done — and this is the only place with reliable workspace attribution and a subagent flag:

```bash
sqlite3 -separator ' | ' "file:$GLOBAL_DB?mode=ro" "
  SELECT datetime(recency/1000,'unixepoch','localtime'), substr(composerId,1,12), workspaceId,
         json_extract(value,'\$.unifiedMode'), json_extract(value,'\$.workspaceIdentifier.uri.fsPath')
  FROM composerHeaders WHERE isSubagent=0 ORDER BY recency DESC LIMIT 20;"
```

## Read a conversation transcript

One query — `json_each` walks the ordered header list and joins each bubble:

```bash
CID="<full composerId>"
sqlite3 "file:$GLOBAL_DB?mode=ro" "
  SELECT CASE json_extract(j.value,'\$.type') WHEN 1 THEN '## USER' ELSE '### ASSISTANT' END
         || coalesce('  ['||json_extract(b.value,'\$.toolFormerData.name')
                     ||' '||coalesce(json_extract(b.value,'\$.toolFormerData.status'),'')||']','')
         || char(10) || coalesce(nullif(json_extract(b.value,'\$.text'),''),'') || char(10)
  FROM cursorDiskKV c, json_each(c.value,'\$.fullConversationHeadersOnly') j
  LEFT JOIN cursorDiskKV b ON b.key = 'bubbleId:' || substr(c.key,14) || ':' || json_extract(j.value,'\$.bubbleId')
  WHERE c.key = 'composerData:$CID'
  ORDER BY j.key;"
```

Add `json_extract(b.value,'$.thinking.text')` for reasoning, `'$.createdAt'` for timestamps, or `'$.toolFormerData.result'` (truncate it — results are large) as needed.

## Search conversations

Fastest path — the FTS5 index (`conversation_fts(title, body)`, joined to `conversations` on `fts_rowid`; `conversations.id` is the composerId):

```bash
sqlite3 -separator ' | ' "file:$SEARCH_DB?mode=ro" "
  SELECT datetime(c.updated_at/1000,'unixepoch','localtime'), substr(c.id,1,12), c.title,
         replace(snippet(conversation_fts,1,'«','»','…',12), char(10),' ')
  FROM conversation_fts f JOIN conversations c ON c.fts_rowid = f.rowid
  WHERE conversation_fts MATCH 'SEARCH_TERM'
  ORDER BY c.updated_at DESC LIMIT 20;"
```

Supports FTS5 syntax (`title:foo`, `a OR b`, `"exact phrase"`, `pref*`). It is **not exhaustive**: it indexes conversations up to a cap (`conversation_search_settings.effective_conversation_cap`) and ~1/3 of indexed rows here have an empty `body`. Fall back to a raw scan of the global DB when a known string isn't found (~0.9 s over a 932 MB DB):

```bash
sqlite3 "file:$GLOBAL_DB?mode=ro" "
  SELECT key, json_extract(value,'\$.type'), substr(json_extract(value,'\$.text'),1,120)
  FROM cursorDiskKV
  WHERE key LIKE 'bubbleId:%' AND value LIKE '%SEARCH_TERM%'
  LIMIT 20;"
```

The `LIKE` on raw `value` also matches `thinking` text and tool results; pull specific fields from the hits afterwards. The key embeds the composerId: `bubbleId:<composerId>:<bubbleId>`.

## List legacy (pre-3.0) conversations with workspace attribution

Conversations from before Cursor 3.0 (April 2026) have no `workspaceIdentifier`; their metadata lives in workspace DBs:

```bash
cd ~/Library/Application\ Support/Cursor/User/workspaceStorage
for d in */; do
  ws=$(jq -r '.folder // .workspace // empty' "$d/workspace.json" 2>/dev/null | sed 's|^file://||')
  sqlite3 "file:$d/state.vscdb?mode=ro" "
    SELECT json_extract(j.value,'\$.lastUpdatedAt') || '|' || substr(json_extract(j.value,'\$.composerId'),1,12)
           || '|' || coalesce(nullif(json_extract(j.value,'\$.name'),''), json_extract(j.value,'\$.subtitle'), '?')
           || '|' || '${ws##*/}'
    FROM ItemTable t, json_each(t.value,'\$.allComposers') j
    WHERE t.key='composer.composerData';" 2>/dev/null
done | sort -t'|' -rn | head -30
```

(Qualify `t.key` — `json_each` emits its own `key` column. Nothing newer than the 3.0 cutover appears here; always check the global DB first.)

## Plaintext export (no SQLite at all)

Each line is one JSON record: turn records `{"role":…,"message":{"content":[…]}}` plus `{"type":"turn_ended","status":"success"}` control records. Content blocks are `{"type":"text",…}` or `{"type":"tool_use","name":…,"input":…}` — iterate all blocks and skip records without a `role`, otherwise tool-call turns vanish and `turn_ended` prints a stray `: `:

```bash
jq -r 'select(.role) | .role + ": " +
  ([.message.content[]
    | if .type=="text" then .text
      elif .type=="tool_use" then "[tool_use "+.name+" "+(.input|tostring)+"]"
      else "["+.type+"]" end] | join("\n"))' \
  ~/.cursor/projects/<slug>/agent-transcripts/<id>/<id>.jsonl
```

`<slug>` = workspace absolute path with the leading `/` dropped and remaining `/` → `-`. User turns wrap the prompt as `<timestamp>…</timestamp>\n<user_query>\n…\n</user_query>`. Tool **results** are not stored — only the `tool_use` call.

## Cursor CLI (`agent`) sessions

A headless run writes both the JSONL transcript above **and** `~/.cursor/chats/<md5(workspacePath)>/<sessionId>/store.db` + `meta.json`. `<sessionId>` is the `session_id` from `--output-format json`. `--continue`/`--resume` rewrite the JSONL with the full conversation. List sessions without the TUI:

```bash
for m in ~/.cursor/chats/*/*/meta.json; do
  jq -r --arg d "$(dirname "$m")" '"\(.updatedAtMs)  \($d|split("/")|last)  \(.cwd // "?")"' "$m"
done | sort -rn
```

`store.db` is a content-addressed blob store (`blobs`, `meta`); the JSONL is the readable surface — see [data-model.md](data-model.md#cli-agent-store-storedb) before touching it.

## Tips

- Tool-call turns have empty `text` — render `toolFormerData.name` instead. The legacy `toolResults` / `suggestedCodeBlocks` / `assistantSuggestedDiffs` fields still exist on every bubble but are **always empty arrays**; don't read them.
- Tool names differ per surface: the DB uses internal names (`read_file_v2`, `ripgrep_raw_search`, `run_terminal_command_v2`), the JSONL uses display names (`Read`, `Grep`, `Shell`). They map 1:1.
- The JSONL mirror is *not* a complete history — only 33 of 990 conversations with content had one here (it starts around Cursor 3.0). Use the DB when a conversation is missing.
- Sub-agent threads are full `composerData` rows too (listed in the parent's `subagentComposerIds`), so they show up in "list recent conversations" — filter with `composerHeaders.isSubagent` when you only want top-level chats.
- Map a composerId to its project via `composerHeaders.workspaceId` / `value.workspaceIdentifier.uri.fsPath`, the legacy workspace lookup, or by which `~/.cursor/projects/<slug>/agent-transcripts/` directory contains it.
- `agent ls` / `agent resume` exist but are hidden Ink TUIs that need a real TTY — piped they hang after "Raw mode is not supported". For scripting use `agent about --format json` / `agent status --format json`, or read `~/.cursor/chats` and the JSONL directly.
- Cloud/background agents (`bc-*` IDs) keep almost nothing locally — only the title is cached, in `conversation-search.db` as `source='cloud-cache'`; transcripts are server-side.
- A conversation that shows "Chat Too Old" in the UI is still fully readable from the DB; only its server `conversationState` token is lost.
