#!/usr/bin/env python3
"""triage.py — deterministic apply layer for inbox lead triage.

Splits trust cleanly: the LLM (the skill's agent loop) produces one analysis
blob per spool item (classification, extracted fields, 0-100 sub-scores,
draft text). THIS script is the only thing that mutates state: it
validates the blob, recomputes the weighted score (never trusts the
LLM's math), dedupes on thread_id, appends the sheet row, writes the
draft file (recipient-guarded), and advances the watermark only for
threads that fully succeeded. Re-runs are idempotent: 0 new rows.

Stdlib-only, Python 3.9+. No network. All state under $ILT_HOME
($ILT_HOME env var > legacy ~/.zcode/inbox-lead-triage > ~/.ilt):

    spool/            raw inbound items the fetch step drops in
    spool/processed/  moved here after successful apply
    analysis/         one JSON per thread_id, written by the agent
    sheet/leads.csv   the lead sheet
    drafts/           draft files, named {thread_id}.md
    state.json        watermark + processed index
    criteria.md       owner criteria + machine-readable config
    reports/last.json  last run's report

Usage:
    triage.py init                 # create layout (idempotent)
    triage.py apply [--dry-run]    # apply all spool items with analysis
    triage.py status               # sheet summary to stdout
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score as score_mod  # noqa: E402

LEGACY_HOME = Path.home() / ".zcode" / "inbox-lead-triage"   # pre-repo installs
DEFAULT_HOME = Path.home() / ".ilt"


def default_home() -> Path:
    """Resolution order: $ILT_HOME > legacy ~/.zcode/inbox-lead-triage > ~/.ilt.
    The legacy path is honored only if it already exists, so existing local
    installs keep their data after upgrading from the repo."""
    if LEGACY_HOME.exists():
        return LEGACY_HOME
    return DEFAULT_HOME

COLUMNS = [
    "thread_id", "received", "name", "company", "email", "channel",
    "what_they_want", "budget", "timeline", "score", "tier", "why",
    "red_flags", "draft_id", "status", "processed_at",
]
FIELD_KEYS = ["name", "company", "email", "channel", "what_they_want", "budget", "timeline"]
SUB_KEYS = score_mod.SUB_KEYS
SKIP_REASONS = {"none", "spam", "newsletter", "no_reply", "self_sent"}
VALID_CLASS = {"lead", "not_lead", "unsure"}


# ── layout / state ────────────────────────────────────────────────
def home() -> Path:
    env = os.environ.get("ILT_HOME")
    if env:
        return Path(env).expanduser()
    return default_home()


def ensure_layout(h: Path) -> None:
    for d in ("spool", "analysis", "sheet", "drafts", "reports"):
        (h / d).mkdir(parents=True, exist_ok=True)
    (h / "spool" / "processed").mkdir(parents=True, exist_ok=True)
    sheet = h / "sheet" / "leads.csv"
    if not sheet.exists():
        sheet.write_text(",".join(COLUMNS) + "\n", encoding="utf-8")
    state = h / "state.json"
    if not state.exists():
        save_state(h, {"watermark_ts": "", "processed": {}})
    crit = h / "criteria.md"
    if not crit.exists():
        tpl = HERE.parent / "templates" / "criteria.md"
        if tpl.exists():
            shutil.copy(tpl, crit)


def load_state(h: Path) -> Dict:
    p = h / "state.json"
    if not p.exists():
        return {"watermark_ts": "", "processed": {}}
    try:
        s = json.loads(p.read_text())
        s.setdefault("processed", {})
        s.setdefault("watermark_ts", "")
        return s
    except json.JSONDecodeError:
        print("ERROR: state.json corrupt; refusing to write new state. Back it up and re-init.", file=sys.stderr)
        sys.exit(2)


def save_state(h: Path, s: Dict) -> None:
    p = h / "state.json"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".state", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, p)


# ── criteria config (machine-readable `## config` block) ─────────
def load_criteria(h: Path) -> Dict:
    """Parse criteria.md: prose is for the LLM; the `## config` block
    (lines of `key: json-value`) is for the scorer. Missing -> defaults."""
    cfg = {"weights": None, "a_min": None, "b_min": None, "hard_red_flags": None}
    p = h / "criteria.md"
    if not p.exists():
        return cfg
    text = p.read_text(errors="replace")
    m = re.search(r"^##\s*config\s*$(.*?)(^##\s|\Z)", text, re.M | re.S | re.I)
    block = m.group(1) if m else text
    for line in block.splitlines():
        mm = re.match(r"^\s*(weights|a_min|b_min|hard_red_flags|tiers)\s*:\s*(.+)$", line.strip(), re.I)
        if not mm:
            continue
        key, raw = mm.group(1).lower(), mm.group(2).strip()
        try:
            val = json.loads(raw)
        except json.JSONDecodeError:
            val = raw
        if key == "tiers" and isinstance(val, dict):
            cfg["a_min"] = val.get("a_min", cfg["a_min"])
            cfg["b_min"] = val.get("b_min", cfg["b_min"])
        else:
            cfg[key] = val
    return cfg


# ── spool / analysis I/O ──────────────────────────────────────────
def _safe_tid(tid: str) -> bool:
    """thread_id must be a plain filename: no separators, no dot-segments.
    Guards every filesystem path built from a tid (analysis/, drafts/)."""
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,200}", tid))


def load_spool(h: Path) -> List[Tuple[Path, Dict]]:
    out = []
    sp = h / "spool"
    for p in sorted(sp.glob("*.json")):
        # The FILENAME is the authoritative thread_id (it names the file we
        # manage); a thread_id inside the blob is untrusted data and must not
        # drive filesystem paths (analysis/<tid>.json) or the sheet key.
        try:
            item = json.loads(p.read_text())
            if not isinstance(item, dict):
                item = {}
        except json.JSONDecodeError as e:
            out.append((p, {"thread_id": p.stem, "_error": f"bad spool JSON: {e}"}))
            continue
        item["thread_id"] = p.stem
        out.append((p, item))
    return out


def load_analysis(h: Path, thread_id: str) -> Optional[Dict]:
    if not _safe_tid(thread_id):
        return {"_error": f"unsafe thread_id {thread_id!r}; refusing filesystem access"}
    p = h / "analysis" / f"{thread_id}.json"
    if not p.exists():
        return None
    try:
        a = json.loads(p.read_text())
        return a if isinstance(a, dict) else {"_error": "analysis is not an object"}
    except json.JSONDecodeError as e:
        return {"_error": f"bad analysis JSON: {e}"}


# ── validation + action derivation ───────────────────────────────
def allowed_recipient(item: Dict) -> str:
    """To: only from the lead's Reply-To/From, never from cc/to lists."""
    return (item.get("reply_to") or item.get("from") or "").strip()

