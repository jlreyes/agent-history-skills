#!/usr/bin/env python3
"""Extract and explore Cursor IDE conversation history from local SQLite databases.

Data model (Cursor 3.x):
- Global DB: ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
  - cursorDiskKV "composerData:<id>" -> conversation metadata (name, timestamps,
    workspaceIdentifier) + ordered bubble list in fullConversationHeadersOnly[]
    (type 1 = user, type 2 = assistant)
  - cursorDiskKV "bubbleId:<composerId>:<bubbleId>" -> message content
    ($.text on text turns; $.toolFormerData on tool turns; $.thinking.text reasoning)
- Workspace DBs: .../workspaceStorage/<hash>/state.vscdb
  - ItemTable "composer.composerData" -> allComposers[] — LEGACY: pre-3.0 metadata
    only (stopped updating at the Cursor 3.0 cutover); used here to enrich old rows
  - workspace.json -> {"folder": ...} or {"workspace": ...} maps hash to project
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CURSOR_BASE = Path.home() / "Library" / "Application Support" / "Cursor" / "User"
GLOBAL_DB = CURSOR_BASE / "globalStorage" / "state.vscdb"
WORKSPACE_DIR = CURSOR_BASE / "workspaceStorage"

COMPOSER_META_PATHS = (
    "$.name", "$.subtitle", "$.unifiedMode", "$.createdAt", "$.lastUpdatedAt",
    "$.workspaceIdentifier.uri.fsPath", "$.isArchived",
    "$.totalLinesAdded", "$.totalLinesRemoved", "$.filesChangedCount",
    "$.contextUsagePercent",
)


def get_db_connection(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def load_legacy_workspace_meta() -> dict[str, dict]:
    """composerId -> metadata from pre-3.0 workspace DBs (allComposers)."""
    legacy: dict[str, dict] = {}
    if not WORKSPACE_DIR.exists():
        return legacy

    for ws_dir in WORKSPACE_DIR.iterdir():
        if not ws_dir.is_dir():
            continue

        workspace_path = ""
        ws_json = ws_dir / "workspace.json"
        if ws_json.exists():
            try:
                meta = json.loads(ws_json.read_text())
                workspace_path = (meta.get("folder") or meta.get("workspace") or "")
                workspace_path = workspace_path.replace("file://", "")
            except (json.JSONDecodeError, OSError):
                pass

        conn = get_db_connection(ws_dir / "state.vscdb")
        if not conn:
            continue
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
            ).fetchone()
            if not row:
                continue
            for c in json.loads(row[0]).get("allComposers", []):
                cid = c.get("composerId", "")
                if cid:
                    legacy[cid] = {
                        "name": c.get("name", ""),
                        "subtitle": c.get("subtitle", ""),
                        "mode": c.get("unifiedMode", ""),
                        "createdAt": c.get("createdAt", 0),
                        "updatedAt": c.get("lastUpdatedAt", 0),
                        "branch": c.get("createdOnBranch", c.get("committedToBranch", "")),
                        "workspace": workspace_path,
                    }
        except (json.JSONDecodeError, sqlite3.Error):
            pass
        finally:
            conn.close()
    return legacy


def list_conversations(
    limit: int = 50,
    workspace_filter: str | None = None,
    include_empty: bool = False,
) -> list[dict]:
    """List conversations from the global DB, enriched with legacy workspace metadata."""
    conn = get_db_connection(GLOBAL_DB)
    if not conn:
        print(f"Error: cannot open global DB at {GLOBAL_DB}", file=sys.stderr)
        return []

    paths = ", ".join(f"'{p}'" for p in COMPOSER_META_PATHS)
    try:
        rows = conn.execute(
            f"""
            SELECT substr(key, 14) AS cid,
                   json_extract(value, {paths}) AS meta,
                   json_array_length(value, '$.fullConversationHeadersOnly') AS msg_count
            FROM cursorDiskKV
            WHERE key LIKE 'composerData:%'
            """
        ).fetchall()
    except sqlite3.Error as e:
        print(f"Error querying global DB: {e}", file=sys.stderr)
        return []
    finally:
        conn.close()

    legacy = load_legacy_workspace_meta()

    results = []
    for row in rows:
        cid = row["cid"]
        msg_count = row["msg_count"] or 0
        if not include_empty and msg_count == 0:
            continue
        try:
            (name, subtitle, mode, created_at, updated_at, ws_path, is_archived,
             lines_added, lines_removed, files_changed, context_pct) = json.loads(row["meta"])
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        old = legacy.get(cid, {})
        name = name or old.get("name", "")
        subtitle = subtitle or old.get("subtitle", "")
        mode = mode or old.get("mode", "")
        workspace_path = ws_path or old.get("workspace", "")
        created_at = created_at or old.get("createdAt", 0) or 0
        # Blob lastUpdatedAt is often stale (= createdAt); take the best signal available
        updated_at = max(updated_at or 0, created_at, old.get("updatedAt", 0) or 0)

        if workspace_filter and workspace_filter.lower() not in (workspace_path or "").lower():
            continue

        results.append({
            "composerId": cid,
            "name": name,
            "subtitle": subtitle,
            "mode": mode,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "branch": old.get("branch", ""),
            "workspace": workspace_path or "",
            "workspaceShort": (workspace_path or "").rstrip("/").split("/")[-1],
            "messageCount": msg_count,
            "linesAdded": lines_added or 0,
            "linesRemoved": lines_removed or 0,
            "filesChanged": files_changed or 0,
            "isArchived": bool(is_archived),
            "contextUsagePercent": round(context_pct or 0, 1),
        })

    results.sort(key=lambda x: x["updatedAt"], reverse=True)
    return results[:limit]


def format_timestamp(ts: int) -> str:
    if not ts:
        return "unknown"
    ts_sec = ts / 1000 if ts > 1e12 else ts
    return datetime.fromtimestamp(ts_sec).strftime("%Y-%m-%d %H:%M")


def print_conversation_list(convos: list[dict], verbose: bool = False):
    for c in convos:
        dt = format_timestamp(c["updatedAt"])
        mode = (c["mode"] or "?")[:5]
        cid = c["composerId"][:12]
        title = c["name"] or c["subtitle"] or "(untitled)"
        ws = c["workspaceShort"]

        if verbose:
            print(f"{dt}  [{mode:5}]  {cid}  {title}")
            print(f"           workspace: {ws}  branch: {c['branch']}  msgs: {c['messageCount']}")
            print(f"           +{c['linesAdded']}/-{c['linesRemoved']}  {c['filesChanged']} files  ctx: {c['contextUsagePercent']}%")
            if c["isArchived"]:
                print("           (archived)")
            print()
        else:
            title_display = title[:55].ljust(55)
            print(f"{dt}  [{mode:5}]  {cid}  {title_display}  ({ws})")


def describe_bubble(bubble_data: dict, include_thinking: bool = False) -> dict:
    """Normalize a bubble row into {role, text, createdAt, tools?, thinking?}."""
    bubble_type = bubble_data.get("type", 0)
    msg = {
        "role": "user" if bubble_type == 1 else "assistant",
        "text": bubble_data.get("text", ""),
        "createdAt": bubble_data.get("createdAt", ""),
    }

    tools = []
    tfd = bubble_data.get("toolFormerData")
    if isinstance(tfd, dict) and tfd.get("name"):
        status = tfd.get("status", "")
        tools.append(f"{tfd['name']}{f' ({status})' if status else ''}")
    # Pre-3.0 bubbles stored tool calls in toolResults
    for tr in bubble_data.get("toolResults", []) or []:
        if isinstance(tr, dict) and tr.get("toolName"):
            tools.append(tr["toolName"])
    if tools:
        msg["tools"] = tools

    if include_thinking:
        thinking = (bubble_data.get("thinking") or {}).get("text", "")
        if thinking:
            msg["thinking"] = thinking

    return msg


def read_conversation(
    composer_id: str, max_messages: int = 0, include_thinking: bool = False
) -> list[dict]:
    """Read all messages from a conversation by composerId."""
    conn = get_db_connection(GLOBAL_DB)
    if not conn:
        print(f"Error: cannot open global DB at {GLOBAL_DB}", file=sys.stderr)
        return []

    try:
        row = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key = ?",
            (f"composerData:{composer_id}",),
        ).fetchone()
        if not row:
            print(f"Error: no composerData found for {composer_id}", file=sys.stderr)
            return []

        bubble_headers = json.loads(row[0]).get("fullConversationHeadersOnly", [])
        if not bubble_headers:
            print("No messages found in this conversation.", file=sys.stderr)
            return []

        messages = []
        for header in bubble_headers:
            bubble_id = header.get("bubbleId", "")
            bubble_row = conn.execute(
                "SELECT value FROM cursorDiskKV WHERE key = ?",
                (f"bubbleId:{composer_id}:{bubble_id}",),
            ).fetchone()
            if not bubble_row:
                continue

            msg = describe_bubble(json.loads(bubble_row[0]), include_thinking)
            msg["bubbleId"] = bubble_id
            messages.append(msg)

            if max_messages and len(messages) >= max_messages:
                break
        return messages

    except (json.JSONDecodeError, sqlite3.Error) as e:
        print(f"Error reading conversation: {e}", file=sys.stderr)
        return []
    finally:
        conn.close()


def print_transcript(messages: list[dict]):
    for msg in messages:
        header = f"--- {msg['role'].upper()}"
        if msg.get("createdAt"):
            header += f"  ({msg['createdAt']})"
        if msg.get("tools"):
            header += f"  [tools: {', '.join(msg['tools'])}]"
        header += " ---"

        print(header)
        if msg.get("thinking"):
            print(f"<thinking>\n{msg['thinking']}\n</thinking>")
        if msg.get("text"):
            print(msg["text"])
        elif not msg.get("tools"):
            print("(no text content)")
        print()


def search_messages(query: str, limit: int = 20) -> list[dict]:
    """Search message and thinking text across all conversations."""
    conn = get_db_connection(GLOBAL_DB)
    if not conn:
        print(f"Error: cannot open global DB at {GLOBAL_DB}", file=sys.stderr)
        return []

    try:
        cursor = conn.execute(
            """
            SELECT key, value FROM cursorDiskKV
            WHERE key LIKE 'bubbleId:%'
            AND value LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit * 3),  # over-fetch since we filter on JSON text
        )

        results = []
        for row in cursor:
            parts = row[0].split(":")
            if len(parts) != 3:
                continue

            try:
                data = json.loads(row[1])
            except json.JSONDecodeError:
                continue

            text = data.get("text", "")
            thinking = (data.get("thinking") or {}).get("text", "")
            haystack = text if query.lower() in text.lower() else thinking
            if query.lower() not in haystack.lower():
                continue

            idx = haystack.lower().find(query.lower())
            start = max(0, idx - 80)
            end = min(len(haystack), idx + len(query) + 80)
            snippet = haystack[start:end].replace("\n", " ")
            if start > 0:
                snippet = "..." + snippet
            if end < len(haystack):
                snippet = snippet + "..."

            results.append({
                "composerId": parts[1],
                "bubbleId": parts[2],
                "role": "user" if data.get("type") == 1 else "assistant",
                "createdAt": data.get("createdAt", ""),
                "matchedIn": "text" if haystack is text else "thinking",
                "snippet": snippet,
            })
            if len(results) >= limit:
                break
        return results

    except sqlite3.Error as e:
        print(f"Error searching: {e}", file=sys.stderr)
        return []
    finally:
        conn.close()


