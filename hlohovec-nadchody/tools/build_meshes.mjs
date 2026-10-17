// Build building wall + roof meshes from buildings.json (straight-skeleton hipped roofs).
// usage: node build_meshes.mjs buildings.json OUT_PREFIX
// Coordinates: three.js frame, X = east, Y = up, Z = -north.
import fs from 'node:fs';
import { createRequire } from 'node:module';
// the wasm bundle is built for browsers only: pretend to be one
globalThis.self = globalThis; globalThis.window = globalThis;
const { SkeletonBuilder } = createRequire(import.meta.url)('straight-skeleton');
import earcut from 'earcut';

const [, , inFile, outPrefix] = process.argv;
const { buildings } = JSON.parse(fs.readFileSync(inFile, 'utf8'));
await SkeletonBuilder.init();

const MAX_ROOF = 6.5;
const walls = { pos: [], uv: [], fac: [] };
const roofs = { pos: [], fac: [] };
const meta = [];
let skFail = 0;

const signedArea = (r) => { let a = 0; for (let i = 0; i < r.length; i++) { const [x1, y1] = r[i], [x2, y2] = r[(i + 1) % r.length]; a += x1 * y2 - x2 * y1; } return a / 2; };
const hash = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return ((h >>> 0) % 997) / 997; };

// uv attribute per wall vertex: (u along this edge, height above ground, edge length, wall height)
function pushWallRing(ring, y0, y1, ground, fac) {
  for (let i = 0; i < ring.length; i++) {
    const [ax, ay] = ring[i], [bx, by] = ring[(i + 1) % ring.length];
    const len = Math.hypot(bx - ax, by - ay);
    if (len < 0.05) continue;
    const A0 = [ax, y0, -ay], B0 = [bx, y0, -by], A1 = [ax, y1, -ay], B1 = [bx, y1, -by];
    // CCW outer ring seen from outside: a -> b with outward normal on the right side
    const v0 = y0 - ground, v1 = y1 - ground;
    const quad = [[A0, 0, v0], [B0, len, v0], [B1, len, v1], [A0, 0, v0], [B1, len, v1], [A1, 0, v1]];
    for (const [p, uu, vv] of quad) { walls.pos.push(...p); walls.uv.push(uu, vv, len, y1 - ground); walls.fac.push(...fac); }
  }
}

function pushFlatRoof(outer, holes, y, fac) {
  const flat = [], holeIdx = [];
  for (const p of outer) flat.push(p[0], p[1]);
  for (const h of holes) { holeIdx.push(flat.length / 2); for (const p of h) flat.push(p[0], p[1]); }
  const tri = earcut(flat, holeIdx);
  for (let i = 0; i < tri.length; i += 3) {
    // earcut returns CW/CCW depending on input; force upward facing (CCW seen from +Y means CW in x,-z)
    const ids = [tri[i], tri[i + 1], tri[i + 2]];
    const [a, b, c] = ids.map((k) => [flat[2 * k], flat[2 * k + 1]]);
    const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const order = cross > 0 ? [a, b, c] : [a, c, b];
    for (const p of order) { roofs.pos.push(p[0], y, -p[1]); roofs.fac.push(...fac); }
  }
}

