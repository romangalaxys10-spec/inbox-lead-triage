# Connectors (getting mail into the spool)

The engine never opens a mailbox. Something drops standard spool items into
`$ILT_HOME/spool/<thread_id>.json`:

```json
{
  "thread_id": "t-real",
  "received": "2026-10-01T09:12:00+03:00",
  "from": "d.miller@acme.io",
  "reply_to": "d.miller@acme.io",
  "subject": "Automation for our lead follow-up",
  "body": "...",
  "headers": {"list-unsubscribe": "<...>"},
  "channel": "email"
}
```

`thread_id` must match `[A-Za-z0-9._-]{1,200}` (it becomes a filename).
`received` must be ISO-8601 with offset.

## Route 1: .eml files (works everywhere, zero credentials)

Mail clients export `.eml`. Save new messages into a folder and convert:

```bash
python3 skills/inbox-lead-triage/scripts/ingest.py ~/Mail/new/lead1.eml
cat lead2.eml | python3 skills/inbox-lead-triage/scripts/ingest.py --stdin
```

The parser derives `thread_id` from the Message-ID (sha1 fallback), `received`
from the Date header, and keeps `List-Unsubscribe` for skip detection. A tiny
launchd/cron/watcher loop over an export folder makes this fully automatic.

## Route 2: mail MCP server

If your agent platform has a Gmail/mail MCP configured, the scheduled tick's
prompt tells the agent to search threads newer than
`state.json.watermark_ts`, inbound only, skipping own-sent / newsletters /
no-reply, and write spool JSON per the schema. The engine stays
credential-free; the MCP client holds its own OAuth.

## Route 3: manual paste

Drop hand-written JSON into `spool/`. Fine for trying it out; the sheet and
drafts behave identically.

## Scheduling per platform

| Platform | Mechanism |
|---|---|
| ZCode | cron automation (CronCreate), prompt: "run the inbox-lead-triage skill" |
| Claude Code | launchd/cron running `claude -p "run the inbox-lead-triage skill"`, or any MCP scheduler |
| Antigravity | scheduled actions invoking the installed `.agent` workflow |
| MCP-only clients | your scheduler calls the MCP client, or cron pipes JSON-RPC into `mcp/server.py` |

Cadence: every 30-60 minutes inside business hours is the reference setup.

## Draft delivery

Drafts are `.md` files in `$ILT_HOME/drafts/`. The owner reads them and
sends from their own mail client. Wiring draft creation into a mailbox via
API is deliberately out of scope: it would need mail credentials in the
loop, and "draft only" is the strongest guarantee when the draft never
leaves the disk until a human touches it.
