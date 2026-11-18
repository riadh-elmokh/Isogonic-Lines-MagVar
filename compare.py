"""Compare given isogonic lines / declination values with the magnetic models.
No QGIS imports."""
import math
import re

import numpy as np

from . import wmm

MAX_POINTS = 400


def parse_declination(value):
    """Declination in decimal degrees, east positive, from a number or text
    such as '2.5', '-2.5', '2.5E', "2\u00b030'W", '2 30 W', 'W 2.5'. None if unreadable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return None if math.isnan(v) else v
    text = str(value).strip().upper().replace(",", ".")
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not nums:
        return None
    parts = [float(n) for n in nums[:3]]
    deg = parts[0] + (parts[1] / 60.0 if len(parts) > 1 else 0.0) \
        + (parts[2] / 3600.0 if len(parts) > 2 else 0.0)
    west = "W" in text or text.startswith("-")
    return -deg if west else deg


def _wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def _subsample(lat, lon, given, group):
    n = len(lat)
    if n <= MAX_POINTS:
        return lat, lon, given, group
    idx = np.linspace(0, n - 1, MAX_POINTS).astype(int)
    return lat[idx], lon[idx], given[idx], group[idx]


def diffs(lat, lon, given, year, model, alt_km=0.0):
    """model minus given, degrees."""
    return _wrap(wmm.declination(lat, lon, year, alt_km, model) - given)


def candidates():
    """(model key, year) pairs to try."""
    out = []
    for key, m in wmm.MODELS.items():
        lo, hi = m["range"]
        step = 0.25 if m["kind"] == "wmm" else 0.5
        y = lo
        while y <= hi + 1e-9:
            if m["kind"] == "wmm" and y >= hi:
                break
            out.append((key, round(y, 3)))
            y += step
    return out


def best_fit(lat, lon, given, group=None, alt_km=0.0, is_canceled=None):
    """Rank every (model, date) by RMS difference to the given values."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    given = np.asarray(given, float)
    grp = np.zeros(len(lat), int) if group is None else np.asarray(group)
    lat, lon, given, grp = _subsample(lat, lon, given, grp)
    res = []
    for key, year in candidates():
        if is_canceled and is_canceled():
            return []
        d = diffs(lat, lon, given, year, key, alt_km)
        bias = float(np.mean(d))
        res.append({"model": key, "year": year,
                    "rms": float(np.sqrt(np.mean(d ** 2))),
                    "bias": bias,
                    "rms_nobias": float(np.sqrt(np.mean((d - bias) ** 2))),
                    "max": float(np.max(np.abs(d)))})
    res.sort(key=lambda r: r["rms"])
    return res


def per_group(lat, lon, given, group, year, model, alt_km=0.0):
    """Mean / max difference for each group (line)."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    given = np.asarray(given, float)
    group = np.asarray(group)
    d = diffs(lat, lon, given, year, model, alt_km)
    rows = []
    for g in sorted(set(group.tolist())):
        sel = group == g
        rows.append({"group": g, "given": float(np.mean(given[sel])),
                     "n": int(sel.sum()), "mean_diff": float(np.mean(d[sel])),
                     "max_diff": float(np.max(np.abs(d[sel])))})
    return rows


def report(res, current, lines_info=None):
    """Plain-text report. res: best_fit() result; current: dict for the
    model/date selected in the dialog."""
    if not res:
        return "No result."
    b = res[0]
    out = []
    out.append("Your lines vs the magnetic models (difference = model - your value):")
    out.append("")
    out.append("Selected now: %s at %.2f -> RMS %.3f deg, average offset %+.3f deg, worst %.3f deg"
               % (current["model"], current["year"], current["rms"], current["bias"], current["max"]))
    out.append("")
    out.append("Best matches:")
    seen = 0
    for r in res:
        out.append("  %-10s %.2f   RMS %.3f deg   offset %+.3f   worst %.3f"
                   % (r["model"], r["year"], r["rms"], r["bias"], r["max"]))
        seen += 1
        if seen >= 6:
            break
    out.append("")
    if b["rms"] < 0.1:
        out.append("Very good fit: your lines were drawn with %s for the date %.2f." % (b["model"], b["year"]))
    elif b["rms"] < 0.3:
        out.append("Good fit: close to %s at %.2f (the difference is smaller than the rounding "
                   "usually seen on charts)." % (b["model"], b["year"]))
    elif b["rms_nobias"] < 0.15:
        out.append("The shape fits %s at %.2f, but your lines are shifted by %+.2f deg on average. "
                   "A constant shift usually means a different date (annual change applied) or a "
                   "different model. Check the chart's stated epoch." % (b["model"], b["year"], -b["bias"]))
    else:
        out.append("No model fits well (best RMS %.2f deg). The lines may come from another model, "
                   "be hand-drawn or generalised, or the declination values in the field may be "
                   "wrong. Ask the client which model and date they used." % b["rms"])
    if lines_info:
        out.append("")
        out.append("Per line at the best match (%s %.2f):" % (b["model"], b["year"]))
        for r in lines_info:
            out.append("  line %s: given %.2f deg, difference %+.3f deg (worst %.3f), %d points"
                       % (r["group"], r["given"], r["mean_diff"], r["max_diff"], r["n"]))
    return "\n".join(out)
