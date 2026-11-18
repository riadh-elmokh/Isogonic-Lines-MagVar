"""Isogonic lines (lines of equal magnetic declination). No QGIS imports."""
import math

import numpy as np

from . import contour, wmm

MAX_CELLS = 4000000
MAX_CELLS_HR = 1000000          # high-resolution models are slower


def cell_limit(model_key):
    return MAX_CELLS if wmm.get_model(model_key)["nmax"] <= 20 else MAX_CELLS_HR


def grid_size(west, south, east, north, step):
    nx = int(math.ceil((east - west) / step)) + 3
    ny = int(math.ceil((north - south) / step)) + 3
    return nx, ny


MAX_LEVELS = 3000
FINER = (0.5, 0.25, 0.1, 0.05, 0.02, 0.01)


def auto_step(west, south, east, north, step=None, max_cells=MAX_CELLS):
    """Grid spacing in degrees. step=None -> automatic: fine enough for small
    extents, never coarser than 0.25 degrees, never too many cells."""
    if step:
        return float(step)
    size = max(east - west, north - south, 1e-6)
    s = min(0.25, max(size / 80.0, 0.002))
    while True:
        nx, ny = grid_size(west, south, east, north, s)
        if nx * ny <= max_cells:
            return s
        s *= 1.5


def _levels(dmin, dmax, interval):
    lo = math.ceil(dmin / interval - 1e-9)
    hi = math.floor(dmax / interval + 1e-9)
    return [round(k * interval, 6) for k in range(lo, hi + 1)]


def isogonic_lines(west, south, east, north, year, interval, step=None, alt_km=0.0,
                   is_canceled=None, progress=None, refine=True, model=None):
    """Return (lines, info). lines: list of dicts with level, coords
    [(lon, lat)...], closed, ann_change. info: dict with the interval used,
    the declination range and the grid step.

    The grid is padded by one cell so lines reach the edge of the extent;
    the caller clips to the exact extent.
    """
    key = wmm.resolve(model, year)
    limit = cell_limit(key)
    step = auto_step(west, south, east, north, step, limit)
    nx, ny = grid_size(west, south, east, north, step)
    if nx * ny > limit:
        raise ValueError(
            "The grid would have %d cells (limit %d). Use a larger grid "
            "spacing or a smaller extent." % (nx * ny, limit))
    lons = west - step + step * np.arange(nx)
    lats = south - step + step * np.arange(ny)
    lats = np.clip(lats, -wmm.MAX_LAT, wmm.MAX_LAT)
    decl = np.empty((ny, nx))
    rows_per_chunk = max(1, int(wmm.chunk_points(key) // nx))
    for r0 in range(0, ny, rows_per_chunk):
        if is_canceled and is_canceled():
            return [], {}
        r1 = min(ny, r0 + rows_per_chunk)
        la, lo = np.meshgrid(lats[r0:r1], lons, indexing="ij")
        decl[r0:r1, :] = wmm.declination(la, lo, year, alt_km, model)
        if progress:
            progress(50.0 * r1 / ny)
    dmin, dmax = float(decl.min()), float(decl.max())
    used = float(interval)
    levels = _levels(dmin, dmax, used)
    if not levels and refine:
        for iv in FINER:
            if iv < interval:
                lv = _levels(dmin, dmax, iv)
                if lv:
                    used, levels = iv, lv
                    break
    if len(levels) > MAX_LEVELS:
        raise ValueError("%d isogonic lines would be drawn: the interval is too small for "
                         "this declination range." % len(levels))
    out = []
    for k, lv in enumerate(levels):
        if is_canceled and is_canceled():
            return [], {}
        for coords, closed in contour.contour_lines(decl, lons, lats, lv):
            if len(coords) < 2:
                continue
            mid = coords[len(coords) // 2]
            ac = float(wmm.annual_change(mid[1], mid[0], year, alt_km, model)[0])
            out.append({"level": lv, "coords": coords, "closed": closed,
                        "ann_change": ac})
        if progress:
            progress(50.0 + 50.0 * (k + 1) / max(len(levels), 1))
    info = {"interval": used, "requested": float(interval), "dmin": dmin,
            "dmax": dmax, "step": step, "model": wmm.resolve(model, year)}
    return out, info
