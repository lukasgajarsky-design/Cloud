// Export the 3D model files: node render/export.mjs OUT_DIR
import { chromium } from 'playwright';
import fs from 'node:fs';
const out = process.argv[2];
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle', '--js-flags=--max-old-space-size=8192'] });
const page = await browser.newPage();
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.text().slice(0, 200)); });
await page.goto('http://127.0.0.1:8766/web/export.html?mode=capture&w=320&h=180', { waitUntil: 'load' });
await page.waitForFunction(() => window.EXPORT_READY || window.EXPORT_ERROR, null, { timeout: 600000 });
const err = await page.evaluate(() => window.EXPORT_ERROR);
if (err) { console.log(err); process.exit(1); }
const jobs = [
  ['Hlohovec_nadchody_maketa_iPhone.usdz', 'usdz', { photoUrl: '../export/ground_usdz.jpg', center: [42, 8], half: 125, gridStep: 2.5, treeDetail: 1, scale: 1 / 400, maxTextureSize: 2048 }],
  ['Hlohovec_nadchody.glb', 'glb', { photoUrl: '../export/ground_glb.jpg', center: [30, 0], half: 300, gridStep: 3, treeDetail: 1 }],
  ['Nadchody_iba_lavky.glb', 'glb', { photoUrl: '../export/ground_usdz.jpg', center: [42, 8], half: 125, onlyOverpasses: true }],
];
for (const [name, kind, o] of jobs) {
  const t = Date.now();
  const r = await page.evaluate(([k, o]) => window.exportModel(k, o), [kind, o]);
  fs.writeFileSync(`${out}/${name}`, Buffer.from(r.b64, 'base64'));
  console.log(name, (r.bytes / 1048576).toFixed(1), 'MB', r.verts, 'verts', JSON.stringify(r.stats), ((Date.now() - t) / 1000).toFixed(0), 's');
}
await browser.close();
