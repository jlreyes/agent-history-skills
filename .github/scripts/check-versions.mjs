// Compares the locally-installed Claude Code / Codex / Cursor CLI versions
// (installed by the workflow steps just before this runs) against
// .github/tracked-versions.json and reports drift via $GITHUB_OUTPUT.
// Read-only: does not write the state file or commit anything, and does not
// edit any skill content — see README.md "Staying current" for why (a
// human, via the opened issue, or the propose-update job, does that).

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const STATE_PATH = fileURLToPath(new URL("../tracked-versions.json", import.meta.url));

const LABELS = {
  claude_code_version: "Claude Code CLI",
  codex_cli_version: "Codex CLI",
  cursor_agent_version: "Cursor CLI (agent)",
};

function readVersion(cmd, args) {
  try {
    return execFileSync(cmd, args, { encoding: "utf8" }).trim();
  } catch (err) {
    console.error(`Failed to read version via \`${cmd} ${args.join(" ")}\`: ${err.message}`);
    return null;
  }
}

const previous = JSON.parse(readFileSync(STATE_PATH, "utf8"));

// Raw examples this parsing expects:
//   claude --version -> "2.1.197 (Claude Code)"
//   codex --version  -> "codex-cli 0.142.4"
//   agent --version  -> "2026.06.29-2ad2186"
const rawClaude = readVersion("claude", ["--version"]);
const rawCodex = readVersion("codex", ["--version"]);
const rawCursor = readVersion("agent", ["--version"]);

const current = {
  claude_code_version: rawClaude?.split(" ")[0] ?? previous.claude_code_version,
  codex_cli_version: rawCodex?.split(" ").pop() ?? previous.codex_cli_version,
  cursor_agent_version: rawCursor ?? previous.cursor_agent_version,
};

const changedKeys = Object.keys(current).filter((k) => current[k] !== previous[k]);

const summaryLines = changedKeys.map(
  (k) => `- **${LABELS[k] ?? k}**: \`${previous[k] ?? "(none)"}\` → \`${current[k]}\``,
);
const summary = summaryLines.join("\n");

console.log(changedKeys.length > 0 ? `Drift detected:\n${summary}` : "No drift.");

const outPath = process.env.GITHUB_OUTPUT;
if (outPath) {
  const lines = [`drift=${changedKeys.length > 0}`, "summary<<__SUMMARY_EOF__", summary, "__SUMMARY_EOF__"];
  writeFileSync(outPath, lines.join("\n") + "\n", { flag: "a" });
}
