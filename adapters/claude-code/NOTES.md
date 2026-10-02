## Platform notes (Claude Code)

- Install target: `~/.claude/skills/inbox-lead-triage/` (personal skill) or
  or as a plugin: the manifests live at the repo root (`.claude-plugin/`);
  run `/plugin marketplace add romangalaxys10-spec/inbox-lead-triage`.
- Skill name/description frontmatter is already in Claude Code's format;
  the body above works as written; `<skill>` is the installed skill dir.
- Slash command: `/ilt-triage` (bundled under `commands/`) runs one tick.
- Scheduling: Claude Code has no built-in cron; use launchd/cron to run
  `claude -p "run the inbox-lead-triage skill"` on business-hours cadence,
  or drive it via the MCP server from any scheduler.
- Fetch route: same as the core engine (.eml via `ingest.py`, a Gmail MCP server, or
  manual paste). The engine never needs mailbox credentials.
