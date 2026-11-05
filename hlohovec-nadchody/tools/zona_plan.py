"""Site plan of the bridge zone drawn from web/data/zona.json over the Esri orthophoto.

usage: zona_plan.py DATA_DIR(with img_l0.jpg/json) ZONA_JSON OUT.jpg
"""
import json, math, sys
import cv2
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString

data, spec_path, out = sys.argv[1:4]
spec = json.load(open(spec_path))
im = cv2.imread(f'{data}/img_l0.jpg'); m = json.load(open(f'{data}/img_l0.json')); ppm = m['size'] / (m['east'] - m['west'])
W0, W1, S0, S1 = -285, -105, 55, 215
px = lambda e, n: ((e - m['west']) * ppm, (m['north'] - n) * ppm)
x0, y0 = px(W0, S1); x1, y1 = px(W1, S0)
c = im[int(y0):int(y1), int(x0):int(x1)]; sc = 1600 / c.shape[1]
c = cv2.resize(c, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
base = Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)).convert('RGBA')
base = Image.blend(base, Image.new('RGBA', base.size, (255, 255, 255, 255)), 0.22)
P = lambda e, n: ((px(e, n)[0] - x0) * sc, (px(e, n)[1] - y0) * sc)
ov = Image.new('RGBA', base.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
F = lambda s, w='SemiBold': ImageFont.truetype(f'/usr/share/fonts/opentype/inter/Inter-{w}.otf', s)
z = spec['zone']
for poly in z['paving']: d.polygon([P(*q) for q in poly], fill=(214, 200, 176, 200), outline=(150, 130, 100, 255), width=2)
for r in z['raingardens']:
    pts = [(r['at'][0] + r['r'][0] * math.cos(t) * math.cos(math.radians(r['rot'])) - r['r'][1] * math.sin(t) * math.sin(math.radians(r['rot'])),
            r['at'][1] + r['r'][0] * math.cos(t) * math.sin(math.radians(r['rot'])) + r['r'][1] * math.sin(t) * math.cos(math.radians(r['rot']))) for t in [i * math.pi / 16 for i in range(32)]]
    d.polygon([P(*q) for q in pts], fill=(70, 120, 160, 170), outline=(40, 80, 120, 255), width=2)
for b in spec['branches']:
    if b['id'] == 'nasyp':
        d.polygon([P(*q) for q in LineString(b['pts']).buffer(b['w'] / 2 + 6, cap_style=2).exterior.coords], fill=(110, 140, 70, 70))
for b in spec['branches']:
    if b.get('style') == 'road':
        d.polygon([P(*q) for q in LineString(b['pts']).buffer(b['w'] / 2, cap_style=2).exterior.coords], fill=(120, 120, 120, 120), outline=(90, 90, 90, 255), width=2)
for b in spec['branches']:
    if b.get('style') != 'road':
        d.polygon([P(*q) for q in LineString(b['pts']).buffer(b['w'] / 2, cap_style=2, join_style=2).exterior.coords], fill=(166, 98, 52, 235), outline=(110, 60, 30, 255), width=2)
for p in z['pergola']:
    a = math.radians(p['rot']); D = (math.cos(a), math.sin(a)); L = (-D[1], D[0])
    q = [(p['at'][0] + su * p['len'] / 2 * D[0] + sv * p['dep'] / 2 * L[0], p['at'][1] + su * p['len'] / 2 * D[1] + sv * p['dep'] / 2 * L[1]) for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    d.polygon([P(*v) for v in q], fill=(30, 45, 80, 230))
for t in z['trees']:
    x, y = P(*t); r = 3.0 * sc * ppm
    d.ellipse((x - r, y - r, x + r, y + r), fill=(60, 120, 50, 210), outline=(30, 80, 30, 255), width=2)
for t in z['tables']:
    x, y = P(*t); d.rectangle((x - 9, y - 6, x + 9, y + 6), fill=(110, 60, 30, 255))
base = Image.alpha_composite(base, ov); d = ImageDraw.Draw(base)
def tag(x, y, text, col, anchor='la', size=26):
    f = F(size); b = d.textbbox((x, y), text, font=f, anchor=anchor)
    d.rounded_rectangle((b[0] - 10, b[1] - 7, b[2] + 10, b[3] + 7), radius=10, fill=(255, 255, 255, 240), outline=col, width=3)
    d.text((x, y), text, font=f, fill=(28, 33, 29, 255), anchor=anchor)
brown, green, blue, grey = (138, 86, 49, 255), (46, 120, 60, 255), (40, 80, 120, 255), (90, 90, 90, 255)
tag(*P(-282, 205), 'Most cez Váh (II/513)', grey)
tag(*P(-150, 186), 'Rampa SV namiesto schodov', brown)
tag(*P(-150, 178), 'k hrádzi a do Parku R. Dilongu', green, size=22)
tag(*P(-188, 96), 'Rampa JZ', brown)
tag(*P(-282, 136), 'Park: stromy, pergola s fotovoltikou, stoly', green)
tag(*P(-200, 160), 'Krytá zóna pod mostom', brown, size=22)
tag(*P(-158, 108), 'Násyp mosta', grey, size=22)
tag(*P(-238, 126), 'Dažďová záhrada', blue, size=20)
W, H = base.size; f = F(22, 'Medium')
L50 = P(-235, 0)[0] - P(-285, 0)[0]
d.rounded_rectangle((20, H - 66, 120 + L50, H - 18), radius=10, fill=(255, 255, 255, 240))
d.line((36, H - 40, 36 + L50, H - 40), fill=(28, 33, 29, 255), width=6); d.text((48 + L50, H - 53), '50 m', font=f, fill=(28, 33, 29, 255))
d.text((W - 24, H - 22), 'Podklad: © Esri, Maxar, Earthstar Geographics · © prispievatelia OpenStreetMap · návrh orientačný', font=F(18, 'Medium'), fill=(255, 255, 255, 255), anchor='rd')
d.text((W - 24, 24), 'S ↑', font=F(30), fill=(255, 255, 255, 255), anchor='ra')
base.convert('RGB').resize((1400, int(1400 * H / W)), Image.LANCZOS).save(out, quality=86)
print(base.size)
