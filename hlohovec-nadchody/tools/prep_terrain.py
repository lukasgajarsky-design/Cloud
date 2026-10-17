"""Fetch Terrarium elevation tiles and resample to a local heightmap (metres, relative to origin).

Writes web/data/terrain.bin (Float32, row-major, north row first) + terrain.json.
"""
import io, json, math, os, sys, urllib.request
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from geo import local_to_tile

Z = 14
EXT = 13000.0      # metres, square side
N = 520            # samples per side (25 m spacing)
CE, CN = 30.0, 0.0
CACHE = os.environ.get("TILE_CACHE", "/tmp/esri_tiles") + "/terrarium"
os.makedirs(CACHE, exist_ok=True)


def tile(x, y):
    p = f"{CACHE}/{Z}_{x}_{y}.png"
    if not os.path.exists(p):
        url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png"
        open(p, "wb").write(urllib.request.urlopen(url, timeout=30).read())
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


cache = {}
xs = np.linspace(CE - EXT / 2, CE + EXT / 2, N)
ys = np.linspace(CN + EXT / 2, CN - EXT / 2, N)
H = np.zeros((N, N), np.float32)
for j, n in enumerate(ys):
    for i, e in enumerate(xs):
        tx, ty = local_to_tile(e, n, Z)
        px, py = tx * 256 - 0.5, ty * 256 - 0.5
        x0, y0 = int(math.floor(px)), int(math.floor(py))
        fx, fy = px - x0, py - y0
        v = 0
        for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            gx, gy = x0 + dx, y0 + dy
            k = (gx // 256, gy // 256)
            if k not in cache:
                cache[k] = tile(*k)
            v += w * cache[k][gy % 256, gx % 256]
        H[j, i] = v
h0 = float(H[N // 2, int((0 - (CE - EXT / 2)) / EXT * (N - 1))])
H -= h0
H.astype("<f4").tofile("web/data/terrain.bin")
json.dump({"west": CE - EXT / 2, "east": CE + EXT / 2, "south": CN - EXT / 2, "north": CN + EXT / 2, "n": N, "h0": h0}, open("web/data/terrain.json", "w"))
print("origin elevation", h0, "range", H.min(), H.max())
