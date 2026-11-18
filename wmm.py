"""Geomagnetic field models in plain Python + numpy. No QGIS imports.

Models: NOAA/NCEI World Magnetic Model WMM2010, 2015v2, 2020, 2025 (public domain)
and IGRF-14 (IAGA, 1900-2030, linear interpolation between 5-year epochs).
Positive declination = east.
"""
import math
import os
from datetime import date, datetime

import numpy as np

A = 6378.137                    # WGS84 semi-major axis, km
F = 1.0 / 298.257223563
E2 = F * (2.0 - F)
RE = 6371.2                     # geomagnetic reference radius, km
MAX_LAT = 89.99                 # declination is undefined at the poles

# key -> file, kind, valid range, label
MODELS = {
    "WMM2025": {"file": "WMM_2025.COF", "kind": "wmm", "range": (2025.0, 2030.0),
                "label": "WMM2025 (2025-2030)"},
    "WMMHR2025": {"file": "WMMHR_2025.COF", "kind": "wmm", "range": (2025.0, 2030.0),
                  "label": "WMMHR2025 high resolution (2025-2030)"},
    "WMM2020": {"file": "WMM_2020.COF", "kind": "wmm", "range": (2020.0, 2025.0),
                "label": "WMM2020 (2020-2025)"},
    "WMM2015v2": {"file": "WMM_2015v2.COF", "kind": "wmm", "range": (2015.0, 2020.0),
                  "label": "WMM2015v2 (2015-2020)"},
    "WMM2010": {"file": "WMM_2010.COF", "kind": "wmm", "range": (2010.0, 2015.0),
                "label": "WMM2010 (2010-2015)"},
    "IGRF14": {"file": "IGRF14.shc", "kind": "igrf", "range": (1900.0, 2030.0),
               "label": "IGRF-14 (1900-2030)"},
}
DEFAULT_MODEL = "WMM2025"
AUTO = "auto"
_CACHE = {}

# kept for the older single-model API
EPOCH = 2025.0
VALID_FROM = 2025.0
VALID_TO = 2030.0


def auto_model(year):
    """Model used for a date when the user leaves the choice on automatic."""
    for key in ("WMM2025", "WMM2020", "WMM2015v2", "WMM2010"):
        lo, hi = MODELS[key]["range"]
        if lo <= year < hi:
            return key
    if 1900.0 <= year < 2030.0:
        return "IGRF14"
    return DEFAULT_MODEL


def resolve(model, year):
    return auto_model(year) if model in (None, AUTO) else model


def _load_wmm(path):
    n_max = 0
    with open(path, "r", encoding="utf-8") as fh:
        for k, line in enumerate(fh):
            parts = line.split()
            if k > 0 and len(parts) == 6:
                n_max = max(n_max, int(parts[0]))
    g = np.zeros((n_max + 1, n_max + 1))
    h = np.zeros_like(g)
    gd = np.zeros_like(g)
    hd = np.zeros_like(g)
    epoch = None
    with open(path, "r", encoding="utf-8") as fh:
        for k, line in enumerate(fh):
            parts = line.split()
            if k == 0:
                epoch = float(parts[0])
                continue
            if len(parts) != 6:
                continue
            n, m = int(parts[0]), int(parts[1])
            g[n, m], h[n, m], gd[n, m], hd[n, m] = (float(v) for v in parts[2:])
    return {"kind": "wmm", "nmax": n_max, "epoch": epoch, "g": g, "h": h, "gd": gd, "hd": hd}


def _load_igrf(path):
    epochs, rows = None, []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if epochs is None:
                if len(parts) >= 7 and "." in parts[-1] and len(parts) < 10:
                    continue                       # the "1 13 27 2 1 1900.0 2030.0" line
                epochs = [float(v) for v in parts]
                continue
            rows.append(parts)
    n_max = max(int(r[0]) for r in rows)
    g = np.zeros((len(epochs), n_max + 1, n_max + 1))
    h = np.zeros_like(g)
    for r in rows:
        n, m = int(r[0]), int(r[1])
        vals = np.array([float(v) for v in r[2:]])
        if m >= 0:
            g[:, n, m] = vals
        else:
            h[:, n, -m] = vals
    return {"kind": "igrf", "nmax": n_max, "epochs": np.array(epochs), "g": g, "h": h}


def get_model(key):
    if key not in MODELS:
        raise ValueError("Unknown magnetic model: %s" % key)
    if key not in _CACHE:
        path = os.path.join(os.path.dirname(__file__), MODELS[key]["file"])
        _CACHE[key] = _load_wmm(path) if MODELS[key]["kind"] == "wmm" else _load_igrf(path)
    return _CACHE[key]