function pushSkeletonRoof(outer, holes, y, pitch, fac, pyramidal) {
  const close = (r) => [...r.map((p) => [p[0], p[1]]), [r[0][0], r[0][1]]];
  const rings = [close(outer), ...holes.map((h) => close([...h].reverse().reverse()))];
  let sk = null;
  try { sk = SkeletonBuilder.buildFromPolygon(rings); } catch (e) { sk = null; }
  if (!sk) { skFail++; pushFlatRoof(outer, holes, y, fac); return 0; }
  const k = Math.tan((pitch * Math.PI) / 180);
  let maxT = 0; for (const v of sk.vertices) maxT = Math.max(maxT, v[2]);
  const cap = Math.min(MAX_ROOF, maxT * k);
  for (const poly of sk.polygons) {
    const pts = poly.map((i) => sk.vertices[i]);
    const flat = []; for (const p of pts) flat.push(p[0], p[1]);
    const tri = earcut(flat);
    for (let i = 0; i < tri.length; i += 3) {
      let tr = [pts[tri[i]], pts[tri[i + 1]], pts[tri[i + 2]]];
      const cross = (tr[1][0] - tr[0][0]) * (tr[2][1] - tr[0][1]) - (tr[1][1] - tr[0][1]) * (tr[2][0] - tr[0][0]);
      if (cross < 0) tr = [tr[0], tr[2], tr[1]];
      for (const p of tr) { roofs.pos.push(p[0], y + Math.min(cap, p[2] * k), -p[1]); roofs.fac.push(...fac); }
    }
  }
  return cap;
}

// group buildings into spatial cells so the viewer can frustum-cull whole chunks
const CELL = 160;
const cellOf = (b) => { let x = 0, y = 0; for (const p of b.outer) { x += p[0]; y += p[1]; } x /= b.outer.length; y /= b.outer.length; return `${Math.floor(x / CELL)},${Math.floor(y / CELL)}`; };
buildings.forEach((b) => { b._cell = cellOf(b); });
buildings.sort((a, b) => (a._cell < b._cell ? -1 : a._cell > b._cell ? 1 : 0));
const chunks = [];
let cur = null;
for (const b of buildings) {
  if (!cur || cur.cell !== b._cell) {
    if (cur) { cur.walls[1] = walls.pos.length / 3 - cur.walls[0]; cur.roofs[1] = roofs.pos.length / 3 - cur.roofs[0]; }
    cur = { cell: b._cell, walls: [walls.pos.length / 3, 0], roofs: [roofs.pos.length / 3, 0] };
    chunks.push(cur);
  }
  let outer = b.outer, holes = b.holes || [];
  if (signedArea(outer) < 0) outer = [...outer].reverse();
  holes = holes.map((h) => (signedArea(h) > 0 ? [...h].reverse() : h));
  const ground = b.base;
  const top = ground + b.wall;
  const seed = Math.floor(hash(b.id) * 255);
  const fac = [b.style, seed];
  pushWallRing(outer, ground - 3, top, ground, fac);
  for (const h of holes) pushWallRing(h, ground - 3, top, ground, fac);
  let roofH = 0;
  if (b.shape === 'flat') {
    pushFlatRoof(outer, holes, top, fac);
    // parapet ring
    if (b.style !== 4) {
      pushWallRing(outer, top, top + 0.45, ground, [b.style + 10, seed]);
    }
  } else {
    roofH = pushSkeletonRoof(outer, holes, top, b.pitch, fac);
  }
  meta.push({ id: b.id, name: b.name, top: +(top + roofH).toFixed(2) });
}
if (cur) { cur.walls[1] = walls.pos.length / 3 - cur.walls[0]; cur.roofs[1] = roofs.pos.length / 3 - cur.roofs[0]; }

const write = (name, arr, T) => { const a = new T(arr); fs.writeFileSync(`${outPrefix}_${name}.bin`, Buffer.from(a.buffer)); return a.length; };
const info = {
  walls: { count: walls.pos.length / 3, pos: write('walls_pos', walls.pos, Float32Array), uv: write('walls_uv', walls.uv, Float32Array), fac: write('walls_fac', walls.fac, Uint8Array) },
  chunks,
  roofs: { count: roofs.pos.length / 3, pos: write('roofs_pos', roofs.pos, Float32Array), fac: write('roofs_fac', roofs.fac, Uint8Array) },
};
fs.writeFileSync(`${outPrefix}_meshes.json`, JSON.stringify(info));
console.log(info.walls.count, info.roofs.count, chunks.length, 'chunks', 'skeleton failures', skFail);
