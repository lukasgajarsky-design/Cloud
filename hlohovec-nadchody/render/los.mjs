// Find sidewalk points near the roundabout with line of sight to both overpass decks.
import { chromium } from 'playwright';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 400, height: 300 } });
await page.goto('http://127.0.0.1:8765/capture.html?mode=capture&w=400&h=300', { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
const res = await page.evaluate(() => {
  const a = window.APP, T = window.THREE;
  const occluders = [];
  a.scene.getObjectByName('walls').traverse((o) => { if (o.isMesh) occluders.push(o); });
  a.scene.getObjectByName('roofs').traverse((o) => { if (o.isMesh) occluders.push(o); });
  const rc = new T.Raycaster();
  const targets = Object.values(a.overpasses).map((o) => {
    const [d0, d1] = o.site.deck;
    return [0.2, 0.5, 0.8].map((f) => o.O.clone().addScaledVector(o.N, d0 + (d1 - d0) * f).setY(o.paths.yTop + 0.6));
  });
  const out = [];
  for (let r = 18; r <= 46; r += 2) for (let a1 = 0; a1 < 360; a1 += 6) {
    const x = r * Math.cos(a1 * Math.PI / 180), n = r * Math.sin(a1 * Math.PI / 180);
    const p = new T.Vector3(x, a.ground(x, -n) + 1.65, -n);
    let score = [];
    for (const tg of targets) {
      let vis = 0;
      for (const t of tg) {
        const dir = t.clone().sub(p); const L = dir.length(); dir.normalize();
        rc.set(p, dir); rc.far = L;
        if (rc.intersectObjects(occluders, false).length === 0) vis++;
      }
      score.push(vis);
    }
    if (score[0] >= 2 && score[1] >= 2) out.push([+x.toFixed(1), +n.toFixed(1), score.join('')]);
  }
  return out;
});
console.log(JSON.stringify(res));
await browser.close();
