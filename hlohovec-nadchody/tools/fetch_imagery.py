"""Download Esri World Imagery tiles and stitch a square mosaic centred on a local point.

usage: fetch_imagery.py ZOOM CENTER_E CENTER_N SIZE_PX OUT.jpg
Writes OUT.jpg plus OUT.json with the exact local-metre bounds of the mosaic.
"""
import io, json, math, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from geo import local_to_tile, tile_to_local

URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
CACHE = os.environ.get("TILE_CACHE", "/tmp/esri_tiles")


def get_tile(z, x, y):
    path = f"{CACHE}/{z}/{x}_{y}.jpg"
    if os.path.exists(path):
        return Image.open(path).convert("RGB")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": "hlohovec-overpass-viz/1.0"})
            data = urllib.request.urlopen(req, timeout=30).read()
            open(path, "wb").write(data)
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            time.sleep(2 ** attempt)
    return Image.new("RGB", (256, 256), (90, 90, 80))


def main():
    z, ce, cn, size, out = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    cx, cy = local_to_tile(ce, cn, z)
    px0, py0 = cx * 256 - size / 2, cy * 256 - size / 2
    tx0, ty0 = int(px0 // 256), int(py0 // 256)
    tx1, ty1 = int((px0 + size) // 256), int((py0 + size) // 256)
    tiles = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(8) as ex:
        imgs = list(ex.map(lambda t: get_tile(z, *t), tiles))
    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for (x, y), im in zip(tiles, imgs):
        canvas.paste(im, ((x - tx0) * 256, (y - ty0) * 256))
    ox, oy = round(px0 - tx0 * 256), round(py0 - ty0 * 256)
    canvas.crop((ox, oy, ox + size, oy + size)).save(out, quality=92)
    # exact bounds of the cropped mosaic in local metres
    w, n = tile_to_local((tx0 * 256 + ox) / 256, (ty0 * 256 + oy) / 256, z)
    e, s = tile_to_local((tx0 * 256 + ox + size) / 256, (ty0 * 256 + oy + size) / 256, z)
    json.dump({"west": w, "east": e, "south": s, "north": n, "zoom": z, "size": size}, open(out.rsplit(".", 1)[0] + ".json", "w"), indent=1)
    print(out, len(tiles), "tiles", {"west": round(w, 2), "east": round(e, 2), "south": round(s, 2), "north": round(n, 2)})


if __name__ == "__main__":
    main()
