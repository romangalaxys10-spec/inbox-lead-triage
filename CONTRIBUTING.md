# Contributing

- Run `make test` and `make mcp-smoke` before opening a PR. CI runs the same
  on Python 3.9-3.12.
- Keep the trust split: agent output is data; `scripts/triage.py` is the only
  writer of sheet, drafts, spool state, and watermark. New features that
  require judgment belong in the analysis JSON schema, not in the engine.
- New platform adapter = one `adapters/<name>/NOTES.md` (and a manifest if
  the platform has a plugin format) + a line in the README matrix and
  install.sh. No engine changes.
- Stdlib only in `scripts/` and `mcp/`. No credentials in code, tests, or
  fixtures.
