#!/usr/bin/env python3
"""Hour-by-hour Twitch viewer forecast for a launch day (GTA VI, 2026-11-19).

Reads every case file in the input directory (schema makefun/twitch-ccu-case/v1)
and writes one forecast per case to the output directory:
{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]} ...]} for hours 2..24.

Method (no network, no model, stdlib only, fully deterministic):
  * Anchor: the case's own hour-1 print p.
  * Shape pool: every comparable past launch whose release day (UTC) has all
    24 hourly viewer counts, expressed as log-ratios to its own hour 1.
  * Similarity: keep the launches whose hour-1 size is close to p in log
    space (within 1.75; widened to 2.5, then to all, if fewer than 6 remain).
    Launch-day shape depends strongly on scale: tiny hour-1 counts belong to
    games that explode later (100-2000x), while big launches ramp ~2-3x to a
    late-day peak. Mixing them wrecks the forecast.
  * Quantiles: per hour, the empirical 5/25/50/75/95 percentiles of the
    pool's log-ratios (linear interpolation). Empirical quantiles capture the
    right skew of launch-day ramps better than a symmetric normal spread.
  * Smoothing: a 3-hour centred moving average of the log-quantiles, because
    a real audience curve is smooth hour to hour and per-hour empirical
    quantiles from ~20 launches are noisy.
  * Fallback: if no comparable is usable at all, fall back to a flat median
    with a widening spread (the house baseline's shape).
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
HOURS = range(2, 25)
MIN_POOL = 6
LOG_WINDOW = 1.75
LOG_WINDOW_WIDE = 2.5


def parse_time(text):
    """Parse an ISO-8601 UTC timestamp into an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def release_day(by_hours, day_start):
    """Map a comparable's hourly points to {hour 1..24: viewers} of its
    release day (the UTC day starting at day_start). Returns {} unless all
    24 hours are present with positive counts."""
    out = {}
    end = day_start + timedelta(days=1)
    for point in by_hours:
        try:
            when = parse_time(point["from"])
            viewers = point["viewers"]
        except (KeyError, TypeError, ValueError):
            continue
        if not (day_start <= when < end):
            continue
        hour = int((when - day_start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24 and hour not in out:
            out[hour] = viewers
    if len(out) != 24:
        return {}
    if any(v is None or v <= 0 for v in out.values()):
        return {}
    return out


def log_ratios(day):
    """Log viewers of each hour relative to hour 1."""
    base = math.log(day[1])
    return {h: math.log(day[h]) - base for h in range(1, 25)}


def empirical_quantiles(sorted_vals, levels):
    """Linear-interpolation quantiles of an already sorted list."""
    n = len(sorted_vals)
    out = []
    for level in levels:
        if n == 1:
            out.append(sorted_vals[0])
            continue
        pos = level * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        out.append(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)
    return out


def pick_pool(curves, anchor_log):
    """Curves whose hour-1 size is near the anchor in log space.
    curves: list of (h1_log, {hour: log-ratio}). Widen until >= MIN_POOL."""
    for window in (LOG_WINDOW, LOG_WINDOW_WIDE, None):
        if window is None:
            return curves
        near = [c for c in curves if abs(c[0] - anchor_log) <= window]
        if len(near) >= MIN_POOL:
            return near
    return curves


def shape_quantiles(pool, hours):
    """Per-hour empirical log-ratio quantiles for the requested hours."""
    rows = {}
    for hour in hours:
        vals = sorted(c[1][hour] for c in pool)
        rows[hour] = empirical_quantiles(vals, LEVELS)
    return rows


def smooth(rows, hours):
    """3-hour centred moving average of the log-quantiles, per level.
    Keeps the curve smooth; per-hour empirical quantiles are noisy.
    Edge hours average over the neighbours they have."""
    hour_set = set(hours)
    out = {}
    for hour in hours:
        neighbours = [h for h in (hour - 1, hour, hour + 1) if h in hour_set]
        out[hour] = [
            sum(rows[h][k] for h in neighbours) / len(neighbours)
            for k in range(len(LEVELS))
        ]
    return out


def baseline_rows(anchor, hours):
    """Fallback shape: flat median, spread widening like the house baseline."""
    rows = {}
    z = (-1.6448536269514722, -0.6744897501960817, 0.0,
         0.6744897501960817, 1.6448536269514722)
    for hour in hours:
        spread = 0.15 * math.sqrt(hour - 1)
        rows[hour] = [z[k] * spread for k in range(len(LEVELS))]
    return rows


def forecast_case(case):
    """Return the forecast rows {hour: [q05..q95]} for one case.
    The hours come from the case's own forecast list (2..24 in this
    competition); the 2..24 default only fills in a case that lists none."""
    want = sorted({r["hour"] for r in case.get("forecast") or []
                   if isinstance(r, dict) and isinstance(r.get("hour"), int)})
    if len(want) != 23:
        want = list(HOURS)
    known = case.get("known") or []
    if isinstance(known, dict):
        known = [known]
    hour_one = None
    for row in known:
        if row.get("hour") == 1:
            hour_one = row
            break
    if hour_one is None and known:
        hour_one = known[0]
    anchor = 1.0
    if hour_one is not None:
        try:
            anchor = float(hour_one.get("viewers") or 0)
        except (TypeError, ValueError):
            anchor = 1.0
    if anchor < 1.0:
        anchor = 1.0

    curves = []
    for comp in case.get("comparables") or []:
        try:
            day_start = parse_time(comp["day_start"])
            day = release_day(comp.get("hourly") or [], day_start)
        except (KeyError, TypeError, ValueError):
            continue
        if not day:
            continue
        curves.append((math.log(day[1]), log_ratios(day)))

    if curves:
        pool = pick_pool(curves, math.log(anchor))
        rows = smooth(shape_quantiles(pool, want), want)
    else:
        rows = baseline_rows(anchor, want)

    out = {}
    for hour in want:
        qs = []
        running = 0.0
        for k in range(len(LEVELS)):
            value = anchor * math.exp(rows[hour][k])
            if value < 0.01:
                value = 0.01
            if value > 1e9:
                value = 1e9
            value = round(value, 2)
            if value < running:
                value = running
            if value < 0.01:
                value = 0.01
            running = value
            qs.append(value)
        out[hour] = qs
    return out


def run_case(path, out_dir):
    with open(path, "r", encoding="utf-8") as handle:
        case = json.load(handle)
    case_id = case.get("id") or os.path.splitext(os.path.basename(path))[0]
    rows = forecast_case(case)
    payload = {"hours": [{"hour": h, "q": rows[h]} for h in sorted(rows)]}
    out_path = os.path.join(out_dir, case_id + ".out")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.write("\n")
    return case_id, out_path


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(in_dir) if n.endswith(".in"))
    if not names:
        sys.stderr.write("no .in case files in %s\n" % in_dir)
        return 1
    for name in names:
        case_id, out_path = run_case(os.path.join(in_dir, name), out_dir)
        sys.stderr.write("forecast %s -> %s\n" % (case_id, out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
