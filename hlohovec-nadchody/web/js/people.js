// Pedestrians: animated mannequins walking over the overpasses and along nearby footways.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { fetchBinary } from './world.js';

const CLOTHES = [0x2f4b7c, 0x8c2f39, 0x3c6e47, 0xd9a441, 0x4a4a4a, 0xe6e1d3, 0x6b4f8a, 0x1f6f8b, 0xb5523b, 0x22313f, 0x9aa5ad, 0xc77d8f];

// Build a timed walking path. pts: Vector3 list (walking surface). Stairs are walked slower.
export function timedPath(pts, flatSpeed = 1.35) {
  const t = [0];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    const dh = Math.abs(b.y - a.y), dxz = Math.hypot(b.x - a.x, b.z - a.z);
    const slope = dh / Math.max(dxz, 1e-3);
    const v = slope > 0.2 ? 0.62 : flatSpeed;
    t.push(t[i - 1] + Math.hypot(dxz, dh) / v);
  }
  return { pts, t, T: t[t.length - 1] };
}

export function samplePath(P, tt, out = new THREE.Vector3()) {
  if (tt <= 0) return { pos: out.copy(P.pts[0]), i: 0, f: 0 };
  if (tt >= P.T) return { pos: out.copy(P.pts[P.pts.length - 1]), i: P.pts.length - 2, f: 1 };
  let lo = 0, hi = P.t.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (P.t[m] <= tt) lo = m; else hi = m; }
  const f = (tt - P.t[lo]) / Math.max(1e-6, P.t[hi] - P.t[lo]);
  return { pos: out.copy(P.pts[lo]).lerp(P.pts[hi], f), i: lo, f };
}

export class People {
  async load(url) {
    const gltf = await new GLTFLoader().parseAsync(await fetchBinary(url), '');
    this.src = gltf.scene;
    this.clip = gltf.animations.find((a) => a.name === 'walk');
    this.group = new THREE.Group();
    this.group.name = 'people';
    this.walkers = [];
    return this;
  }

  // loop path: forward then back (no teleporting)
  addWalker(pts, phase, colorIdx, speed = 1.35, tag = null) {
    const loop = [...pts, ...pts.slice(0, -1).reverse()];
    const P = timedPath(loop, speed);
    const obj = SkeletonUtils.clone(this.src);
    obj.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true; o.receiveShadow = true; o.frustumCulled = true;
        o.material = o.material.clone();
        if (o.material.name.includes('Surface') || o.name.includes('Surface')) o.material.color.setHex(CLOTHES[colorIdx % CLOTHES.length]);
        else o.material.color.setHex(0xdcdcdc);
        o.material.roughness = 0.65; o.material.metalness = 0.05;
      }
    });
    const s = 0.92 + ((colorIdx * 37) % 17) / 100;
    obj.scale.setScalar(s);
    const mixer = new THREE.AnimationMixer(obj);
    const act = mixer.clipAction(this.clip);
    act.play();
    this.group.add(obj);
    this.walkers.push({ obj, mixer, act, P, phase, speed, tag });
  }

  // walkers of a hidden design variant stay invisible
  setTag(tag, on) { (this.hidden ||= new Set())[on ? 'delete' : 'add'](tag); }

  cull(camPos, maxD = 90) {
    for (const w of this.walkers) {
      const d = w.obj.position.distanceTo(camPos);
      w.obj.visible = d < maxD && d > 2.4 && !(this.hidden && this.hidden.has(w.tag));
    }
  }

  update(time, camPos) {
    const ahead = new THREE.Vector3();
    for (const w of this.walkers) {
      const tt = ((time + w.phase) % w.P.T + w.P.T) % w.P.T;
      const { pos } = samplePath(w.P, tt, w.obj.position);
      samplePath(w.P, Math.min(w.P.T, tt + 0.6), ahead);
      const dx = ahead.x - pos.x, dz = ahead.z - pos.z;
      const L = Math.hypot(dx, dz);
      if (L > 1e-2) {
        w.obj.rotation.y = Math.atan2(dx, dz);
        // keep right (people pass each other on the left)
        pos.x += (-dz / L) * 0.62; pos.z += (dx / L) * 0.62;
      }
      if (camPos && pos.distanceTo(camPos) < 1.6 + 1.0) w.obj.visible = false;
      w.mixer.setTime((time + w.phase) * w.speed / 1.3);
    }
  }
}
