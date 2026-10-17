// Camera choreography for the three videos: two first-person walks (one per overpass) and an aerial flight.
import * as THREE from 'three';

const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
const wrapPi = (a) => Math.atan2(Math.sin(a), Math.cos(a));

// ---------------- first-person walk ----------------
class Walk {
  constructor(app) { this.app = app; this.keys = []; this.t = 0; }
  start(p) { this.keys.push({ t: 0, p: p.clone() }); return this; }
  hold(sec) { this.t += sec; this.keys.push({ t: this.t, p: this.keys.at(-1).p.clone() }); return this; }
  to(points, speed = 1.45, stairSpeed = 1.25) {
    for (const q of points) {
      const last = this.keys.at(-1).p;
      const dxz = Math.hypot(q.x - last.x, q.z - last.z), dy = Math.abs(q.y - last.y);
      const stairs = dy / Math.max(dxz, 1e-3) > 0.2;
      const dt = stairs ? dxz / stairSpeed : Math.hypot(dxz, dy) / speed;
      if (dt < 1e-3) continue;
      this.t += dt;
      this.keys.push({ t: this.t, p: q.clone(), stairs });
    }
    return this;
  }
  mark(name) { (this.marks ||= {})[name] = this.t; return this; }

  build(rate = 50) {
    const T = this.t, n = Math.ceil(T * rate) + 1;
    const raw = [];
    let k = 0;
    for (let i = 0; i < n; i++) {
      const t = i / rate;
      while (k < this.keys.length - 2 && this.keys[k + 1].t <= t) k++;
      const a = this.keys[k], b = this.keys[Math.min(k + 1, this.keys.length - 1)];
      const f = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 1;
      raw.push(a.p.clone().lerp(b.p, f));
    }
    // gaussian smoothing in time -> natural acceleration and rounded corners
    const sig = 0.32 * rate, R = Math.ceil(sig * 3);
    const w = []; for (let j = -R; j <= R; j++) w.push(Math.exp(-(j * j) / (2 * sig * sig)));
    const pos = raw.map((_, i) => {
      const acc = new THREE.Vector3(); let ws = 0;
      for (let j = -R; j <= R; j++) { const q = raw[Math.min(n - 1, Math.max(0, i + j))]; acc.addScaledVector(q, w[j + R]); ws += w[j + R]; }
      return acc.multiplyScalar(1 / ws);
    });
    // never sink below the walking surface used by the raw path on stairs (smoothing cuts corners vertically)
    for (let i = 0; i < n; i++) pos[i].y = Math.max(pos[i].y, raw[i].y - 0.05);
    // heading (held while standing), pitch from slope, step phase
    const yaw = new Float32Array(n), pitch = new Float32Array(n), phase = new Float32Array(n), speed = new Float32Array(n);
    let lastYaw = null, ph = 0;
    for (let i = 0; i < n; i++) {
      const a = pos[Math.max(0, i - 5)], b = pos[Math.min(n - 1, i + 25)];
      const dx = b.x - a.x, dz = b.z - a.z, d = Math.hypot(dx, dz);
      if (d > 0.25) lastYaw = Math.atan2(dx, -dz);
      yaw[i] = lastYaw ?? 0;
      const slope = d > 0.2 ? (b.y - a.y) / d : 0;
      pitch[i] = slope > 0.2 ? 0.05 : slope < -0.2 ? -0.22 : -0.06;
      if (i > 0) {
        const s = Math.hypot(pos[i].x - pos[i - 1].x, pos[i].z - pos[i - 1].z);
        const dy = Math.abs(pos[i].y - pos[i - 1].y);
        speed[i] = s * rate;
        ph += (Math.abs(slope) > 0.2 ? dy / 0.16 : s / 0.74);
      }
      phase[i] = ph;
    }
    // first sample has no heading until the walk starts: back-fill
    const firstYaw = yaw.find((v, i) => i > 0 && v !== 0) ?? 0;
    for (let i = 0; i < n && yaw[i] === 0; i++) yaw[i] = firstYaw;
    const unwrap = (arr) => { for (let i = 1; i < arr.length; i++) arr[i] = arr[i - 1] + wrapPi(arr[i] - arr[i - 1]); };
    unwrap(yaw);
    const smooth = (arr, s) => { const r = Math.ceil(s * 3), out = new Float32Array(arr.length); for (let i = 0; i < arr.length; i++) { let a = 0, ws = 0; for (let j = -r; j <= r; j++) { const ww = Math.exp(-(j * j) / (2 * s * s)); a += arr[Math.min(arr.length - 1, Math.max(0, i + j))] * ww; ws += ww; } out[i] = a / ws; } return out; };
    this.yaw = smooth(yaw, 0.45 * rate);
    this.pitch = smooth(pitch, 0.6 * rate);
    this.speed = smooth(speed, 0.3 * rate);
    this.pos = pos; this.phase = phase; this.rate = rate; this.n = n;
    return this;
  }

