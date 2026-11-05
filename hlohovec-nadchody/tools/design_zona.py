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

# north-east side towards R. Dilonga: the existing zig-zag concrete stair complex (OSM ways 30722363 and
# 30722362, 34 + 20 steps, top at the bridge sidewalk) is kept and gets wheel channels for bikes and scooters
stairs = [
    {'id': 'schody_SV', 'steps': 34, 'w': 2.2, 'channels': True,
     'pts': [[-172.3, 139.1], [-171.6, 139.9], [-163.9, 149.0], [-169.2, 153.3], [-167.1, 155.8], [-161.9, 151.9], [-157.6, 157.6]]},
    {'id': 'schody_SV2', 'steps': 20, 'w': 2.0, 'channels': True, 'top': [-163.9, 149.0],
     'pts': [[-163.9, 149.0], [-158.9, 145.4], [-156.5, 147.8], [-161.9, 151.9]]},
]

# south-west side (inbound, towards Nábrežie A. Hlinku and the garden): a natural descent for bikes and
# scooters running down the embankment slope from the cycle path, then under the bridge edge to the riverside road
emb_h = lambda s: max(0.0, H * (1 - s / 95))
desc_sl = [(52, -6.9), (45, -7.4), (38, -8.2), (31, -9.4), (24, -10.8), (17, -12.0), (10, -13.0), (5, -13.6), (0, -14.2), (-6, -14.8),
           (-12, -15.3), (-18, -15.8), (-24, -16.4), (-30, -17.0), (-35, -17.5)]
desc_pts = [r2(C(s, l)) for s, l in desc_sl]
desc_z = [round(emb_h(52) * max(0.0, (s - 5) / 47), 2) for s, l in desc_sl]
branches.append({'id': 'zjazd_JZ', 'style': 'bikepath', 'solid': True, 'w': 3.0, 'pts': desc_pts, 'z': desc_z})
dl = sum(math.dist(desc_pts[i], desc_pts[i + 1]) for i in range(len(desc_pts) - 1))
report['zjazd_JZ'] = dict(length_m=round(dl, 1), drop_m=round(desc_z[0], 2),
                          grade_pct=round(100 * desc_z[0] / sum(math.dist(desc_pts[i], desc_pts[i + 1]) for i in range(5)), 1),
                          buildings_m2=round(LineString(desc_pts).buffer(2.0).intersection(BLD).area, 1))

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
    'branches': branches, 'platforms': platforms, 'access': [], 'piers': piers, 'mast': None, 'zone': zone_items, 'stairs': stairs,
    # peak hour on the bridge: ~1 600 vehicles/h both ways (SSC census 2022: 17 800 vehicles/day on this section)
    'traffic': {'plan': {'HN-SE': 7, 'SE-HN': 7, 'W-SE': 16, 'SE-W': 16, 'HN-W': 13, 'W-HN': 13, 'S-HN': 2, 'SE-S': 2, 'HN-S': 2, 'S-SE': 2, 'S-W': 3, 'W-S': 3}},
    'views': [
        {'key': 'overview', 'label': 'Prehľad', 'pos': [-300, 90, -10], 'target': [-195, 0, 115]},
        {'key': 'sv', 'label': 'Schody SV', 'pos': [-140, 14, 190], 'target': [-165, 2, 150]},
        {'key': 'jz', 'label': 'Zjazd JZ', 'pos': [-150, 12, 80], 'target': [-195, 1, 118]},
        {'key': 'pod', 'label': 'Pod mostom', 'pos': [-230, 3, 150], 'target': [-190, 1.6, 140]},
        {'key': 'park', 'label': 'Park', 'pos': [-270, 12, 120], 'target': [-228, 1, 88]},
    ],
    'video': {'center': [-195, 125], 'radius': 55, 'title': 'Zelená zóna pri moste cez Váh', 'sub': 'Hlohovec · zjazd pre bicykle, schody so žliabkami a oddychová zóna',
              'captions': ['Schodisko k Dilongovej so žliabkami na bicykel a kolobežku',
                           'Prirodzený zjazd z mosta pre bicykle a kolobežky smerom na nábrežie',
                           'Krytá zóna pod mostom so stolmi a lavicami', 'Park so stromami, solárnou pergolou a dažďovými záhradami',
                           'Z mosta rovno na hrádzu a do Parku R. Dilongu'],
              'endcard': {'title': 'Zelená zóna pri moste cez Váh', 'items': ['žliabky na schodisku k Dilongovej', 'zjazd z mosta po svahu násypu pre bicykle a kolobežky', 'krytá zóna pod mostom', 'stromy, lavice, stoly, pergola s fotovoltikou', 'dažďové záhrady pre vodu z mosta'], 'note': 'Ilustračná vizualizácia · vytvoril Lukáš Gajarský'}},
}
json.dump(spec, open(out, 'w'), ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
