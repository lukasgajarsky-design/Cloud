import { chromium } from 'playwright';
const [, , url, out, ...views] = process.argv;
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto('http://127.0.0.1:8766/web/glb_check.html');
await page.waitForFunction(() => window.READY);
console.log('bbox', JSON.stringify(await page.evaluate((u) => window.load(u), url)));
let i = 0;
for (const v of views) {
  const [px, py, pz, tx, ty, tz] = v.split(',').map(Number);
  await page.evaluate(([p, t]) => window.shot(p, t), [[px, py, pz], [tx, ty, tz]]);
  await page.screenshot({ path: `${out}_${i++}.jpg`, type: 'jpeg', quality: 85 });
}
await browser.close();