  sample(t) {
    const f = Math.min(this.n - 1.001, Math.max(0, t * this.rate)), i = Math.floor(f), a = f - i;
    const lerp = (arr) => arr[i] * (1 - a) + arr[i + 1] * a;
    return { pos: this.pos[i].clone().lerp(this.pos[i + 1], a), yaw: lerp(this.yaw), pitch: lerp(this.pitch), phase: lerp(this.phase), speed: lerp(this.speed) };
  }
}

// look overrides: [t0, t1, target(Vector3) | {yaw, pitch}, weight]
function applyLooks(t, eye, yaw, pitch, looks) {
  for (const [t0, t1, tg, wmax = 1] of looks) {
    if (t < t0 - 0.01 || t > t1 + 0.01) continue;
    const ramp = Math.min(1.1, (t1 - t0) / 2);
    const w = wmax * ease((t - t0) / ramp) * (1 - ease((t - (t1 - ramp)) / ramp));
    let ty, tp;
    if (tg.isVector3) { const d = tg.clone().sub(eye); ty = Math.atan2(d.x, -d.z); tp = Math.atan2(d.y, Math.hypot(d.x, d.z)); } else { ty = tg.yaw; tp = tg.pitch; }
    yaw = yaw + wrapPi(ty - yaw) * w;
    pitch = pitch + (tp - pitch) * w;
  }
  return [yaw, pitch];
}

// ---------------- aerial spline (time-aware Hermite) ----------------
function hermiteKeys(keys) {
  const tan = keys.map((k, i) => {
    if (i === 0 || i === keys.length - 1) return { p: new THREE.Vector3(), q: new THREE.Vector3() };
    const a = keys[i - 1], b = keys[i + 1], dt = b.t - a.t;
    return { p: b.pos.clone().sub(a.pos).multiplyScalar(1 / dt), q: b.look.clone().sub(a.look).multiplyScalar(1 / dt) };
  });
  return (t) => {
    let i = 0;
    while (i < keys.length - 2 && keys[i + 1].t <= t) i++;
    const a = keys[i], b = keys[i + 1], h = b.t - a.t;
    const s = Math.min(1, Math.max(0, (t - a.t) / h));
    const h00 = 2 * s ** 3 - 3 * s ** 2 + 1, h10 = s ** 3 - 2 * s ** 2 + s, h01 = -2 * s ** 3 + 3 * s ** 2, h11 = s ** 3 - s ** 2;
    const pos = a.pos.clone().multiplyScalar(h00).addScaledVector(tan[i].p, h10 * h).addScaledVector(b.pos, h01).addScaledVector(tan[i + 1].p, h11 * h);
    const look = a.look.clone().multiplyScalar(h00).addScaledVector(tan[i].q, h10 * h).addScaledVector(b.look, h01).addScaledVector(tan[i + 1].q, h11 * h);
    const fov = a.fov + (b.fov - a.fov) * ease(s);
    return { pos, look, fov };
  };
}

