#!/usr/bin/env python3
"""score.py — deterministic weighted lead scoring.

Pure function. No I/O: given 0-100 sub-scores, weights, hard red-flags and a
classification, it returns a total, a tier, and the component math. No
network, no randomness, no LLM. Reproducibility is the whole point: the same
inputs always yield the same total/tier.

Sub-scores (0-100): fit, budget, urgency, clarity, source_trust.
Weights default to {fit:40, budget:25, urgency:15, clarity:10, source_trust:10}
(summing to 100); the owner's criteria.md `## config` block may override.

Tier bands: A >= a_min (default 75), B >= b_min (default 50), else C.
A hard red flag forces the tier to C regardless of the numeric total and
regardless of classification (a flagged lead is not promoted by numbers),
and is recorded in `overrides`. A non-"lead" classification forces tier "?".

Usage:
    python3 score.py '{"sub_scores":{"fit":80,"budget":60,...},"classification":"lead"}'
"""
from __future__ import annotations

import json
import math
import sys
from typing import Dict, List, Optional

DEFAULT_WEIGHTS = {"fit": 40, "budget": 25, "urgency": 15, "clarity": 10, "source_trust": 10}
SUB_KEYS = list(DEFAULT_WEIGHTS.keys())
DEFAULT_A_MIN = 75
DEFAULT_B_MIN = 50


def _finite_num(value, default: float) -> float:
    """Coerce to a finite float in [0, 100]; NaN/inf/None/str-garbage -> default."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return max(0.0, min(100.0, v))


def normalize_weights(weights: Optional[Dict[str, float]]) -> Dict[str, float]:
    """Merge owner weights over defaults; always cover all SUB_KEYS, sum to 100."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k in SUB_KEYS:
            v = weights.get(k)
            if v is not None:
                try:
                    vf = float(v)
                    if math.isfinite(vf) and vf >= 0:
                        w[k] = vf
                except (TypeError, ValueError):
                    pass
    total = sum(w.values())
    if total <= 0:
        # Fall back to defaults rather than divide by zero / a nonsense scale.
        return dict(DEFAULT_WEIGHTS)
    # Scale to exactly 100 so the weighted average is a true 0-100 score.
    scale = 100.0 / total
    return {k: v * scale for k, v in w.items()}


def compute_score(
    sub_scores: Dict[str, float],
    classification: str = "lead",
    weights: Optional[Dict[str, float]] = None,
    a_min: Optional[float] = None,
    b_min: Optional[float] = None,
    hard_red_flags: Optional[List[str]] = None,
    triggered_flags: Optional[List[str]] = None,
) -> Dict:
    """Return {total, tier, components, overrides, hard_flag_capped, ...}."""
    sub_scores = sub_scores or {}
    w = normalize_weights(weights)

    a_thr = _finite_num(a_min if a_min is not None else DEFAULT_A_MIN, DEFAULT_A_MIN)
    b_thr = _finite_num(b_min if b_min is not None else DEFAULT_B_MIN, DEFAULT_B_MIN)
    if a_thr < b_thr:
        a_thr, b_thr = b_thr, a_thr  # config typo guard: A band must sit above B

    components: Dict[str, Dict] = {}
    total = 0.0
    missing: List[str] = []
    for k in SUB_KEYS:
        if sub_scores.get(k) is None:
            missing.append(k)
        s = _finite_num(sub_scores.get(k), 0.0) if sub_scores.get(k) is not None else 0.0
        contribution = s * w[k] / 100.0
        total += contribution
        components[k] = {"score": round(s, 1), "weight": round(w[k], 1), "contribution": round(contribution, 2)}
    total = round(total, 1)

    triggered = [str(f).strip() for f in (triggered_flags or []) if str(f).strip()]
    hard = [str(f).strip() for f in (hard_red_flags or []) if str(f).strip()]
    hit = [f for f in triggered if f in hard]
    hard_flag_capped = bool(hit)

    overrides: List[str] = []
    if hard_flag_capped:
        # A hard red flag caps the tier to C no matter the numeric total or
        # classification — numbers must never promote a flagged lead.
        tier = "C"
        overrides.append("hard_red_flag_cap:" + ",".join(hit))
    elif classification != "lead":
        tier = "?"
        overrides.append("tier_forced_? ({})".format(classification))
    else:
        tier = "C" if total < b_thr else ("B" if total < a_thr else "A")

    return {
        "total": total,
        "tier": tier,
        "components": components,
        "overrides": overrides,
        "hard_flag_capped": hard_flag_capped,
        "triggered_flags": triggered,
        "missing_sub_scores": missing,
        "normalized_weights": {k: round(v, 1) for k, v in w.items()},
        "config": {"a_min": a_thr, "b_min": b_thr},
    }


if __name__ == "__main__":
    payload = {}
    if len(sys.argv) > 1:
        try:
            payload = json.loads(sys.argv[1])
            if not isinstance(payload, dict):
                payload = {}
        except json.JSONDecodeError:
            payload = {}
    out = compute_score(
        payload.get("sub_scores") or {},
        str(payload.get("classification", "lead")),
        payload.get("weights"),
        payload.get("a_min"),
        payload.get("b_min"),
        payload.get("hard_red_flags"),
        payload.get("triggered_flags"),
    )
    print(json.dumps(out, indent=2))