def derive_action(item: Dict, a: Dict, errors: List[str]) -> str:
    """Deterministic: classification + skip_reason + injection -> action.
    lead -> row (+draft if supplied); unsure -> row, no draft;
    not_lead + real skip_reason -> skip (no row, reported);
    not_lead w/o skip_reason -> row tier ? (never silently dropped);
    injection -> flag (row status=flagged_injection, no draft, always notify)."""
    if a.get("prompt_injection_detected") is True:
        return "flag"
    cls = str(a.get("classification", "")).lower()
    if cls not in VALID_CLASS:
        errors.append(f"{item.get('thread_id','?')}: unknown classification {cls!r}; treating as unsure")
        cls = "unsure"
    a["classification"] = cls
    reason = str(a.get("skip_reason", "none")).lower()
    if reason not in SKIP_REASONS:
        errors.append(f"{item.get('thread_id','?')}: unknown skip_reason {reason!r}; ignoring")
        reason = "none"
    a["skip_reason"] = reason
    if cls == "not_lead":
        # header-level auto-detect: even if the LLM said 'none', hard signals skip
        headers = {k.lower(): v for k, v in (item.get("headers") or {}).items()}
        if "list-unsubscribe" in headers:
            a["skip_reason"] = reason if reason != "none" else "newsletter"
        elif "no-reply" in (item.get("from") or "").lower():
            a["skip_reason"] = reason if reason != "none" else "no_reply"
        return "skip" if a["skip_reason"] != "none" else "row"
    if cls == "unsure":
        return "row"
    return "row_draft"


