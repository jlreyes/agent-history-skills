---
description: Re-verify all three agent-history skills against the currently-installed CLIs and real local history, then open one PR.
allowed-tools: Read, Edit, Write, Bash, WebFetch, WebSearch, Agent
---

# Refresh the agent-history skills

This repo documents where three coding agents store local conversation history
and how to read it. Each skill is a `SKILL.md` (recipes + quick reference) and a
`data-model.md` (full schema, verified against a specific CLI version and date),
plus a `references/` directory of archived historical schema snapshots — old
transcripts on disk don't retroactively upgrade, so superseded schemas stay
documented instead of being overwritten.

| Skill | Tool | CLI | Storage |
|---|---|---|---|
| `skills/exploring-claude-sessions` | Claude Code | `claude` | `~/.claude/` |
| `skills/exploring-codex-sessions` | OpenAI Codex CLI | `codex` | `~/.codex/` |
| `skills/exploring-cursor-history` | Cursor (IDE + CLI) | `agent` | `~/Library/Application Support/Cursor/`, `~/.cursor/`, `~/.config/cursor/` |

Run this on a machine with real history for all three tools and, ideally, the
Cursor **IDE** app installed — CI cannot verify the IDE's SQLite model at all,
and a bare runner has no real corpus to enumerate against.

## 1. Establish ground truth

Update each CLI to current, then record exact versions:

```bash
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
curl https://cursor.com/install -fsS | bash
claude --version; codex --version; agent --version
defaults read /Applications/Cursor.app/Contents/Info.plist CFBundleShortVersionString
```

Compare against `.github/tracked-versions.json` and against each skill's
"Verified against" line. Note which tools moved.

## 2. Fan out — one subagent per skill, in parallel

Spawn one subagent per skill **in a single message** so they run concurrently,
and **wait for all of them to return before doing anything else**. Do not
summarize the fan-out and end your turn — the run is not complete until every
subagent has reported back. (This is exactly how the retired CI job failed: it
announced three background subagents, ended its turn, and produced nothing.)

Each subagent is fully self-contained — it does not see this file, the repo's
history, or the other subagents. Give each one the tool it owns, the version
range in question, and the whole checklist below verbatim.

### Per-subagent checklist

1. Read that skill's current `SKILL.md`, `data-model.md`, and every file in
   `references/` in full, first. Know what is already claimed before looking at
   anything else.
2. Actually run the installed CLI — `--version`, `--help`, and `--help` on every
   subcommand related to sessions, history, resume, or export — and diff the real
   output against what the skill documents. Do not rely on memory or on training
   data about how the tool used to behave.
3. `ls -la` the tool's real storage directories and diff against the documented
   layout. Look for new files and directories, not just changed ones.
4. Enumerate **every** distinct entry type, event type, and field actually
   present in real local data — `jq -r '.type' … | sort -u` across the whole
   corpus, `.schema` on every table, grep for keys — and diff against the
   documented enums and field tables. Spot-checking two examples is not
   enumeration; a field that appears in 0.1% of records is exactly what gets
   missed.
5. Re-run **every** recipe in `SKILL.md` against real local data. Any recipe that
   errors, returns nothing, or produces wrong-looking output gets fixed and
   re-run until it passes.
6. Generate fresh, guaranteed-current data with a live headless run where you
   can: `codex exec "…"`, `agent -p "…" --output-format json --force`. For Claude
   Code, no credential is needed — you *are* Claude Code, so this session's own
   transcript under `~/.claude/projects/` is direct ground truth, readable
   mid-run. If a credential is missing, skip the live run, say so plainly, and
   fall back to `--help` and official docs rather than guessing at behavior you
   did not observe.
7. Cross-check the official docs and, where possible, the tool's real source,
   releases, and PR history for the specific version range since the skill was
   last verified — e.g. diff the relevant structs between release tags. Do not
   trust a changelog's prose summary as evidence of an on-disk shape.
8. Before overwriting `data-model.md`, decide which of two things this is:
   - **A genuine format change** — old files on disk really do use the old shape
     (a field or entry type was renamed, removed, or restructured). Copy the
     *current* `data-model.md` verbatim into
     `references/<tool-version-anchor>.md` first, matching the archival-banner
     template already used by the existing files in that directory, then update
     the live doc and its "older transcript?" pointer paragraph to reference the
     new archive.
   - **A pure documentation correction** — the old doc was simply wrong and never
     matched any real on-disk data. Fix in place; do not archive. An archive
     pointing at a shape nothing on disk uses is worse than no archive.
9. Update `SKILL.md` and `data-model.md` to match reality and bump the "Verified
   against / on" line. Keep the terse, source-verified, index-not-tutorial tone
   and the existing structure — do not restructure sections that are still
   accurate, and do not add speculative content you could not verify.
10. Report back: (a) what you corrected, with the evidence for each, (b) what you
    newly documented, (c) what you explicitly confirmed as still accurate and
    left alone, (d) anything you noticed but deliberately did not change, and
    why. Name the commands you actually ran so a reviewer can spot-check without
    redoing the work.

## 3. Land it

After every subagent has returned:

- Update `.github/tracked-versions.json` to the versions just verified.
- Open **one** PR covering whichever skills actually needed changes. Synthesize
  the subagents' reports into the description: what changed per skill, why, and
  what was run to prove it. Include reviewer spot-check commands.
- If a tool's version moved but its subagent found no real schema or behavior
  difference, leave that skill's files untouched and say so in the description
  rather than forcing a change.

## Notes

- The weekly `.github/workflows/check-upstream.yml` job only *detects* version
  drift and opens a tracking issue. It does not propose updates — that is what
  this command is for. An open "Upstream agent CLI versions changed" issue is
  the signal to run this.
- Prior refresh PRs are worth reading as prior art before starting, but treat
  their findings as claims to re-confirm against current data, not as facts.
