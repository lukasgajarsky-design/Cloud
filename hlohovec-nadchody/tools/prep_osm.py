"""Convert raw OSM extracts into scene data (local metres).

usage: prep_osm.py OUT_DIR file1.osm [file2.osm ...]
Writes buildings.json (consumed by build_meshes.mjs) and roads.json.
Roof shape / colour class is guessed from the satellite mosaic when OSM has no tags.
"""
import colorsys, hashlib, json, math, os, sys, xml.etree.ElementTree as ET
import numpy as np
import cv2
from shapely.geometry import Polygon, LineString
from shapely.geometry.polygon import orient
from scipy.ndimage import gaussian_filter
sys.path.insert(0, os.path.dirname(__file__))
from geo import to_local

out_dir, files = sys.argv[1], sys.argv[2:]
DATA = "web/data"

# ---------- load OSM ----------
nodes, ways, rels = {}, {}, {}
for f in files:
    root = ET.parse(f).getroot()
    for n in root.iter("node"):
        nodes[n.get("id")] = (float(n.get("lat")), float(n.get("lon")), {t.get("k"): t.get("v") for t in n.iter("tag")})
    for w in root.iter("way"):
        ways[w.get("id")] = ([nd.get("ref") for nd in w.iter("nd")], {t.get("k"): t.get("v") for t in w.iter("tag")})
    for r in root.iter("relation"):
        rels[r.get("id")] = ([(m.get("type"), m.get("ref"), m.get("role")) for m in r.iter("member")], {t.get("k"): t.get("v") for t in r.iter("tag")})

local = {}
def P(nid):
    if nid not in local:
        la, lo, _ = nodes[nid]
        local[nid] = to_local(la, lo)
    return local[nid]

def ring(refs):
    if any(r not in nodes for r in refs):
        return None
    return [P(r) for r in refs]

