#!/usr/bin/env python3
"""ingest.py — fetch-adapter helper: turn a raw .eml file into a spool item.

The core engine never talks to a mailbox itself; *something* must drop
standard spool JSON into $ILT_HOME/spool/. This script is the smallest
useful adapter: parse an RFC-822 .eml (file or stdin) with the stdlib
email module and write the spool item. Mail clients export .eml; IMAP
pipelines can save messages in .eml; that makes "any mailbox" one
`save as` / fetch loop away from the engine.

Usage:
    python3 ingest.py path/to/message.eml
    cat message.eml | python3 ingest.py --stdin
    python3 ingest.py msg.eml --thread-id my-id --out /tmp/item.json

Derivation rules (deterministic):
    thread_id  --thread-id, else sha1(message-id | from+date+subject)[:12]
    received   Date header, ISO-8601 with offset (naive dates -> UTC)
    reply_to   Reply-To header, else From
    headers    list-unsubscribe / list-id kept for skip detection
    body       first text/plain part, else text/html with tags stripped
"""
from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage as triage_mod  # noqa: E402  (for home()/layout/_safe_tid)


def _decode_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.is_multipart():
                return part.get_content()
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not part.is_multipart():
                return re.sub(r"<[^>]+>", " ", part.get_content())
        return ""
    payload = msg.get_content() if hasattr(msg, "get_content") else ""
    return re.sub(r"<[^>]+>", " ", payload) if msg.get_content_type() == "text/html" else payload


def _addr(header_value: Optional[str]) -> str:
    if not header_value:
        return ""
    from email.header import decode_header, make_header
    try:
        display = str(make_header(decode_header(header_value)))
    except Exception:
        display = header_value
    m = re.search(r"<([^>]+)>", display)
    return (m.group(1) if m else display).strip()


def _received(msg: email.message.Message) -> str:
    raw = msg.get("Date")
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def derive_thread_id(msg: email.message.Message) -> str:
    mid = msg.get("Message-ID") or ""
    basis = mid or "|".join([msg.get("From", ""), msg.get("Date", ""), msg.get("Subject", "")])
    tid = hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:12]
    return tid


def to_spool_item(msg: email.message.Message, thread_id: str) -> Dict:
    reply_to = _addr(msg.get("Reply-To")) or _addr(msg.get("From"))
    headers = {}
    for h in ("List-Unsubscribe", "List-Id"):
        if msg.get(h):
            headers[h.lower()] = msg.get(h)
    return {
        "thread_id": thread_id,
        "received": _received(msg),
        "from": _addr(msg.get("From")),
        "reply_to": reply_to,
        "subject": str(msg.get("Subject", "")),
        "body": _decode_body(msg).strip(),
        "headers": headers,
        "channel": "email",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("eml", nargs="?", help="path to .eml file (omit with --stdin)")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--thread-id", default=None)
    ap.add_argument("--out", default=None, help="write JSON here instead of $ILT_HOME/spool/")
    args = ap.parse_args()

    if args.stdin:
        raw = sys.stdin.read()
    elif args.eml:
        raw = Path(args.eml).read_text(errors="replace")
    else:
        ap.error("give an .eml path or --stdin")

    msg = email.message_from_string(raw, policy=email.policy.default)
    tid = args.thread_id or derive_thread_id(msg)
    if not triage_mod._safe_tid(tid):
        print(f"ERROR: derived/unsafe thread_id {tid!r}", file=sys.stderr)
        return 2
    item = to_spool_item(msg, tid)

    out = Path(args.out) if args.out else triage_mod.home() / "spool" / f"{tid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(item, indent=2))
    print(json.dumps({"written": str(out), "thread_id": tid,
                      "received": item["received"], "from": item["from"],
                      "subject": item["subject"],
                      "newsletter": "list-unsubscribe" in item["headers"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
