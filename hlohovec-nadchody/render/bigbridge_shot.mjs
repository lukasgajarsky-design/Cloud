// Screenshots of the long footbridge variant from a few camera positions (local check).
import { chromium } from 'playwright';
const [, , out, ...views] = process.argv;
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const variant = process.env.VARIANT || 'big';
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[console]', m.text().slice(0, 300)); });
await page.goto(`http://127.0.0.1:8766/web/capture.html?mode=capture&w=1280&h=720&variant=${variant}&shadow=2048`, { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY, null, { timeout: 600000 });
await page.addStyleTag({ content: 'body > :not(canvas) { display: none !important; }' });
let i = 0;
for (const v of views) {
  const [px, py, pz, tx, ty, tz] = v.split(',').map(Number);
  await page.evaluate(([p, t]) => {
    const app = window.APP;
    app.camera.position.set(p[0], p[1], p[2]);
    app.camera.lookAt(t[0], t[1], t[2]);
    app.camera.aspect = 1280 / 720; app.camera.updateProjectionMatrix();
    app.setShadowFocus({ x: t[0], y: t[1], z: t[2] }, 120);
    app.setTime(20, app.camera.position);
    app.render();
  }, [[px, py, pz], [tx, ty, tz]]);
  await page.screenshot({ path: `${out}_${i++}.jpg`, type: 'jpeg', quality: 85 });
}
await browser.close();