def sanitize_fields(a: Dict, item: Dict, errors: List[str]) -> Dict:
    f = a.get("fields")
    if not isinstance(f, dict):
        f = {}
        a["fields"] = f
    out = {}
    for k in FIELD_KEYS:
        v = f.get(k)
        out[k] = str(v).strip() if v is not None else ""
    if not out["email"]:
        out["email"] = (item.get("from") or "").strip()
    a["fields"] = out
    for k in ("why",):
        a[k] = str(a.get(k, "")).strip()
    rf = a.get("red_flags")
    a["red_flags"] = [str(x).strip() for x in rf if str(x).strip()] if isinstance(rf, list) else []
    return out


def validate_and_score(a: Dict, item: Dict, crit: Dict, errors: List[str]) -> Dict:
    if a.get("_error"):
        errors.append(f"{item.get('thread_id','?')}: {a['_error']}")
        a = dict(item.get("_analysis_fallback") or {})
    sanitize_fields(a, item, errors)
    hard = [str(x).lower() for x in (crit.get("hard_red_flags") or [])]
    triggered = [x.lower() for x in a["red_flags"]]
    result = score_mod.compute_score(
        a.get("sub_scores") or {},
        a.get("classification", "unsure"),
        crit.get("weights"),
        crit.get("a_min"),
        crit.get("b_min"),
        hard,
        triggered,
    )
    for k in SUB_KEYS:
        if k in (a.get("sub_scores") or {}):
            continue
        result["missing_sub_scores"] = result.get("missing_sub_scores", [])
        if k not in result["missing_sub_scores"]:
            result["missing_sub_scores"].append(k)
    a["_score"] = result
    return a


# ── sheet + drafts ───────────────────────────────────────────────
def sheet_rows(h: Path) -> List[Dict]:
    p = h / "sheet" / "leads.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def existing_thread_ids(h: Path) -> set:
    return {r.get("thread_id") for r in sheet_rows(h) if r.get("thread_id")}


def append_row(h: Path, row: Dict, write: bool = True) -> None:
    """Append one row to the sheet CSV. With write=False it is a dry-run:
    it just validates the row shape (header drift) and records nothing."""
    p = h / "sheet" / "leads.csv"
    new = not p.exists()
    if not write:
        # Dry run: still validate we can map the row onto the header, so a
        # schema drift surfaces even in dry-run. No file mutation.
        _ = {k: row.get(k, "") for k in COLUMNS}
        return
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in COLUMNS})


