"""Green zone at the town end of the Váh bridge -> web/data/zona.json (+ geometry checks).

Existing bridge (II/513) and its approach embankment, two switchback ramps replacing the
L-shaped stairs (NE side) and adding a second descent (SW side), a covered seating area
under the deck and a small park with trees, benches, tables, a solar pergola and rain gardens.
Heights: bridge sidewalk ~5.0 m above the ground at the stairs (34 risers in OSM way 30722363).
usage: design_zona.py DATA_DIR OUT_JSON
"""
import json, math, sys
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union

data, out = sys.argv[1], sys.argv[2]
BLD = unary_union([Polygon(b['outer']).buffer(0) for b in json.load(open(f'{data}/buildings.json'))['buildings'] if len(b['outer']) > 2])

END = (-175.0, 135.0)                 # town end of the bridge deck (OSM way 5184308)
D = (0.797, -0.604)                   # along the bridge towards town (SE)
NRM = (0.604, 0.797)                  # left of D = north-east side
H = 5.0                               # sidewalk height above the ground at the bridge end
BW = 13.0                             # bridge width incl. both sidewalks
RW = 2.6                              # ramp width
C = lambda s, l=0.0: (END[0] + s * D[0] + l * NRM[0], END[1] + s * D[1] + l * NRM[1])
r2 = lambda p: [round(p[0], 2), round(p[1], 2)]

# existing bridge: level 5.6 m over the river, dropping to 5.0 m at the town end
L_BR = 362.0
br_s = [-L_BR + i * 10 for i in range(int(L_BR / 10) + 1)] + [0.0]
bridge = {'id': 'most', 'style': 'road', 'w': BW, 'pts': [r2(C(s)) for s in br_s],
          'z': [round(H + 0.6 * min(1, -s / 120), 2) for s in br_s]}
piers = [{'at': r2(C(-s)), 'style': 'wall', 'len': BW - 1.0, 'dir': list(NRM)} for s in (44, 88, 132, 176, 220, 264, 308, 352)]
# approach on an earth embankment down to the road level ~95 m towards the roundabout
emb_s = [i * 5 for i in range(20)]
embank = {'id': 'nasyp', 'style': 'road', 'solid': True, 'w': BW, 'pts': [r2(C(s)) for s in emb_s],
          'z': [round(max(0.0, H * (1 - s / 95)), 2) for s in emb_s]}


def switchback(side, legs, leg_len, first_off, s0):
    """Ramp beside the embankment: legs along +-D stacked away from the road, 8 % runs <= 9 m, 2 m landings."""
    grade, run, landing = 0.08, 9.0, 2.0
    pts, z = [], []
    h = H
    lane = RW + 0.7
    for k in range(legs):
        off = side * (first_off + k * lane)
        fwd = k % 2 == 0
        a, b = (s0, s0 + leg_len) if fwd else (s0 + leg_len, s0)
        n = int(leg_len / 1.0)
        seg = []
        for i in range(n + 1):
            s = a + (b - a) * i / n
            seg.append(s)
        # height profile along the leg: runs of 9 m at 8 %, then 2 m level landings
        dist, prev = 0.0, None
        for s in seg:
            if prev is not None:
                step = abs(s - prev)
                pos = dist % (run + landing)
                slope_len = max(0.0, min(step, run - pos)) if pos < run else 0.0
                h = max(0.0, h - grade * slope_len)
                dist += step
            if not pts or pts[-1] != r2(C(s, off)):
                pts.append(r2(C(s, off))); z.append(round(h, 3))
            prev = s
        # level turn landing across to the next leg
        if k < legs - 1:
            pts.append(r2(C(b + (1.2 if fwd else -1.2), off + side * lane / 2))); z.append(round(h, 3))
    return pts, z


branches = [bridge, embank]
platforms, report = [], {}
for name, side in (('SV', 1), ('JZ', -1)):
    # level link from the sidewalk at the bridge end out over the embankment slope
    s_link = -4.0
    a = C(s_link, side * (BW / 2 - 0.4)); b = C(s_link, side * 15.5)
    branches.append({'id': f'spoj_{name}', 'w': RW + 0.4, 'pts': [r2(a), r2(b)]})
    pts, z = switchback(side, 4, 21.0, 15.5, s_link)
    branches.append({'id': f'rampa_{name}', 'w': RW, 'pts': pts, 'z': z})
    foot = LineString(pts).buffer(RW / 2 + 0.5)
    L = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    gr = max((z[i] - z[i + 1]) / max(1e-6, math.dist(pts[i], pts[i + 1])) for i in range(len(z) - 1))
    report[f'rampa_{name}'] = dict(length_m=round(L, 1), end_height=z[-1], max_grade_pct=round(100 * gr, 1),
                                   buildings_m2=round(foot.intersection(BLD).area, 1), end=pts[-1])

