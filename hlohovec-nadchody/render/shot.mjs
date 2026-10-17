// Quick preview renderer: node render/shot.mjs OUT_PREFIX 'x,y,z,tx,ty,tz,fov[,time]' ...
import { chromium } from 'playwright';
const [, , prefix, ...views] = process.argv;
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: +(process.env.VW || 1920), height: +(process.env.VH || 1080) } });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.type(), m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto('http://127.0.0.1:8765/capture.html?mode=capture' + (process.env.QS || ''), { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
const err = await page.evaluate(() => window.APP_ERROR);
if (err) { console.log('APP ERROR', err); process.exit(1); }
console.log('ready in', await page.evaluate(() => window.APP_READY), 'ms');
let i = 0;
for (const v of views) {
  const [x, y, z, tx, ty, tz, fov, time] = v.split(',').map(Number);
  const ms = await page.evaluate(([x, y, z, tx, ty, tz, fov, time]) => {
    const a = window.APP, c = a.camera;
    c.position.set(x, y, z); c.fov = fov; c.lookAt(tx, ty, tz);
    const h = y - a.ground(x, z);
    c.near = Math.min(5, Math.max(0.15, h * 0.02)); c.updateProjectionMatrix();
    const focus = new window.THREE.Vector3(tx, ty, tz);
    a.setShadowFocus(focus, Math.min(600, Math.max(40, c.position.distanceTo(focus) * 0.9)));
    a.setTime(time || 0);
    const t = performance.now();
    a.render();
    a.renderer.getContext().finish();
    return performance.now() - t;
  }, [x, y, z, tx, ty, tz, fov, time]);
  const file = `${prefix}_${i++}.jpg`;
  const t = Date.now();
  await page.screenshot({ path: file, type: 'jpeg', quality: 90 });
  console.log(file, 'render', ms.toFixed(0), 'ms', 'shot', Date.now() - t, 'ms');
}
await browser.close();
