"""Spider footbridge over the Hlohovec roundabout -> web/data/bigbridge.json (+ checks).

Ring deck over the roundabout hung from a central mast (Hovenring style); level legs to the
two roomy corners (W, S) ending in helical ramps at a constant 5 % (barrier-free, no landings
needed), and switchback stairs with a lift in the two tight corners (N, E).
usage: design_spider.py DATA_DIR OUT_JSON
"""
import json, math, sys
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union

data, out = sys.argv[1], sys.argv[2]
B = unary_union([Polygon(b['outer']).buffer(0) for b in json.load(open(f'{data}/buildings.json'))['buildings'] if len(b['outer']) > 2])
ROADS = unary_union([LineString(r['pts']).buffer(3.3 * max(1, int(r.get('lanes') or 2)) / 2 + 0.6)
                     for r in json.load(open(f'{data}/roads.json'))['roads']
                     if r['hw'] in ('secondary', 'secondary_link', 'tertiary', 'residential', 'unclassified', 'service') and len(r['pts']) > 1
                     and min(math.hypot(*p) for p in r['pts']) < 120 and r['hw'] != 'service'])

CLEAR, DEPTH = 5.0, 0.9            # clearance over the road, structure depth under the walking surface
H = round(CLEAR + DEPTH - 0.15, 2)  # walking height of the level deck (5.75 m)
RING_R, RING_W, LEG_W, RAMP_W = 20.0, 4.0, 3.2, 2.8
GRADE = 0.05                        # VL 4 / TP 048: <=5 % any length, no landings required
pol = lambda r, deg, c=(0, 0): [c[0] + r * math.cos(math.radians(deg)), c[1] + r * math.sin(math.radians(deg))]

def helix(center, R, start_deg, ccw, grade=GRADE, run=None, landing=2.0):
    """Helical ramp: constant grade, or (run set) 9 m runs at `grade` with level landings between them."""
    prof = []                                   # (arc length, height) breakpoints
    s, h = 0.0, H
    if run is None:
        prof = [(0, H), (H / grade, 0)]
    else:
        prof.append((0, H))
        while h > 1e-6:
            dh = min(run * grade, h)
            s += dh / grade; h -= dh; prof.append((s, h))
            if h > 1e-6: s += landing; prof.append((s, h))
    L = prof[-1][0]
    n = int(L / 1.0) + 1
    ks = sorted(set([L * i / n for i in range(n + 1)] + [p[0] for p in prof]))
    pts, z = [], []
    for sv in ks:
        j = max(i for i in range(len(prof)) if prof[i][0] <= sv + 1e-9)
        if j == len(prof) - 1: zz = prof[-1][1]
        else:
            (s0, h0), (s1, h1) = prof[j], prof[j + 1]
            zz = h0 + (h1 - h0) * (sv - s0) / (s1 - s0)
        a = math.radians(start_deg) + (1 if ccw else -1) * sv / R
        pts.append([round(center[0] + R * math.cos(a), 3), round(center[1] + R * math.sin(a), 3)])
        z.append(round(zz, 3))
    return pts, z, L, L / (2 * math.pi * R)

ring = [[round(v, 3) for v in pol(RING_R, i * 360 / 96)] for i in range(96)]
branches = [{'id': 'ring', 'pts': ring, 'closed': True, 'w': RING_W}]
platforms, report = [], {}
# legs to helical ramps: (id, ring angle, helix centre distance from origin, helix radius, turn direction)
for lid, ang, dist, R, ccw, run in [('W', 186, 44.0, 11.0, False, None), ('S', 272, 31.5, 8.0, True, 9.0)]:
    c = pol(dist, ang)
    top = pol(dist - R, ang)                       # helix point nearest the ring
    leg = [pol(RING_R, ang), top]
    branches.append({'id': f'leg_{lid}', 'pts': [[round(v, 3) for v in p] for p in leg], 'w': LEG_W})
    platforms.append({'id': f'pl_{lid}', 'at': [round(v, 3) for v in top], 'r': 2.2})
    pts, z, L, turns = helix(c, R, ang + 180, ccw, 0.08 if run else GRADE, run)
    branches.append({'id': f'ramp_{lid}', 'pts': pts, 'w': RAMP_W, 'z': z})
    foot = LineString(pts).buffer(RAMP_W / 2 + 0.3)
    pitch = H / turns
    report[f'ramp_{lid}'] = dict(length_m=round(L, 1), turns=round(turns, 2), pitch_m=round(pitch, 2), headroom_ok=pitch >= 3.3,
                                max_grade_pct=round(100 * max((z[i] - z[i + 1]) / max(1e-6, math.dist(pts[i], pts[i + 1])) for i in range(len(z) - 1)), 2), buildings_overlap_m2=round(foot.intersection(B).area, 1),
                                road_overlap_m2=round(foot.intersection(ROADS).area, 1), leg_len=round(dist - R - RING_R, 1))
