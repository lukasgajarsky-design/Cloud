// Build an export-friendly copy of the scene (plain PBR materials, real UVs) for glTF / USDZ files.
// The live viewer relies on custom shaders (satellite draping, procedural facades) that 3D file formats
// cannot carry, so here the photo is a baked texture and facades use a tiling window texture.
import * as THREE from 'three';
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';

const srgb = (r, g, b) => new THREE.Color().setRGB(r, g, b, THREE.SRGBColorSpace);

// same plaster palette as the viewer's facade shader, as a small set of discrete colours
function paletteKey(style, seed) {
  const a = (seed * 7.13) % 1, b = (seed * 13.7) % 1;
  if (style === 0) return a < 0.35 ? 'cream' : a < 0.62 ? 'ochre' : a < 0.8 ? 'salmon' : a < 0.9 ? 'sage' : 'white';
  if (style === 1) return b > 0.75 ? 'sand' : a < 0.5 ? 'light' : 'grey';
  if (style === 2) return a < 0.5 ? 'panel' : 'panelwarm';
  if (style === 3) return 'shop';
  if (style === 4) return 'garage';
  return 'church';
}
const PALETTE = {
  cream: [0.93, 0.86, 0.70], ochre: [0.95, 0.78, 0.52], salmon: [0.90, 0.73, 0.65], sage: [0.80, 0.84, 0.75], white: [0.93, 0.91, 0.86],
  light: [0.90, 0.89, 0.86], grey: [0.80, 0.77, 0.72], sand: [0.92, 0.86, 0.72], panel: [0.88, 0.86, 0.82], panelwarm: [0.86, 0.82, 0.74],
  shop: [0.84, 0.84, 0.82], garage: [0.76, 0.74, 0.70], church: [0.95, 0.93, 0.87],
};

// one 3 m x 3 m facade bay: plaster (tinted by the material colour) with a framed window
function facadeTexture() {
  const S = 256, c = document.createElement('canvas');
  c.width = c.height = S;
  const g = c.getContext('2d');
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, S, S);
  const px = S / 3;
  const ww = 1.2 * px, x0 = (S - ww) / 2, top = (3 - 2.4) * px, bot = (3 - 0.9) * px;
  g.fillStyle = '#f2f1ee'; g.fillRect(x0 - 7, top - 7, ww + 14, bot - top + 14);      // frame
  g.fillStyle = '#2f3b46'; g.fillRect(x0, top, ww, bot - top);                         // glass
  const grd = g.createLinearGradient(0, top, 0, bot);
  grd.addColorStop(0, 'rgba(160,190,215,0.35)'); grd.addColorStop(1, 'rgba(160,190,215,0.0)');
  g.fillStyle = grd; g.fillRect(x0, top, ww, bot - top);
  g.fillStyle = '#f2f1ee'; g.fillRect(S / 2 - 3, top, 6, bot - top);                   // mullion
  g.fillRect(x0, top + (bot - top) * 0.32, ww, 5);                                     // transom
  g.fillStyle = '#d9d6cf'; g.fillRect(x0 - 12, bot + 7, ww + 24, 7);                   // sill
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.flipY = false;
  t.userData.mimeType = 'image/png';
  return t;
}

function labelTexture(lines) {
  const W = 2048, H = 256, c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  g.fillStyle = '#20251f'; g.fillRect(0, 0, W, H);
  g.fillStyle = '#c98b5b'; g.fillRect(0, 0, 18, H);
  g.fillStyle = '#ffffff'; g.font = '700 92px Inter, "DejaVu Sans", sans-serif'; g.textBaseline = 'middle';
  g.fillText(lines[0], 70, H * 0.36);
  g.fillStyle = '#e7c3a3'; g.font = '600 64px Inter, "DejaVu Sans", sans-serif';
  g.fillText(lines[1], 70, H * 0.76);
  const t = new THREE.CanvasTexture(c); // flipY stays true: PlaneGeometry UVs expect it, exporters honour it
  t.colorSpace = THREE.SRGBColorSpace;
  t.userData.mimeType = 'image/png';
  return t;
}

/**
 * @param app       the running scene (main.js createApp)
 * @param opts.center [east, north]  centre of the exported square
 * @param opts.half   half side length in metres
 * @param opts.photo  THREE.Texture of the baked ground photo (flipY = false) and opts.photoBounds {west,east,south,north}
 * @param opts.gridStep ground grid spacing (m), opts.treeDetail icosahedron detail for crowns
 */
