// Static world: terrain draped with multi-resolution satellite imagery, OSM buildings with
// procedural facades and imagery-textured roofs, trees detected from the imagery.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const json = (u) => fetch(u).then((r) => r.json());
// binary files; hosts that only serve text get them base64-encoded as <name>.b64.txt
export async function fetchBinary(u) {
  if (!window.HLOHOVEC_B64) return fetch(u).then((r) => r.arrayBuffer());
  const txt = await fetch(`${u}.b64.txt`).then((r) => r.text());
  const raw = atob(txt.trim());
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}
const bin = (u, T) => fetchBinary(u).then((b) => new T(b));

export async function loadData(base, opts = {}) {
  const [terrainMeta, terrain, l0, l1, l2, meshes, trees, routes, sites] = await Promise.all([
    json(`${base}/terrain.json`), bin(`${base}/terrain_s.bin`, Float32Array),
    json(`${base}/img_l0.json`), json(`${base}/img_l1.json`), json(`${base}/img_l2.json`),
    json(`${base}/city_meshes.json`), json(`${base}/trees.json`), json(`${base}/routes.json`), json(`${base}/sites.json`),
  ]);
  const [wp, wuv, wfac, rp, rfac] = await Promise.all([
    bin(`${base}/city_walls_pos.bin`, Float32Array), bin(`${base}/city_walls_uv.bin`, Float32Array), bin(`${base}/city_walls_fac.bin`, Uint8Array),
    bin(`${base}/city_roofs_pos.bin`, Float32Array), bin(`${base}/city_roofs_fac.bin`, Uint8Array),
  ]);
  const loader = new THREE.TextureLoader();
  const tex = (f) => new Promise((res) => loader.load(`${base}/${f}`, res));
  const [t0, t1, t2, tS, streetsMeta] = await Promise.all([tex(opts.l0 || 'img_l0.jpg'), tex(opts.l1 || 'img_l1.jpg'), tex('img_l2.jpg'), tex('streets.png'), json(`${base}/streets.json`)]);
  return { terrainMeta, terrain, imgMeta: [l0, l1, l2], textures: [t0, t1, t2], streets: { tex: tS, meta: streetsMeta }, walls: { pos: wp, uv: wuv, fac: wfac }, roofs: { pos: rp, fac: rfac }, chunks: meshes.chunks, trees: trees.trees, routes: routes.routes, sites };
}

export function makeGroundSampler(meta, H) {
  const n = meta.n;
  return (x, z) => {
    const e = x, nn = -z;
    const fx = Math.min(n - 1.001, Math.max(0, ((e - meta.west) / (meta.east - meta.west)) * (n - 1)));
    const fy = Math.min(n - 1.001, Math.max(0, ((meta.north - nn) / (meta.north - meta.south)) * (n - 1)));
    const x0 = Math.floor(fx), y0 = Math.floor(fy), ax = fx - x0, ay = fy - y0;
    const i = y0 * n + x0;
    return H[i] * (1 - ax) * (1 - ay) + H[i + 1] * ax * (1 - ay) + H[i + n] * (1 - ax) * ay + H[i + n + 1] * ax * ay;
  };
}

