# Changelog

## 1.0.0 - 2026-10-02

First release.

- Deterministic engine: `triage.py apply` (dedupe, sheet, drafts, watermark,
  injection flagging) + pure `score.py` (weighted scoring, hard red-flag cap).
- Canonical skill for agents (`skills/inbox-lead-triage/SKILL.md`).
- Adapters: ZCode plugin + skill, Claude Code skill + plugin manifests +
  `/ilt-triage`, Antigravity `.agent` workflow, AGENTS.md snippet.
- Universal MCP server (7 tools, stdlib-only, stdio JSON-RPC).
- `.eml` ingest adapter; dry-run mode; 5-case end-to-end test + idempotency.
