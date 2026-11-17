"""GTA VI launch-day Twitch CCU forecast (gta6-twitch-ccu-forecast-01).

Method: an ensemble of two scale-conditioned views of how past big launches
unfolded over their release day, both fitted on the case's own `comparables`.

The dominant structure in the comparable launches is that a launch's shape
depends on how big it already is at the first print: the (log) peak-to-hour-0
ratio correlates about -0.94 with (log) hour-0 viewers. Small launches ramp
several-fold through the day as regions unlock and word spreads; the biggest
launches are already near their peak at the first print and mostly dip, then
recover into the evening. So every forecast is conditioned on the case's
hour-1 print p1, and works in log-ratios to p1.

Component A -- neighbourhood: the 15 comparables whose hour-0 print is
closest to p1 in log space; per forecast hour, the mean and spread of their
log-ratios give Normal quantiles.

Component B -- trend: per forecast hour, an ordinary least-squares fit of
log-ratio on log hour-0 across comparables with hour-0 >= 10,000 (the tiny
pre-unlock prints of simultaneous-global launches are excluded, they would
drag the fit), evaluated at log p1; the residual spread gives Normal
quantiles. This extrapolates smoothly when p1 exceeds every comparable,
which is the expected regime for GTA VI.

The two components are averaged 50/50 in log space (geometric mean of the
quantile forecasts). Their spreads are shrunk by 0.65: the raw neighbour /
residual spread overstates the true conditional spread, because it mixes
genuine shape variation with scale mismatch inside the neighbourhood, and
the unshrunk intervals over-cover on every practice case. Forecast hours
13..24 get a small +0.05 log lift: GTA VI unlocks at midnight local, so the
Americas are still dark at hour 1 and join through the morning, which lifts
the afternoon and evening above what the (partly simultaneous-unlock)
comparable pool implies on its own.

Fallbacks keep the output valid no matter what the case carries: if no
comparable yields a usable release-day curve, the forecast is persistence
(the house starter shape); a regression hour with too few points falls back
to the neighbourhood quantiles. Every row is clamped to (0, 1e9], rounded
half-up to 2 decimals, and forced non-decreasing.

Runs offline on the standard library only: python3 main.py reads every
<id>.in under $MAKEFUN_INPUT_DIR (default /input) and writes <id>.out under
$MAKEFUN_OUTPUT_DIR (default /output).
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# Quantile levels the contest scores, in row order.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at those levels.
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Neighbourhood size for component A.
K_NEIGHBOURS = 15
# Minimum hour-0 print for a comparable to enter the component B fit.
P0_MIN_FIT = 10_000
# Blend weight of component B (regression) in the log-space average.
W_REGRESSION = 0.5
# Spread shrinkage: raw neighbour / residual spreads overstate the
# conditional spread (see module docstring).
SIGMA_SCALE = 0.65
SIGMA_FLOOR = 0.25
SIGMA_CAP = 1.2
# Log lift for the afternoon/evening hours (Americas unlock after hour 1).
EVENING_LIFT = 0.05
EVENING_FROM_HOUR = 13
# Persistence fallback spread (house starter), log units per sqrt hour.
FALLBACK_SIGMA = 0.15


def parse_ts(text):
    """'2026-11-19T00:00:00Z' -> epoch seconds (UTC)."""
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc).timestamp())


def release_day_curve(hourly, day_start):
    """{hour 0..23: viewers} for the UTC release day, from an hourly series."""
    start = parse_ts(day_start)
    curve = {}
    for point in hourly:
        viewers = point.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        hour = (parse_ts(point["from"]) - start) // 3600
        if 0 <= hour < 24:
            curve[hour] = viewers
    return curve


def comparable_curves(case):
    """Usable (hour-0 print, release-day curve) pairs from the comparables.

    A comparable is usable when its release day has an hour-0 print and at
    least 12 hourly points. The GTA VI category's own pre-release series is
    dropped automatically: its hourly data starts at 17:00Z, so it has no
    hour 0.
    """
    out = []
    for comp in case.get("comparables") or []:
        curve = release_day_curve(comp.get("hourly") or [], comp["day_start"])
        if 0 in curve and len(curve) >= 12:
            out.append((curve[0], curve))
    return out


def fit_line(xs, ys):
    """OLS y ~ a + b*x; returns (a, b, residual std)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return my, 0.0, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    var = sum(r * r for r in resid) / max(1, n - 2)
    return a, b, math.sqrt(var)