def _coefficients(m, year):
    if m["kind"] == "wmm":
        dt = year - m["epoch"]
        return m["g"] + dt * m["gd"], m["h"] + dt * m["hd"]
    ep = m["epochs"]
    y = min(max(year, ep[0]), ep[-1])
    i = int(np.searchsorted(ep, y, side="right")) - 1
    i = min(max(i, 0), len(ep) - 2)
    t = (y - ep[i]) / (ep[i + 1] - ep[i])
    return (1 - t) * m["g"][i] + t * m["g"][i + 1], (1 - t) * m["h"][i] + t * m["h"][i + 1]


def decimal_year(d=None):
    """Decimal year from a date / datetime (default: today)."""
    if d is None:
        d = date.today()
    if isinstance(d, datetime):
        d = d.date()
    start = date(d.year, 1, 1).toordinal()
    end = date(d.year + 1, 1, 1).toordinal()
    return d.year + (d.toordinal() - start) / float(end - start)


def in_valid_range(year, model=None):
    key = resolve(model, year)
    lo, hi = MODELS[key]["range"]
    return lo <= year < hi or (MODELS[key]["kind"] == "igrf" and lo <= year <= hi)


def chunk_points(model_key):
    """Number of points per calculation block (keeps memory and time bounded)."""
    nmax = get_model(model_key)["nmax"]
    return max(500, int(3000000 // (nmax + 1)))


def field(lat, lon, year, alt_km=0.0, model=None):
    """Geomagnetic field. lat/lon in degrees (scalars or arrays).

    Returns dict of arrays: x (north), y (east), z (down) in nT, and
    d, i (degrees), h, f (nT).
    """
    key = resolve(model, year)
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    lat, lon = np.broadcast_arrays(lat, lon)
    shape = lat.shape
    la, lo = lat.ravel(), lon.ravel()
    step = chunk_points(key)
    parts = [_field_block(la[i:i + step], lo[i:i + step], year, alt_km, key)
             for i in range(0, la.size, step)]
    out = {}
    for k in parts[0]:
        out[k] = np.concatenate([p[k] for p in parts]).reshape(shape)
    return out


def _field_block(lat, lon, year, alt_km, key):
    m = get_model(key)
    nmax = m["nmax"]
    g, h = _coefficients(m, year)
    lat = np.clip(lat, -MAX_LAT, MAX_LAT)
    phi = np.radians(lat)
    lam = np.radians(lon)
    sphi, cphi = np.sin(phi), np.cos(phi)
    rc = A / np.sqrt(1.0 - E2 * sphi ** 2)
    p = (rc + alt_km) * cphi
    z = (rc * (1.0 - E2) + alt_km) * sphi
    r = np.sqrt(p ** 2 + z ** 2)
    phi_c = np.arcsin(z / r)             # geocentric latitude
    theta = np.pi / 2.0 - phi_c
    x_ = np.cos(theta)
    s_ = np.sin(theta)
    npts = lat.size

    mm = np.arange(nmax + 1)[:, None]
    cosm = np.cos(mm * lam[None, :])
    sinm = np.sin(mm * lam[None, :])
    ar = RE / r

    br = np.zeros(npts)
    bt = np.zeros(npts)
    bp = np.zeros(npts)
    # Schmidt semi-normalised Legendre functions P[m] and theta-derivatives dP[m],
    # kept for the two latest degrees only (rows: order m)
    P0, dP0 = np.ones((1, npts)), np.zeros((1, npts))            # degree 0
    P1 = None
    dP1 = None
    Pn2, dPn2 = None, None
    for n in range(1, nmax + 1):
        if n == 1:
            Pn = np.stack([x_, s_])
            dPn = np.stack([-s_, x_])
        else:
            Pa, dPa = (P1, dP1)                                  # degree n-1, shape (n, N)
            Pb, dPb = (Pn2, dPn2) if n > 2 else (P0, dP0)        # degree n-2, shape (n-1, N)
            Pn = np.empty((n + 1, npts))
            dPn = np.empty((n + 1, npts))
            k_low = n - 1                                        # m = 0 .. n-2 use both
            if k_low > 0:
                mr = np.arange(k_low)[:, None].astype(float)
                den = np.sqrt(n * n - mr ** 2)
                bb = np.sqrt((n - 1.0) ** 2 - mr ** 2)
                Pn[:k_low] = ((2.0 * n - 1.0) * x_ * Pa[:k_low] - bb * Pb[:k_low]) / den
                dPn[:k_low] = ((2.0 * n - 1.0) * (x_ * dPa[:k_low] - s_ * Pa[:k_low])
                               - bb * dPb[:k_low]) / den
            den1 = math.sqrt(2.0 * n - 1.0)                       # m = n-1
            Pn[n - 1] = (2.0 * n - 1.0) * x_ * Pa[n - 1] / den1
            dPn[n - 1] = (2.0 * n - 1.0) * (x_ * dPa[n - 1] - s_ * Pa[n - 1]) / den1
            kk = math.sqrt((2.0 * n - 1.0) / (2.0 * n))           # m = n
            Pn[n] = kk * s_ * Pa[n - 1]
            dPn[n] = kk * (s_ * dPa[n - 1] + x_ * Pa[n - 1])
        fac = ar ** (n + 2)
        gn = g[n, :n + 1, None]
        hn = h[n, :n + 1, None]
        gh = gn * cosm[:n + 1] + hn * sinm[:n + 1]
        br += (n + 1.0) * fac * np.einsum("ij,ij->j", gh, Pn)
        bt -= fac * np.einsum("ij,ij->j", gh, dPn)
        mrow = np.arange(n + 1)[:, None]
        bp += fac * np.einsum("ij,ij->j", mrow * (gn * sinm[:n + 1] - hn * cosm[:n + 1]), Pn)
        Pn2, dPn2 = P1, dP1
        P1, dP1 = Pn, dPn
    bp = bp / s_

    xg = -bt
    yg = bp
    zg = -br
    psi = phi - phi_c
    xx = xg * np.cos(psi) + zg * np.sin(psi)
    zz = zg * np.cos(psi) - xg * np.sin(psi)
    yy = yg
    hh = np.hypot(xx, yy)
    return {
        "x": xx, "y": yy, "z": zz, "h": hh,
        "f": np.sqrt(hh ** 2 + zz ** 2),
        "d": np.degrees(np.arctan2(yy, xx)),
        "i": np.degrees(np.arctan2(zz, hh)),
    }


def declination(lat, lon, year, alt_km=0.0, model=None):
    return field(lat, lon, year, alt_km, model)["d"]


def annual_change(lat, lon, year, alt_km=0.0, model=None):
    """Annual change of declination in degrees per year (east positive)."""
    d1 = declination(lat, lon, year + 0.5, alt_km, model)
    d0 = declination(lat, lon, year - 0.5, alt_km, model)
    diff = (d1 - d0 + 180.0) % 360.0 - 180.0
    return diff


def decimals_for(interval):
    """Label decimals that keep neighbouring isogonic lines distinguishable."""
    for d in (0, 1, 2, 3):
        step = round(float(interval) * 10 ** d)
        if abs(step - float(interval) * 10 ** d) < 1e-6:
            return d
    return 3


def format_label(decl_deg, decimals=0):
    """Annex 4 style label: 5\u00b0E, 2.5\u00b0W, 0.25\u00b0E, 0\u00b0."""
    v = round(float(decl_deg), decimals)
    if v == 0:
        return "0\u00b0"
    num = ("%d" % abs(v)) if decimals == 0 else ("%.*f" % (decimals, abs(v)))
    return "%s\u00b0%s" % (num, "E" if v > 0 else "W")


def format_dm(decl_deg):
    """Degrees and minutes, e.g. 5°12'E."""
    v = float(decl_deg)
    hemi = "E" if v >= 0 else "W"
    v = abs(v)
    deg = int(v)
    mins = int(round((v - deg) * 60.0))
    if mins == 60:
        deg, mins = deg + 1, 0
    return "%d°%02d'%s" % (deg, mins, hemi)


def format_coord_dms(value, is_lat, decimals=3):
    """Exact DMS with decimal seconds, e.g. 36\u00b048'00.000\"N or 010\u00b012'00.000\"E."""
    v = float(value)
    hemi = ("N" if v >= 0 else "S") if is_lat else ("E" if v >= 0 else "W")
    scale = 10 ** decimals
    units = int(round(abs(v) * 3600 * scale))        # integer arithmetic: no 60.000 carry bug
    deg, rem = divmod(units, 3600 * scale)
    mins, sec_units = divmod(rem, 60 * scale)
    width = 2 if is_lat else 3
    return "%0*d\u00b0%02d'%0*.*f\"%s" % (width, deg, mins, decimals + 3, decimals,
                                          sec_units / float(scale), hemi)


def format_position_dms(lat, lon, decimals=3):
    return (format_coord_dms(lat, True, decimals), format_coord_dms(lon, False, decimals))
