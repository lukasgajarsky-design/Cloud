"""Fetch an aerial-image mosaic of a local-metre box from a tile provider.

usage: fetch_mosaic.py PROVIDER Z WEST SOUTH EAST NORTH OUT.jpg
providers: esri, wayback (latest Esri Wayback release), bing, google
Writes OUT.jpg (north-up, cropped to the box) and OUT.json with the box.
"""
import io, json, math, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
sys.path.insert(0, __import__('os').path.dirname(__file__))
from geo import local_to_tile

prov, z = sys.argv[1], int(sys.argv[2])
W, S, E, N = map(float, sys.argv[3:7]); out = sys.argv[7]

def quadkey(x, y, z):
    return ''.join(str((1 if x & (1 << (i - 1)) else 0) + (2 if y & (1 << (i - 1)) else 0)) for i in range(z, 0, -1))

if prov == 'wayback':
    cfg = json.loads(subprocess.run(['curl', '-sS', 'https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json'], capture_output=True).stdout)
    rel = max(cfg, key=lambda k: cfg[k]['itemTitle'])
    print('wayback release', cfg[rel]['itemTitle'])
URL = {
    'esri': lambda x, y: f'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    'wayback': lambda x, y: f'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/{rel}/{z}/{y}/{x}',
    'bing': lambda x, y: f'https://ecn.t{(x + y) % 4}.tiles.virtualearth.net/tiles/a{quadkey(x, y, z)}.jpeg?g=1',
    'google': lambda x, y: f'https://mt{(x + y) % 4}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
}[prov]

tx0, ty0 = local_to_tile(W, N, z); tx1, ty1 = local_to_tile(E, S, z)
xs, ys = range(int(tx0), int(tx1) + 1), range(int(ty0), int(ty1) + 1)
def get(xy):
    x, y = xy
    r = subprocess.run(['curl', '-sS', '-m', '30', '-A', 'Mozilla/5.0', URL(x, y)], capture_output=True)
    try:
        return xy, Image.open(io.BytesIO(r.stdout)).convert('RGB')
    except Exception:
        return xy, None
with ThreadPoolExecutor(8) as ex:
    tiles = dict(ex.map(get, [(x, y) for y in ys for x in xs]))
ts = next(t.size[0] for t in tiles.values() if t)
img = Image.new('RGB', (len(xs) * ts, len(ys) * ts), (40, 40, 40))
miss = 0
for (x, y), t in tiles.items():
    if t: img.paste(t.resize((ts, ts)), ((x - xs[0]) * ts, (y - ys[0]) * ts))
    else: miss += 1
crop = img.crop((int((tx0 - xs[0]) * ts), int((ty0 - ys[0]) * ts), int((tx1 - xs[0]) * ts), int((ty1 - ys[0]) * ts)))
crop.save(out, quality=90)
json.dump({'west': W, 'south': S, 'east': E, 'north': N, 'w': crop.size[0], 'h': crop.size[1], 'provider': prov, 'z': z}, open(out.replace('.jpg', '.json'), 'w'))
print(prov, crop.size, 'missing tiles', miss)