def clamp_sigma(raw):
    return min(SIGMA_CAP, max(SIGMA_FLOOR, raw)) * SIGMA_SCALE


def neighbourhood_quantiles(neighbours, hour):
    """Component A: Normal quantiles from the k nearest comparables' log-ratios."""
    values = [math.log(curve[hour] / p0)
              for p0, curve in neighbours if hour in curve]
    if not values:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
    sigma = clamp_sigma(math.sqrt(var))
    return [mean + z * sigma for z in Z]


def trend_quantiles(fit_points, hour, log_p1):
    """Component B: Normal quantiles from the per-hour OLS trend in log p0."""
    pts = [(math.log(p0), math.log(curve[hour] / p0))
           for p0, curve in fit_points if hour in curve]
    if len(pts) < 8:
        return None
    a, b, resid = fit_line([p[0] for p in pts], [p[1] for p in pts])
    mean = a + b * log_p1
    return [mean + z * clamp_sigma(resid) for z in Z]


def persistence_quantiles(hour):
    """Fallback: the house starter shape (flat in expectation, widening spread)."""
    return [z * FALLBACK_SIGMA * math.sqrt(hour - 1) for z in Z]


def hour1_print(case):
    """The case's hour-1 print (the anchor), or None if the case carries none."""
    known = case.get("known") or []
    first = next((k for k in known if k.get("hour") == 1), None)
    if first is None and known:
        first = known[-1]
    if first is None:
        return None
    return max(1, first["viewers"])


def persistence_forecast(p1, hours):
    """Flat-in-expectation fallback rows (the house starter shape)."""
    rows = {}
    for hour in hours:
        qs = [p1 * math.exp(z * FALLBACK_SIGMA * math.sqrt(hour - 1)) for z in Z]
        rows[hour] = [min(max(v, 0.01), 1e9) for v in qs]
    return rows


def forecast_case(case):
    """{forecast hour 2..24: [q05, q25, q50, q75, q95]} in viewers."""
    p1 = hour1_print(case)
    if p1 is None:
        raise ValueError("case has no known hour-1 print")
    log_p1 = math.log(p1)

    comps = comparable_curves(case)
    neighbours = sorted(comps, key=lambda pc: abs(math.log(pc[0]) - log_p1))[:K_NEIGHBOURS]
    fit_points = [pc for pc in comps if pc[0] >= P0_MIN_FIT]

    hours = [row["hour"] for row in case.get("forecast") or []]
    if not hours:
        hours = list(range(2, 25))
    out = {}
    for hour in hours:
        # The case's hour h is the comparables' release-day hour h-1: the
        # case's hour-1 print is the comparables' hour-0 print.
        day_hour = hour - 1
        qa = neighbourhood_quantiles(neighbours, day_hour)
        qb = trend_quantiles(fit_points, day_hour, log_p1)
        if qa is None and qb is None:
            qs = persistence_quantiles(hour)
        elif qb is None:
            qs = qa
        elif qa is None:
            qs = qb
        else:
            qs = [(1 - W_REGRESSION) * x + W_REGRESSION * y for x, y in zip(qa, qb)]
        if hour >= EVENING_FROM_HOUR:
            qs = [q + EVENING_LIFT for q in qs]
        row = []
        for q in qs:
            value = p1 * math.exp(q)
            value = min(max(value, 0.01), 1e9)
            row.append(value)
        for i in range(1, 5):
            row[i] = max(row[i], row[i - 1])
        out[hour] = row
    return out


def round_half_up(x):
    """x rounded to 2 decimals, half up (whole numbers come back as ints)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("levels") != LEVELS:
            raise ValueError(f"{path.name} asks for levels {case.get('levels')}, not {LEVELS}")
        hours = [row["hour"] for row in case.get("forecast") or []]
        if not hours:
            hours = list(range(2, 25))
        try:
            forecast = forecast_case(case)
        except Exception:
            # Never lose the whole entry to one odd case: fall back to the
            # persistence shape around the hour-1 print, which is always a
            # valid forecast (and the house baseline's score).
            p1 = hour1_print(case)
            if p1 is None:
                raise
            forecast = persistence_forecast(p1, hours)
        rows = [{"hour": h, "q": [round_half_up(v) for v in forecast[h]]}
                for h in sorted(forecast)]
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps({"hours": rows}, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
