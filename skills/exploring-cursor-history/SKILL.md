---
name: exploring-cursor-history
description: Finds and explores Cursor IDE conversation history stored locally in SQLite databases and plaintext agent transcripts. Use when the user asks to find, search, read, or export a Cursor chat session, agent conversation, composer thread, or transcript.
compatibility: Requires sqlite3 CLI and python3. macOS only (paths are macOS-specific).
allowed-tools: Bash(sqlite3 *) Bash(python3 *) Bash(jq *)
metadata:
  author: jlreyes
---

# Exploring Cursor History

Cursor stores conversations in SQLite databases (`state.vscdb`), with the **global DB as the single source of truth** — workspace DBs only hold legacy metadata (pre-3.0). IDE agent sessions are also mirrored as plaintext JSONL under `~/.cursor/projects/`.

## Storage locations (macOS)

| Path | What it holds |
|------|---------------|
| `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` | All conversation content + metadata (`cursorDiskKV` table). Can be ~1 GB |
| `~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/state.vscdb` | Legacy per-workspace conversation metadata (stopped updating at Cursor 3.0); `workspace.json` sibling maps hash → folder (`folder` or `workspace` key) |
| `~/.cursor/projects/<path-slug>/agent-transcripts/<composerId>/<composerId>.jsonl` | **Plaintext JSONL mirror** of IDE agent conversations — easiest grep/export surface |
| `~/.cursor/chats/<md5>/<agentId>/store.db` | Cursor CLI (`cursor-agent`) sessions |
| `~/.cursor/plans/*.plan.md` | Plan-mode artifacts (markdown) |
| `~/.cursor/prompt_history.json` | Rolling array of recent prompts |

Full schema, key families, and the legacy (pre-3.0) model: [data-model.md](data-model.md).

## Schema (quick reference)

Global DB, `cursorDiskKV` table (key/value):

- `composerData:<composerId>` — one row per conversation: `name`, `subtitle`, `createdAt`/`lastUpdatedAt` (epoch ms; **lastUpdatedAt is unreliable** — use the last bubble's `createdAt` for true recency), `unifiedMode` (`agent`|`chat`|`plan`|`edit`), `workspaceIdentifier.uri.fsPath` (project path, newer rows), and `fullConversationHeadersOnly[]` — the ordered message list: `{bubbleId, type}` (1=user, 2=assistant)
- `bubbleId:<composerId>:<bubbleId>` — one row per message: `text` (only on text turns), `type`, `createdAt` (ISO), `toolFormerData` (`{name, params, result, status}` — tool calls), `thinking.text` (reasoning), `codeBlocks`, `context` (file selections etc.)

**Iterate via headers, not raw bubble rows** — orphan bubbles from regenerated/deleted turns exist. Always open DBs read-only (`file:...?mode=ro`).

## Helper script (preferred)

[scripts/cursor_history.py](scripts/cursor_history.py) handles current + legacy layouts, partial IDs, and tool/thinking rendering:

```bash
python3 scripts/cursor_history.py list -n 30 [-w workspace-filter] [-v] [--json]
python3 scripts/cursor_history.py read <composerId-or-prefix> [--thinking] [--json]
python3 scripts/cursor_history.py search "query" [-n 20] [--json]
```

## Raw queries

### List recent conversations (Cursor 3.x)

```bash
GLOBAL_DB="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
sqlite3 "file:$GLOBAL_DB?mode=ro" "
  SELECT json_extract(value,'\$.createdAt'),
         substr(key,14,12),
         json_extract(value,'\$.unifiedMode'),
         coalesce(json_extract(value,'\$.name'), json_extract(value,'\$.subtitle'), ''),
         json_extract(value,'\$.workspaceIdentifier.uri.fsPath')
  FROM cursorDiskKV
  WHERE key LIKE 'composerData:%'
    AND json_array_length(value,'\$.fullConversationHeadersOnly') > 0
  ORDER BY 1 DESC LIMIT 30;"
```

(The old approach — looping workspace DBs' `composer.composerData` → `allComposers[]` — only sees pre-3.0 conversations; use it solely for old history. The helper script merges both.)

### Read a conversation transcript

```bash
CID="<composerId>"
sqlite3 "file:$GLOBAL_DB?mode=ro" \
  "SELECT value FROM cursorDiskKV WHERE key='composerData:$CID';" | \
  python3 -c "
import sys,json
for b in json.loads(sys.stdin.read()).get('fullConversationHeadersOnly',[]):
    print(f\"{b['bubbleId']}|{b['type']}\")" | \
while IFS='|' read -r bid btype; do
  role=$( [ "$btype" = "1" ] && echo "USER" || echo "ASSISTANT" )
  sqlite3 "file:$GLOBAL_DB?mode=ro" "
    SELECT coalesce(nullif(json_extract(value,'\$.text'),''),
           '[tool] ' || json_extract(value,'\$.toolFormerData.name') ||
           ' (' || coalesce(json_extract(value,'\$.toolFormerData.status'),'?') || ')')
    FROM cursorDiskKV WHERE key='bubbleId:$CID:$bid';" | sed "1s/^/--- $role --- /"
done
```

### Search message text across all conversations

```bash
sqlite3 "file:$GLOBAL_DB?mode=ro" "
  SELECT key, json_extract(value,'$.type'), substr(json_extract(value,'$.text'),1,120)
  FROM cursorDiskKV
  WHERE key LIKE 'bubbleId:%' AND value LIKE '%SEARCH_TERM%'
  LIMIT 20;"
```

The `LIKE` on raw `value` prefilters cheaply (also matches `thinking` text); parse JSON only on hits.

### Plaintext export (no SQLite at all)

```bash
jq -r '.role + ": " + (.message.content[0].text // "")' \
  ~/.cursor/projects/<slug>/agent-transcripts/<composerId>/<composerId>.jsonl
```

## Tips

- Partial composer IDs work: `WHERE key LIKE 'composerData:5b86dd7b%'`.
- Tool-call turns have empty `text` — render `toolFormerData.name` instead (the legacy `toolResults` field no longer exists).
- Map a composerId to its project via `workspaceIdentifier.uri.fsPath`, or by which `~/.cursor/projects/<slug>/agent-transcripts/` directory contains it.
- Cloud/background agents (`bc-*` IDs) keep almost nothing locally — transcripts are server-side.
- A conversation that shows "Chat Too Old" in the UI is still fully readable from the DB; only its server `conversationState` token is lost.