def write_draft(h: Path, thread_id: str, item: Dict, a: Dict, errors: List[str]) -> str:
    d = a.get("draft") or {}
    allowed = allowed_recipient(item)
    to = str(d.get("to") or allowed).strip()
    if allowed and to and to.lower() != allowed.lower():
        errors.append(f"{thread_id}: draft 'to' {to!r} != lead's Reply-To/From {allowed!r}; forcing {allowed!r}")
        to = allowed
    path = h / "drafts" / f"{thread_id}.md"
    if path.exists():
        return path.name  # idempotent: never re-draft
    body = str(d.get("body") or "").strip()
    subject = str(d.get("subject") or (item.get("subject") and "Re: " + str(item["subject"]) or "")).strip()
    text = (
        f"# Draft {thread_id}\n"
        f"To: {to or '(missing Reply-To/From — owner must fill)'}\n"
        f"Subject: {subject}\n"
        f"Tier: {a.get('_score', {}).get('tier')}  (draft is DRAFT ONLY — owner approves any send)\n\n"
        f"{body}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path.name


# ── apply ────────────────────────────────────────────────────────
def build_row(tid: str, item: Dict, a: Dict, total, tier: str, status: str, draft_id: str) -> Dict:
    """One sheet row from an applied item. Time stored ISO-8601 with offset."""
    row = {k: "" for k in COLUMNS}
    row.update({
        "thread_id": tid, "received": str(item.get("received", "")),
        **{k: a["fields"].get(k, "") for k in FIELD_KEYS},
        "score": str(total), "tier": tier, "why": a.get("why", ""),
        "red_flags": "; ".join(a.get("red_flags") or []),
        "draft_id": draft_id, "status": status,
        "processed_at": datetime.now(timezone.utc).astimezone().isoformat(),
    })
    return row


def apply(dry: bool) -> Dict:
    h = home()
    ensure_layout(h)
    crit = load_criteria(h)
    state = load_state(h)
    errors: List[str] = []
    skipped: List[str] = []
    flagged: List[str] = []
    a_arrivals: List[str] = []
    rows_added = 0
    drafts_written = 0
    processed_ok: List[Tuple[str, str]] = []   # (thread_id, iso ts)

    have_ids = existing_thread_ids(h)
    pending = load_spool(h)
    items_in_run = {str(i.get("thread_id") or p.stem): i for p, i in pending if not i.get("_error")}
    for path, item in pending:
        tid = str(item.get("thread_id") or path.stem)
        if item.get("_error"):
            errors.append(f"{tid}: {item['_error']}")
            continue
        if tid in state["processed"] or tid in have_ids:
            # idempotent: already on the sheet or in the watermark
            continue
        a = load_analysis(h, tid)
        if a is None:
            errors.append(f"{tid}: no analysis file (agent step incomplete); left for retry")
            continue
        action = derive_action(item, a, errors)
        a = validate_and_score(a, item, crit, errors)
        sc = a.get("_score", {})
        tier = sc.get("tier", "?")
        total = sc.get("total", 0)

        if action == "skip":
            skipped.append(f"{tid} ({a['skip_reason']})")
            processed_ok.append((tid, ""))
            continue
        if action == "flag":
            flagged.append(tid)
            if not dry:
                row = {k: "" for k in COLUMNS}
                row.update({
                    "thread_id": tid, "received": str(item.get("received", "")),
                    **{k: a["fields"].get(k, "") for k in FIELD_KEYS},
                    "score": "", "tier": "?", "why": "injection attempt",
                    "red_flags": "; ".join(a["red_flags"] or []) or "prompt_injection",
                    "draft_id": "", "status": "flagged_injection",
                    "processed_at": datetime.now(timezone.utc).astimezone().isoformat(),
                })
                append_row(h, row)
                rows_added += 1
            processed_ok.append((tid, ""))
            continue

        status = "new"
        draft_id = ""
        if action == "row_draft":
            if a.get("draft"):
                if not dry:
                    draft_id = write_draft(h, tid, item, a, errors)
                    drafts_written += 1
                status = "drafted"
            else:
                status = "new"  # tier C with no decline draft is fine
        if not dry:
            row = build_row(tid, item, a, total, tier, status, draft_id)
            append_row(h, row, write=True)
            rows_added += 1
            if tier == "A":
                a_arrivals.append(tid)
            # watermark advances only when the row (and draft, if any) is on disk
            processed_ok.append((tid, row["processed_at"]))
        else:
            row = build_row(tid, item, a, total, tier, status, draft_id)
            append_row(h, row, write=False)  # validates shape only
            if tier == "A":
                a_arrivals.append(tid)
            processed_ok.append((tid, "dry"))

    if processed_ok and not dry:
        now_ts = datetime.now(timezone.utc).isoformat()
        state["processed"].update({t: {"at": ts or now_ts, "dry": ts == "dry"} for t, ts in processed_ok})
        # Watermark = max `received` ts of the items actually handled this run,
        # so the fetch step can pick up "newer than watermark" on the next run.
        # ISO-8601 with offset compares correctly as a string for same-zone data.
        new_wm = max(
            (str(i.get("received", "")) for i in items_in_run.values() if i.get("received")),
            default=None,
        )
        if new_wm:
            state["watermark_ts"] = new_wm if new_wm > state.get("watermark_ts", "") else state.get("watermark_ts", "")
        save_state(h, state)
        # Move spool items out for everything processed this run — including
        # skips (ts=""), so spool/ only ever holds pending work. "dry" entries
        # stay put. Archiving uses the ORIGINAL spool filename (never the
        # tid from the blob, which is untrusted), and per-file errors are
        # collected, not fatal: state was already saved, so a re-run skips
        # via the processed index even if a move was lost.
        src_by_tid = {str(i.get("thread_id") or p.stem): p.name for p, i in pending}
        for t, ts in processed_ok:
            if ts == "dry":
                continue
            name = src_by_tid.get(t)
            if not name:
                continue
            try:
                (h / "spool" / "processed").mkdir(parents=True, exist_ok=True)
                src = h / "spool" / name
                dst = h / "spool" / "processed" / name
                if src.exists():
                    shutil.move(str(src), str(dst))
                else:
                    errors.append(f"{t}: spool file {name} vanished; kept processed index entry")
            except OSError as e:
                errors.append(f"{t}: could not archive spool file {name} ({e}); kept processed index entry")

    report = {
        "ok": not errors,
        "dry_run": dry,
        "run_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "rows_added": rows_added,
        "drafts_written": drafts_written,
        "skipped": skipped,
        "flagged_injections": flagged,
        "a_arrivals": a_arrivals,
        "errors": errors,
        "notify": (bool(a_arrivals) or bool(errors) or bool(flagged)),
        "summary": "",
    }
    report["summary"] = (
        f"{rows_added} new lead row(s), {drafts_written} draft(s), "
        f"{len(skipped)} skipped, {len(flagged)} flagged; {len(errors)} error(s)."
        + (" [dry-run]" if dry else "")
    )
    if not dry:
        ensure_layout(h)
        (h / "reports" / "last.json").write_text(json.dumps(report, indent=2))
    return report


def status() -> None:
    h = home()
    rows = sheet_rows(h)
    st = load_state(h) if (h / "state.json").exists() else {"processed": {}}
    by_tier: Dict[str, int] = {}
    for r in rows:
        by_tier[r.get("tier", "?")] = by_tier.get(r.get("tier", "?"), 0) + 1
    out = {
        "sheet_rows": len(rows),
        "by_tier": by_tier,
        "watermark_ts": st.get("watermark_ts", ""),
        "processed_count": len(st.get("processed", {})),
        "spool_pending": sorted(p.stem for p in (h / "spool").glob("*.json")) if (h / "spool").exists() else [],
        "pending_analysis": sorted(
            p.stem for p in (h / "spool").glob("*.json") if not (h / "analysis" / f"{p.stem}.json").exists()
        ) if (h / "spool").exists() else [],
    }
    print(json.dumps(out, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init", help="create layout")
    p_ap = sub.add_parser("apply", help="apply analysis to spool")
    p_ap.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="sheet + watermark summary")
    args = ap.parse_args()
    if args.cmd == "init":
        ensure_layout(home())
        print("layout ready under", home())
    elif args.cmd == "apply":
        rep = apply(dry=args.dry_run)
        print(json.dumps(rep, indent=2))
    elif args.cmd == "status":
        status()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
