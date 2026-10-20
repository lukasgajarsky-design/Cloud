// Long footbridge built from a design spec (deck centrelines, access stairs and lifts, piers, mast)
// in the same style as the short overpasses: brown deck and fascia, grey steel railings.
// Spec: web/data/bigbridge.json, local metres [E, N]; see tools/prep_bigbridge.py.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { Overpass, DESIGN } from './overpass.js';

const Y = new THREE.Vector3(0, 1, 0);
const V = ([e, n], y = 0) => new THREE.Vector3(e, y, -n);
const flat = (v) => new THREE.Vector3(v.x, 0, v.z);

// per-vertex tangent, left normal and mitre scale of a polyline in the XZ plane
function frames(P, closed) {
  const n = P.length, out = [];
  const seg = (a, b) => flat(b).sub(flat(a)).normalize();
  for (let i = 0; i < n; i++) {
    const hasIn = closed || i > 0, hasOut = closed || i < n - 1;
    const dIn = hasIn ? seg(P[(i - 1 + n) % n], P[i]) : seg(P[i], P[i + 1]);
    const dOut = hasOut ? seg(P[i], P[(i + 1) % n]) : dIn.clone();
    const t = dIn.clone().add(dOut).normalize();
    const L = new THREE.Vector3(t.z, 0, -t.x);
    const Lin = new THREE.Vector3(dIn.z, 0, -dIn.x);
    out.push({ t, L, k: Math.min(2, 1 / Math.max(0.5, L.dot(Lin))) });
  }
  return out;
}

export class BigBridge extends Overpass {
  constructor(key, spec, groundAt, mats) {
    super(key, { c: spec.origin || [0, 0], t: [1, 0], spec }, groundAt, mats);
  }

  build() {
    const spec = this.site.spec;
    const d = this.d = { ...DESIGN, ...(spec.design || {}) };
    d.H = d.clearance + d.fascia - 0.15;
    d.risers = Math.round(d.H / 0.16);
    d.upper = Math.ceil(d.risers / 2);
    // level deck: the reference ground is the highest road point under the deck
    let gMax = -Infinity;
    for (const b of spec.branches) for (const p of b.pts) gMax = Math.max(gMax, this.groundAt(p[0], -p[1]));
    this.y0 = gMax;
    const yTop = this.yTop = gMax + d.H;
    this.paths = { yTop, list: [] };

    this.branches = spec.branches.map((b) => {
      const P = b.pts.map((p) => V(p, yTop));
      const closed = !!b.closed;
      const F = frames(P, closed);
      const s = [0];
      for (let i = 1; i < P.length + (closed ? 1 : 0); i++) s.push(s[i - 1] + P[i % P.length].distanceTo(P[i - 1]));
      return { id: b.id, P, F, s, closed, w: b.w || d.deckW, openings: [[], []], capped: [!closed, !closed] };
    });
    for (const p of spec.platforms || []) this.platform(p);
    for (const a of spec.access || []) this.access(a);
    for (const b of this.branches) this.deck(b);
    for (const p of spec.piers || []) this.pier(p);
    if (spec.mast) this.mast(spec.mast);
    this.finish();
  }

  // nearest deck location to a world point: branch, arc length, side (+1 left / -1 right of travel)
  locate(Q) {
    let best = null;
    for (const b of this.branches) {
      const n = b.P.length, m = b.closed ? n : n - 1;
      for (let i = 0; i < m; i++) {
        const A = flat(b.P[i]), B = flat(b.P[(i + 1) % n]);
        const AB = B.clone().sub(A), len = AB.length();
        const u = THREE.MathUtils.clamp(flat(Q).sub(A).dot(AB) / (len * len), 0, 1);
        const C = A.clone().addScaledVector(AB, u);
        const dist = C.distanceTo(flat(Q));
        if (!best || dist < best.dist) {
          const L = new THREE.Vector3(AB.z, 0, -AB.x).normalize();
          best = { b, s: b.s[i] + u * len, dist, C, L, T: AB.normalize(), side: Math.sign(flat(Q).sub(C).dot(L)) || 1, i };
        }
      }
    }
    return best;
  }

