"""Bake the street overlay (asphalt, markings, curbs, sidewalks) into the sharp satellite mosaic for a region.

The live viewer draws streets with a shader; exported 3D files need it baked into one texture.
usage: bake_ground.py OUT.jpg WEST SOUTH EAST NORTH SIZE_PX
"""
import json, sys
import cv2
import numpy as np

out, W, S, E, N, size = sys.argv[1], *map(float, sys.argv[2:6]), int(sys.argv[6])
b = json.load(open("web/data/img_l0.json"))
sm = json.load(open("web/data/streets.json"))
photo = cv2.imread("web/data/img_l0.jpg")  # uint8, BGR
sdf = cv2.imread("web/data/streets.png")[:, :, ::-1].astype(np.float32) / 255.0
P = photo.shape[0]
mpp = (E - W) / size

xs = W + (np.arange(size) + 0.5) * mpp
ys = N - (np.arange(size) + 0.5) * (N - S) / size
# photo sampling (area-average when shrinking: blur by the scale factor first)
scale = (b["east"] - b["west"]) / P
shrink = mpp / scale
src = cv2.GaussianBlur(photo, (0, 0), 0.5 * shrink) if shrink > 1.5 else photo
mx = ((xs - b["west"]) / scale - 0.5).astype(np.float32)
my = ((b["north"] - ys) / scale - 0.5).astype(np.float32)
img = cv2.remap(src, np.broadcast_to(mx[None, :], (size, size)).copy(), np.broadcast_to(my[:, None], (size, size)).copy(), cv2.INTER_LINEAR)
del src, photo
img = img[:, :, ::-1].astype(np.float32) / 255.0

sx = ((xs - sm["west"]) / sm["size"] * sm["tex"] - 0.5).astype(np.float32)
sy = ((sm["south"] + sm["size"] - ys) / sm["size"] * sm["tex"] - 0.5).astype(np.float32)
s = cv2.remap(sdf, np.broadcast_to(sx[None, :], (size, size)).copy(), np.broadcast_to(sy[:, None], (size, size)).copy(), cv2.INTER_LINEAR,
              borderMode=cv2.BORDER_CONSTANT, borderValue=(1, 1, 1))
d_road, d_mark, d_walk = (s[..., 0] - 0.5) * 3.0, (s[..., 1] - 0.5) * 1.0, (s[..., 2] - 0.5) * 3.0
aa = max(mpp * 0.75, 0.02)
cover = lambda d: np.clip(0.5 - d / (2 * aa), 0, 1)
road = cover(d_road)
curb = cover(d_road - 0.17) * (1 - road)
walk = cover(d_walk) * (1 - road)
mark = cover(d_mark) * road
fx = np.clip(np.minimum(xs - sm["west"], sm["west"] + sm["size"] - xs) / (0.06 * sm["size"]), 0, 1)
fy = np.clip(np.minimum(ys - sm["south"], sm["south"] + sm["size"] - ys) / (0.06 * sm["size"]), 0, 1)
fade = np.minimum(fx[None, :], fy[:, None])
fade = fade * fade * (3 - 2 * fade)

rng = np.random.default_rng(3)
grain = cv2.GaussianBlur(rng.random((size, size)).astype(np.float32), (0, 0), 1.0)
grain = ((grain - grain.mean()) / (grain.std() + 1e-6))[..., None]
blotch = cv2.resize(rng.random((max(2, size // 48),) * 2).astype(np.float32), (size, size), interpolation=cv2.INTER_CUBIC)[..., None]
col = lambda v: np.array(v, np.float32) / 255.0
layers = [
    (col([138, 133, 126]) * (1 + 0.05 * grain), walk),
    (col([170, 168, 162]) * (1 + 0.03 * grain), curb),
    (col([74, 74, 77]) * (0.93 + 0.12 * blotch) * (1 + 0.05 * grain), road),
    (col([226, 226, 221]) * (1 + 0.03 * grain), mark),
]
for c, m in layers:
    w = (m * fade)[..., None]
    img = img * (1 - w) + c * w
cv2.imwrite(out, np.clip(img * 255 + 0.5, 0, 255).astype(np.uint8)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88])
json.dump({"west": W, "south": S, "east": E, "north": N, "size": size}, open(out.rsplit(".", 1)[0] + ".json", "w"))
print(out, size, "px,", round(mpp, 3), "m/px")
