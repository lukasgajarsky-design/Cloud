// Deterministic traffic: cars and buses following prepared lane routes with curvature-based speeds.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

function carBody(len = 4.35, wid = 1.78, h = 1.45) {
  // side profile, x along length (front at +x), y up
  const s = new THREE.Shape();
  const L = len / 2;
  s.moveTo(-L, 0.32);
  s.lineTo(-L, 0.78);
  s.quadraticCurveTo(-L + 0.05, 0.92, -L + 0.35, 0.95);
  s.lineTo(-L + 0.75, 0.98);
  s.lineTo(-L + 1.25, h - 0.02);
  s.quadraticCurveTo(-L + 1.35, h + 0.02, -L + 1.55, h);
  s.lineTo(L - 1.55, h);
  s.lineTo(L - 1.05, 1.0);
  s.lineTo(L - 0.25, 0.86);
  s.quadraticCurveTo(L + 0.02, 0.8, L, 0.55);
  s.lineTo(L, 0.32);
  s.lineTo(-L, 0.32);
  const g = new THREE.ExtrudeGeometry(s, { depth: wid - 0.12, bevelEnabled: true, bevelThickness: 0.06, bevelSize: 0.06, bevelSegments: 2, curveSegments: 6 });
  g.translate(0, 0, -(wid - 0.12) / 2);
  return g;
}

function carGlass(len = 4.35, wid = 1.78, h = 1.45) {
  const L = len / 2;
  const s = new THREE.Shape();
  s.moveTo(-L + 0.82, 1.0);
  s.lineTo(-L + 1.28, h - 0.06);
  s.lineTo(L - 1.58, h - 0.06);
  s.lineTo(L - 1.12, 1.02);
  s.lineTo(-L + 0.82, 1.0);
  const g = new THREE.ExtrudeGeometry(s, { depth: wid - 0.02, bevelEnabled: false });
  g.translate(0, 0, -(wid - 0.02) / 2);
  return g;
}

function wheels(len = 4.35, wid = 1.78) {
  const parts = [];
  for (const x of [len / 2 - 0.85, -len / 2 + 0.8]) for (const z of [wid / 2 - 0.12, -wid / 2 + 0.12]) {
    const g = new THREE.CylinderGeometry(0.33, 0.33, 0.24, 14);
    g.rotateX(Math.PI / 2);
    g.translate(x, 0.33, z);
    parts.push(g);
  }
  return mergeGeometries(parts);
}

function lights(len = 4.35, wid = 1.78, front = true) {
  const parts = [];
  for (const z of [wid / 2 - 0.3, -wid / 2 + 0.3]) {
    const g = new THREE.BoxGeometry(0.06, 0.12, 0.34);
    g.translate(front ? len / 2 + 0.035 : -len / 2 - 0.035, front ? 0.7 : 0.82, z);
    parts.push(g);
  }
  return mergeGeometries(parts);
}

function busBody() {
  const g = new THREE.BoxGeometry(12, 2.85, 2.5, 1, 1, 1);
  g.translate(0, 0.35 + 2.85 / 2, 0);
  return g;
}
function busGlass() {
  const parts = [];
  const side = new THREE.BoxGeometry(10.6, 1.05, 2.52);
  side.translate(-0.3, 2.05, 0);
  parts.push(side);
  const front = new THREE.BoxGeometry(0.05, 1.7, 2.3);
  front.translate(6.01, 1.9, 0);
  parts.push(front);
  return mergeGeometries(parts);
}
function busWheels() {
  const parts = [];
  for (const x of [3.9, -3.4]) for (const z of [1.13, -1.13]) {
    const g = new THREE.CylinderGeometry(0.5, 0.5, 0.3, 14);
    g.rotateX(Math.PI / 2); g.translate(x, 0.5, z); parts.push(g);
  }
  return mergeGeometries(parts);
}

const CAR_COLORS = [0xf2f2f2, 0xe9e9e9, 0x1c1c1e, 0x2b2d31, 0x8d9196, 0xb5b8bb, 0x7a0f14, 0x1f3f6b, 0x3a5e8c, 0x274d32, 0xc8c2b4, 0x5b5f63, 0xd0d3d6, 0x9c1b1b, 0x0f1f3a];