# covered seating under the deck, between the abutment and the street under the bridge
under = [C(-12, -4), C(-12, 4), C(-27, 4), C(-27, -4)]
zone_items = {
    'paving': [[r2(p) for p in under],
               [[-266, 96], [-246, 108], [-216, 114], [-209, 104], [-214, 93], [-236, 86], [-262, 86]]],
    'raingardens': [{'at': r2(C(-6, -11)), 'r': [5.0, 2.6], 'rot': 37}, {'at': [-226, 104], 'r': [5.5, 2.6], 'rot': 20},
                    {'at': r2(C(-6, 11.5)), 'r': [4.0, 2.2], 'rot': 37}],
    'pergola': [{'at': [-246, 96], 'len': 14, 'dep': 5, 'rot': 20, 'pv': True}],
    'tables': [r2(C(-16, -1.5)), r2(C(-22, 1.5)), r2(C(-19, -2.5)), [-250, 95], [-243, 98], [-246, 92]],
    'benches': [{'at': r2(C(-14, 3.2)), 'rot': 37}, {'at': r2(C(-24, -3.2)), 'rot': 37}, {'at': [-228, 96], 'rot': 20},
                {'at': [-262, 92], 'rot': 110}, {'at': [-216, 100], 'rot': 20}, {'at': [-150, 162], 'rot': -40}],
    'lamps': [r2(C(-15, 0)), r2(C(-25, 0)), [-258, 88], [-230, 108], [-214, 98]],
    'trees': [[-268, 104], [-258, 112], [-246, 116], [-234, 118], [-222, 116], [-270, 84], [-256, 78], [-242, 80],
              [-228, 82], [-218, 86], [-152, 170], [-142, 166], [-132, 168]],
    'bikes': [{'at': [-220, 108], 'rot': 20, 'n': 6}],
}
# trees must stand on free ground: not in buildings, not on the ramps or under the deck
blocked = unary_union([LineString(b['pts']).buffer(b['w'] / 2 + (3.0 if b.get('solid') else 2.0)) for b in branches] + [BLD.buffer(2.0)])
zone_items['trees'] = [t for t in zone_items['trees'] if not Point(t).buffer(2.0).intersects(blocked)]
report['trees_kept'] = len(zone_items['trees'])
report['pergola_in_buildings'] = Point(-246, 96).buffer(8).intersects(BLD)

spec = {
    'name': 'Zelená zóna pri moste', 'H': H, 'datum': list(END), 'flatten': {'at': [-195, 130], 'r0': 85, 'r1': 140},
    'design': {'clearance': 3.8, 'fascia': 1.2, 'deckW': BW},
    'branches': branches, 'platforms': platforms, 'access': [], 'piers': piers, 'mast': None, 'zone': zone_items,
    'views': [
        {'key': 'overview', 'label': 'Prehľad', 'pos': [-300, 90, -10], 'target': [-195, 0, 115]},
        {'key': 'sv', 'label': 'Rampa SV', 'pos': [-120, 22, 205], 'target': [-160, 2, 145]},
        {'key': 'jz', 'label': 'Rampa JZ', 'pos': [-250, 20, 55], 'target': [-192, 2, 110]},
        {'key': 'pod', 'label': 'Pod mostom', 'pos': [-230, 3, 150], 'target': [-190, 1.6, 140]},
        {'key': 'park', 'label': 'Park', 'pos': [-270, 12, 120], 'target': [-228, 1, 88]},
    ],
    'video': {'center': [-195, 125], 'radius': 55, 'title': 'Zelená zóna pri moste cez Váh', 'sub': 'Hlohovec · rampy namiesto schodov a oddychová zóna',
              'captions': ['Rampy namiesto schodov na oboch stranách mosta – pre kočíky, vozíky aj bicykle',
                           'Krytá zóna pod mostom so stolmi a lavicami', 'Park so stromami, solárnou pergolou a dažďovými záhradami',
                           'Z mosta rovno na hrádzu a do Parku R. Dilongu'],
              'endcard': {'title': 'Zelená zóna pri moste cez Váh', 'items': ['2 rampy so sklonom 8 % a odpočívadlami', 'krytá zóna pod mostom', 'stromy, lavice, stoly, pergola s fotovoltikou', 'dažďové záhrady pre vodu z mosta'], 'note': 'Ilustračná vizualizácia · vytvoril Lukáš Gajarský'}},
}
json.dump(spec, open(out, 'w'), ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