# stairs + lift in the tight corners: (id, ring angle)
access = []
for aid, ang in [('N', 119), ('E', 6)]:
    dp, fp = pol(RING_R + RING_W / 2, ang), pol(RING_R + 12, ang)
    access.append({'id': aid, 'kind': 'stairs+lift', 'deck_point': [round(v, 3) for v in dp], 'foot_point': [round(v, 3) for v in fp], 'flights': 3, 'stair_offset': 3.4})
    tower = Point(pol(RING_R + RING_W / 2 + 5.5, ang)).buffer(6.0)
    report[f'stairs_{aid}'] = dict(buildings_overlap_m2=round(tower.intersection(B).area, 1), road_overlap_m2=round(tower.intersection(ROADS).area, 1))
ring_poly = LineString(ring + [ring[0]]).buffer(RING_W / 2)
report['ring'] = dict(length_m=round(2 * math.pi * RING_R, 1), buildings_overlap_m2=round(ring_poly.intersection(B).area, 1))
walk = 2 * math.pi * RING_R + sum(r.get('length_m', 0) + r.get('leg_len', 0) for r in report.values() if 'leg_len' in r)

spec = {
    'name': 'Lávka „Pavúk“ nad kruhovým objazdom', 'H': H,
    'design': {'clearance': CLEAR, 'fascia': DEPTH, 'deckW': RING_W},
    'branches': branches, 'platforms': platforms, 'access': access, 'piers': [],
    'mast': {'at': [0, 0], 'height': 42, 'cables': 24},
    'video': {
        'center': [-6, -8], 'radius': 46, 'brand': 'návrh lávky',
        'title': 'Lávka „Pavúk“ nad kruhovým objazdom', 'sub': 'Hlohovec · jedna lávka namiesto štyroch zebier',
        'captions': [
            f'Kruhová lávka Ø {2 * RING_R:.0f} m nad kruhovým objazdom, zavesená na stožiari',
            'Podjazdná výška 5,0 m – autá, autobusy aj kamióny jazdia bez zastavenia',
            'Dve točité rampy pre vozíčkarov, kočíky aj bicykle (5 % a 8 % s odpočívadlami)',
            'Pri domoch, kde rampa nemá miesto: schodisko a výťah',
            f'Spolu asi {walk:.0f} m chodníka nad zemou, všetky 4 rohy križovatky prepojené',
        ],
        'endcard': {'title': 'Lávka „Pavúk“ – Hlohovec', 'items': [
            f'kruh Ø {2 * RING_R:.0f} m, šírka 4,0 m, stožiar 42 m a 24 lán',
            'podjazdná výška 5,0 m nad vozovkou',
            f'2 točité rampy: {report["ramp_W"]["length_m"]:.0f} m so sklonom 5 % a {report["ramp_S"]["length_m"]:.0f} m s odpočívadlami',
            '2 schodiská s výťahom (TP 048)',
            'nahrádza 4 zebry pri kruhovom objazde'],
            'note': 'Ilustračná vizualizácia · vytvoril Lukáš Gajarský'},
    },
}
json.dump(spec, open(out, 'w'), ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
print('walkway total m', round(walk, 1), 'H', H)
