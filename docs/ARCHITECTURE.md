# Architecture

## Trust split

| Concern | Owner | Why |
|---|---|---|
| classify / extract / sub-score / draft | the agent (LLM) | judgment, tone, nuance |
| scoring math, tiers | `scripts/score.py` (pure) | reproducibility |
| sheet writes, dedupe, watermark, drafts on disk, injection flagging | `scripts/triage.py` | single writer, provable behavior |

The agent's analysis JSON is **input data**, never instructions to the
engine. The engine recomputes every derived value (score, tier, recipient,
status) from raw inputs.

## Data flow per scheduled tick

```
1. fetch      new inbound -> spool/<thread_id>.json   (ISO-8601 received, headers)
2. analyze    agent reads item + criteria.md, writes analysis/<thread_id>.json
3. apply      triage.py: validate -> derive action -> score -> sheet/draft -> watermark
4. report     reports/last.json; owner ping only on tier A / injection / error
```

## Action derivation (deterministic)

```
prompt_injection_detected        -> flag   (row status=flagged_injection, no draft, notify)
classification=lead              -> row    (+ draft if provided; status=drafted)
classification=unsure            -> row    tier ?, never dropped
classification=not_lead
  skip_reason in known set       -> skip   (no row, reported)
  skip_reason none/unknown       -> row    tier ? (never silently dropped)
```

Header-level auto-detect: a spool item carrying `List-Unsubscribe` or a
`no-reply@` sender is skipped even if the agent misclassified it.

## Idempotency, three layers

1. `state.json` processed index: applied thread_ids are skipped on re-run.
2. `sheet/leads.csv`: `thread_id` checked against existing rows before append.
3. Spool files move to `spool/processed/` only after `state.json` is saved
   (crash between the two still dedupes via layer 1).

The watermark (`state.json.watermark_ts`) is the max `received` of items
handled in a run; the fetch step uses it to select "newer than".

## Hard-flag cap

`score.py` caps the tier at C when a triggered flag matches the owner's
`hard_red_flags`, regardless of the numeric total and regardless of
classification. Numbers never promote a flagged lead.

## Path safety

`thread_id` comes from the spool **filename** (the blob's field is
untrusted) and must match `[A-Za-z0-9._-]{1,200}` before it is used in any
filesystem path (`analysis/`, `drafts/`).
