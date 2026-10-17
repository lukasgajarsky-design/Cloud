// Line-of-sight search including tree crowns as spheres.
import { chromium } from 'playwright';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 400, height: 300 } });
await page.goto('http://127.0.0.1:8765/capture.html?mode=capture&w=400&h=300', { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
const res = await page.evaluate(() => {
  const a = window.APP, T = window.THREE;
  const occ = [];
  a.scene.getObjectByName('walls').traverse((o) => { if (o.isMesh) occ.push(o); });
  a.scene.getObjectByName('roofs').traverse((o) => { if (o.isMesh) occ.push(o); });
  const tr = a.trees, m = new T.Matrix4(), p = new T.Vector3(), q = new T.Quaternion(), s = new T.Vector3();
  const spheres = [];
  for (let i = 0; i < tr.N; i++) { m.fromArray(tr.crownM, i * 16); m.decompose(p, q, s); if (Math.hypot(p.x - 30, p.z) < 160) spheres.push(new T.Sphere(p.clone().setY(p.y + 0.55 * s.y), 0.55 * s.x)); }
  const rc = new T.Raycaster();
  const targets = Object.values(a.overpasses).map((o) => { const [d0, d1] = o.site.deck; return [0.2, 0.5, 0.8].map((f) => o.O.clone().addScaledVector(o.N, d0 + (d1 - d0) * f).setY(o.paths.yTop + 0.6)); });
  const out = [];
  const test = (x, n) => {
    const P = new T.Vector3(x, a.ground(x, -n) + 1.65, -n);
    const sc = targets.map((tg) => tg.filter((t) => {
      const dir = t.clone().sub(P); const L = dir.length(); dir.normalize();
      const ray = new T.Ray(P, dir);
      for (const sp of spheres) { const hit = ray.intersectSphere(sp, new T.Vector3()); if (hit && hit.distanceTo(P) < L) return false; }
      rc.set(P, dir); rc.far = L;
      return rc.intersectObjects(occ, false).length === 0;
    }).length);
    if (sc[0] >= 2 && sc[1] >= 2) out.push([+x.toFixed(1), +n.toFixed(1), sc.join('')]);
  };
  for (let x = -40; x <= 60; x += 2.5) for (let n = -50; n <= 45; n += 2.5) test(x, n);
  return out;
});
console.log(JSON.stringify(res));
await browser.close();
