# Security and trust model

## What the agent can and cannot do

The LLM running the skill writes **analysis JSON**. It cannot write the
sheet, drafts, spool state, or watermark directly except by going through
`triage.py`, which validates and re-derives everything. Prompt-level
compliance ("never send") is backed by a mechanical one: the engine has no
send path at all.

## Untrusted email bodies

Email bodies are data. Instructions inside them (override criteria, change
recipients, approve drafts, wire money) must be flagged by the agent via
`prompt_injection_detected: true`; the engine then forces a
`flagged_injection` row with no draft and pings the owner. Bodies are never
forwarded outside the owner's own sheet and drafts.

Known limits: the agent's injection detector is probabilistic. The
recipient guard and draft-only guarantee hold even if it misses an
injection, because compliance would require an engine feature that does
not exist.

## Recipient guard

Draft `To:` is forced to the item's `Reply-To` (or `From`). A mismatch is
overridden and logged as an error in `reports/last.json`.

## Path safety

`thread_id` is taken from the spool filename, not the JSON, and must match
`[A-Za-z0-9._-]{1,200}` before any path is built from it. Untrusted JSON
cannot traverse `analysis/` or `drafts/`.

## Credentials

The engine stores none. Mailbox auth lives in whatever connector the owner
chooses (a mail MCP client's OAuth, or plain `.eml` exports with no auth at
all). Criteria files may contain business-sensitive text; keep `$ILT_HOME`
outside any repo you publish, and never commit real lead data: the test
suite uses synthetic fixtures only.

## Dry-run first

`triage.py apply --dry-run` performs the whole pipeline (validation,
scoring, action derivation) with zero writes. Review it before live mode.

## Failure behavior

- Missing analysis: item stays in spool, error reported, retried next tick.
- Corrupt `state.json`: the run aborts without writing (fail closed).
- Connector auth expiry: stop and report; no retry loops.
