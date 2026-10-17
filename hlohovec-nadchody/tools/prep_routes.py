"""Build smoothed traffic routes (right-hand lanes) through the Hlohovec roundabout.

usage: prep_routes.py ROADS_JSON OUT_JSON
"""
import heapq, json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from geo import to_local

roads = json.load(open(sys.argv[1]))["roads"]
# main roads only, plus the short southern leg of the roundabout, so routes stay on the real through-traffic streets
DRIVE = {"primary", "secondary", "primary_link", "secondary_link"}
EXTRA_WAYS = {"5184317", "944994473", "944994476"}
G, pos, oneway_edge = {}, {}, {}
for r in roads:
    if r["hw"] not in DRIVE and r["id"] not in EXTRA_WAYS:
        continue
    for (a, b), pa, pb in zip(zip(r["nodes"], r["nodes"][1:]), r["pts"], r["pts"][1:]):
        pos[a], pos[b] = pa, pb
        d = math.dist(pa, pb)
        G.setdefault(a, []).append((b, d))
        oneway_edge[(a, b)] = r["oneway"]
        if not r["oneway"]:
            G.setdefault(b, []).append((a, d))
            oneway_edge[(b, a)] = False


def nearest(p):
    return min(pos, key=lambda k: math.dist(pos[k], p) if k in G else 1e9)


def path(a, b):
    dist, prev, q = {a: 0}, {}, [(0, a)]
    while q:
        d, u = heapq.heappop(q)
        if u == b:
            break
        if d > dist.get(u, 1e18):
            continue
        for v, w in G.get(u, []):
            if d + w < dist.get(v, 1e18):
                dist[v], prev[v] = d + w, u
                heapq.heappush(q, (d + w, v))
    out = [b]
    while out[-1] != a:
        out.append(prev[out[-1]])
    return out[::-1]


def offset_poly(nodes_):
    pts, out = [pos[n] for n in nodes_], []
    for i, p in enumerate(pts):
        a = pts[max(i - 1, 0)]
        c = pts[min(i + 1, len(pts) - 1)]
        dx, dy = c[0] - a[0], c[1] - a[1]
        L = math.hypot(dx, dy) or 1
        e = (nodes_[i], nodes_[min(i + 1, len(nodes_) - 1)]) if i < len(nodes_) - 1 else (nodes_[i - 1], nodes_[i])
        off = 0.0 if oneway_edge.get(e, False) else 1.75
        out.append((p[0] + dy / L * off, p[1] - dx / L * off))
    return out


def resample(pts, step=1.0):
    out = [pts[0]]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        t = step - acc
        while t <= d:
            out.append((a[0] + (b[0] - a[0]) * t / d, a[1] + (b[1] - a[1]) * t / d))
            t += step
        acc = d - (t - step)
    return out


def smooth(pts, n=60):
    for _ in range(n):
        pts = [pts[0]] + [((pts[i - 1][0] + 2 * pts[i][0] + pts[i + 1][0]) / 4, (pts[i - 1][1] + 2 * pts[i][1] + pts[i + 1][1]) / 4) for i in range(1, len(pts) - 1)] + [pts[-1]]
    return pts


ENDS = {
    "HN": to_local(48.4336, 17.80125),
    "SE": to_local(48.42503, 17.80600),
    "W": to_local(48.43095, 17.79020),
    "S": (-32.47, -64.31),
}
PAIRS = [("HN", "SE"), ("SE", "HN"), ("W", "SE"), ("SE", "W"), ("HN", "W"), ("W", "HN"), ("S", "HN"), ("SE", "S"), ("HN", "S"), ("S", "SE"), ("S", "W"), ("W", "S")]
routes = {}
for a, b in PAIRS:
    ns = path(nearest(ENDS[a]), nearest(ENDS[b]))
    pts = smooth(resample(offset_poly(ns), 1.0))
    # speed profile from curvature
    sp = []
    for i in range(len(pts)):
        p0, p1, p2 = pts[max(i - 4, 0)], pts[i], pts[min(i + 4, len(pts) - 1)]
        a1 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        a2 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        da = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        R = (math.dist(p0, p1) + math.dist(p1, p2)) / 2 / max(da, 1e-4)
        sp.append(min(12.5, math.sqrt(1.8 * R)))
    # limit acceleration/deceleration (forward/backward passes)
    for i in range(1, len(sp)):
        sp[i] = min(sp[i], math.sqrt(sp[i - 1] ** 2 + 2 * 1.6 * 1.0))
    for i in range(len(sp) - 2, -1, -1):
        sp[i] = min(sp[i], math.sqrt(sp[i + 1] ** 2 + 2 * 2.5 * 1.0))
    routes[f"{a}-{b}"] = {"pts": [[round(x, 2), round(y, 2)] for x, y in pts], "v": [round(v, 2) for v in sp]}
    print(a, b, len(pts), "m")
json.dump({"routes": routes}, open(sys.argv[2], "w"))
