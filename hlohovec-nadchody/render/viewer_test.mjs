import { chromium } from 'playwright';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const out = process.argv[2];
for (const [w, h, name] of [[1280, 720, 'desk'], [400, 820, 'phone']]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 200)); });
  await page.goto('http://127.0.0.1:8765/viewer_local.html', { waitUntil: 'load' });
  await page.waitForFunction(() => document.body.classList.contains('ready') || !document.getElementById('status').querySelector('.spinner'), null, { timeout: 600000 });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: `${out}/viewer_${name}.jpg`, type: 'jpeg', quality: 85 });
  if (name === 'desk') {
    await page.click('[data-go="hlohova"]');
    await page.waitForTimeout(9000);
    await page.screenshot({ path: `${out}/viewer_${name}_h.jpg`, type: 'jpeg', quality: 85 });
  }
  await page.close();
}
await browser.close();