def print_search_results(results: list[dict]):
    for r in results:
        print(f"[{r['role']:9}]  composer:{r['composerId'][:12]}  {r.get('createdAt', '')}"
              + ("  (in thinking)" if r.get("matchedIn") == "thinking" else ""))
        print(f"  {r['snippet']}")
        print()


def find_composer_id(partial: str) -> str | None:
    """Resolve a partial composer ID to a full one."""
    conn = get_db_connection(GLOBAL_DB)
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT key FROM cursorDiskKV WHERE key LIKE ? AND key LIKE 'composerData:%' LIMIT 1",
            (f"composerData:{partial}%",),
        ).fetchone()
        return row[0].replace("composerData:", "") if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Explore Cursor IDE conversation history")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list
    list_parser = subparsers.add_parser("list", help="List recent conversations")
    list_parser.add_argument("-n", "--limit", type=int, default=50, help="Max results")
    list_parser.add_argument("-w", "--workspace", help="Filter by workspace path substring")
    list_parser.add_argument("-v", "--verbose", action="store_true", help="Show extra detail")
    list_parser.add_argument("--include-empty", action="store_true", help="Include empty/draft conversations")
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")

    # read
    read_parser = subparsers.add_parser("read", help="Read a conversation transcript")
    read_parser.add_argument("composer_id", help="Composer ID (full or partial)")
    read_parser.add_argument("-n", "--max-messages", type=int, default=0, help="Max messages (0=all)")
    read_parser.add_argument("--thinking", action="store_true", help="Include reasoning/thinking text")
    read_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")

    # search
    search_parser = subparsers.add_parser("search", help="Search message text")
    search_parser.add_argument("query", help="Text to search for")
    search_parser.add_argument("-n", "--limit", type=int, default=20, help="Max results")
    search_parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        convos = list_conversations(
            limit=args.limit,
            workspace_filter=args.workspace,
            include_empty=args.include_empty,
        )
        if args.as_json:
            print(json.dumps(convos, indent=2))
        else:
            print_conversation_list(convos, verbose=args.verbose)

    elif args.command == "read":
        composer_id = args.composer_id
        if len(composer_id) < 36:
            resolved = find_composer_id(composer_id)
            if not resolved:
                print(f"Error: no conversation found matching '{args.composer_id}'", file=sys.stderr)
                sys.exit(1)
            composer_id = resolved

        messages = read_conversation(
            composer_id, max_messages=args.max_messages, include_thinking=args.thinking
        )
        if args.as_json:
            print(json.dumps(messages, indent=2))
        else:
            print_transcript(messages)

    elif args.command == "search":
        results = search_messages(args.query, limit=args.limit)
        if args.as_json:
            print(json.dumps(results, indent=2))
        else:
            print_search_results(results)


if __name__ == "__main__":
    main()