// ---------- satellite-draped material (ground + roofs) ----------
export function makeGeoMaterial(data, renderer, extra = {}, withStreets = false) {
  const aniso = renderer.capabilities.getMaxAnisotropy();
  data.textures.forEach((t, i) => {
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = aniso;
    t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
    t.minFilter = THREE.LinearMipmapLinearFilter;
    t.needsUpdate = true;
  });
  const b = data.imgMeta.map((m) => new THREE.Vector4(m.west, m.south, m.east - m.west, m.north - m.south));
  // Lambert is much cheaper than PBR in software rendering and the photo already carries its own shading
  const mat = new THREE.MeshLambertMaterial({ color: 0xffffff, ...extra });
  const sm = data.streets.meta;
  // SDF texture: no mipmaps (averaged distance fields of thin markings wobble); edges are anti-aliased with fwidth
  data.streets.tex.generateMipmaps = false;
  data.streets.tex.minFilter = THREE.LinearFilter;
  if (withStreets) mat.defines = { GEO_STREETS: 1 };
  mat.userData.kd = { value: 0.62 };
  mat.userData.ke = { value: 0.34 };
  mat.userData.noise = { value: grainTexture() };
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, { tL0: { value: data.textures[0] }, tL1: { value: data.textures[1] }, tL2: { value: data.textures[2] }, bL0: { value: b[0] }, bL1: { value: b[1] }, bL2: { value: b[2] }, geoKd: mat.userData.kd, geoKe: mat.userData.ke, tGrain: mat.userData.noise, tStreets: { value: data.streets.tex }, bS: { value: new THREE.Vector3(sm.west, sm.south, sm.size) } });
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vGeoW;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvGeoW = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 vGeoW;
uniform sampler2D tL0, tL1, tL2;
uniform vec4 bL0, bL1, bL2;
uniform float geoKd, geoKe;
uniform sampler2D tGrain, tStreets;
uniform vec3 bS;
vec3 geoPhoto;
float edgeW(vec2 uv, float f) { vec2 e = min(uv, 1.0 - uv); return smoothstep(0.0, f, min(e.x, e.y)); }`)
      .replace('#include <map_fragment>', `
{
  vec2 en = vec2(vGeoW.x, -vGeoW.z);
  vec2 u0 = (en - bL0.xy) / bL0.zw, u1 = (en - bL1.xy) / bL1.zw, u2 = (en - bL2.xy) / bL2.zw;
  float w0 = edgeW(u0, 0.025);
  vec4 c;
  if (w0 >= 1.0) c = texture2D(tL0, u0);
  else {
    c = texture2D(tL2, u2);
    float w1 = edgeW(u1, 0.03);
    if (w1 > 0.0) c = mix(c, texture2D(tL1, u1), w1);
    if (w0 > 0.0) c = mix(c, texture2D(tL0, u0), w0);
  }
  // close to the camera add procedural micro-detail (asphalt grain / grass) so the photo does not look smeared
  float camD = length(vGeoW - cameraPosition);
  float nearF = 1.0 - smoothstep(12.0, 70.0, camD);
  if (nearF > 0.0) {
    vec4 g1 = texture2D(tGrain, vGeoW.xz * 0.37);
    vec4 g2 = texture2D(tGrain, vGeoW.xz * 1.9 + 0.31);
    float green = clamp((c.g - max(c.r, c.b)) * 8.0, 0.0, 1.0);
    vec3 asphalt = c.rgb * (0.86 + 0.28 * g1.r) * (0.80 + 0.40 * g2.g);
    vec3 grass = c.rgb * mix(vec3(0.75, 0.85, 0.65), vec3(1.15, 1.2, 1.0), g2.b) * (0.85 + 0.3 * g1.a);
    c.rgb = mix(c.rgb, mix(asphalt, grass, green), nearF * 0.85);
#ifdef GEO_STREETS
    // tree crowns and their shadows baked into the photo read as dark blotches at eye level: turn them into lawn
    float veg = smoothstep(-0.006, 0.01, c.g - c.r);
    float lumP = dot(c.rgb, vec3(0.3, 0.59, 0.11));
    float dark = 1.0 - smoothstep(0.035, 0.085, lumP);
    vec3 lawn = vec3(0.075, 0.115, 0.035) * (0.75 + 0.5 * g2.b) * (0.85 + 0.3 * g1.a);
    c.rgb = mix(c.rgb, lawn, veg * dark * nearF);
#endif
  }
#ifndef GEO_STREETS
  {
    // roofs seen up close: clay-tile rows following the height contours of pitched faces
    vec3 fn = normalize(cross(dFdx(vGeoW), dFdy(vGeoW)));
    if (fn.y < 0.0) fn = -fn;
    float camR = length(vGeoW - cameraPosition);
    float nearR = (1.0 - smoothstep(30.0, 110.0, camR)) * smoothstep(0.985, 0.93, fn.y);
    if (nearR > 0.0) {
      vec2 along = normalize(vec2(-fn.z, fn.x) + 1e-5);
      float rowF = vGeoW.y / 0.14;
      float row = fract(rowF);
      float s = dot(vGeoW.xz, along) / 0.24 + 0.5 * floor(rowF);
      float tile = mix(0.70, 1.05, smoothstep(0.0, 0.3, row)) * mix(0.82, 1.0, smoothstep(0.0, 0.08, abs(fract(s) - 0.5) * 2.0 - 0.0));
      vec4 gr = texture2D(tGrain, vGeoW.xz * 0.5);
      c.rgb = mix(c.rgb, c.rgb * tile * (0.9 + 0.2 * gr.r), nearR);
    }
  }
#endif
#ifdef GEO_STREETS
  {
    vec2 su = (en - bS.xy) / bS.z;
    if (su.x > 0.0 && su.y > 0.0 && su.x < 1.0 && su.y < 1.0) {
      vec3 sd = texture2D(tStreets, su).rgb;
      float dRoad = (sd.r - 0.5) * 3.0, dMark = (sd.g - 0.5) * 1.0, dWalk = (sd.b - 0.5) * 3.0;
      float aR = fwidth(dRoad) * 0.8 + 0.004, aM = fwidth(dMark) * 0.8 + 0.003, aW = fwidth(dWalk) * 0.8 + 0.004;
      float road = 1.0 - smoothstep(-aR, aR, dRoad);
      float curb = (1.0 - smoothstep(-aR, aR, dRoad - 0.17)) * (1.0 - road);
      float walk = (1.0 - smoothstep(-aW, aW, dWalk)) * (1.0 - road);
      float mark = (1.0 - smoothstep(-aM, aM, dMark)) * road;
      vec2 e2 = min(su, 1.0 - su);
      float fade = smoothstep(0.0, 0.06, min(e2.x, e2.y));
      vec4 s1 = texture2D(tGrain, vGeoW.xz * 0.29), s2 = texture2D(tGrain, vGeoW.xz * 2.7 + 0.17);
      vec3 asphalt = vec3(0.072, 0.072, 0.077) * (0.78 + 0.44 * s1.r) * (0.84 + 0.32 * s2.g);
      vec3 paving = vec3(0.25, 0.235, 0.215) * (0.86 + 0.28 * s2.g) * (0.88 + 0.24 * s1.a);
      vec3 curbC = vec3(0.40, 0.39, 0.37) * (0.9 + 0.2 * s2.g);
      vec3 markC = vec3(0.72, 0.72, 0.70) * (0.82 + 0.18 * s2.r);
      c.rgb = mix(c.rgb, paving, walk * fade);
      c.rgb = mix(c.rgb, curbC, curb * fade);
      c.rgb = mix(c.rgb, asphalt, road * fade);
      c.rgb = mix(c.rgb, markC, mark * fade);
    }
  }
#endif
  geoPhoto = c.rgb;
  diffuseColor.rgb *= c.rgb * geoKd;
}`).replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += geoPhoto * geoKe;');
    mat.userData.shader = sh;
  };
  return mat;
}

function grainTexture() {
  const S = 256, c = document.createElement('canvas');
  c.width = c.height = S;
  const g = c.getContext('2d');
  const img = g.createImageData(S, S);
  // tileable value noise at a few octaves (r: blotches, g: fine grain, b: grass blades, a: medium)
  let seed = 9;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const grid = (n) => { const a = []; for (let i = 0; i < n * n; i++) a.push(rnd()); return a; };
  const vnoise = (G, n, x, y) => {
    const fx = (x / S) * n, fy = (y / S) * n, x0 = Math.floor(fx), y0 = Math.floor(fy), ax = fx - x0, ay = fy - y0;
    const at = (i, j) => G[((j % n) + n) % n * n + (((i % n) + n) % n)];
    const sx = ax * ax * (3 - 2 * ax), sy = ay * ay * (3 - 2 * ay);
    return (at(x0, y0) * (1 - sx) + at(x0 + 1, y0) * sx) * (1 - sy) + (at(x0, y0 + 1) * (1 - sx) + at(x0 + 1, y0 + 1) * sx) * sy;
  };
  const G4 = grid(4), G16 = grid(16), G64 = grid(64), G8 = grid(8);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const k = (y * S + x) * 4;
    img.data[k] = 255 * (0.6 * vnoise(G4, 4, x, y) + 0.4 * vnoise(G16, 16, x, y));
    img.data[k + 1] = 255 * (0.35 * vnoise(G64, 64, x, y) + 0.65 * rnd());
    img.data[k + 2] = 255 * (rnd() < 0.5 ? rnd() * 0.5 : 0.5 + rnd() * 0.5);
    img.data[k + 3] = 255 * vnoise(G8, 8, x, y);
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8;
  return t;
}

export function makeTerrain(data, sampler, mat) {
  const N = 300, S = 6450, A = 5.0, cx = 30, cz = 0;
  const coord = (i) => (S * Math.sinh(A * ((i / (N - 1)) * 2 - 1))) / Math.sinh(A);
  const pos = new Float32Array(N * N * 3);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const x = cx + coord(i), z = cz + coord(j);
    const k = (j * N + i) * 3;
    pos[k] = x; pos[k + 1] = sampler(x, z) - 0.05; pos[k + 2] = z;
  }
  // normals from the full grid, then split into tiles so off-screen tiles get culled
  const full = new THREE.BufferGeometry();
  full.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const idxAll = [];
  for (let j = 0; j < N - 1; j++) for (let i = 0; i < N - 1; i++) { const a = j * N + i; idxAll.push(a, a + N, a + 1, a + 1, a + N, a + N + 1); }
  full.setIndex(idxAll);
  full.computeVertexNormals();
  const nrm = full.attributes.normal;
  const group = new THREE.Group(); group.name = 'terrain';
  const TILES = 10, step = Math.ceil((N - 1) / TILES);
  for (let tj = 0; tj < N - 1; tj += step) for (let ti = 0; ti < N - 1; ti += step) {
    const idx = [];
    for (let j = tj; j < Math.min(N - 1, tj + step); j++) for (let i = ti; i < Math.min(N - 1, ti + step); i++) {
      const a = j * N + i; idx.push(a, a + N, a + 1, a + 1, a + N, a + N + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', full.attributes.position);
    g.setAttribute('normal', nrm);
    g.setIndex(idx);
    // bounding sphere of just this tile
    const box = new THREE.Box3(), v = new THREE.Vector3();
    for (const k of [idx[0], idx[idx.length - 1]]) box.expandByPoint(v.fromBufferAttribute(full.attributes.position, k));
    for (let k = 0; k < idx.length; k += 97) box.expandByPoint(v.fromBufferAttribute(full.attributes.position, idx[k]));
    box.expandByScalar(5);
    g.boundingBox = box; g.boundingSphere = box.getBoundingSphere(new THREE.Sphere());
    const m = new THREE.Mesh(g, mat);
    m.receiveShadow = true;
    group.add(m);
  }
  return group;
}

// ---------- buildings ----------
const FACADE_GLSL = `
varying vec4 vFuv;
varying vec2 vFac;
uniform float nightMix;
float h11(float n) { return fract(sin(n) * 43758.5453); }
float h21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
vec3 srgb(vec3 c) { return pow(c, vec3(2.2)); }
vec3 palette(float style, float seed) {
  // hash-driven pastel palettes (no dynamic array indexing: it is slow in software GL)
  float a = fract(seed * 7.13), b = fract(seed * 13.7);
  if (style < 0.5) { // old town plaster: cream, ochre, salmon, sage, white
    vec3 c = mix(vec3(.93,.86,.70), vec3(.95,.78,.52), step(0.35, a));
    c = mix(c, vec3(.90,.73,.65), step(0.62, a));
    c = mix(c, vec3(.80,.84,.75), step(0.80, a));
    c = mix(c, vec3(.93,.91,.86), step(0.90, a));
    return srgb(c * (0.94 + 0.08 * b));
  } else if (style < 1.5) {
    vec3 c = mix(vec3(.90,.89,.86), vec3(.80,.77,.72), a);
    c = mix(c, vec3(.92,.86,.72), step(0.75, b));
    return srgb(c);
  } else if (style < 2.5) {
    return srgb(mix(vec3(.88,.86,.82), vec3(.86,.82,.74), a));
  } else if (style < 3.5) {
    return srgb(vec3(.84,.84,.82));
  } else if (style < 4.5) {
    return srgb(vec3(.76,.74,.70));
  }
  return srgb(vec3(.95,.93,.87));
}`;

export function makeBuildings(data) {
  const { walls, roofs } = data;
  const wmat = new THREE.MeshLambertMaterial({ color: 0xffffff });
  wmat.onBeforeCompile = (sh) => {
    sh.uniforms.nightMix = { value: 0 };
    wmat.userData.shader = sh;
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute vec4 fuv;\nattribute vec2 fac;\nvarying vec4 vFuv;\nvarying vec2 vFac;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvFuv = fuv; vFac = fac;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\n' + FACADE_GLSL)
      .replace('#include <map_fragment>', `