  // walking-surface point at arc length s, lateral offset l
  at(b, s, l = 0, y = this.yTop) {
    const n = b.P.length;
    let i = 0;
    while (i < b.s.length - 2 && b.s[i + 1] < s) i++;
    const f = THREE.MathUtils.clamp((s - b.s[i]) / Math.max(1e-6, b.s[i + 1] - b.s[i]), 0, 1);
    const A = b.P[i], B = b.P[(i + 1) % n];
    const p = A.clone().lerp(B, f);
    const L = b.F[i].L.clone().lerp(b.F[(i + 1) % n].L, f).normalize();
    return p.addScaledVector(L, l).setY(y);
  }

  // swept closed profile [[lateral, dy], ...] along a branch (dy relative to the walking surface);
  // faces are wound outwards from the profile centre whatever the profile orientation
  sweep(key, b, profile, opts = {}) {
    const { P, F, closed } = b;
    const n = P.length, m = closed ? n : n - 1;
    const lc = profile.reduce((a, q) => a + q[0], 0) / profile.length, yc = profile.reduce((a, q) => a + q[1], 0) / profile.length;
    const pos = [];
    const pt = (i, [l, dy]) => P[i % n].clone().addScaledVector(F[i % n].L, l * F[i % n].k).setY(this.yTop + dy);
    const tri = (a, c, e, away) => {
      const nrm = new THREE.Vector3().subVectors(c, a).cross(new THREE.Vector3().subVectors(e, a));
      const fc = a.clone().add(c).add(e).divideScalar(3);
      if (nrm.dot(fc.sub(away)) < 0) pos.push(...a.toArray(), ...e.toArray(), ...c.toArray());
      else pos.push(...a.toArray(), ...c.toArray(), ...e.toArray());
    };
    for (let i = 0; i < m; i++) {
      const mid = pt(i, [lc, yc]).lerp(pt(i + 1, [lc, yc]), 0.5);
      for (let j = 0; j < profile.length; j++) {
        const a = profile[j], c = profile[(j + 1) % profile.length];
        const p00 = pt(i, a), p01 = pt(i, c), p10 = pt(i + 1, a), p11 = pt(i + 1, c);
        tri(p00, p10, p11, mid); tri(p00, p11, p01, mid);
      }
    }
    if (!closed && opts.caps !== false) {
      for (const [i, j] of [[0, 1], [n - 1, n - 2]]) {
        const inside = pt(j, [lc, yc]);
        const c0 = pt(i, profile[0]);
        for (let k = 1; k < profile.length - 1; k++) tri(c0, pt(i, profile[k]), pt(i, profile[k + 1]), inside);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.computeVertexNormals();
    g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array((pos.length / 3) * 2), 2));
    this.add(key, g);
  }

