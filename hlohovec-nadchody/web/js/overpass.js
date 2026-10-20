// Parametric pedestrian overpass in the style of the reference sketch:
// brown deck and steps, grey steel railings with horizontal bars,
// each side = open upper flight on saw-tooth stringers -> landing -> wide solid lower flight.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

export const DESIGN = {
  clearance: 5.0,        // free height above the road (m)
  fascia: 0.9,           // depth of the brown deck beams
  deckW: 3.0,            // deck width
  risers: 36,            // total steps from ground to deck
  upper: 18,             // risers in the upper (open) flight
  tread: 0.30,
  upperW: 2.2,
  lowerW: 3.2,
  landingLen: 2.0,
  railH: 1.15,
};
DESIGN.H = DESIGN.clearance + DESIGN.fascia - 0.15; // walking surface above road

function plankTexture() {
  const c = document.createElement('canvas');
  c.width = 512; c.height = 512;
  const g = c.getContext('2d');
  g.fillStyle = '#5e3820'; g.fillRect(0, 0, 512, 512);
  const boards = 16;
  for (let i = 0; i < boards; i++) {
    const y = (i * 512) / boards;
    const l = 0.85 + Math.random() * 0.3;
    g.fillStyle = `rgb(${Math.round(138 * l)},${Math.round(90 * l)},${Math.round(56 * l)})`;
    g.fillRect(0, y + 2, 512, 512 / boards - 4);
    for (let k = 0; k < 40; k++) { // grain
      g.strokeStyle = `rgba(60,35,18,${0.05 + Math.random() * 0.08})`;
      g.beginPath(); const yy = y + 3 + Math.random() * (512 / boards - 6);
      g.moveTo(0, yy); g.bezierCurveTo(170, yy + Math.random() * 3 - 1.5, 340, yy + Math.random() * 3 - 1.5, 512, yy); g.stroke();
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

export function makeMaterials() {
  const planks = plankTexture();
  return {
    brown: new THREE.MeshStandardMaterial({ color: 0x6e4126, roughness: 0.7, metalness: 0.15 }),
    brownTop: new THREE.MeshStandardMaterial({ color: 0x8e5c37, roughness: 0.85 }),
    deck: new THREE.MeshStandardMaterial({ color: 0xffffff, map: planks, roughness: 0.8 }),
    metal: new THREE.MeshStandardMaterial({ color: 0xb8bdc2, roughness: 0.32, metalness: 0.75 }),
    steel: new THREE.MeshStandardMaterial({ color: 0x8d949a, roughness: 0.45, metalness: 0.55 }),
    concrete: new THREE.MeshStandardMaterial({ color: 0xb3ada3, roughness: 0.95 }),
    paving: new THREE.MeshStandardMaterial({ color: 0xa89c84, roughness: 0.95 }),
    led: new THREE.MeshStandardMaterial({ color: 0xfff1d6, emissive: 0xffe2b0, emissiveIntensity: 0.0, roughness: 0.4 }),
    glass: new THREE.MeshStandardMaterial({ color: 0xa9c4d4, transparent: true, opacity: 0.3, roughness: 0.06, metalness: 0.2, depthWrite: false }),
  };
}

const Y = new THREE.Vector3(0, 1, 0);

export class Overpass {
  constructor(key, site, groundAt, mats) {
    this.key = key;
    this.site = site;
    this.mats = mats;
    this.groundAt = groundAt;           // (x, z) -> y
    const [te, tn] = site.t;
    this.T = new THREE.Vector3(te, 0, -tn).normalize();       // along the road
    this.N = new THREE.Vector3(tn, 0, te).normalize();        // across the road (deck axis)
    this.O = new THREE.Vector3(site.c[0], 0, -site.c[1]);
    this.O.y = groundAt(this.O.x, this.O.z);
    this.y0 = this.O.y;
    this.parts = {};
    this.footprint = [];   // [cx, cz, halfLen, halfWid, dirX, dirZ] rectangles (for clearing trees)
    this.paths = {};
    this.group = new THREE.Group();
    this.group.name = key;
    this.build();
  }

  // overpass-local (d across road, u along road) -> world XZ
  W(d, u) { return this.O.clone().addScaledVector(this.N, d).addScaledVector(this.T, u).setY(0); }
  dirW(dd, du) { return new THREE.Vector3().addScaledVector(this.N, dd).addScaledVector(this.T, du).normalize(); }

  add(key, geo) { (this.parts[key] ||= []).push(geo); }

  // box centred at world point c, x-axis along horizontal dir D
  box(key, c, D, len, wid, hgt) {
    const g = new THREE.BoxGeometry(len, hgt, wid);
    const m = new THREE.Matrix4().makeBasis(D, Y, new THREE.Vector3().crossVectors(D, Y)).setPosition(c);
    g.applyMatrix4(m);
    this.add(key, g);
  }

  tube(key, a, b, r) {
    const d = new THREE.Vector3().subVectors(b, a);
    const len = d.length();
    const g = new THREE.CylinderGeometry(r, r, len, 8, 1, false);
    g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(Y, d.normalize()));
    g.translate((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2);
    this.add(key, g);
  }

  // railing between two walking-surface points (world, y = walking level)
  railing(a, b, opts = {}) {
    const h = opts.h ?? DESIGN.railH;
    const len = a.distanceTo(b);
    const n = Math.max(1, Math.ceil(len / (opts.spacing ?? 1.6)));
    for (let i = 0; i <= n; i++) {
      if ((i === 0 && opts.skipFirst) || (i === n && opts.skipLast)) continue;
      const p = a.clone().lerp(b, i / n);
      this.tube('metal', p, p.clone().setY(p.y + h), 0.032);
    }
    const up = (k) => [a.clone().setY(a.y + k), b.clone().setY(b.y + k)];
    this.tube('metal', ...up(h), 0.04);                     // hand rail
    for (const k of [0.22, 0.44, 0.66, 0.88]) this.tube('metal', ...up(k * h), 0.018); // horizontal bars
  }

  column(c, top) {
    const base = this.groundAt(c.x, c.z);
    this.box('steel', new THREE.Vector3(c.x, (base + top) / 2, c.z), this.N, 0.36, 0.36, top - base);
    this.box('concrete', new THREE.Vector3(c.x, base + 0.08, c.z), this.N, 0.9, 0.9, 0.3);
  }

  // Staircase starting at the top edge point S (world, at deck level), descending along D.
  // Returns walking path points (world) from top to bottom.
  stair(S, D, opts = {}) {
    const { H, risers, upper, tread: g, upperW, lowerW, landingLen } = { ...DESIGN, ...opts };
    const yTop = this.y0 + H;
    const r = H / risers;
    const L = new THREE.Vector3().crossVectors(D, Y).normalize();
    const at = (s, l, y) => S.clone().addScaledVector(D, s).addScaledVector(L, l).setY(y);
    const path = [at(0, 0, yTop)];

    // --- upper flight: open treads on saw-tooth stringers
    const runU = (upper - 1) * g;
    for (let i = 1; i < upper; i++) {
      const y = yTop - i * r;
      this.box('brownTop', at((i - 0.5) * g, 0, y - 0.03), D, g + 0.04, upperW - 0.1, 0.06);
    }
    const yL = yTop - upper * r;
    const shape = new THREE.Shape();
    shape.moveTo(0, yTop - this.y0 + 0.02);
    for (let i = 1; i < upper; i++) {
      shape.lineTo((i - 1) * g, yTop - i * r - this.y0);
      shape.lineTo(i * g, yTop - i * r - this.y0);
    }
    shape.lineTo(runU, yL - this.y0);
    shape.lineTo(runU, yL - this.y0 - 0.42);
    shape.lineTo(0.0, yTop - this.y0 - 0.55);
    shape.closePath();
    for (const side of [-1, 1]) {
      const sg = new THREE.ExtrudeGeometry(shape, { depth: 0.07, bevelEnabled: false });
      const m = new THREE.Matrix4().makeBasis(D, Y, L).setPosition(at(0, side * (upperW / 2) - 0.035, this.y0));
      sg.applyMatrix4(m);
      this.add('brown', sg);
    }
    path.push(at(runU, 0, yL));

    // --- landing (solid block, wider) + lower solid flight
    const yLand = yL;
    const s0 = runU, s1 = runU + landingLen;
    const base = this.groundAt(at(s1, 0, 0).x, at(s1, 0, 0).z) - 0.4;
    this.box('brown', at((s0 + s1) / 2, 0, (yLand - 0.05 + base) / 2), D, landingLen, lowerW, yLand - 0.05 - base);
    this.box('brownTop', at((s0 + s1) / 2, 0, yLand - 0.025), D, landingLen + 0.02, lowerW + 0.02, 0.05);
    const lower = risers - upper;
    for (let j = 1; j < lower; j++) {
      const y = yLand - j * r;
      const sa = s1 + (j - 1) * g;
      this.box('brown', at(sa + g / 2, 0, (y - 0.05 + base) / 2), D, g, lowerW, y - 0.05 - base);
      this.box('brownTop', at(sa + g / 2 - 0.01, 0, y - 0.025), D, g + 0.03, lowerW + 0.02, 0.05);
    }
    const sEnd = s1 + (lower - 1) * g;
    path.push(at(s1, 0, yLand), at(sEnd, 0, this.y0), at(sEnd + 1.5, 0, this.y0));

    // --- handrails
    for (const side of [-1, 1]) {
      const lu = side * (upperW / 2 + 0.02), ll = side * (lowerW / 2 - 0.06);
      this.railing(at(0, lu, yTop), at(runU, lu, yL), { spacing: 1.3 });
      this.railing(at(runU, ll, yLand), at(s1, ll, yLand), { spacing: 1.0, skipFirst: true });
      this.railing(at(s1, ll, yLand), at(sEnd, ll, this.y0 + r), { spacing: 1.4 });
      // close the step between upper (narrow) and landing (wide)
      this.railing(at(runU, lu, yLand), at(runU, ll, yLand), { spacing: 1, skipFirst: true, skipLast: true });
    }
    // paving pad at the foot of the stairs
    this.box('paving', at(sEnd + 0.9, 0, this.groundAt(at(sEnd + 0.9, 0, 0).x, at(sEnd + 0.9, 0, 0).z) + 0.02), D, 2.2, lowerW + 1.0, 0.08);
    this.footprint.push([at((sEnd + 2) / 2, 0, 0), D, (sEnd + 3) / 2, lowerW / 2 + 1.5]);
    return path;
  }

  build() {
    const { H, fascia, deckW } = DESIGN;
    const [d0, d1] = this.site.deck;
    const yTop = this.y0 + H;
    const N = this.N, T = this.T;
    const mid = (d0 + d1) / 2, len = d1 - d0;
    const cAt = (d, u, y) => this.W(d, u).setY(y);

    // deck: plank surface, slab and two deep brown fascia beams
    const top = new THREE.PlaneGeometry(len, deckW - 0.3);
    const uv = top.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * len / 2.4, uv.getY(i) * (deckW - 0.3) / 2.4);
    top.rotateX(-Math.PI / 2);
    top.applyMatrix4(new THREE.Matrix4().makeBasis(N, Y, new THREE.Vector3().crossVectors(N, Y)).setPosition(cAt(mid, 0, yTop + 0.005)));
    this.add('deck', top);
    this.box('brown', cAt(mid, 0, yTop - 0.15), N, len, deckW, 0.3);
    for (const s of [-1, 1]) this.box('brown', cAt(mid, s * (deckW / 2 - 0.12), yTop - fascia / 2 + 0.15), N, len, 0.24, fascia);
    // cross girders underneath (visible from the street)
    for (let d = d0 + 0.2; d <= d1 - 0.1; d += 2.0) this.box('brown', cAt(d, 0, yTop - fascia + 0.25), T, deckW - 0.3, 0.16, 0.35);

    const ends = this.site.ends;
    const rl = deckW / 2 - 0.06;
    const pathA = [], pathB = [];
    // ---- end A (d0 side) and end B (d1 side)
    for (const [which, dEnd, sgn] of [['a', d0, -1], ['b', d1, 1]]) {
      const e = ends[which];
      let stairPath;
      if (e.stair === 'axis') {
        const S = cAt(dEnd, 0, yTop);
        stairPath = this.stair(S, N.clone().multiplyScalar(sgn));
        // jog railings in from deck width to stair width
        for (const s of [-1, 1]) this.railing(cAt(dEnd, s * rl, yTop), cAt(dEnd, s * (DESIGN.upperW / 2 + 0.02), yTop), { skipLast: true, skipFirst: true, spacing: 1 });
        this.column(cAt(dEnd - sgn * 0.35, -(deckW / 2 - 0.35), 0), yTop - 0.3);
        this.column(cAt(dEnd - sgn * 0.35, (deckW / 2 - 0.35), 0), yTop - 0.3);
      } else {
        const dir = e.stair === '-t' ? -1 : 1;
        const dp = e.plat;
        const S = cAt(dp, dir * deckW / 2, yTop);
        stairPath = this.stair(S, T.clone().multiplyScalar(dir));
        // end cap railing across the deck end
        this.railing(cAt(dEnd, -rl, yTop), cAt(dEnd, rl, yTop), { spacing: 1.5 });
        // side opening where the stair leaves the platform
        const half = DESIGN.upperW / 2 + 0.02;
        this.railing(cAt(dEnd, dir * rl, yTop), cAt(dp + sgn * half, dir * rl, yTop), { skipLast: true });
        this.column(cAt(dEnd - sgn * 0.35, -(deckW / 2 - 0.35), 0), yTop - 0.3);
        this.column(cAt(dEnd - sgn * 0.35, (deckW / 2 - 0.35), 0), yTop - 0.3);
        // walking path: deck point above the stair -> stair
        stairPath.unshift(cAt(dp, 0, yTop));
      }
      (which === 'a' ? pathA : pathB).push(...stairPath);
    }
    // side railings along the deck with an opening for side-attached stairs
    for (const s of [-1, 1]) {
      let a = d0, b = d1;
      const segs = [];
      const openA = ends.a.stair !== 'axis' && ((ends.a.stair === '-t' ? -1 : 1) === s) ? ends.a.plat + DESIGN.upperW / 2 + 0.02 : null;
      const openB = ends.b.stair !== 'axis' && ((ends.b.stair === '-t' ? -1 : 1) === s) ? ends.b.plat - DESIGN.upperW / 2 - 0.02 : null;
      if (openA !== null) a = openA;
      if (openB !== null) b = openB;
      segs.push([a, b]);
      for (const [x0, x1] of segs) this.railing(cAt(x0, s * rl, yTop), cAt(x1, s * rl, yTop), { spacing: 1.6 });
    }
    this.footprint.push([cAt(mid, 0, 0), N, len / 2 + 0.5, deckW / 2 + 0.5]);

    // full crossing path: bottom A -> up -> deck -> down -> bottom B
    this.paths.cross = [...pathA.slice().reverse(), ...pathB];
    this.paths.yTop = yTop;

    for (const [key, list] of Object.entries(this.parts)) {
      const geo = mergeGeometries(list.map((g) => (g.index ? g.toNonIndexed() : g)).map((g) => { g.deleteAttribute('uv1'); return g; }), false);
      const mesh = new THREE.Mesh(geo, this.mats[key]);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.name = `${this.key}-${key}`;
      this.group.add(mesh);
    }
  }

  // true if world (x,z) is under/near the structure (used to clear trees)
  blocks(x, z, margin = 1.5) {
    for (const [c, D, hl, hw] of this.footprint) {
      const dx = x - c.x, dz = z - c.z;
      const a = dx * D.x + dz * D.z;
      const b = -dx * D.z + dz * D.x;
      if (Math.abs(a) < hl + margin && Math.abs(b) < hw + margin) return true;
    }
    return false;
  }
}