float style = floor(vFac.x * 255.0 + 0.5);
float seed = vFac.y;
bool parapet = style > 9.5;
float st = parapet ? style - 10.0 : style;
vec3 base = palette(st, seed);
float u = vFuv.x, v = vFuv.y, len = vFuv.z, wh = vFuv.w;
float glassMask = 0.0, frameMask = 0.0, lit = 0.0;
// storey and window layout per style
float fh = 3.2, ww = 1.15, wh2 = 1.5, sill = 0.95, sp = 2.9;
if (st > 0.5 && st < 1.5) { fh = 3.0; ww = 1.4; wh2 = 1.45; sill = 0.9; sp = 3.0; }
if (st > 1.5 && st < 2.5) { fh = 2.8; ww = 1.7; wh2 = 1.35; sill = 0.85; sp = 3.3; }
if (st > 2.5 && st < 3.5) { fh = 3.8; ww = 2.6; wh2 = 1.0; sill = 1.3; sp = 3.0; }
if (st > 4.5) { fh = 20.0; ww = 1.4; wh2 = 4.6; sill = 3.2; sp = 5.0; }
if (!parapet && st < 3.5 || st > 4.5) {
  float n = floor((len - 0.6) / sp);
  if (n >= 1.0) {
    float off = (len - n * sp) * 0.5;
    float lu = u - off;
    float cell = floor(lu / sp);
    float fu = lu - cell * sp - sp * 0.5;
    float fl = floor(v / fh);
    float fv = v - fl * fh;
    bool shop = (st > 2.5 && st < 3.5 && fl < 0.5) || (st < 0.5 && fl < 0.5 && seed > 0.62);
    float w2 = shop ? sp * 0.42 : ww * 0.5;
    float y0 = shop ? 0.35 : sill;
    float y1 = shop ? min(3.0, fh - 0.25) : sill + wh2;
    if (cell >= 0.0 && cell < n && v > 0.3 && v < wh - 0.5) {
      float dx = abs(fu) - w2, dy = max(y0 - fv, fv - y1);
      float d = max(dx, dy);
      if (d < 0.0) {
        glassMask = 1.0;
        // mullions / frames
        float fr = 0.07;
        if (-d < fr || abs(fu) < 0.035 || (!shop && abs(fv - (y0 + (y1 - y0) * 0.68)) < 0.03)) frameMask = 1.0;
        lit = step(0.55, h21(vec2(cell + seed * 97.0, fl * 13.0 + floor(len))));
      } else if (!shop && dx < 0.12 && fv > y0 - 0.12 && fv < y0) {
        frameMask = 0.6; // sill
      }
    }
  }
}
vec3 col = base;
// plinth and fake ambient occlusion near the ground
if (!parapet) {
  if (v < 0.5) col *= 0.72;
  col *= mix(0.78, 1.0, smoothstep(0.0, 2.5, v));
} else col *= 0.9;
// subtle large-scale plaster variation
col *= 0.94 + 0.06 * h21(floor(vec2(u, v) * 0.7) + seed * 31.0);
// fake reflective glass: darker towards the viewer, sky-tinted at grazing angles
float fres = pow(1.0 - abs(dot(normalize(vViewPosition), normalize(vNormal))), 3.0);
vec3 glass = mix(vec3(0.03, 0.045, 0.06), vec3(0.42, 0.52, 0.62), clamp(0.15 + 0.25 * h21(vec2(floor(u / sp), floor(v / fh))) + fres * 0.8, 0.0, 1.0));
col = mix(col, glass, glassMask * (1.0 - frameMask));
col = mix(col, srgb(vec3(.95)), frameMask);
float glassOnly = glassMask * (1.0 - frameMask);
diffuseColor.rgb *= mix(col, col * 0.35, glassOnly);
vec3 glassEmit = glass * glassOnly * 0.55;
`)
      .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += glassEmit + glassOnly * lit * nightMix * vec3(1.0, 0.72, 0.42) * 1.6;');
  };
  const wallGroup = new THREE.Group(); wallGroup.name = 'walls';
  const roofGeos = [];
  for (const ch of data.chunks) {
    const [ws, wc] = ch.walls, [rs, rc] = ch.roofs;
    if (wc > 0) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(walls.pos.slice(ws * 3, (ws + wc) * 3), 3));
      g.setAttribute('fuv', new THREE.BufferAttribute(walls.uv.slice(ws * 4, (ws + wc) * 4), 4));
      g.setAttribute('fac', new THREE.BufferAttribute(walls.fac.slice(ws * 2, (ws + wc) * 2), 2, true));
      g.computeVertexNormals();
      g.computeBoundingSphere();
      const m = new THREE.Mesh(g, wmat);
      m.castShadow = true; m.receiveShadow = true;
      wallGroup.add(m);
    }
    if (rc > 0) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(roofs.pos.slice(rs * 3, (rs + rc) * 3), 3));
      g.computeVertexNormals();
      g.computeBoundingSphere();
      roofGeos.push(g);
    }
  }
  return { walls: wallGroup, roofGeos, wallMat: wmat };
}

// ---------- trees ----------
function mulberry(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// crown made of a few noisy spheres with smooth (spherical) normals and baked under-side darkening
function crownGeometry(blobs, detail, seed) {
  const rnd = mulberry(seed);
  const pos = [], nrm = [], col = [];
  for (const [bx, by, bz, br] of blobs) {
    const g = new THREE.IcosahedronGeometry(br, detail).toNonIndexed();
    const p = g.attributes.position;
    const jit = new Map();
    for (let i = 0; i < p.count; i++) {
      const v = new THREE.Vector3().fromBufferAttribute(p, i);
      const key = `${v.x.toFixed(3)},${v.y.toFixed(3)},${v.z.toFixed(3)}`;
      if (!jit.has(key)) jit.set(key, 1 + (rnd() - 0.5) * 0.22);
      const n = v.clone().normalize();
      v.multiplyScalar(jit.get(key));
      pos.push(v.x + bx, v.y + by, v.z + bz);
      nrm.push(n.x, n.y, n.z);
      const k = 0.5 + 0.5 * Math.min(1, Math.max(0, (v.y + by) / 1.0));
      col.push(k, k, k);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return g;
}

const BLOBS_HI = [[0, 0.55, 0, 0.6], [0.34, 0.45, 0.12, 0.44], [-0.3, 0.42, -0.14, 0.45], [0.02, 0.76, -0.22, 0.42]];
const BLOBS_MID = [[0, 0.52, 0, 0.6], [0.18, 0.62, 0.1, 0.42]];

export class TreeField {
  constructor(list, sampler, isBlocked) {
    this.group = new THREE.Group();
    this.group.name = 'trees';
    const rnd = mulberry(42);
    const items = list.filter(([e, n]) => !isBlocked(e, -n));
    const N = items.length;
    this.N = N;
    this.crownM = new Float32Array(N * 16);
    this.trunkM = new Float32Array(N * 16);
    this.color = new Float32Array(N * 3);
    this.sphere = new Float32Array(N * 4);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color(), Yax = new THREE.Vector3(0, 1, 0);
    items.forEach(([e, n, r, h, kind], i) => {
      const x = e, z = -n, y = sampler(x, z);
      q.setFromAxisAngle(Yax, rnd() * Math.PI * 2);
      const crownH = Math.max(2.2, h - Math.max(1.6, h * 0.32));
      const sx = r * 1.08, sy = kind === 1 ? crownH * 1.15 : crownH * 0.92;
      m.compose(new THREE.Vector3(x, y + h - crownH * 0.97, z), q, new THREE.Vector3(sx, sy, sx));
      m.toArray(this.crownM, i * 16);
      m.compose(new THREE.Vector3(x, y - 0.2, z), q, new THREE.Vector3(r * 0.2 + 0.45, h - crownH * 0.55, r * 0.2 + 0.45));
      m.toArray(this.trunkM, i * 16);
      const tint = 0.78 + rnd() * 0.3;
      if (kind === 1) c.setRGB(0.07 * tint, 0.13 * tint, 0.07 * tint);
      else {
        const hue = rnd();
        c.setRGB((0.11 + hue * 0.07) * tint, (0.19 + rnd() * 0.04) * tint, (0.06 + hue * 0.02) * tint);
      }
      c.toArray(this.color, i * 3);
      this.sphere.set([x, y + h * 0.6, z, Math.max(r, h * 0.6)], i * 4);
    });
    const crownMat = new THREE.MeshLambertMaterial({ color: 0xffffff, vertexColors: true });
    crownMat.onBeforeCompile = (sh) => {
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vLeafP;')
        .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvLeafP = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', `#include <common>
