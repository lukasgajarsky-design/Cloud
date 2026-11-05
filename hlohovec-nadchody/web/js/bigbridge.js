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
    d.H = spec.H || d.clearance + d.fascia - 0.15;
    d.risers = Math.round(d.H / 0.16);
    d.upper = Math.ceil(d.risers / 2);
    // level deck: the reference ground is the highest road point under the deck
    let gMax = -Infinity;
    if (spec.datum) gMax = this.groundAt(spec.datum[0], -spec.datum[1]);
    else for (const b of spec.branches) b.pts.forEach((p, i) => { if (!b.z || b.z[i] >= d.H - 0.01) gMax = Math.max(gMax, this.groundAt(p[0], -p[1])); });
    this.y0 = gMax;
    const yTop = this.yTop = gMax + d.H;
    this.paths = { yTop, list: [] };

    this.branches = spec.branches.map((b) => {
      const P = b.pts.map((p) => V(p, yTop));
      const closed = !!b.closed;
      const F = frames(P, closed);
      // walking-surface height per vertex: level parts at H, ramps from their z profile (the foot snaps to the local ground)
      const Yv = b.pts.map((p, i) => {
        if (!b.z) return yTop;
        const z = b.z[i], g = this.groundAt(p[0], -p[1]);
        if (b.solid) return Math.max(gMax + z, g + 0.05);
        return z <= 0.001 ? g + 0.02 : gMax + z;
      });
      P.forEach((q, i) => q.setY(Yv[i]));
      const s = [0];
      for (let i = 1; i < P.length + (closed ? 1 : 0); i++) s.push(s[i - 1] + flat(P[i % P.length]).distanceTo(flat(P[i - 1])));
      return { id: b.id, P, F, s, closed, sloped: !!b.z, z: b.z, style: b.style, solid: !!b.solid, w: b.w || d.deckW, openings: [[], []], capped: [!closed, !closed], trim: [0, 0] };
    });
    this.joints();
    for (const p of spec.platforms || []) this.platform(p);
    for (const a of spec.access || []) this.access(a);
    for (const b of this.branches) this.deck(b);
    for (const p of spec.piers || []) this.pier(p);
    if (spec.mast) this.mast(spec.mast);
    if (spec.zone) this.furnish(spec.zone);
    this.finish();
  }

  // nearest level-deck location to a world point: branch, arc length, side (+1 left / -1 right of travel)
  locate(Q) {
    let best = null;
    for (const b of this.branches) {
      if (b.sloped) continue;
      const loc = this.locateOn(b, Q);
      if (!best || loc.dist < best.dist) best = loc;
    }
    return best;
  }

  // walking-surface point at arc length s, lateral offset l, dy above the walking surface
  at(b, s, l = 0, dy = 0) {
    const n = b.P.length;
    let i = 0;
    while (i < b.s.length - 2 && b.s[i + 1] < s) i++;
    const f = THREE.MathUtils.clamp((s - b.s[i]) / Math.max(1e-6, b.s[i + 1] - b.s[i]), 0, 1);
    const A = b.P[i], B = b.P[(i + 1) % n];
    const p = A.clone().lerp(B, f);
    const L = b.F[i].L.clone().lerp(b.F[(i + 1) % n].L, f).normalize();
    return p.addScaledVector(L, l).setY(p.y + dy);
  }

  // top of a modelled road deck at (x, z), or -Infinity off the carriageway
  roadSurface(x, z) {
    const Q = new THREE.Vector3(x, 0, z);
    let y = -Infinity;
    for (const b of this.branches) {
      if (b.style !== 'road') continue;
      const l = this.locateOn(b, Q);
      if (l.dist < b.w / 2 - 2.5 && l.s > 0.01 && l.s < b.s[b.s.length - 1] - 0.01) y = Math.max(y, this.at(b, l.s).y + 0.02);
    }
    return y;
  }

  // where an open branch end meets another branch or a platform: open that railing, drop the end cap
  // and keep this branch's own railings off the other deck
  joints() {
    const spec = this.site.spec;
    for (const b of this.branches) {
      if (b.closed) continue;
      for (const end of [0, 1]) {
        const Q = b.P[end ? b.P.length - 1 : 0];
        let hit = null;
        for (const o of this.branches) {
          if (o === b) continue;
          const loc = this.locateOn(o, Q);
          if (loc.dist < o.w / 2 + 1.0 && Math.abs(this.at(o, loc.s).y - Q.y) < 0.3 && (!hit || loc.dist < hit.dist)) hit = { ...loc, o };
        }
        if (hit) {
          b.capped[end] = false;
          (b.joint ||= [null, null])[end] = { o: hit.o, s: hit.s };
          const dir = flat(b.P[end ? b.P.length - 2 : 1]).sub(flat(Q)).normalize();
          if (Math.abs(dir.dot(hit.L)) < 0.5) {
            const oEnd = hit.s < 1 ? 0 : hit.s > hit.o.s[hit.o.s.length - 1] - 1 ? 1 : -1;
            if (oEnd >= 0) hit.o.capped[oEnd] = false;
            continue;
          }
          const sin = Math.max(0.35, Math.abs(dir.dot(hit.L)));
          b.trim[end] = Math.max(0, (hit.o.w / 2 - hit.dist * Math.sign(flat(Q).sub(hit.C).dot(dir) || 1)) / sin);
          const half = b.w / 2 / sin + 0.1;
          const side = Math.sign(dir.dot(hit.L)) || 1;
          hit.o.openings[side > 0 ? 0 : 1].push([hit.s - half, hit.s + half]);
          continue;
        }
        for (const p of spec.platforms || []) {
          const c = p.at ? V(p.at) : null;
          if ((c && flat(Q).distanceTo(c) < p.r + 0.5) || (p.poly && this.inPoly(p.poly, Q))) b.capped[end] = false;
        }
      }
    }
  }

  inPoly(poly, Q) {
    const x = Q.x, y = -Q.z;
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  locateOn(b, Q) {
    let best = null;
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
    return best;
  }

  // swept closed profile [[lateral, dy], ...] along a branch (dy relative to the walking surface);
  // faces are wound outwards from the profile centre whatever the profile orientation
  sweep(key, b, profile, opts = {}) {
    const { P, F, closed } = b;
    const n = P.length, m = closed ? n : n - 1;
    const lc = profile.reduce((a, q) => a + q[0], 0) / profile.length, yc = profile.reduce((a, q) => a + q[1], 0) / profile.length;
    const pos = [];
    const pt = (i, [l, dy]) => P[i % n].clone().addScaledVector(F[i % n].L, l * F[i % n].k).setY(P[i % n].y + dy);
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
    if (b.style === 'road') return this.roadDeck(b);
    const { fascia } = this.d, w = b.w;
    const { P, F, closed } = b;
    const n = P.length, m = closed ? n : n - 1;
    // plank surface with UVs running along the deck, wound to face up
    const pos = [], uv = [], hw = (w - 0.3) / 2;
    const q = (k, l) => P[k % n].clone().addScaledVector(F[k % n].L, l * F[k % n].k).setY(P[k % n].y + 0.005);
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
      const c = this.at(b, s, 0, -fascia + 0.25);
      const L = this.at(b, s, 1).sub(this.at(b, s, 0)).normalize();
      this.box('brown', c, L, w - 0.3, 0.16, 0.35);
    }
    // railings on both edges, leaving the openings where stairs/lifts join
    const rl = w / 2 - 0.06;
    for (const [k, sd] of [[0, 1], [1, -1]]) {
      const open = b.openings[k].slice().sort((x, y) => x[0] - y[0]);
      const runs = [];
      let s0 = b.trim[0];
      const s1 = total - b.trim[1];
      for (const [a, c] of open) { if (a > s0 + 0.3) runs.push([s0, Math.min(a, s1)]); s0 = Math.max(s0, c); }
      if (s1 > s0 + 0.3) runs.push([s0, s1]);
      for (const [a, c] of runs) {
        if (c - a < 0.3) continue;
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
    if (b.sloped && b.style !== 'road') this.rampSupports(b);
    this.footprintAlong(b);
  }

  // existing road bridge / approach: asphalt carriageway between red sidewalks on a concrete box,
  // or (solid) an earth embankment with grassed slopes down to the ground
  roadDeck(b) {
    const w = b.w, hw = w / 2, side = 3.0;
    const strip = (key, l0, l1, dy = 0.01) => this.sweep(key, b, [[l0, dy - 0.02], [l1, dy - 0.02], [l1, dy], [l0, dy]]);
    strip('redway', -hw, -hw + side, 0.15); strip('redway', hw - side, hw, 0.15);
    strip('asphalt', -hw + side, hw - side, 0.0);
    if (b.solid) {
      const { P, F } = b, n = P.length, pos = [];
      const q = (i, l, y) => P[i].clone().addScaledVector(F[i].L, l * F[i].k).setY(y);
      for (let i = 0; i < n - 1; i++) {
        for (const sd of [-1, 1]) {
          const g0 = this.groundAt(P[i].x, P[i].z), g1 = this.groundAt(P[i + 1].x, P[i + 1].z);
          const h0 = Math.max(0, P[i].y - g0), h1 = Math.max(0, P[i + 1].y - g1);
          const a = q(i, sd * hw, P[i].y), c = q(i + 1, sd * hw, P[i + 1].y);
          const a2 = q(i, sd * (hw + 1.6 * h0), g0 - 0.2), c2 = q(i + 1, sd * (hw + 1.6 * h1), g1 - 0.2);
          const up = new THREE.Vector3().subVectors(c, a).cross(new THREE.Vector3().subVectors(a2, a)).dot(F[i].L) * sd > 0;
          if (up) pos.push(...a.toArray(), ...c.toArray(), ...a2.toArray(), ...c.toArray(), ...c2.toArray(), ...a2.toArray());
          else pos.push(...a.toArray(), ...a2.toArray(), ...c.toArray(), ...c.toArray(), ...a2.toArray(), ...c2.toArray());
        }
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.computeVertexNormals();
      g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array((pos.length / 3) * 2), 2));
      this.add('grass', g);
      // kerbs instead of railings on the embankment
      strip('bridgeConcrete', -hw, -hw + 0.3, 0.3); strip('bridgeConcrete', hw - 0.3, hw, 0.3);
    } else {
      this.sweep('bridgeConcrete', b, [[-hw + 1.0, -this.d.fascia], [hw - 1.0, -this.d.fascia], [hw, -0.05], [-hw, -0.05]]);
      for (const sd of [-1, 1]) this.sweep('bridgeConcrete', b, [[sd * hw - (sd > 0 ? 0.35 : 0), -0.4], [sd * hw + (sd > 0 ? 0 : 0.35), -0.4], [sd * hw + (sd > 0 ? 0 : 0.35), 0.25], [sd * hw - (sd > 0 ? 0.35 : 0), 0.25]]);
      const total = b.s[b.s.length - 1], rl = hw - 0.2;
      for (const [k, sd] of [[0, 1], [1, -1]]) {
        const open = b.openings[k].slice().sort((x, y) => x[0] - y[0]);
        let s0 = 0;
        const runs = [];
        for (const [a, c] of open) { if (a > s0 + 0.3) runs.push([s0, a]); s0 = Math.max(s0, c); }
        if (total > s0 + 0.3) runs.push([s0, total]);
        for (const [a, c] of runs) {
          const steps = Math.max(1, Math.ceil((c - a) / 6));
          for (let i = 0; i < steps; i++) this.railing(this.at(b, a + ((c - a) * i) / steps, sd * rl, 0.25), this.at(b, a + ((c - a) * (i + 1)) / steps, sd * rl, 0.25), { spacing: 2.0, h: 1.1, skipFirst: i > 0 });
        }
      }
    }
    this.footprintAlong(b);
    if (b.solid) for (let i = 0; i < b.P.length - 1; i++) {
      const A = flat(b.P[i]), B = flat(b.P[i + 1]);
      const h = Math.max(0, b.P[i].y - this.groundAt(A.x, A.z));
      this.footprint.push([A.clone().add(B).multiplyScalar(0.5), B.clone().sub(A).normalize(), A.distanceTo(B) / 2 + 0.3, b.w / 2 + 1.6 * h + 1.0]);
    }
  }

  // the green zone: paving, rain gardens, solar pergola, picnic tables, benches, lamps, bike racks, trees
  furnish(z) {
    const G = (e, n) => this.groundAt(e, -n);
    const Dir = (deg) => new THREE.Vector3(Math.cos(THREE.MathUtils.degToRad(deg)), 0, -Math.sin(THREE.MathUtils.degToRad(deg)));
    const at = ([e, n], dy = 0) => new THREE.Vector3(e, G(e, n) + dy, -n);
    const local = (c, deg, u, v, y) => { const D = Dir(deg), L = new THREE.Vector3(-D.z, 0, D.x); return c.clone().addScaledVector(D, u).addScaledVector(L, v).setY(c.y + y); };
    for (const poly of z.paving || []) {
      const shape = new THREE.Shape(poly.map(([e, n]) => new THREE.Vector2(e, n)));
      const g = new THREE.ShapeGeometry(shape); g.rotateX(-Math.PI / 2);
      const c = poly.reduce((a, p) => [a[0] + p[0] / poly.length, a[1] + p[1] / poly.length], [0, 0]);
      g.translate(0, G(c[0], c[1]) + 0.06, 0);
      this.add('paving', g);
      const pg = poly.map(([e, n]) => [e, n]);
      const bb = pg.reduce((a, p) => [Math.min(a[0], p[0]), Math.min(a[1], p[1]), Math.max(a[2], p[0]), Math.max(a[3], p[1])], [1e9, 1e9, -1e9, -1e9]);
      this.footprint.push([new THREE.Vector3((bb[0] + bb[2]) / 2, 0, -(bb[1] + bb[3]) / 2), new THREE.Vector3(1, 0, 0), (bb[2] - bb[0]) / 2, (bb[3] - bb[1]) / 2]);
    }
    for (const r of z.raingardens || []) {
      const shape = new THREE.Shape(); shape.absellipse(0, 0, r.r[0], r.r[1], 0, Math.PI * 2, false, 0);
      const g = new THREE.ShapeGeometry(shape, 32); g.rotateX(-Math.PI / 2); g.rotateY(THREE.MathUtils.degToRad(r.rot || 0));
      const c = at(r.at, 0.05); g.translate(c.x, c.y, c.z); this.add('rain', g);
      for (let i = 0; i < 18; i++) {
        const a = (i / 18) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
        const p = local(c, r.rot || 0, r.r[0] * ca, r.r[1] * sa, 0.1);
        const st = new THREE.DodecahedronGeometry(0.28 + (i % 3) * 0.06); st.translate(p.x, p.y, p.z); this.add('concrete', st);
      }
      for (let i = 0; i < 7; i++) { // reeds / perennials
        const p = local(c, r.rot || 0, (Math.sin(i * 2.1) * r.r[0]) / 2, (Math.cos(i * 1.7) * r.r[1]) / 2, 0.35);
        const b = new THREE.IcosahedronGeometry(0.45, 0); b.scale(1, 0.8, 1); b.translate(p.x, p.y, p.z); this.add('leaf', b);
      }
    }
    for (const p of z.pergola || []) {
      const c = at(p.at), D = Dir(p.rot || 0);
      for (const u of [-p.len / 2 + 0.3, 0, p.len / 2 - 0.3]) for (const v of [-p.dep / 2 + 0.3, p.dep / 2 - 0.3]) {
        const q = local(c, p.rot || 0, u, v, 0);
        this.box('steel', q.clone().setY(c.y + 1.4), D, 0.15, 0.15, 2.8 + (v > 0 ? 0.6 : 0));
      }
      // panels tilted towards the south side of the frame
      const roof = new THREE.BoxGeometry(p.len, 0.06, p.dep + 0.4);
      roof.rotateX(THREE.MathUtils.degToRad(-7));
      roof.applyMatrix4(new THREE.Matrix4().makeBasis(D, Y, new THREE.Vector3().crossVectors(D, Y)).setPosition(c.clone().setY(c.y + 3.1)));
      this.add(p.pv ? 'pv' : 'brownTop', roof);
      this.footprint.push([flat(c), D, p.len / 2 + 1, p.dep / 2 + 1]);
    }
    const bench = (c, deg) => {
      const D = Dir(deg);
      this.box('brownTop', local(c, deg, 0, 0, 0.45), D, 1.8, 0.45, 0.06);
      this.box('brownTop', local(c, deg, 0, -0.22, 0.75), D, 1.8, 0.06, 0.35);
      for (const u of [-0.75, 0.75]) this.box('steel', local(c, deg, u, 0, 0.22), D, 0.06, 0.42, 0.45);
    };
    for (const b of z.benches || []) bench(at(b.at), b.rot || 0);
    for (const t of z.tables || []) {
      const c = at(t);
      this.box('brownTop', c.clone().setY(c.y + 0.75), Dir(0), 2.0, 0.8, 0.06);
      for (const u of [-0.8, 0.8]) this.box('steel', local(c, 0, u, 0, 0.37), Dir(0), 0.08, 0.6, 0.74);
      for (const v of [-0.75, 0.75]) this.box('brownTop', local(c, 0, 0, v, 0.45), Dir(0), 2.0, 0.3, 0.05);
    }
    for (const l of z.lamps || []) {
      const c = at(l);
      this.box('steel', c.clone().setY(c.y + 2.0), Dir(0), 0.1, 0.1, 4.0);
      this.box('led', c.clone().setY(c.y + 4.05), Dir(0), 0.5, 0.5, 0.12);
    }
    for (const r of z.bikes || []) {
      const c = at(r.at);
      for (let i = 0; i < r.n; i++) {
        const a = local(c, r.rot || 0, (i - (r.n - 1) / 2) * 0.9, 0, 0);
        const D2 = Dir((r.rot || 0) + 90);
        this.tube('metal', a.clone().addScaledVector(D2, -0.4), a.clone().addScaledVector(D2, -0.4).setY(a.y + 0.8), 0.03);
        this.tube('metal', a.clone().addScaledVector(D2, 0.4), a.clone().addScaledVector(D2, 0.4).setY(a.y + 0.8), 0.03);
        this.tube('metal', a.clone().addScaledVector(D2, -0.4).setY(a.y + 0.8), a.clone().addScaledVector(D2, 0.4).setY(a.y + 0.8), 0.03);
      }
    }
    (z.trees || []).forEach((t, i) => {
      const c = at(t), h = 3.0 + (i % 3) * 0.5, r = 2.0 + (i % 4) * 0.35;
      const trunk = new THREE.CylinderGeometry(0.16, 0.22, h, 8); trunk.translate(c.x, c.y + h / 2, c.z); this.add('bark', trunk);
      for (const [dx, dy, dz, k] of [[0, 0, 0, 1], [0.6, -0.5, 0.4, 0.75], [-0.5, -0.4, -0.5, 0.7]]) {
        const crown = new THREE.IcosahedronGeometry(r * k, 1); crown.scale(1, 0.85, 1);
        crown.translate(c.x + dx * r, c.y + h + r * 0.55 + dy * r, c.z + dz * r); this.add('leaf', crown);
      }
    });
  }

  // ramps stand on single steel columns every <=9 m; near the ground they sit on a solid plinth
  rampSupports(b) {
    const total = b.s[b.s.length - 1], fascia = Math.min(this.d.fascia, 0.75);
    for (let s = Math.max(1.5, b.trim[0] + 1.5); s < total - 0.5; s += 8.5) {
      const top = this.at(b, s, 0, -fascia + 0.15);
      const g = this.groundAt(top.x, top.z);
      if (top.y - g < 0.9) continue;
      const col = new THREE.CylinderGeometry(0.2, 0.24, top.y - g, 12);
      col.translate(top.x, (top.y + g) / 2, top.z);
      this.add('steel', col);
      const L = this.at(b, s, 1).sub(this.at(b, s, 0)).normalize();
      this.box('steel', top.clone().setY(top.y - 0.12), L, b.w - 0.4, 0.3, 0.25);
      this.box('concrete', new THREE.Vector3(top.x, g + 0.1, top.z), L, 1.0, 1.0, 0.3);
    }
    // solid end where the ramp meets the ground
    for (let i = 0; i < b.P.length - 1; i++) {
      const A = b.P[i], B = b.P[i + 1];
      const gA = this.groundAt(A.x, A.z), gB = this.groundAt(B.x, B.z);
      if (Math.max(A.y - gA, B.y - gB) > 1.1) continue;
      const D = flat(B).sub(flat(A)), len = D.length();
      const h = Math.max(0.1, (A.y + B.y) / 2 - (gA + gB) / 2 - 0.05);
      this.box('concrete', flat(A).add(flat(B)).multiplyScalar(0.5).setY((gA + gB) / 2 + h / 2 - 0.05), D.normalize(), len + 0.05, b.w - 0.1, h + 0.1);
    }
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
    slab.translate(0, this.yTop - fascia, 0);
    this.add('brown', slab);
    const top = new THREE.ShapeGeometry(shape);
    top.rotateX(-Math.PI / 2);
    const uv = top.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) / 2.4, uv.getY(i) / 2.4);
    top.translate(0, this.yTop + 0.006, 0);
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
      path = a.type === 'straight' ? this.stair(S2, D, this.d) : this.switchback(S2, D, a.turn || 1, a.flights);
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

  // switchback stair tower (TP 048: risers <=150 mm, <=16 per flight): a short top landing along D,
  // then flights alternating along +D / -D in side-by-side lanes on the `turn` side, landings at each turn
  switchback(S, D, turn, flights) {
    const d = this.d, g = 0.30, w = d.upperW, yTop = this.yTop;
    const nR = Math.ceil(d.H / 0.15), nF = Math.max(flights || 0, Math.ceil(nR / 16)), r = d.H / nR;
    const per = Array.from({ length: nF }, (_, k) => Math.floor(nR / nF) + (k < nR % nF ? 1 : 0));
    const L = new THREE.Vector3().crossVectors(D, Y).normalize().multiplyScalar(turn);
    const lane = w + 0.3, depth = w + 0.2, LT = depth + 0.2, run = (Math.max(...per) - 1) * g;
    const at = (s, l, y) => S.clone().addScaledVector(D, s).addScaledVector(L, l).setY(y);
    const base = this.y0 - 0.3;
    const post = (s, l, y) => { const p = at(s, l, 0); const gy = this.groundAt(p.x, p.z); this.box('steel', new THREE.Vector3(p.x, (gy + y) / 2, p.z), D, 0.2, 0.2, y - gy); };
    // top landing joining the deck
    this.box('brown', at(LT / 2, 0, yTop - 0.15), D, LT, w, 0.3);
    this.box('brownTop', at(LT / 2, 0, yTop + 0.005), D, LT, w - 0.05, 0.02);
    const path = [at(0, 0, yTop), at(LT, 0, yTop)];
    let y = yTop;
    for (let k = 0; k < nF; k++) {
      const fwd = k % 2 === 0, l = k * lane, n = per[k];
      const s0 = fwd ? LT : LT + run, sg = fwd ? 1 : -1;
      const Dk = D.clone().multiplyScalar(sg);
      const yEnd = y - n * r, last = k === nF - 1;
      for (let i = 1; i <= n; i++) {
        const sy = y - i * r, sc = s0 + sg * (i - 0.5) * g;
        if (sy < this.y0 + 1.2 && last) this.box('brown', at(sc, l, (sy - 0.05 + base) / 2), D, g, w, sy - 0.05 - base);
        if (i < n || last) this.box('brownTop', at(sc, l, sy - 0.03), D, g + 0.03, w - 0.05, 0.06);
      }
      const sEnd = s0 + sg * (n - (last ? 0 : 1)) * g;
      for (const sd of [-1, 1]) {
        this.tube('brown', at(s0, l + sd * (w / 2 - 0.05), y - 0.25), at(sEnd, l + sd * (w / 2 - 0.05), yEnd - 0.25), 0.08);
        this.railing(at(s0, l + sd * (w / 2 + 0.02), y), at(sEnd, l + sd * (w / 2 + 0.02), yEnd + (last ? r : 0)), { spacing: 1.3 });
      }
      path.push(at(s0, l, y), at(sEnd, l, yEnd));
      if (!last) {
        // landing spanning this lane and the next at the turn
        const sa = fwd ? LT + run : LT - depth, lc = l + lane / 2;
        this.box('brown', at(sa + depth / 2, lc, yEnd - 0.18), D, depth, 2 * w + 0.3, 0.36);
        this.box('brownTop', at(sa + depth / 2, lc, yEnd + 0.003), D, depth, 2 * w + 0.25, 0.02);
        for (const lp of [l - w / 2 + 0.2, l + lane + w / 2 - 0.2]) for (const sp of [sa + 0.2, sa + depth - 0.2]) post(sp, lp, yEnd - 0.36);
        const edge = fwd ? sa + depth - 0.06 : sa + 0.06;
        this.railing(at(edge, l - w / 2, yEnd), at(edge, l + lane + w / 2, yEnd), { spacing: 1.2 });
        path.push(at(sa + depth / 2, lc, yEnd));
      } else {
        const foot = at(sEnd + sg * 1.6, l, this.y0);
        path.push(foot);
        this.box('paving', foot.clone().setY(this.groundAt(foot.x, foot.z) + 0.02), D, 2.4, w + 1.0, 0.08);
      }
      // posts under the high end of each flight
      if (!last || y - this.y0 > 1.5) post(s0 + sg * 0.3, l, y - 0.35);
      y = yEnd;
    }
    for (const sp of [0.3, LT - 0.3]) post(sp, 0, yTop - 0.3);
    this.footprint.push([at(LT + run / 2, (nF - 1) * lane / 2, 0), D, LT + run / 2 + 2.5, (nF * lane) / 2 + 1.0]);
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
    if (p.style === 'wall') {
      const c = V(p.at), base = this.groundAt(c.x, c.z);
      let best = null;
      for (const b of this.branches) { const l = this.locateOn(b, c); if (!best || l.dist < best.dist) best = { ...l, b }; }
      const top = this.at(best.b, best.s).y - this.d.fascia;
      const D = new THREE.Vector3(p.dir[0], 0, -p.dir[1]).normalize();
      this.box('bridgeConcrete', new THREE.Vector3(c.x, (base - 1 + top) / 2, c.z), D, p.len, 1.4, top - base + 1);
      this.box('bridgeConcrete', new THREE.Vector3(c.x, top - 0.3, c.z), D, p.len + 0.8, 1.9, 0.6);
      return;
    }
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
    const targets = this.branches.filter((b) => (m.to ? m.to.includes(b.id) : b.closed));
    for (const b of targets) {
      const total = b.s[b.s.length - 1];
      const nC = m.cables || 24;
      for (let i = 0; i < nC; i++) {
        const s = ((i + 0.5) / nC) * total;
        const inner = this.at(b, s, 0);
        const side = Math.sign(flat(c).sub(flat(inner)).dot(flat(this.at(b, s, 1)).sub(flat(this.at(b, s, 0))))) || 1;
        this.tube('metal', head, this.at(b, s, side * (b.w / 2 + 0.05), -0.2), 0.035);
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
    // ramps are walkable routes too: from where they leave the deck down to the ground
    for (const b of this.branches) {
      if (!b.sloped || !b.joint) continue;
      const top = b.joint[0] ? 0 : b.joint[1] ? 1 : -1;
      if (top < 0) continue;
      const pts = b.P.map((q) => q.clone());
      if (top === 1) pts.reverse();
      this.paths.list.push({ id: b.id, pts, b: b.joint[top].o, s: b.joint[top].s });
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
