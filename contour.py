"""Marching-squares contour lines on a regular grid. No QGIS imports.

contour_lines(z, xs, ys, level) -> list of (coords, closed)
  z  : 2D array, z[row, col]
  xs : 1D array of column coordinates (monotonic)
  ys : 1D array of row coordinates (monotonic)
  coords: list of (x, y) tuples
Cells touching NaN are skipped.
"""
import numpy as np


def _edge_points(z, xs, ys, level):
    """Crossing point of every horizontal / vertical grid edge (NaN where none)."""
    nr, nc = z.shape
    # horizontal edges H[i, j]: between (i, j) and (i, j+1)
    za, zb = z[:, :-1], z[:, 1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        th = (level - za) / (zb - za)
    hmask = ((za >= level) != (zb >= level)) & np.isfinite(th)
    hx = xs[:-1][None, :] + th * (xs[1:] - xs[:-1])[None, :]
    hy = np.broadcast_to(ys[:, None], hx.shape)
    # vertical edges V[i, j]: between (i, j) and (i+1, j)
    za, zb = z[:-1, :], z[1:, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        tv = (level - za) / (zb - za)
    vmask = ((za >= level) != (zb >= level)) & np.isfinite(tv)
    vy = ys[:-1][:, None] + tv * (ys[1:] - ys[:-1])[:, None]
    vx = np.broadcast_to(xs[None, :], vy.shape)
    return hmask, hx, hy, vmask, vx, vy


def contour_lines(z, xs, ys, level):
    z = np.asarray(z, dtype=float)
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    nr, nc = z.shape
    if nr < 2 or nc < 2:
        return []
    hmask, hx, hy, vmask, vx, vy = _edge_points(z, xs, ys, level)

    a = z[:-1, :-1]
    b = z[:-1, 1:]
    c = z[1:, 1:]
    d = z[1:, :-1]
    valid = np.isfinite(a) & np.isfinite(b) & np.isfinite(c) & np.isfinite(d)
    ha, hb, hc, hd = (a >= level), (b >= level), (c >= level), (d >= level)
    idx = ha * 8 + hb * 4 + hc * 2 + hd * 1
    idx = np.where(valid, idx, 0)
    with np.errstate(invalid="ignore"):
        center_high = (a + b + c + d) / 4.0 >= level
    ci, cj = np.nonzero((idx != 0) & (idx != 15))
    if ci.size == 0:
        return []
    k = idx[ci, cj]
    ch = center_high[ci, cj]
    H = nc * nr          # offset for vertical edge ids

    def top(i, j):
        return i * (nc - 1) + j

    def bottom(i, j):
        return (i + 1) * (nc - 1) + j

    def left(i, j):
        return H + i * nc + j

    def right(i, j):
        return H + i * nc + j + 1

    segs = []
    # (case, centre_high or None) -> list of (edgeA, edgeB)
    table = {
        1: [("L", "B")], 2: [("B", "R")], 3: [("L", "R")], 4: [("T", "R")],
        6: [("T", "B")], 7: [("T", "L")], 8: [("T", "L")], 9: [("T", "B")],
        11: [("T", "R")], 12: [("L", "R")], 13: [("B", "R")], 14: [("L", "B")],
    }
    sad = {
        (5, True): [("T", "L"), ("B", "R")], (5, False): [("T", "R"), ("L", "B")],
        (10, True): [("T", "R"), ("L", "B")], (10, False): [("T", "L"), ("B", "R")],
    }
    fn = {"T": top, "B": bottom, "L": left, "R": right}
    for case, pairs in table.items():
        sel = k == case
        if not sel.any():
            continue
        ii, jj = ci[sel], cj[sel]
        for ea, eb in pairs:
            segs.append(np.stack([fn[ea](ii, jj), fn[eb](ii, jj)], axis=1))
    for (case, high), pairs in sad.items():
        sel = (k == case) & (ch == high)
        if not sel.any():
            continue
        ii, jj = ci[sel], cj[sel]
        for ea, eb in pairs:
            segs.append(np.stack([fn[ea](ii, jj), fn[eb](ii, jj)], axis=1))
    if not segs:
        return []
    segs = np.concatenate(segs, axis=0)

    def point(eid):
        if eid < H:
            i, j = divmod(eid, nc - 1)
            return (float(hx[i, j]), float(hy[i, j]))
        i, j = divmod(eid - H, nc)
        return (float(vx[i, j]), float(vy[i, j]))

    # stitch segments into polylines by shared edge id
    adj = {}
    for s, (e1, e2) in enumerate(segs.tolist()):
        adj.setdefault(e1, []).append(s)
        adj.setdefault(e2, []).append(s)
    used = np.zeros(len(segs), dtype=bool)
    sl = segs.tolist()
    lines = []

    def walk(start_edge, first_seg):
        chain = [start_edge]
        cur, s = start_edge, first_seg
        while True:
            used[s] = True
            e1, e2 = sl[s]
            nxt = e2 if e1 == cur else e1
            chain.append(nxt)
            cur = nxt
            nxt_segs = [t for t in adj[cur] if not used[t]]
            if not nxt_segs:
                break
            s = nxt_segs[0]
        return chain

    # open lines first (edges with a single segment), then closed rings
    for e, lst in adj.items():
        if len(lst) == 1 and not used[lst[0]]:
            chain = walk(e, lst[0])
            lines.append((chain, False))
    for s in range(len(sl)):
        if not used[s]:
            e1 = sl[s][0]
            chain = walk(e1, s)
            lines.append((chain, chain[0] == chain[-1]))
    out = []
    for chain, closed in lines:
        out.append(([point(e) for e in chain], closed))
    return out


def smooth_grid(z, passes=1):
    """Light 3x3 mean filter that ignores NaN (used to calm noisy DEMs)."""
    z = np.asarray(z, dtype=float)
    for _ in range(int(passes)):
        pad = np.pad(z, 1, mode="edge")
        acc = np.zeros_like(z)
        cnt = np.zeros_like(z)
        for di in (0, 1, 2):
            for dj in (0, 1, 2):
                w = pad[di:di + z.shape[0], dj:dj + z.shape[1]]
                ok = np.isfinite(w)
                acc += np.where(ok, w, 0.0)
                cnt += ok
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where(cnt > 0, acc / cnt, np.nan)
    return z
