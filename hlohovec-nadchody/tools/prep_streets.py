"""Rasterise street surfaces (carriageways, sidewalks, white markings) as signed-distance textures.

usage: prep_streets.py OUT.png file1.osm [...]
The ground shader uses the SDFs to draw crisp asphalt, curbs, paving and lane markings
over the satellite photo near the two overpasses (sharp even at pedestrian eye level).
"""
import json, math, os, sys, xml.etree.ElementTree as ET
import cv2
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
sys.path.insert(0, os.path.dirname(__file__))
from geo import to_local

out, files = sys.argv[1], sys.argv[2:]
W0, S0, SIZE_M, TEX = -170.0, -190.0, 409.6, 4096
RES = 3  # supersampling factor for the raster
PX = TEX * RES / SIZE_M  # pixels per metre in the working raster

nodes, ways = {}, {}
for f in files:
    r = ET.parse(f).getroot()
    for n in r.iter("node"):
        nodes[n.get("id")] = (float(n.get("lat")), float(n.get("lon")), {t.get("k"): t.get("v") for t in n.iter("tag")})
    for w in r.iter("way"):
        ways[w.get("id")] = ([nd.get("ref") for nd in w.iter("nd")], {t.get("k"): t.get("v") for t in w.iter("tag")})
loc = {k: to_local(v[0], v[1]) for k, v in nodes.items()}

DRIVE = {"secondary", "tertiary", "residential", "unclassified", "living_street", "secondary_link", "tertiary_link"}


def road_width(t):
    name, ref = t.get("name", ""), t.get("ref", "")
    if t.get("junction") == "roundabout":
        return 7.5
    if t.get("oneway") == "yes":
        return 5.0
    if name == "Hlohová" and t.get("highway") == "secondary":
        return 10.5
    if name in ("Námestie sv. Michala", "Slov. nár. povstania"):
        return 9.5
    if "513" in ref:
        return 8.5
    if t.get("highway") == "secondary":
        return 8.5
    if t.get("highway") == "tertiary":
        return 7.0
    return 6.0


roads, sidewalks, center_lines, road_dirs = [], [], [], {}
for wid, (refs, t) in ways.items():
    hw = t.get("highway")
    pts = [loc[r] for r in refs if r in loc]
    if len(pts) < 2:
        continue
    if hw in DRIVE:
        w = road_width(t)
        ls = LineString(pts)
        roads.append(ls.buffer(w / 2, cap_style="round", join_style="round", resolution=12))
        for i, r in enumerate(refs):
            a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
            road_dirs[r] = (math.atan2(b[1] - a[1], b[0] - a[0]), w)
        if t.get("oneway") != "yes" and t.get("junction") != "roundabout" and hw in ("secondary", "tertiary"):
            center_lines.append(ls)
    elif hw == "footway" and t.get("footway") == "sidewalk" or hw == "pedestrian" and t.get("area") != "yes":
        sidewalks.append(LineString(pts).buffer(1.3, cap_style="flat", join_style="round"))

road = unary_union(roads)
walk = unary_union(sidewalks).difference(road.buffer(0.15))

N = TEX * RES


def to_px(x, y):
    return ((x - W0) * PX, (S0 + SIZE_M - y) * PX)


def raster(geom):
    m = np.zeros((N, N), np.uint8)
    polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    for p in polys:
        if p.is_empty:
            continue
        ext = np.array([to_px(*c) for c in p.exterior.coords], np.float32)
        cv2.fillPoly(m, [np.round(ext * 4).astype(np.int32)], 1, shift=2)
        for h in p.interiors:
            cv2.fillPoly(m, [np.round(np.array([to_px(*c) for c in h.coords], np.float32) * 4).astype(np.int32)], 0, shift=2)
    return m


marks = []
# dashed centre lines: 3 m dash / 6 m gap, 0.15 m wide (Slovak V 2a)
for ls in center_lines:
    L = ls.length
    s = 1.5
    while s + 3 < L:
        seg = LineString([ls.interpolate(s), ls.interpolate(s + 3)])
        marks.append(seg.buffer(0.08, cap_style="flat"))
        s += 9
# zebra crossings (bars parallel to traffic, 0.5 m wide, 0.5 m gaps, 4 m long)
for nid, (la, lo, t) in nodes.items():
    if t.get("highway") != "crossing" or t.get("crossing") in ("unmarked", "no") or t.get("crossing:markings") == "no":
        continue
    if nid not in road_dirs:
        continue
    ang, w = road_dirs[nid]
    cx, cy = loc[nid]
    if not (W0 < cx < W0 + SIZE_M and S0 < cy < S0 + SIZE_M):
        continue
    tx, ty = math.cos(ang), math.sin(ang)
    nx, ny = -ty, tx
    k = -w / 2 + 0.5
    while k < w / 2 - 0.3:
        c = (cx + nx * k, cy + ny * k)
        bar = Polygon([(c[0] + tx * sx * 2.0 + nx * sy * 0.25, c[1] + ty * sx * 2.0 + ny * sy * 0.25) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        marks.append(bar)
        k += 1.0
marking = unary_union(marks).intersection(road)


def sdf(mask, rng):
    inside = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    outside = cv2.distanceTransform(1 - mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    d = (outside - inside) / PX  # metres, negative inside
    d = cv2.GaussianBlur(d, (0, 0), 2.0)  # remove the raster staircase from slanted edges
    d = cv2.resize(d, (TEX, TEX), interpolation=cv2.INTER_AREA)
    return np.clip(np.round((0.5 + d / (2 * rng)) * 255), 0, 255).astype(np.uint8)


R = sdf(raster(road), 1.5)
G = sdf(raster(marking), 0.5)
B = sdf(raster(walk), 1.5)
cv2.imwrite(out, np.dstack([B, G, R]))  # OpenCV writes BGR -> file is RGB = road, marking, sidewalk
json.dump({"west": W0, "south": S0, "size": SIZE_M, "tex": TEX, "rangeRoad": 1.5, "rangeMark": 0.5, "rangeWalk": 1.5}, open(out.rsplit(".", 1)[0] + ".json", "w"))
print("road area", round(road.area), "sidewalk area", round(walk.area), "marks", len(marks))