def h01(s):
    return int(hashlib.md5(str(s).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

# ---------- terrain (smoothed) ----------
tj = json.load(open(f"{DATA}/terrain.json"))
T = np.fromfile(f"{DATA}/terrain.bin", "<f4").reshape(tj["n"], tj["n"])
T = gaussian_filter(T, 1.6)   # ~40 m: removes SRTM building/tree bumps
T.astype("<f4").tofile(f"{DATA}/terrain_s.bin")  # the scene uses this same smoothed field

def terrain(e, n):
    fx = (e - tj["west"]) / (tj["east"] - tj["west"]) * (tj["n"] - 1)
    fy = (tj["north"] - n) / (tj["north"] - tj["south"]) * (tj["n"] - 1)
    x0, y0 = int(fx), int(fy); ax, ay = fx - x0, fy - y0
    return float(T[y0, x0] * (1 - ax) * (1 - ay) + T[y0, x0 + 1] * ax * (1 - ay) + T[y0 + 1, x0] * (1 - ax) * ay + T[y0 + 1, x0 + 1] * ax * ay)

# ---------- imagery for roof colour (sharp L0 mosaic where available, L1 elsewhere) ----------
IMGS = []
for name, f in (("img_l0.jpg", 4), ("img_l1.jpg", 1)):
    im = cv2.imread(f"{DATA}/{name}")
    if im is None:
        continue
    if f > 1:
        im = cv2.resize(im, (im.shape[1] // f, im.shape[0] // f), interpolation=cv2.INTER_AREA)
    IMGS.append((im[:, :, ::-1].copy(), json.load(open(f"{DATA}/{name.replace('.jpg', '.json')}"))))

def roof_colour(poly):
    for img, ib in IMGS:
        c = roof_colour_in(poly, img, ib)
        if c is not None:
            return c
    return None

def roof_colour_in(poly, img, ib):
    isz = img.shape[0]
    def img_px(e, n):
        return ((e - ib["west"]) / (ib["east"] - ib["west"]) * isz, (ib["north"] - n) / (ib["north"] - ib["south"]) * isz)
    pts = np.array([img_px(x, y) for x, y in poly.exterior.coords], np.float32)
    x0, y0 = np.floor(pts.min(0)).astype(int) - 2
    x1, y1 = np.ceil(pts.max(0)).astype(int) + 2
    if x0 < 0 or y0 < 0 or x1 >= isz or y1 >= isz:
        return None
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(m, [np.round((pts - [x0, y0]) * 4).astype(np.int32)], 1, shift=2)
    if m.sum() > 12:
        m = cv2.erode(m, np.ones((2, 2), np.uint8))
    sel = img[y0:y1, x0:x1][m > 0]
    if len(sel) == 0:
        return None
    return np.median(sel, axis=0) / 255.0

# ---------- buildings ----------
SKIP = {"roof", "carport", "construction", "ruins", "bridge", "parking", "tomb"}
LOW = {"garage", "garages", "shed", "kiosk", "service", "greenhouse", "hut", "cabin"}

def classify(tags, poly, bid):
    area = poly.area
    btype = tags.get("building", "yes")
    lv = tags.get("building:levels")
    try:
        lv = float(lv) if lv else None
    except ValueError:
        lv = None
    hraw = tags.get("height")
    try:
        hraw = float(hraw.replace("m", "").strip()) if hraw else None
    except ValueError:
        hraw = None
    r = h01(bid)
    col = roof_colour(poly)
    reddish = False
    if col is not None:
        hh, s, v = colorsys.rgb_to_hsv(*col)
        reddish = (hh < 0.115 or hh > 0.94) and s > 0.2 and v > 0.18
    # levels
    if lv is None:
        if btype in LOW:
            lv = 1
        elif btype in ("detached", "house"):
            lv = 1 + (r > 0.45)
        elif btype == "apartments":
            lv = 4 if area < 450 else (8 if area > 900 and r > 0.5 else 5)
        elif btype in ("industrial", "warehouse", "retail"):
            lv = 2
        elif btype in ("school", "kindergarten", "office", "government", "hospital"):
            lv = 3
        elif btype in ("church", "chapel"):
            lv = 3
        else:
            if area < 30: lv = 1
            elif area < 140: lv = 1 + (r > 0.35)
            elif area < 600: lv = 2 + (r > 0.75)
            elif area < 2500: lv = 2 + (r > 0.5)
            else: lv = 2
    shape = tags.get("roof:shape")
    if shape is None:
        if btype in ("church", "chapel"):
            shape = "hipped"
        elif reddish and area < 4000:
            shape = "hipped"
        elif btype in ("detached", "house") and area < 300:
            shape = "hipped"
        else:
            shape = "flat"
    if shape not in ("flat",):
        shape = "hipped" if shape not in ("pyramidal", "dome") else "pyramidal"
    floor_h = 3.4 if btype in ("retail", "industrial", "warehouse", "school", "office") else 3.0
    wall_h = hraw if hraw else lv * floor_h + 0.6
    if btype in LOW:
        wall_h = min(wall_h, 2.8)
    if btype in ("church",):
        wall_h = max(wall_h, 11.0)
    if hraw and shape != "flat":
        wall_h = max(2.5, hraw * 0.72)
    pitch = 38 if btype in ("church", "chapel") else (32 if area > 800 else 36)
    if btype in ("industrial", "warehouse", "retail") or area > 2500:
        style = 3  # commercial / hall
    elif btype == "apartments" or (lv >= 4 and shape == "flat"):
        style = 2  # panel block
    elif btype in LOW:
        style = 4  # garage
    elif btype in ("church", "chapel"):
        style = 5
    else:
        style = 1 if shape == "flat" else 0  # 0: old-town plaster, 1: modern plaster
    return dict(wall=round(wall_h, 2), shape=shape, pitch=pitch, style=style, levels=lv, type=btype)

buildings = []
used_ways = set()

def add_building(outer, holes, tags, bid):
    try:
        poly = Polygon(outer, holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
            if poly.geom_type != "Polygon":
                poly = max(poly.geoms, key=lambda g: g.area)
        poly = orient(poly.simplify(0.12, preserve_topology=True), 1.0)
    except Exception:
        return
    if poly.area < 6:
        return
    c = classify(tags, poly, bid)
    hs = [terrain(x, y) for x, y in poly.exterior.coords]
    base = sum(hs) / len(hs)  # walls extend 3 m below ground, so the mean keeps long buildings on slopes grounded
    b = dict(id=bid, outer=[[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords[:-1]],
             holes=[[[round(x, 2), round(y, 2)] for x, y in h.coords[:-1]] for h in poly.interiors],
             base=round(base, 2), name=tags.get("name"), **c)
    buildings.append(b)

for rid, (members, tags) in rels.items():
    if "building" not in tags or tags.get("type") != "multipolygon":
        continue
    outers = [ring(ways[m[1]][0]) for m in members if m[0] == "way" and m[2] == "outer" and m[1] in ways]
    inners = [ring(ways[m[1]][0]) for m in members if m[0] == "way" and m[2] == "inner" and m[1] in ways]
    for m in members:
        if m[0] == "way":
            used_ways.add(m[1])
    for o in outers:
        if o and len(o) >= 4:
            add_building(o, [i for i in inners if i and len(i) >= 4 and Polygon(o).contains(Polygon(i))], tags, "r" + rid)

for wid, (refs, tags) in ways.items():
    if wid in used_ways or "building" not in tags or tags["building"] in SKIP or refs[0] != refs[-1]:
        continue
    r = ring(refs)
    if r and len(r) >= 4:
        add_building(r, [], tags, wid)

# ---------- roads & footways ----------
roads = []
for wid, (refs, tags) in ways.items():
    hw = tags.get("highway")
    if not hw:
        continue
    pts = ring(refs)
    if not pts or len(pts) < 2:
        continue
    roads.append(dict(id=wid, hw=hw, name=tags.get("name"), ref=tags.get("ref"), oneway=tags.get("oneway") == "yes" or tags.get("junction") == "roundabout",
                      lanes=tags.get("lanes"), junction=tags.get("junction"), nodes=refs, pts=[[round(x, 2), round(y, 2)] for x, y in pts]))

trees = []
for nid, (la, lo, tags) in nodes.items():
    if tags.get("natural") == "tree":
        trees.append([round(v, 2) for v in to_local(la, lo)])

json.dump(dict(buildings=buildings), open(f"{out_dir}/buildings.json", "w"))
json.dump(dict(roads=roads, osm_trees=trees), open(f"{out_dir}/roads.json", "w"))
import collections
print(len(buildings), "buildings", collections.Counter(b["shape"] for b in buildings), collections.Counter(b["style"] for b in buildings))
print(len(roads), "roads", len(trees), "osm trees")
