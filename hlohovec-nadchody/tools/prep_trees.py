"""Detect tree canopies in the satellite mosaics and emit tree instances.

usage: prep_trees.py BUILDINGS_JSON L0_JPG OUT_JSON
Each tree: [east, north, crown_radius, height, kind]  (kind 0 = broadleaf, 1 = conifer-ish dark)
"""
import json, sys
import cv2
import numpy as np

bfile, l0file, out = sys.argv[1:4]
B = json.load(open(bfile))["buildings"]
l0b = json.load(open(l0file.rsplit(".", 1)[0] + ".json"))
l1b = json.load(open("web/data/img_l1.json"))


def detect(img, bounds, mpp, keep_fn):
    """img: RGB uint8 at mpp metres/pixel."""
    f = img.astype(np.float32) / 255.0
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    s = r + g + b + 1e-3
    exg = (2 * g - r - b) / s
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    k = max(3, int(round(2.0 / mpp)) | 1)
    mean = cv2.blur(lum, (k, k))
    std = np.sqrt(np.maximum(cv2.blur(lum * lum, (k, k)) - mean * mean, 0))
    ks = max(3, int(round(1.2 / mpp)) | 1)
    exg_s, lum_s = cv2.blur(exg, (ks, ks)), cv2.blur(lum, (ks, ks))
    veg = (((exg_s > 0.07) & (lum_s < 0.48)) | ((exg_s > 0.035) & (lum_s < 0.2))) & (std > 0.03)
    veg = veg.astype(np.uint8)
    # remove buildings
    H, W = veg.shape
    bm = np.zeros_like(veg)
    sx = W / (bounds["east"] - bounds["west"])
    for bd in B:
        pts = np.array([[(x - bounds["west"]) * sx, (bounds["north"] - y) * sx] for x, y in bd["outer"]], np.float32)
        cv2.fillPoly(bm, [np.round(pts * 4).astype(np.int32)], 1, shift=2)
    bm = cv2.dilate(bm, np.ones((3, 3), np.uint8))
    veg[bm > 0] = 0
    rad = max(1, int(round(0.8 / mpp)))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1, 2 * rad + 1))
    veg = cv2.morphologyEx(veg, cv2.MORPH_OPEN, ker)
    veg = cv2.morphologyEx(veg, cv2.MORPH_CLOSE, ker)
    dist = cv2.distanceTransform(veg, cv2.DIST_L2, 5) * mpp  # metres to canopy edge
    # local maxima of distance -> crown centres; greedy non-max suppression
    dil = cv2.dilate(dist, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(3.0 / mpp) | 1, int(3.0 / mpp) | 1)))
    cand = np.argwhere((dist >= dil - 1e-4) & (dist > 1.1))
    vals = dist[cand[:, 0], cand[:, 1]]
    order = np.argsort(-vals)
    taken = np.zeros_like(veg)
    trees = []
    darkness = cv2.blur(lum, (int(3 / mpp) | 1, int(3 / mpp) | 1))
    for idx in order:
        y, x = cand[idx]
        if taken[y, x]:
            continue
        rr = float(min(dist[y, x] * 1.25 + 0.6, 8.5))
        e = bounds["west"] + (x + 0.5) * mpp
        n = bounds["north"] - (y + 0.5) * mpp
        if not keep_fn(e, n):
            continue
        cv2.circle(taken, (int(x), int(y)), max(1, int(rr * 0.75 / mpp)), 1, -1)
        h = rr * 1.9 + 2.5 + (hash((int(e * 10), int(n * 10))) % 100) / 100 * 2.0
        kind = 1 if darkness[y, x] < 0.13 and rr < 4 else 0
        trees.append([round(e, 2), round(n, 2), round(rr, 2), round(h, 2), kind])
    return trees


Image0 = cv2.imread(l0file)[:, :, ::-1]
mpp0 = (l0b["east"] - l0b["west"]) / Image0.shape[1]
f = 4
small = cv2.resize(Image0, (Image0.shape[1] // f, Image0.shape[0] // f), interpolation=cv2.INTER_AREA)
inside0 = lambda e, n: l0b["west"] + 5 < e < l0b["east"] - 5 and l0b["south"] + 5 < n < l0b["north"] - 5
t0 = detect(small, l0b, mpp0 * f, inside0)
Image1 = cv2.imread("web/data/img_l1.jpg")[:, :, ::-1]
mpp1 = (l1b["east"] - l1b["west"]) / Image1.shape[1]
t1 = detect(Image1, l1b, mpp1, lambda e, n: not inside0(e, n) and abs(e - 30) < 1450 and abs(n) < 1450)
t1 = [t for t in t1 if t[2] >= 1.8]
rng = np.random.default_rng(7)
if len(t1) > 16000:
    t1 = [t1[i] for i in sorted(rng.choice(len(t1), 16000, replace=False))]
json.dump({"trees": t0 + t1}, open(out, "w"))
print(len(t0), "core trees,", len(t1), "outer trees")
