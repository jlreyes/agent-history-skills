---
name: exploring-cursor-history
description: Finds and explores Cursor IDE conversation history stored locally in SQLite databases and plaintext agent transcripts. Use when the user asks to find, search, read, export, or resume a Cursor chat session, agent conversation, composer thread, or transcript.
compatibility: Requires sqlite3 CLI and jq. macOS only (paths are macOS-specific). The CLI recipes additionally require the `agent`/`cursor-agent` binary.
allowed-tools: Bash(sqlite3 *) Bash(jq *)
metadata:
  author: jlreyes
---

# Exploring Cursor History

Cursor stores IDE conversations in SQLite databases (`state.vscdb`), with the **global DB as the single source of truth** — workspace DBs only hold legacy metadata (pre-3.0). The CLI (`agent`/`cursor-agent`) keeps a separate, per-session SQLite store under `~/.cursor/chats/` — see the CLI recipes below. Query them directly with `sqlite3`; the recipes below are building blocks — swap the `json_extract` paths for any field in [data-model.md](data-model.md).

## Storage locations (macOS)

| Path | What it holds |
|------|---------------|
| `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` | All conversation content + metadata (`cursorDiskKV` table). Can be ~1 GB |
| `~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/state.vscdb` | Legacy per-workspace conversation metadata (stopped updating at Cursor 3.0); `workspace.json` sibling maps hash → folder (`folder` or `workspace` key) |
| `~/.cursor/projects/<path-slug>/agent-transcripts/<composerId>/<composerId>.jsonl` | **Plaintext JSONL mirror** of agent conversations from both the IDE *and* the CLI — easiest grep/export surface |
| `~/.cursor/chats/<md5>/<agentId>/{meta.json,store.db}` | Cursor CLI (`agent`/`cursor-agent`) sessions — separate from the global DB, no `composerData`/`bubbleId` rows exist for these. `meta.json` is a lightweight sidecar written as soon as the chat is created; `store.db` (the real transcript) only appears once a message is actually sent |
| `~/.cursor/plans/*.plan.md` | Plan-mode artifacts (markdown) |
| `~/.cursor/prompt_history.json` | Rolling array of recent prompts |

## Schema (quick reference)

Global DB, `cursorDiskKV` table (key/value):