export function buildExportScene(app, opts) {
  const { center, half, photo, photoBounds: pb, gridStep = 3, treeDetail = 1 } = opts;
  const [ce, cn] = center;
  const inArea = (x, z) => Math.abs(x - ce) <= half && Math.abs(-z - cn) <= half;
  const root = new THREE.Group();
  root.name = 'Hlohovec_nadchody';
  const uvOf = (x, z) => [(x - pb.west) / (pb.east - pb.west), (pb.north - -z) / (pb.north - pb.south)];

  // ---- ground (terrain patch) + roofs, both draped with the baked photo
  const photoMat = new THREE.MeshStandardMaterial({ map: photo, roughness: 1, metalness: 0, name: 'Satelitna_snimka' });
  const n = Math.round((2 * half) / gridStep) + 1;
  const gp = [], guv = [], gi = [];
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const x = ce - half + i * gridStep, z = -(cn + half - j * gridStep);
    gp.push(x, app.ground(x, z) - 0.04, z);
    guv.push(...uvOf(x, z));
  }
  for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) { const a = j * n + i; gi.push(a, a + n, a + 1, a + 1, a + n, a + n + 1); }
  const ground = new THREE.BufferGeometry();
  ground.setAttribute('position', new THREE.Float32BufferAttribute(gp, 3));
  ground.setAttribute('uv', new THREE.Float32BufferAttribute(guv, 2));
  ground.setIndex(gi);
  ground.computeVertexNormals();
  const rp = [], ruv = [];
  app.scene.getObjectByName('roofs').traverse((m) => {
    if (!m.isMesh) return;
    const p = m.geometry.attributes.position.array;
    for (let k = 0; k < p.length; k += 9) {
      const cx = (p[k] + p[k + 3] + p[k + 6]) / 3, cz = (p[k + 2] + p[k + 5] + p[k + 8]) / 3;
      if (!inArea(cx, cz)) continue;
      for (let v = 0; v < 9; v += 3) { rp.push(p[k + v], p[k + v + 1], p[k + v + 2]); ruv.push(...uvOf(p[k + v], p[k + v + 2])); }
    }
  });
  const roofs = new THREE.BufferGeometry();
  roofs.setAttribute('position', new THREE.Float32BufferAttribute(rp, 3));
  roofs.setAttribute('uv', new THREE.Float32BufferAttribute(ruv, 2));
  roofs.computeVertexNormals();
  const groundRoofs = mergeGeometries([ground.toNonIndexed(), roofs]);
  const gm = new THREE.Mesh(mergeVertices(groundRoofs, 1e-4), photoMat);
  gm.name = 'Teren_a_strechy';
  root.add(gm);

  // ---- walls grouped by plaster colour; windowed facades get the tiling window texture
  const facade = facadeTexture();
  const groups = {};
  app.scene.getObjectByName('walls').traverse((m) => {
    if (!m.isMesh) return;
    const p = m.geometry.attributes.position.array, f = m.geometry.attributes.fuv.array, fac = m.geometry.attributes.fac.array;
    for (let t = 0; t < p.length / 9; t++) {
      const k = t * 9, cx = (p[k] + p[k + 3] + p[k + 6]) / 3, cz = (p[k + 2] + p[k + 5] + p[k + 8]) / 3;
      if (!inArea(cx, cz)) continue;
      const style = fac[t * 6], seed = fac[t * 6 + 1] / 255;
      const plain = style >= 10 || style === 4;
      const key = (plain ? 'plain_' : 'win_') + paletteKey(style >= 10 ? style - 10 : style, seed);
      const gr = (groups[key] ||= { p: [], uv: [] });
      for (let v = 0; v < 3; v++) {
        const vi = t * 3 + v;
        // walls start 3 m below ground: keep geometry, clamp the facade pattern to above ground
        gr.p.push(p[vi * 3], p[vi * 3 + 1], p[vi * 3 + 2]);
        gr.uv.push(f[vi * 4] / 3, -Math.max(0, f[vi * 4 + 1]) / 3);
      }
    }
  });
  for (const [key, gr] of Object.entries(groups)) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(gr.p, 3));
    geo.setAttribute('uv', new THREE.Float32BufferAttribute(gr.uv, 2));
    geo.computeVertexNormals();
    const name = key.split('_')[1];
    const plain = key.startsWith('plain');
    const mat = new THREE.MeshStandardMaterial({ color: srgb(...PALETTE[name]).multiplyScalar(plain ? 0.9 : 1), map: plain ? null : facade, roughness: 0.92, metalness: 0, name: `Fasada_${key}` });
    const mesh = new THREE.Mesh(mergeVertices(geo, 1e-4), mat);
    mesh.name = `Budovy_${key}`;
    root.add(mesh);
  }

  // ---- trees: crowns in four greens + trunks
  const tr = app.trees;
  const crownProto = mergeVertices(new THREE.IcosahedronGeometry(0.62, treeDetail).translate(0, 0.5, 0).deleteAttribute('uv'));
  crownProto.computeVertexNormals();
  const trunkProto = new THREE.CylinderGeometry(0.1, 0.16, 1, 6).translate(0, 0.5, 0).deleteAttribute('uv');
  const crownBins = [[], [], [], []], trunks = [];
  const m4 = new THREE.Matrix4(), pos = new THREE.Vector3();
  for (let i = 0; i < tr.N; i++) {
    m4.fromArray(tr.crownM, i * 16);
    pos.setFromMatrixPosition(m4);
    if (!inArea(pos.x, pos.z)) continue;
    const g = tr.color[i * 3 + 1];
    const bin = g < 0.12 ? 0 : g < 0.17 ? 1 : g < 0.2 ? 2 : 3;
    crownBins[bin].push(crownProto.clone().applyMatrix4(m4));
    m4.fromArray(tr.trunkM, i * 16);
    trunks.push(trunkProto.clone().applyMatrix4(m4));
  }
  const greens = [[0.10, 0.20, 0.10], [0.17, 0.29, 0.10], [0.22, 0.34, 0.12], [0.27, 0.40, 0.15]];
  crownBins.forEach((list, b) => {
    if (!list.length) return;
    const mesh = new THREE.Mesh(mergeGeometries(list), new THREE.MeshStandardMaterial({ color: new THREE.Color(...greens[b]), roughness: 0.95, name: `Koruny_${b}` }));
    mesh.name = `Stromy_${b}`;
    root.add(mesh);
  });
  if (trunks.length) {
    const mesh = new THREE.Mesh(mergeGeometries(trunks), new THREE.MeshStandardMaterial({ color: 0x4f3d2f, roughness: 1, name: 'Kmene' }));
    mesh.name = 'Kmene';
    root.add(mesh);
  }

  // ---- the two overpasses, one node each, materials kept (planks texture included)
  for (const [key, o] of Object.entries(app.overpasses)) {
    const node = new THREE.Group();
    node.name = key === 'hlohova' ? 'Nadchod_Hlohova' : 'Nadchod_SNP';
    o.group.children.forEach((m) => {
      const mat = m.material.clone();
      mat.name = m.name.replace(/^\w+-/, '');
      if (mat.metalness > 0.3) mat.metalness = 0.35; // without an environment map strong metals render black in viewers
      if (mat.map) { mat.map = mat.map.clone(); mat.map.flipY = false; mat.map.userData.mimeType = 'image/png'; }
      const geo = mergeVertices(m.geometry.clone(), 1e-4);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.name = `${node.name}_${mat.name}`;
      node.add(mesh);
    });
    root.add(node);
  }

  // ---- plinth: skirts down from the terrain edge to a flat base, so the model reads as a solid maquette
  let minY = Infinity;
  for (let k = 1; k < gp.length; k += 3) minY = Math.min(minY, gp[k]);
  const baseY = minY - 3;
  const sp = [];
  const edge = (pts) => {
    for (let k = 0; k < pts.length - 1; k++) {
      const [ax, ay, az] = pts[k], [bx, by, bz] = pts[k + 1];
      sp.push(ax, ay, az, ax, baseY, az, bx, baseY, bz, ax, ay, az, bx, baseY, bz, bx, by, bz);
    }
  };
  const P = (i, j) => [gp[(j * n + i) * 3], gp[(j * n + i) * 3 + 1], gp[(j * n + i) * 3 + 2]];
  const idx = [...Array(n).keys()];
  edge(idx.map((i) => P(i, 0)));                       // north edge, walking east
  edge(idx.map((j) => P(n - 1, j)));                   // east edge, walking south
  edge(idx.map((i) => P(n - 1 - i, n - 1)));           // south edge, walking west
  edge(idx.map((j) => P(0, n - 1 - j)));               // west edge, walking north
  const x0 = ce - half, x1 = ce + half, z0 = -(cn + half), z1 = -(cn - half);
  sp.push(x0, baseY, z0, x1, baseY, z1, x1, baseY, z0, x0, baseY, z0, x0, baseY, z1, x1, baseY, z1); // bottom
  const skirt = new THREE.BufferGeometry();
  skirt.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
  skirt.computeVertexNormals();
  const plinth = new THREE.Mesh(skirt, new THREE.MeshStandardMaterial({ color: 0x3a2f27, roughness: 0.9, name: 'Podstavec' }));
  plinth.name = 'Podstavec';
  root.add(plinth);

  // ---- author label lying on the ground at the south edge of the model
  const lw = half * 0.55, lh = lw / 8;
  const lx = ce - half + lw / 2 + half * 0.04, lz = -(cn - half + lh / 2 + half * 0.04);
  const label = new THREE.Mesh(
    new THREE.PlaneGeometry(lw, lh).rotateX(-Math.PI / 2),
    new THREE.MeshStandardMaterial({ map: labelTexture(['Hlohovec – návrh dvoch nadchodov', 'Vytvoril: Lukáš Gajarský']), roughness: 1, name: 'Stitok' }),
  );
  label.position.set(lx, app.ground(lx, lz) + 0.6, lz);
  label.name = 'Stitok_autor';
  root.add(label);

  // centre the model on the origin with the bottom of the plinth at y = 0 (AR places it on the table)
  root.position.set(-ce, -baseY, cn);
  const scene = new THREE.Scene();
  scene.name = 'Hlohovec';
  const wrapper = new THREE.Group();
  wrapper.name = 'Model';
  wrapper.add(root);
  scene.add(wrapper);
  scene.updateMatrixWorld(true);
  return { scene, wrapper, stats: { roofTris: rp.length / 9, wallGroups: Object.keys(groups).length, trees: trunks.length } };
}
