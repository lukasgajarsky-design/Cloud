import { chromium } from 'playwright';
const out = process.argv[2];
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
for (const [w, h, name] of [[1280, 720, 'desk'], [400, 820, 'phone']]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await page.goto('http://127.0.0.1:8766/web/zona_local.html', { waitUntil: 'load' });
  await page.waitForFunction(() => document.body.classList.contains('ready'), null, { timeout: 600000 });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${out}/zv_${name}.jpg`, type: 'jpeg', quality: 85 });
  if (name === 'desk') { await page.click('[data-go="jz"]'); await page.waitForTimeout(8000); await page.screenshot({ path: `${out}/zv_${name}_jz.jpg`, type: 'jpeg', quality: 85 }); }
  await page.close();
}
await browser.close();
