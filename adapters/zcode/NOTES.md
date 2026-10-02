## Platform notes (ZCode)

- Install target: `~/.zcode/skills/inbox-lead-triage/` (user-level skill) or
  the bundled plugin via the repo's `marketplace.json`.
- The skill body above works as written; `<skill>` is
  `~/.zcode/skills/inbox-lead-triage`.
- Slash command: `/inbox-lead-triage` (bundled under `commands/`) runs one
  triage tick interactively.
- Scheduling: create a ZCode cron automation whose prompt is
  "run the inbox-lead-triage skill" (weekdays, every 30-60 min, business
  hours). ZCode CronCreate keeps it running unattended.
- Fetch route: if a mail MCP server is configured, its search/get-thread
  tools feed the spool; otherwise `skills/inbox-lead-triage/scripts/ingest.py` accepts .eml
  exports, or items are pasted in by hand.