export class Traffic {
  constructor(routes, sampler, opts = {}) {
    this.sampler = sampler;
    this.group = new THREE.Group();
    this.group.name = 'traffic';
    this.routes = {};
    for (const [k, r] of Object.entries(routes)) this.routes[k] = this.prepare(r);
    // vehicles: [routeKey, phase seconds, kind, colour]
    this.vehicles = [];
    let rnd = 1234567;
    const rand = () => ((rnd = (rnd * 16807) % 2147483647) / 2147483647);
    const plan = opts.plan || {
      'HN-SE': 7, 'SE-HN': 7, 'W-SE': 5, 'SE-W': 5, 'HN-W': 4, 'W-HN': 4, 'S-HN': 2, 'SE-S': 2, 'HN-S': 2, 'S-SE': 2, 'S-W': 1, 'W-S': 1,
    };
    for (const [k, count] of Object.entries(plan)) {
      const T = this.routes[k].T;
      const gap = T / count;
      for (let i = 0; i < count; i++) {
        const isBus = (k === 'HN-SE' || k === 'SE-HN') && i === 0;
        this.vehicles.push({ route: k, phase: i * gap + rand() * gap * 0.45 + (k.length * 3.1) % 7, bus: isBus, color: CAR_COLORS[Math.floor(rand() * CAR_COLORS.length)] });
      }
    }
    const cars = this.vehicles.filter((v) => !v.bus), buses = this.vehicles.filter((v) => v.bus);
    const paint = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.28, metalness: 0.55 });
    const glass = new THREE.MeshStandardMaterial({ color: 0x10161c, roughness: 0.05, metalness: 0.9 });
    const tyre = new THREE.MeshStandardMaterial({ color: 0x151515, roughness: 0.85 });
    const head = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff4dd, emissiveIntensity: 0.4 });
    const tail = new THREE.MeshStandardMaterial({ color: 0x8a0000, emissive: 0xff1000, emissiveIntensity: 0.5 });
    this.lightMats = [head, tail];
    const mk = (geo, mat, n, colors) => {
      const m = new THREE.InstancedMesh(geo, mat, n);
      m.castShadow = true; m.receiveShadow = true;
      m.frustumCulled = false;
      if (colors) colors.forEach((c, i) => m.setColorAt(i, new THREE.Color(c)));
      this.group.add(m);
      return m;
    };
    this.carMeshes = [mk(carBody(), paint, cars.length, cars.map((c) => c.color)), mk(carGlass(), glass, cars.length), mk(wheels(), tyre, cars.length), mk(lights(4.35, 1.78, true), head, cars.length), mk(lights(4.35, 1.78, false), tail, cars.length)];
    const busPaint = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35, metalness: 0.3 });
    this.busMeshes = [mk(busBody(), busPaint, buses.length, buses.map(() => 0xeef2f0)), mk(busGlass(), glass, buses.length), mk(busWheels(), tyre, buses.length)];
    this.cars = cars; this.buses = buses;
    this.tmp = { m: new THREE.Matrix4(), q: new THREE.Quaternion(), p: new THREE.Vector3(), s: new THREE.Vector3(1, 1, 1) };
  }

  prepare(r) {
    const pts = r.pts.map(([e, n]) => new THREE.Vector2(e, -n)); // x, z
    const v = r.v;
    const t = [0];
    for (let i = 1; i < pts.length; i++) t.push(t[i - 1] + pts[i].distanceTo(pts[i - 1]) / ((v[i] + v[i - 1]) / 2));
    return { pts, t, T: t[t.length - 1] };
  }

  // position & heading of a vehicle at absolute time
  pose(route, time, out) {
    const R = this.routes[route];
    const tt = ((time % R.T) + R.T) % R.T;
    let lo = 0, hi = R.t.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (R.t[m] <= tt) lo = m; else hi = m; }
    const f = (tt - R.t[lo]) / Math.max(1e-6, R.t[hi] - R.t[lo]);
    const a = R.pts[lo], b = R.pts[hi];
    const x = a.x + (b.x - a.x) * f, z = a.y + (b.y - a.y) * f;
    const j = Math.min(R.pts.length - 1, hi + 2), i = Math.max(0, lo - 2);
    const dir = Math.atan2(-(R.pts[j].y - R.pts[i].y), R.pts[j].x - R.pts[i].x);
    out.x = x; out.z = z; out.y = this.sampler(x, z); out.heading = dir; out.u = tt / R.T;
    return out;
  }

  update(time) {
    const { m, q, p, s } = this.tmp;
    const pose = {};
    const Y = new THREE.Vector3(0, 1, 0);
    const place = (list, meshes) => list.forEach((veh, i) => {
      this.pose(veh.route, time + veh.phase, pose);
      q.setFromAxisAngle(Y, pose.heading);
      p.set(pose.x, pose.y, pose.z);
      m.compose(p, q, s);
      for (const mesh of meshes) mesh.setMatrixAt(i, m);
      veh.pos = p.clone(); veh.heading = pose.heading;
    });
    place(this.cars, this.carMeshes);
    place(this.buses, this.busMeshes);
    for (const mesh of [...this.carMeshes, ...this.busMeshes]) mesh.instanceMatrix.needsUpdate = true;
  }

  // distances from a point to all vehicles (used for audio synthesis)
  nearby(pos, maxD = 80, camera = null) {
    const out = [];
    const right = new THREE.Vector3();
    if (camera) right.setFromMatrixColumn(camera.matrixWorld, 0);
    for (const v of [...this.cars, ...this.buses]) {
      if (!v.pos) continue;
      const d = v.pos.distanceTo(pos);
      if (d >= maxD) continue;
      const pan = camera ? v.pos.clone().sub(pos).normalize().dot(right) : 0;
      out.push([+d.toFixed(2), v.bus ? 1 : 0, +pan.toFixed(2)]);
    }
    return out;
  }
}