export function buildDirector(app) {
  const G = app.ground;
  const V = (e, n, h = 0) => new THREE.Vector3(e, G(e, -n) + h, -n);
  const H = app.overpasses.hlohova, S = app.overpasses.snp;
  const at = (o, d, u, h = null) => { const p = o.W(d, u); p.y = h === null ? G(p.x, p.z) : h; return p; };
  const deckC = (o, f = 0.5) => { const [d0, d1] = o.site.deck; return at(o, d0 + (d1 - d0) * f, 0, o.paths.yTop + 0.6); };
  const deckEye = (o) => deckC(o).setY(o.paths.yTop - 1.2);
  const EYE = 1.65;
  const videos = {};

  // ---------- video 1: first person, Hlohová overpass ----------
  {
    const A = V(-4.5, 20.8);
    const cross = H.paths.cross;               // west foot -> up -> deck -> east foot
    const iPlat = 5;                           // platform point above the west stair
    const w = new Walk(app).start(A).hold(7.4).mark('go')
      .to([V(1.5, 23.6), V(5.8, 30.0), V(7.6, 37.5), V(8.2, 41.6)], 1.75)
      .to([cross[0], cross[1]], 1.4).mark('stairs')
      .to(cross.slice(2, iPlat + 1)).mark('deck')
      .to([at(H, -2.5, 0, H.paths.yTop)], 1.55).mark('mid').hold(4.8)
      .to([cross[iPlat + 1]], 1.55).mark('down')
      .to(cross.slice(iPlat + 2), 1.4).mark('bottom')
      .to([at(H, 8.4, -19.8)], 1.3).mark('end').hold(6.0);
    w.build();
    const m = w.marks;
    const looks = [
      [0.0, 4.4, deckEye(S)],
      [3.9, 8.6, deckEye(H)],
      [m.go + 2.5, m.stairs - 1.5, deckC(H), 0.55],
      [m.mid - 0.4, m.mid + 2.9, { yaw: Math.atan2(-H.T.x, H.T.z), pitch: -0.32 }],
      [m.mid + 2.5, m.mid + 5.6, { yaw: Math.atan2(H.T.x, -H.T.z), pitch: -0.30 }],
      [m.end - 0.6, w.t, deckC(H, 0.6)],
    ];
    const cues = [
      { t0: 0.4, t1: 6.6, type: 'title', title: 'Nadchod Hlohová', sub: 'pohľad chodca · vizualizácia návrhu' },
      { t0: 0.6, t1: 4.2, type: 'label', key: 'snp' },
      { t0: 4.3, t1: 9.5, type: 'label', key: 'hlohova' },
      { t0: m.stairs - 0.5, t1: m.stairs + 7, type: 'caption', text: 'Schodisko s medzipodestou · 36 schodov' },
      { t0: m.deck + 0.5, t1: m.mid + 5.5, type: 'caption', text: 'Lávka ponad ulicu Hlohová · podjazdná výška 5,0 m' },
      { t0: m.end, t1: w.t, type: 'caption', text: 'Bezpečný prechod ponad ulicu Hlohová' },
    ];
    videos.fpv_hlohova = { duration: Math.ceil(w.t * 10) / 10, kind: 'fpv', walk: w, looks, cues, minimap: true, timeOffset: 11 };
  }

  // ---------- video 2: first person, SNP overpass ----------
  {
    // intro: standing at the roundabout corner from where both overpasses are visible, then a short fade
    const A = V(-4.5, 20.8);
    const intro = new Walk(app).start(A).hold(8.6).build();
    const tj = 8.2;
    const cross = S.paths.cross;               // north foot -> up -> deck -> south foot (park)
    const iPlat = 5;
    const w = new Walk(app).start(at(S, -9.8, -36)).hold(1.6).mark('go')
      .to([at(S, -10.5, -30), at(S, -10.8, -25), at(S, -11.8, -21), at(S, -11.6, -18.2), at(S, -9.6, -16.6)], 1.6)
      .to([cross[0], cross[1]], 1.4).mark('stairs')
      .to(cross.slice(2, iPlat + 1)).mark('deck')
      .to([at(S, -0.8, 0, S.paths.yTop)], 1.55).mark('mid').hold(4.8)
      .to([cross[iPlat + 1]], 1.55).mark('down')
      .to(cross.slice(iPlat + 2), 1.4).mark('bottom')
      .to([at(S, 25.0, -0.6)], 1.3).mark('end').hold(6.0);
    w.build();
    const m = Object.fromEntries(Object.entries(w.marks).map(([k, v]) => [k, v + tj]));
    const total = tj + w.t;
    const looks = [
      [-1.2, 4.6, deckEye(H)],
      [4.1, 8.25, deckEye(S)],
      [tj, m.stairs - 1.5, deckC(S), 0.6],
      [m.mid - 0.4, m.mid + 2.9, { yaw: Math.atan2(-S.T.x, S.T.z), pitch: -0.32 }],
      [m.mid + 2.5, m.mid + 5.6, { yaw: Math.atan2(S.T.x, -S.T.z), pitch: -0.30 }],
      [m.end - 0.6, total, deckC(S, 0.5)],
    ];
    const cues = [
      { t0: 0.4, t1: 6.6, type: 'title', title: 'Nadchod SNP', sub: 'pohľad chodca · vizualizácia návrhu' },
      { t0: 0.6, t1: 4.4, type: 'label', key: 'hlohova' },
      { t0: 4.3, t1: 7.9, type: 'label', key: 'snp' },
      { t0: tj - 0.55, t1: tj + 0.55, type: 'fade' },
      { t0: m.stairs - 0.5, t1: m.stairs + 7, type: 'caption', text: 'Schodisko s medzipodestou · 36 schodov' },
      { t0: m.deck + 0.5, t1: m.mid + 5.5, type: 'caption', text: 'Lávka ponad ulicu SNP · podjazdná výška 5,0 m' },
      { t0: m.end, t1: total, type: 'caption', text: 'Bezpečný prechod ponad ulicu SNP' },
    ];
    videos.fpv_snp = { duration: Math.ceil(total * 10) / 10, kind: 'fpv', walks: [[0, intro], [tj, w]], looks, cues, minimap: true, timeOffset: 37 };
  }

  // ---------- video 3: aerial flight ----------
  {
    const c = new THREE.Vector3(40, G(40, 0), -5);
    const hC = deckC(H), sC = deckC(S);
    const K = (t, p, l, fov = 50) => ({ t, pos: p, look: l, fov });
    const orbit = (ang, r, alt) => new THREE.Vector3(c.x + r * Math.cos(ang), c.y + alt, c.z + r * Math.sin(ang));
    const keys = [
      K(0, new THREE.Vector3(-900, 720, 1150), c.clone().setY(c.y + 20), 45),
      K(8, new THREE.Vector3(-260, 260, 330), c.clone(), 48),
      K(13, orbit(2.35, 190, 120), c.clone(), 50),
      K(18, orbit(1.55, 185, 105), c.clone(), 50),
      K(23, orbit(0.75, 180, 95), c.clone(), 50),
      K(29, H.W(2, -62).setY(hC.y + 22), hC.clone().setY(hC.y - 2), 52),
      K(34, H.W(0.5, -30).setY(hC.y + 2.5), hC.clone().setY(hC.y - 1), 58),
      K(38, H.W(1.0, -12).setY(G(H.W(1, -12).x, H.W(1, -12).z) + 3.0), H.W(0, 12).setY(hC.y - 1.5), 62),
      K(41.5, H.W(1.0, 10).setY(G(H.W(1, 10).x, H.W(1, 10).z) + 3.4), H.W(0, 40).setY(hC.y), 62),
      K(45.5, H.W(-4, 34).setY(hC.y + 16), c.clone().setY(c.y + 5), 56),
      K(50.5, S.W(-40, 12).setY(sC.y + 34), sC.clone(), 54),
      K(55, S.W(-22, 22).setY(sC.y + 6), sC.clone().setY(sC.y - 1.5), 58),
      K(59.5, S.W(1.5, 27).setY(sC.y + 3.5), sC.clone().setY(sC.y - 1.5), 58),
      K(64, S.W(6.3, -24).setY(G(S.W(6.3, -24).x, S.W(6.3, -24).z) + 1.7), sC.clone().setY(sC.y - 0.5), 62),
      K(70, orbit(-1.2, 260, 210), c.clone(), 50),
      K(76, orbit(-1.7, 420, 330), c.clone(), 48),
    ];
    const curve = hermiteKeys(keys);
    const cues = [
      { t0: 0.6, t1: 7.4, type: 'title', title: 'Hlohovec · dva nové nadchody', sub: 'ulica Hlohová a ulica SNP pri kruhovom objazde' },
      { t0: 9.0, t1: 27.5, type: 'label', key: 'hlohova' },
      { t0: 9.0, t1: 27.5, type: 'label', key: 'snp' },
      { t0: 30, t1: 37.5, type: 'caption', text: 'Nadchod Hlohová · lávka ponad cestu II/507' },
      { t0: 37.5, t1: 43, type: 'caption', text: 'Podjazdná výška 5,0 m – bez obmedzenia autobusov a nákladnej dopravy' },
      { t0: 51, t1: 64.5, type: 'caption', text: 'Nadchod SNP · schodisko do parku a pozdĺž chodníka' },
      { t0: 65.5, t1: 69.2, type: 'label', key: 'hlohova' },
      { t0: 65.5, t1: 69.2, type: 'label', key: 'snp' },
      { t0: 69.0, t1: 76, type: 'endcard' },
    ];
    videos.aerial = { duration: 76, kind: 'aerial', curve, cues, minimap: false, timeOffset: 23 };
  }

  const tmpF = new THREE.Vector3();
  function apply(name, t) {
    const v = videos[name];
    const cam = app.camera;
    const info = { steps: [] };
    if (v.kind === 'fpv') {
      let seg = [0, v.walk];
      for (const sg of v.walks || []) if (t >= sg[0]) seg = sg;
      const s = seg[1].sample(t - seg[0]);
      const eye = s.pos.clone(); eye.y += EYE;
      let [yaw, pitch] = applyLooks(t, eye, s.yaw, s.pitch, v.looks);
      // head bob scaled by walking speed
      const amp = Math.min(1, s.speed / 1.2);
      const bob = 0.032 * amp * (0.5 - 0.5 * Math.cos(2 * Math.PI * s.phase));
      const sway = 0.016 * amp * Math.sin(Math.PI * s.phase);
      const right = new THREE.Vector3(Math.cos(yaw), 0, Math.sin(yaw));
      // keep right on stairs and the deck so oncoming walkers pass on the left
      const keepRight = s.pos.y - G(s.pos.x, s.pos.z) > 0.3 ? 0.45 : 0.0;
      eye.y += bob; eye.addScaledVector(right, sway + keepRight);
      cam.position.copy(eye);
      tmpF.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
      cam.lookAt(eye.clone().add(tmpF));
      cam.fov = 56; cam.near = 0.08; cam.far = 20000;
      app.setShadowFocus(eye.clone().addScaledVector(tmpF.setY(0).normalize(), 22), 48);
      info.phase = s.phase; info.onDeck = s.pos.y - G(s.pos.x, s.pos.z) > 0.25;
    } else {
      const k = v.curve(t);
      k.pos.y = Math.max(k.pos.y, G(k.pos.x, k.pos.z) + 1.5);   // spline overshoot must never dip under the ground
      cam.position.copy(k.pos); cam.lookAt(k.look); cam.fov = k.fov;
      const hgt = k.pos.y - G(k.pos.x, k.pos.z);
      cam.near = Math.min(4, Math.max(0.2, hgt * 0.015)); cam.far = 30000;
      const dist = k.pos.distanceTo(k.look);
      app.setShadowFocus(k.look, Math.min(420, Math.max(45, dist * 0.75)));
    }
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    app.setTime(t + v.timeOffset, cam.position);
    info.cars = app.traffic.nearby(cam.position, 90, cam);
    info.cam = [cam.position.x, cam.position.y, cam.position.z].map((x) => +x.toFixed(2));
    return info;
  }

  return { videos, apply, deckC };
}
