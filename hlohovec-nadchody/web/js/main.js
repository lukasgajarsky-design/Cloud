// Scene bootstrap + render API used by the interactive viewer and by the offline frame renderer.
import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { loadData, makeGroundSampler, makeGeoMaterial, makeTerrain, makeBuildings, TreeField } from './world.js';
import { Overpass, makeMaterials, DESIGN } from './overpass.js';
import { BigBridge } from './bigbridge.js';
import { Traffic } from './traffic.js';
import { People } from './people.js';

const params = new URLSearchParams(location.search);
const MODE = params.get('mode') || 'view';          // view | capture
const DATA = params.get('data') || 'data';
const W = +(params.get('w') || 1920), H = +(params.get('h') || 1080);

export const SUN = { az: 150, el: 41 };

export async function createApp(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: params.get('aa') !== '0', preserveDrawingBuffer: MODE === 'capture', powerPreference: 'high-performance' });
  renderer.setPixelRatio(MODE === 'capture' ? 1 : Math.min(window.devicePixelRatio, 1.5));
  if (MODE === 'capture') renderer.setSize(W, H, false);
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  const data = await loadData(DATA, { l0: params.get('l0') || window.HLOHOVEC_L0 || undefined, l1: window.HLOHOVEC_L1 || undefined });
  const ground = makeGroundSampler(data.terrainMeta, data.terrain);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, W / H, 0.5, 30000);

  // ---- sky, sun, environment
  const sky = new Sky();
  sky.scale.setScalar(25000);
  const su = sky.material.uniforms;
  su.turbidity.value = 5.5; su.rayleigh.value = 1.4; su.mieCoefficient.value = 0.004; su.mieDirectionalG.value = 0.8;
  const sunDir = new THREE.Vector3();
  const setSun = (az, el) => {
    const a = THREE.MathUtils.degToRad(az), e = THREE.MathUtils.degToRad(el);
    sunDir.set(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
    su.sunPosition.value.copy(sunDir);
  };
  setSun(SUN.az, SUN.el);
  scene.add(sky);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envScene = new THREE.Scene();
  const sky2 = new Sky(); sky2.scale.setScalar(1000); sky2.material.uniforms.sunPosition.value.copy(sunDir);
  Object.assign(sky2.material.uniforms, { turbidity: su.turbidity, rayleigh: su.rayleigh, mieCoefficient: su.mieCoefficient, mieDirectionalG: su.mieDirectionalG });
  envScene.add(sky2);
  const groundDisc = new THREE.Mesh(new THREE.CircleGeometry(900, 32).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0x5f6655 }));
  groundDisc.position.y = -2; envScene.add(groundDisc);
  scene.environment = pmrem.fromScene(envScene, 0.02).texture;
  scene.environmentIntensity = 0.3;
  scene.fog = new THREE.FogExp2(0xc4d3e2, 0.00011);

  const sun = new THREE.DirectionalLight(0xfff3e4, 2.9);
  sun.castShadow = true;
  const shadowSize = +(params.get('shadow') || window.HLOHOVEC_SHADOW || 3072);
  sun.shadow.mapSize.set(shadowSize, shadowSize);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.03;
  scene.add(sun, sun.target);
  const hemi = new THREE.HemisphereLight(0xd6e4f5, 0x8a8170, 1.45);
  scene.add(hemi);
  const setShadowFocus = (p, radius) => {
    const r = Math.max(25, radius);
    sun.target.position.copy(p);
    sun.position.copy(p).addScaledVector(sunDir, 1500);
    const c = sun.shadow.camera;
    c.left = -r; c.right = r; c.top = r; c.bottom = -r; c.near = 1000; c.far = 2200;
    c.updateProjectionMatrix();
  };
  setShadowFocus(new THREE.Vector3(30, 0, 0), 250);

  // ---- world
  const geoMat = makeGeoMaterial(data, renderer);
  const groundMat = makeGeoMaterial(data, renderer, {}, true);
  const terrain = makeTerrain(data, ground, groundMat);
  scene.add(terrain);
  const b = makeBuildings(data);
  const roofs = new THREE.Group(); roofs.name = 'roofs';
  for (const g of b.roofGeos) { const m = new THREE.Mesh(g, geoMat); m.castShadow = true; m.receiveShadow = true; roofs.add(m); }
  scene.add(b.walls, roofs);

  const mats = makeMaterials();
  const overpasses = {};
  for (const [k, s] of Object.entries(data.sites)) {
    overpasses[k] = new Overpass(k, s, ground, mats);
    scene.add(overpasses[k].group);
  }
  // optional long footbridge (variant B); hidden until setVariant('big')
  let bigbridge = null;
  try {
    const spec = await fetch(`${DATA}/bigbridge.json`).then((r) => (r.ok ? r.json() : null));
    if (spec) { bigbridge = new BigBridge('bigbridge', spec, ground, mats); scene.add(bigbridge.group); }
  } catch (e) { /* variant B is optional */ }
  const blocked = (x, z) => Object.values(overpasses).some((o) => o.blocks(x, z, 1.2)) || (bigbridge && bigbridge.blocks(x, z, 1.2));
  const trees = new TreeField(data.trees, ground, blocked);
  scene.add(trees.group);

  const traffic = new Traffic(data.routes, ground);
  scene.add(traffic.group);

  const people = await new People().load(`${DATA}/Xbot.glb`);
  scene.add(people.group);
  let ci = 0;
  for (const o of Object.values(overpasses)) {
    const cross = o.paths.cross;
    for (let k = 0; k < 3; k++) people.addWalker(cross, k * 17.3 + ci * 5.1, ci++, 1.25 + (k % 3) * 0.1, 'small');
  }
  if (bigbridge) {
    const routes = bigbridge.paths.list;
    for (let k = 0; k < routes.length; k++) {
      const a = routes[k], z = routes[(k + 1) % routes.length];
      if (a === z || !a.b || a.b !== z.b) continue;
      const path = [...a.pts.slice().reverse(), ...bigbridge.deckRoute(a.b, a.s, z.s), ...z.pts];
      people.addWalker(path, k * 13.7, ci++, 1.2 + (k % 3) * 0.1, 'big');
    }
  }
  try {
    const fw = await fetch(`${DATA}/footways.json`).then((r) => r.json());
    fw.footways.filter((f) => f.len > 35).slice(0, 7).forEach((f, i) => {
      const pts = f.pts.map(([e, n]) => new THREE.Vector3(e, ground(e, -n) + 0.12, -n));
      people.addWalker(pts, i * 7.3, ci++, 1.2 + (i % 4) * 0.08);
    });
  } catch (e) { /* footways are optional */ }

  const app = { renderer, scene, camera, data, ground, overpasses, bigbridge, traffic, people, trees, sun, sunDir, setSun, setShadowFocus, geoMat, wallMat: b.wallMat, sky, DESIGN, mats, hemi };

  // 'small' = the two short overpasses (variant A), 'big' = the long footbridge (variant B)
  app.variant = 'small';
  app.setVariant = (v) => {
    if (!bigbridge) v = 'small';
    app.variant = v;
    for (const o of Object.values(overpasses)) o.group.visible = v === 'small';
    if (bigbridge) bigbridge.group.visible = v === 'big';
    people.setTag('small', v === 'small');
    people.setTag('big', v === 'big');
  };
  app.setVariant(params.get('variant') || 'small');

  app.setTime = (t, camPos) => {
    traffic.update(t);
    people.update(t, camPos);
  };
  app.render = () => {
    camera.updateMatrixWorld();
    trees.update(camera);
    people.cull(camera.position);
    renderer.render(scene, camera);
  };
  if (MODE === 'view') {
    const controls = new OrbitControls(camera, canvas);
    const o = overpasses.hlohova.O;
    camera.position.set(o.x - 60, o.y + 45, o.z + 70);
    controls.target.set(o.x + 10, o.y + 3, o.z - 20);
    controls.maxPolarAngle = Math.PI * 0.495;
    controls.update();
    app.controls = controls;
  }
  return app;
}