- `composerData:<composerId>` — one row per conversation: `name`, `subtitle`, `createdAt`/`lastUpdatedAt` (epoch ms; **lastUpdatedAt is unreliable** — the last bubble's `createdAt` is the true recency signal), `unifiedMode` (`agent`|`chat`|`plan`|`edit`), `workspaceIdentifier.uri.fsPath` (project path, newer rows), and `fullConversationHeadersOnly[]` — the ordered message list: `{bubbleId, type}` (1=user, 2=assistant)
- `bubbleId:<composerId>:<bubbleId>` — one row per message: `text` (only on text turns), `type`, `createdAt` (ISO), `toolFormerData` (`{name, params, result, status}` — tool calls), `thinking.text` (reasoning), `codeBlocks`, `context` (file selections etc.)

**Iterate via headers, not raw bubble rows** — orphan bubbles from regenerated/deleted turns exist. Always open DBs read-only (`file:...?mode=ro`). In `sqlite3` shell arguments, escape JSON paths as `'\$.field'` so the shell doesn't mangle them.

All queries below assume:

```bash
GLOBAL_DB="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
```

## Resolve a partial composer ID

```bash
sqlite3 "file:$GLOBAL_DB?mode=ro" \
  "SELECT substr(key,14) FROM cursorDiskKV WHERE key LIKE 'composerData:5b86dd7b%' LIMIT 1;"
```

## List recent conversations

```bash
sqlite3 -separator ' | ' "file:$GLOBAL_DB?mode=ro" "
  SELECT datetime(json_extract(value,'\$.createdAt')/1000,'unixepoch','localtime'),
         substr(key,14,12),
         json_extract(value,'\$.unifiedMode'),
         coalesce(nullif(json_extract(value,'\$.name'),''), json_extract(value,'\$.subtitle'), '?'),
         coalesce(json_extract(value,'\$.workspaceIdentifier.uri.fsPath'), '')
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

## Search message text across all conversations

```bash
sqlite3 "file:$GLOBAL_DB?mode=ro" "
  SELECT key, json_extract(value,'\$.type'), substr(json_extract(value,'\$.text'),1,120)
  FROM cursorDiskKV
  WHERE key LIKE 'bubbleId:%' AND value LIKE '%SEARCH_TERM%'
  LIMIT 20;"
```

The `LIKE` on raw `value` prefilters cheaply and also matches `thinking` text and tool results; pull specific fields from the hits afterwards. The key embeds the composerId: `bubbleId:<composerId>:<bubbleId>`.

## List legacy (pre-3.0) conversations with workspace attribution

Conversations from before Cursor 3.0 lack `workspaceIdentifier`; their metadata lives in workspace DBs:

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

(Qualify `t.key` — `json_each` emits its own `key` column. Post-3.0 conversations never appear here; always check the global DB first.)

## Plaintext export (no SQLite at all)

```bash
jq -r '.role + ": " + (.message.content[0].text // "")' \
  ~/.cursor/projects/<slug>/agent-transcripts/<composerId>/<composerId>.jsonl
```

Content blocks can be `{"type":"text","text":"…"}` or `{"type":"tool_use","name":"…","input":{...}}`; a turn with only a tool call has no `content[0].text`, so this one-liner prints a blank line for it (add a `tool_use` fallback if you need those). Files end with a trailing `{"type":"turn_ended","status":"success"}` line.

## List recent Cursor CLI sessions

CLI (`agent`/`cursor-agent`) sessions don't have `composerData` rows — list them via the `meta.json` sidecar instead:

```bash
for f in ~/.cursor/chats/*/*/meta.json; do
  jq -r --arg d "$(dirname "$f")" '[(.updatedAtMs/1000|todate), .hasConversation, $d] | @tsv' "$f"
done | sort -r | head -20
```

Only covers sessions that have a `meta.json` (added in recent CLI versions — see [data-model.md](data-model.md#the-cursor-tree)); older sessions have `store.db` only, and its `meta` key must be hex-decoded (`SELECT value FROM meta` is a TEXT column holding hex, not a BLOB).

## Resume a session via the CLI

```bash
agent --resume <chatId> -p "prompt" --output-format json --force   # headless, by ID
agent --continue -p "prompt" --output-format json --force          # headless, latest for this workspace/cwd
agent resume                                                        # interactive: latest chat (needs a real TTY)
agent ls                                                             # interactive: pick from a list (needs a real TTY)
agent create-chat                                                    # register a new empty chat, print its ID
```

`resume`/`ls` render an Ink-based picker and fail (`Raw mode is not supported on the current process.stdin`) without a real TTY — only `--resume <chatId>` / `--continue` combined with `-p` are scriptable. Any of these need `--force` (or `--trust`/`--yolo`) once to clear the workspace-trust prompt in a non-interactive shell. `create-chat` only registers the ID server-side — nothing appears under `~/.cursor/chats/` until that ID is actually resumed/messaged, at which point `meta.json` + `store.db` are created together.

## Tips

- Tool-call turns have empty `text` — render `toolFormerData.name` instead. (`toolResults`/`suggestedCodeBlocks`/`assistantSuggestedDiffs` are still present as keys on ~99% of bubbles, but always empty arrays — dead fields, not a data source.)
- Map a composerId to its project via `workspaceIdentifier.uri.fsPath`, or by which `~/.cursor/projects/<slug>/agent-transcripts/` directory contains it — the latter also works for CLI-originated sessions, which have no `composerData`/`bubbleId` rows in the global DB at all.
- Cloud/background agents (`bc-*` IDs) keep almost nothing locally — transcripts are server-side.
- A conversation that shows "Chat Too Old" in the UI is still fully readable from the DB; only its server `conversationState` token is lost.