  deck(b) {
    const { fascia } = this.d, w = b.w;
    const { P, F, closed } = b;
    const n = P.length, m = closed ? n : n - 1;
    // plank surface with UVs running along the deck, wound to face up
    const pos = [], uv = [], hw = (w - 0.3) / 2;
    const q = (k, l) => P[k % n].clone().addScaledVector(F[k % n].L, l * F[k % n].k).setY(this.yTop + 0.005);
    for (let i = 0; i < m; i++) {
      const u0 = b.s[i] / 2.4, u1 = b.s[i + 1] / 2.4, v0 = -hw / 2.4, v1 = hw / 2.4;
      const A = q(i, -hw), B = q(i + 1, -hw), C = q(i + 1, hw), D = q(i, hw);
      const up = new THREE.Vector3().subVectors(B, A).cross(new THREE.Vector3().subVectors(C, A)).y > 0;
      if (up) { pos.push(...A.toArray(), ...B.toArray(), ...C.toArray(), ...A.toArray(), ...C.toArray(), ...D.toArray()); uv.push(u0, v0, u1, v0, u1, v1, u0, v0, u1, v1, u0, v1); }
      else { pos.push(...A.toArray(), ...C.toArray(), ...B.toArray(), ...A.toArray(), ...D.toArray(), ...C.toArray()); uv.push(u0, v0, u1, v1, u1, v0, u0, v0, u0, v1, u1, v1); }
    }
    const top = new THREE.BufferGeometry();
    top.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    top.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    top.computeVertexNormals();
    this.add('deck', top);
    // slab and two deep fascia beams
    this.sweep('brown', b, [[-w / 2, -0.3], [w / 2, -0.3], [w / 2, 0], [-w / 2, 0]]);
    for (const sd of [-1, 1]) {
      const l0 = sd * (w / 2 - 0.24), l1 = sd * w / 2;
      this.sweep('brown', b, [[Math.min(l0, l1), -fascia + 0.15], [Math.max(l0, l1), -fascia + 0.15], [Math.max(l0, l1), 0.15], [Math.min(l0, l1), 0.15]]);
    }
    // cross girders seen from below
    const total = b.s[b.s.length - 1];
    for (let s = 1; s < total - 0.5; s += 2.0) {
      const c = this.at(b, s, 0, this.yTop - fascia + 0.25);
      const L = this.at(b, s, 1).sub(this.at(b, s, 0)).normalize();
      this.box('brown', c, L, w - 0.3, 0.16, 0.35);
    }
    // railings on both edges, leaving the openings where stairs/lifts join
    const rl = w / 2 - 0.06;
    for (const [k, sd] of [[0, 1], [1, -1]]) {
      const open = b.openings[k].slice().sort((x, y) => x[0] - y[0]);
      const runs = [];
      let s0 = 0;
      for (const [a, c] of open) { if (a > s0 + 0.3) runs.push([s0, a]); s0 = Math.max(s0, c); }
      if (total > s0 + 0.3) runs.push([s0, total]);
      for (const [a, c] of runs) {
        const steps = Math.max(1, Math.ceil((c - a) / 2.0));
        let prev = this.at(b, a, sd * rl);
        for (let i = 1; i <= steps; i++) {
          const cur = this.at(b, a + ((c - a) * i) / steps, sd * rl);
          this.railing(prev, cur, { spacing: 1.6, skipFirst: i > 1 });
          prev = cur;
        }
      }
    }
    // end caps across open deck ends
    if (!b.closed) {
      if (b.capped[0]) this.railing(this.at(b, 0, -rl), this.at(b, 0, rl), { spacing: 1.5 });
      if (b.capped[1]) this.railing(this.at(b, total, -rl), this.at(b, total, rl), { spacing: 1.5 });
    }
    this.footprintAlong(b);
  }

  footprintAlong(b) {
    const n = b.P.length, m = b.closed ? n : n - 1;
    for (let i = 0; i < m; i++) {
      const A = flat(b.P[i]), B = flat(b.P[(i + 1) % n]);
      const D = B.clone().sub(A), len = D.length();
      this.footprint.push([A.clone().add(B).multiplyScalar(0.5), D.normalize(), len / 2 + 0.3, b.w / 2 + 0.5]);
    }
  }