varying vec3 vLeafP;
float lh(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
float lnoise(vec3 p) { vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(lh(i), lh(i + vec3(1,0,0)), f.x), mix(lh(i + vec3(0,1,0)), lh(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(lh(i + vec3(0,0,1)), lh(i + vec3(1,0,1)), f.x), mix(lh(i + vec3(0,1,1)), lh(i + vec3(1,1,1)), f.x), f.y), f.z); }`)
        .replace('#include <color_fragment>', `#include <color_fragment>
float leaf = lnoise(vLeafP * 2.3) * 0.6 + lnoise(vLeafP * 6.1) * 0.4;
diffuseColor.rgb *= 0.62 + 0.75 * leaf;
diffuseColor.rgb += vec3(0.012, 0.016, 0.0) * step(0.72, leaf);`);
    };
    const trunkMat = new THREE.MeshLambertMaterial({ color: 0x4f3d2f });
    const trunkG = (seg) => { const g = new THREE.CylinderGeometry(0.1, 0.16, 1, seg); g.translate(0, 0.5, 0); return g; };
    const mk = (geo, mat, shadow) => {
      const im = new THREE.InstancedMesh(geo, mat, N);
      im.count = 0; im.frustumCulled = false; im.castShadow = shadow; im.receiveShadow = true;
      im.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      this.group.add(im);
      return im;
    };
    this.lod = [
      { crown: mk(crownGeometry(BLOBS_HI, 2, 7), crownMat, true), trunk: mk(trunkG(8), trunkMat, true), maxD: 70 },
      { crown: mk(crownGeometry(BLOBS_MID, 1, 9), crownMat, true), trunk: mk(trunkG(5), trunkMat, false), maxD: 650 },
      { crown: mk(crownGeometry([[0, 0.5, 0, 0.62]], 0, 3), crownMat, false), trunk: null, maxD: 5000 },
    ];
    for (const l of this.lod) l.crown.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(N * 3), 3).setUsage(THREE.DynamicDrawUsage);
    this.frustum = new THREE.Frustum();
    this.pm = new THREE.Matrix4();
    this.sph = new THREE.Sphere();
  }

  update(camera) {
    this.pm.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this.pm);
    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
    const counts = [0, 0, 0];
    const S = this.sphere, sph = this.sph;
    for (let i = 0; i < this.N; i++) {
      const dx = S[4 * i] - cx, dy = S[4 * i + 1] - cy, dz = S[4 * i + 2] - cz;
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (d > 5000) continue;
      sph.center.set(S[4 * i], S[4 * i + 1], S[4 * i + 2]); sph.radius = S[4 * i + 3] + 1;
      if (!this.frustum.intersectsSphere(sph)) continue;
      const k = d < this.lod[0].maxD ? 0 : d < this.lod[1].maxD ? 1 : 2;
      const L = this.lod[k], j = counts[k]++;
      L.crown.instanceMatrix.array.set(this.crownM.subarray(16 * i, 16 * i + 16), 16 * j);
      L.crown.instanceColor.array.set(this.color.subarray(3 * i, 3 * i + 3), 3 * j);
      if (L.trunk) L.trunk.instanceMatrix.array.set(this.trunkM.subarray(16 * i, 16 * i + 16), 16 * j);
    }
    this.lod.forEach((L, k) => {
      L.crown.count = counts[k]; L.crown.instanceMatrix.needsUpdate = true; L.crown.instanceColor.needsUpdate = true;
      if (L.trunk) { L.trunk.count = counts[k]; L.trunk.instanceMatrix.needsUpdate = true; }
    });
  }

  // shadow casters must include trees just outside the view, so refresh with a widened frustum when needed
}
