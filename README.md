# inbox-lead-triage

Scheduled lead-triage engine for coding agents. An agent scans an inbox for
new inbound leads, extracts who wants what, scores the lead against the
owner's own criteria with a reproducible formula, fills a lead sheet, and
drafts a reply. **Drafts are never sent.** The owner approves every reply.

Works on ZCode, Claude Code, Antigravity, and any MCP client. Plain
AGENTS.md instructions cover everything else.

## The design in one paragraph

Two trust layers. The agent layer (an LLM) does judgment work: classify the
thread (lead / not lead / unsure), extract fields, assign 0-100 sub-scores
with a one-line reason each, and write a draft in the owner's tone. The
deterministic layer (plain Python) owns everything that must be provable:
it validates the agent's JSON, recomputes the weighted score (the agent
cannot fudge the math), dedupes on `thread_id`, appends the sheet row,
writes the draft file with a recipient guard, advances the watermark, and
flags prompt injection instead of obeying it. Re-runs add zero rows.

```
 inbox (.eml / mail MCP / manual)         agent (LLM judgment)
        │                                        │
        ▼                                        ▼
  spool/<thread_id>.json  ──read──▶  analysis/<thread_id>.json
        │                                        │
        └──────────────▶ triage.py apply ◀───────┘
                          (deterministic)
                                 │
        ┌────────────┬───────────┼──────────────┐
        ▼            ▼           ▼              ▼
   leads.csv    drafts/*.md  state.json   reports/last.json
   (sheet)     (never sent)  (watermark)  (owner report)
```

## Install

```bash
git clone https://github.com/romangalaxys10-spec/inbox-lead-triage.git
cd inbox-lead-triage
./install.sh --all          # zcode + claude (add ANTIGRAVITY_PROJECT=dir for antigravity)
python3 skills/inbox-lead-triage/tests/run_tests.py   # self-check
```

| Platform | Command | What you get |
|---|---|---|
| ZCode | `./install.sh --zcode` | user skill + plugin `marketplace.json` |
| Claude Code | `./install.sh --claude` | user skill + `/ilt-triage` command + plugin manifests |
| Antigravity | `ANTIGRAVITY_PROJECT=dir ./install.sh --antigravity` | `.agent/workflows/inbox-lead-triage.md` |
| Any MCP client | config below | 7 typed tools, no prompt conventions |
| Anything else | `./install.sh --agents-md` | AGENTS.md block with the whole loop |

### MCP (universal path)

Point any MCP-speaking client at the bundled stdio server:

```json
{ "mcpServers": { "inbox-lead-triage": {
    "command": "python3",
    "args": ["/path/to/inbox-lead-triage/mcp/server.py"] } } }
```

Tools: `ilt_init`, `ilt_status`, `ilt_new_items`, `ilt_save_analysis`,
`ilt_apply` (dry-run by default), `ilt_score`, `ilt_ingest_eml`. The client
agent loops: `ilt_new_items` → reason per item → `ilt_save_analysis` →
`ilt_apply`. Same engine, same guarantees, no skill-format needed.

## First run (once, with the owner)

1. `python3 skills/inbox-lead-triage/scripts/triage.py init`
2. Fill `$ILT_HOME/criteria.md` (`~/.ilt/criteria.md`, or the legacy
   `~/.zcode/inbox-lead-triage/` if it exists): offer, ideal client, min
   budget, red flags, tone. The `## config` block feeds the scorer.
3. Feed mail: save messages as `.eml` and run
   `python3 skills/inbox-lead-triage/scripts/ingest.py msg.eml`, wire a mail
   MCP server, or paste items into `spool/`. Format spec is in SKILL.md.
4. Dry run: let your agent analyze the spool, then
   `triage.py apply --dry-run`. Review `reports/last.json` and
   `sheet/leads.csv` together before going live.
5. Schedule the tick on business hours (30-60 min cadence): a ZCode cron
   automation, launchd/cron invoking `claude -p`, or Antigravity scheduled
   actions. The prompt is one line: "run the inbox-lead-triage skill".

## Scoring

`scripts/score.py` is a pure function. Weighted total over five sub-scores
(fit 40, budget 25, urgency 15, clarity 10, source_trust 10 by default;
owner's `criteria.md` overrides). Tier A >= 75, B 50-74, C < 50, `?` for
unsure. Any hard red flag (exposure, free work, no budget...) caps the tier
at C regardless of the total. Same inputs, same output, every time.

## Safety model

- Drafts are files. Nothing sends, auto-replies, or archives mail.
- Email bodies are untrusted data. Injection attempts become
  `flagged_injection` rows plus an owner notification, never compliance.
- Draft recipients are forced to the lead's `Reply-To`/`From`.
- `thread_id` (the spool filename) is format-checked; untrusted JSON inside
  a spool item cannot drive filesystem paths.
- Watermark advances only after the sheet row is durable, so failures retry.
- No mailbox credentials are stored or needed by the engine. See
  [docs/SECURITY.md](docs/SECURITY.md).

## Repo layout

```
skills/inbox-lead-triage/    canonical skill (SKILL.md, scripts, tests)
  scripts/triage.py            deterministic apply layer
  scripts/score.py             pure weighted scorer
  scripts/ingest.py            .eml -> spool adapter
  tests/run_tests.py           5 seed cases + idempotency check
commands/                     slash commands (ilt-triage, inbox-lead-triage)
adapters/                     per-platform NOTES + manifests (zcode, claude-code,
                              antigravity, agents-md)
mcp/server.py                 universal MCP server (stdlib only)
install.sh                    assembles platform installs from one source
docs/                         architecture, connectors, security
examples/                     filled criteria + sample sheet output
```

## Verification

```bash
make test        # 5 seed cases: real lead -> A + draft, vague -> low tier row,
                 # spam/newsletter skipped, injection flagged, re-run adds 0 rows
make mcp-smoke   # JSON-RPC handshake + tools/list
```

## Sources

Pattern from Grace Leung's Google AI Pro ad short (09-NEO0IUxg): a Gemini
"lead filter skill" plus a scheduled task. That UI flow was never observed;
claims are from the narration and are treated as inspiration, not spec.

## License

MIT