  // flat deck area (hub above the island, lift landing): polygon [[E,N],...] or circle {at, r}
  platform(p) {
    const { fascia } = this.d;
    const pts = p.poly || Array.from({ length: 40 }, (_, i) => [p.at[0] + p.r * Math.cos((i / 40) * Math.PI * 2), p.at[1] + p.r * Math.sin((i / 40) * Math.PI * 2)]);
    const shape = new THREE.Shape(pts.map(([e, n]) => new THREE.Vector2(e, n)));
    const slab = new THREE.ExtrudeGeometry(shape, { depth: fascia, bevelEnabled: false });
    slab.rotateX(-Math.PI / 2);
    slab.translate(0, this.yTop + 0.15 - fascia, 0);
    this.add('brown', slab);
    const top = new THREE.ShapeGeometry(shape);
    top.rotateX(-Math.PI / 2);
    const uv = top.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) / 2.4, uv.getY(i) / 2.4);
    top.translate(0, this.yTop + 0.16, 0);
    this.add('deck', top);
    if (p.rail !== false) {
      const ring = pts.map((q) => V(q, this.yTop));
      for (let i = 0; i < ring.length; i++) {
        const a = ring[i], c = ring[(i + 1) % ring.length];
        if ((p.railSkip || []).some(([e, n, r]) => a.distanceTo(V([e, n], this.yTop)) < r || c.distanceTo(V([e, n], this.yTop)) < r)) continue;
        this.railing(a, c, { spacing: 1.6, skipFirst: i > 0 });
      }
    }
  }

  access(a) {
    const deckPt = V(a.deck_point, this.yTop), foot = V(a.foot_point);
    const loc = this.locate(deckPt);
    const D = flat(foot).sub(flat(deckPt)).normalize();
    const edge = loc ? loc.C.clone().addScaledVector(loc.L, loc.side * loc.b.w / 2).setY(this.yTop) : deckPt;
    const tangential = loc && Math.abs(D.dot(loc.T)) > 0.8 && (loc.s < 0.5 || loc.s > loc.b.s[loc.b.s.length - 1] - 0.5);
    const S = tangential ? flat(loc.C).setY(this.yTop) : edge;
    let width = 0;
    let path;
    if (a.kind.includes('lift')) {
      width = Math.max(width, this.lift(a, loc, S, D));
    }
    if (a.kind.includes('stairs') || a.kind === 'stairs') {
      const off = a.kind.includes('lift') ? (a.stair_offset ?? 0) : 0;
      const S2 = S.clone().addScaledVector(loc ? loc.T : new THREE.Vector3(), off);
      path = a.type === 'dogleg' ? this.dogleg(S2, D, a.turn || 1) : this.stair(S2, D, this.d);
      width = Math.max(width, this.d.upperW + 0.2);
      if (loc) path.unshift(this.at(loc.b, loc.s + off));
    }
    if (a.kind === 'ramp') path = this.ramp(a, S);
    if (loc && width) {
      if (tangential) loc.b.capped[loc.s < 0.5 ? 0 : 1] = false;
      else loc.b.openings[loc.side > 0 ? 0 : 1].push([loc.s - width / 2 + (a.stair_offset || 0) * 0, loc.s + width / 2 + Math.abs(a.stair_offset || 0)]);
    }
    if (path) this.paths.list.push({ id: a.id, pts: path, b: loc && loc.b, s: loc && loc.s });
  }

  // U-shaped stair tower: flight 1 down along D, landing, flight 2 back on the `turn` side
  dogleg(S, D, turn) {
    const d = this.d, g = d.tread, w = d.upperW, r = d.H / d.risers;
    const L = new THREE.Vector3().crossVectors(D, Y).normalize().multiplyScalar(turn);
    const n1 = d.upper, n2 = d.risers - n1;
    const at = (s, l, y) => S.clone().addScaledVector(D, s).addScaledVector(L, l).setY(y);
    const yTop = this.yTop, yL = yTop - n1 * r, base = this.y0 - 0.4;
    const run1 = (n1 - 1) * g, depth = w + 0.2;
    const path = [at(0, 0, yTop)];
    // flight 1: open treads on stringers
    for (let i = 1; i < n1; i++) this.box('brownTop', at((i - 0.5) * g, 0, yTop - i * r - 0.03), D, g + 0.04, w - 0.1, 0.06);
    for (const sd of [-1, 1]) this.tube('brown', at(0, sd * (w / 2 - 0.05), yTop - 0.25), at(run1, sd * (w / 2 - 0.05), yL - 0.25), 0.09);
    // landing spanning both flights
    const lc = (w + 0.3) / 2;
    this.box('brown', at(run1 + depth / 2, lc, yL - 0.2), D, depth, 2 * w + 0.3, 0.4);
    this.box('brownTop', at(run1 + depth / 2, lc, yL - 0.02), D, depth + 0.02, 2 * w + 0.32, 0.04);
    for (const c of [[run1 + depth - 0.2, -w / 2 + 0.2], [run1 + depth - 0.2, w * 1.5 + 0.1], [run1 - 0.2, -w / 2 + 0.2], [run1 - 0.2, w * 1.5 + 0.1]]) {
      const p = at(c[0], c[1], 0);
      this.box('steel', new THREE.Vector3(p.x, (base + yL - 0.4) / 2, p.z), D, 0.24, 0.24, yL - 0.4 - base);
    }
    // flight 2: solid steps back towards the deck
    const l2 = w + 0.3;
    for (let j = 1; j <= n2; j++) {
      const y = yL - j * r, sa = run1 - (j - 1) * g;
      this.box('brown', at(sa - g / 2, l2, (y - 0.05 + base) / 2), D, g, w, y - 0.05 - base);
      this.box('brownTop', at(sa - g / 2, l2, y - 0.025), D, g + 0.03, w + 0.02, 0.05);
    }
    const sEnd = run1 - n2 * g;
    path.push(at(run1, 0, yL), at(run1 + depth / 2, lc, yL), at(run1, l2, yL), at(sEnd, l2, this.y0), at(sEnd - 1.5, l2, this.y0));
    // handrails
    for (const sd of [-1, 1]) {
      this.railing(at(0, sd * (w / 2 + 0.02), yTop), at(run1, sd * (w / 2 + 0.02), yL), { spacing: 1.3 });
      this.railing(at(run1, l2 + sd * (w / 2 - 0.04), yL), at(sEnd + g, l2 + sd * (w / 2 - 0.04), this.y0 + r), { spacing: 1.4 });
    }
    this.railing(at(run1 + depth - 0.06, -w / 2, yL), at(run1 + depth - 0.06, l2 + w / 2, yL), { spacing: 1.2 });
    this.box('paving', at(sEnd - 0.9, l2, this.groundAt(at(sEnd - 0.9, l2, 0).x, at(sEnd - 0.9, l2, 0).z) + 0.02), D, 2.2, w + 1.0, 0.08);
    this.footprint.push([at(run1 / 2, w / 2, 0), D, run1 / 2 + 2.5, w + 1.5]);
    return path;
  }

  // glazed lift shaft beside the deck; returns the width of the deck opening it needs
  lift(a, loc, S, D) {
    const sz = a.size || [2.4, 2.6];
    const c = a.shaft ? V(a.shaft) : S.clone().addScaledVector(D, sz[1] / 2 + 0.6);
    const base = this.groundAt(c.x, c.z), top = this.yTop + 3.4;
    const Dx = D.clone(), Lx = new THREE.Vector3().crossVectors(D, Y).normalize();
    const corner = (u, v) => c.clone().addScaledVector(Dx, u).addScaledVector(Lx, v);
    // steel corner posts and ring beams
    for (const [u, v] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) {
      const p = corner((u * sz[1]) / 2, (v * sz[0]) / 2);
      this.box('steel', new THREE.Vector3(p.x, (base + top) / 2, p.z), Dx, 0.16, 0.16, top - base);
    }
    for (const y of [base + 0.15, this.y0 + 2.6, this.yTop - 0.4, this.yTop + 2.5, top - 0.1]) {
      for (const [u, v, dir, len] of [[0, -1, Dx, sz[1]], [0, 1, Dx, sz[1]], [-1, 0, Lx, sz[0]], [1, 0, Lx, sz[0]]]) {
        const p = corner((u * sz[1]) / 2, (v * sz[0]) / 2);
        this.box('steel', new THREE.Vector3(p.x, y, p.z), dir, len, 0.12, 0.16);
      }
    }
    // glass skin and a solid head with the machine room
    const glass = new THREE.BoxGeometry(sz[1] - 0.1, this.yTop + 2.5 - base, sz[0] - 0.1);
    glass.applyMatrix4(new THREE.Matrix4().makeBasis(Dx, Y, new THREE.Vector3().crossVectors(Dx, Y)).setPosition(c.clone().setY((base + this.yTop + 2.5) / 2)));
    this.add('glass', glass);
    this.box('brown', c.clone().setY(this.yTop + 2.95), Dx, sz[1] + 0.2, sz[0] + 0.2, 0.9);
    this.box('concrete', c.clone().setY(base + 0.1), Dx, sz[1] + 0.8, sz[0] + 0.8, 0.3);
    // short covered link from the deck edge to the lift door
    const door = c.clone().addScaledVector(Dx, -sz[1] / 2);
    const gap = flat(door).distanceTo(flat(S));
    if (gap > 0.2) {
      const mid = flat(S).add(flat(door)).multiplyScalar(0.5);
      this.box('brown', mid.clone().setY(this.yTop - 0.15), Dx, gap + 0.1, 2.0, 0.3);
      this.box('brownTop', mid.clone().setY(this.yTop + 0.02), Dx, gap + 0.1, 1.9, 0.04);
      for (const sd of [-1, 1]) this.railing(flat(S).addScaledVector(Lx, sd * 0.95).setY(this.yTop), flat(door).addScaledVector(Lx, sd * 0.95).setY(this.yTop), { spacing: 1.2 });
    }
    // a paved apron at the ground door
    this.box('paving', c.clone().addScaledVector(Dx, sz[1] / 2 + 1.2).setY(base + 0.02), Dx, 2.0, sz[0] + 0.6, 0.08);
    this.footprint.push([flat(c), Dx, sz[1] / 2 + 2.2, sz[0] / 2 + 1.0]);
    return 2.1;
  }

  ramp() { return null; }

  pier(p) {
    const c = V(p.at);
    const base = this.groundAt(c.x, c.z), topY = this.yTop - this.d.fascia + 0.1;
    const r = p.r || 0.32;
    const col = new THREE.CylinderGeometry(r, r * 1.1, topY - base, 18);
    col.translate(c.x, (base + topY) / 2, c.z);
    this.add('steel', col);
    const cap = new THREE.CylinderGeometry(r * 1.9, r * 1.2, 0.35, 18);
    cap.translate(c.x, topY - 0.17, c.z);
    this.add('steel', cap);
    this.box('concrete', new THREE.Vector3(c.x, base + 0.12, c.z), new THREE.Vector3(1, 0, 0), r * 4, r * 4, 0.35);
    this.footprint.push([flat(c), new THREE.Vector3(1, 0, 0), r + 0.8, r + 0.8]);
  }

  // central mast with stay cables to the inner deck edge (Hovenring style)
  mast(m) {
    const c = V(m.at), base = this.groundAt(c.x, c.z), h = m.height || 30;
    const col = new THREE.CylinderGeometry(0.28, 0.7, h, 20);
    col.translate(c.x, base + h / 2, c.z);
    this.add('steel', col);
    this.box('concrete', new THREE.Vector3(c.x, base + 0.2, c.z), new THREE.Vector3(1, 0, 0), 3.2, 3.2, 0.5);
    const head = new THREE.Vector3(c.x, base + h - 0.6, c.z);
    for (const b of this.branches) {
      const total = b.s[b.s.length - 1];
      const nC = m.cables || 24;
      for (let i = 0; i < nC; i++) {
        const s = ((i + 0.5) / nC) * total;
        const inner = this.at(b, s, 0);
        const side = Math.sign(flat(c).sub(flat(inner)).dot(this.at(b, s, 1).sub(this.at(b, s, 0)))) || 1;
        this.tube('metal', head, this.at(b, s, side * (b.w / 2 + 0.05), this.yTop - 0.2), 0.035);
      }
    }
  }

  finish() {
    for (const [key, list] of Object.entries(this.parts)) {
      const geo = mergeGeometries(list.map((g) => (g.index ? g.toNonIndexed() : g)).map((g) => { g.deleteAttribute('uv1'); if (!g.attributes.uv) g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2)); if (!g.attributes.normal) g.computeVertexNormals(); return g; }), false);
      const mesh = new THREE.Mesh(geo, this.mats[key]);
      mesh.castShadow = key !== 'glass';
      mesh.receiveShadow = key !== 'glass';
      mesh.renderOrder = key === 'glass' ? 2 : 0;
      mesh.name = `${this.key}-${key}`;
      this.group.add(mesh);
    }
    // a representative crossing path: first access -> along the deck -> last access
    const L = this.paths.list;
    if (L.length >= 2) {
      const a = L[0], z = L[L.length - 1];
      const mid = a.b && a.b === z.b ? this.deckRoute(a.b, a.s, z.s) : [];
      this.paths.cross = [...a.pts.slice().reverse(), ...mid, ...z.pts];
    }
  }

  // points along a branch between two arc lengths (the shorter way round on a closed ring)
  deckRoute(b, s0, s1) {
    const total = b.s[b.s.length - 1];
    let len = s1 - s0;
    if (b.closed && Math.abs(len) > total / 2) len -= Math.sign(len) * total;
    const n = Math.max(1, Math.ceil(Math.abs(len) / 2));
    const out = [];
    for (let i = 1; i < n; i++) out.push(this.at(b, (((s0 + (len * i) / n) % total) + total) % total));
    return out;
  }
}
