// Local check of the viewer's model download: serves web/ (dl/ from export/dl) through request
// routing, mocks the downloads capability and compares each saved ZIP with the manifest sha256.
import { chromium } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import { join, extname } from 'node:path';
const root = new URL('..', import.meta.url).pathname;
const out = process.argv[2];
const manifest = JSON.parse(readFileSync(join(root, 'export/dl/model_downloads.json'), 'utf8'));
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.txt': 'text/plain', '.jpg': 'image/jpeg', '.png': 'image/png' };
const page0 = '<!doctype html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body>\n'
  + readFileSync(join(root, 'web/viewer.html'), 'utf8').replace("window.HLOHOVEC_B64 = true;", '');
const mock = (failCode) => {
  const hex = (b) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
  window.__saved = [];
  window.claude = { use: async (n) => (n !== 'downloads' ? null : { save: async ({ filename, data }) => {
    if (failCode) throw Object.assign(new Error(failCode), { code: failCode });
    const buf = await data.arrayBuffer();
    window.__saved.push({ filename, size: buf.byteLength, sha256: hex(await crypto.subtle.digest('SHA-256', buf)) });
    return { status: 'saved' };
  } }) };
};
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
let ok = true;
for (const [w, h, name, scheme, failCode] of [[1280, 720, 'desk', 'light', null], [390, 844, 'phone', 'dark', null], [390, 844, 'phone_err', 'light', 'extension_not_enabled']]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme, deviceScaleFactor: name === 'desk' ? 1 : 2 });
  await ctx.route('http://localhost/**', (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p === '/viewer.html') return route.fulfill({ body: page0, contentType: types['.html'] });
    const f = p.startsWith('/dl/') ? join(root, 'export', p) : join(root, 'web', p);
    if (!existsSync(f)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ body: readFileSync(f), contentType: types[extname(f)] || 'application/octet-stream' });
  });
  const page = await ctx.newPage();
  await page.addInitScript(mock, failCode);
  page.on('pageerror', (e) => console.log(`[${name}] pageerror`, e.message));
  await page.goto('http://localhost/viewer.html', { waitUntil: 'load' });
  await page.waitForSelector('#dl-open:not([hidden])', { timeout: 60000 });
  await page.waitForFunction(() => !document.getElementById('status').querySelector('.spinner') || document.getElementById('status').hidden || getComputedStyle(document.getElementById('status')).display === 'none', null, { timeout: 600000 });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${out}/${name}_plate.jpg`, type: 'jpeg', quality: 85 });
  await page.click('#dl-open');
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/${name}_dialog.jpg`, type: 'jpeg', quality: 85 });
  const packs = failCode ? ['iphone'] : ['iphone', 'full'];
  for (const k of packs) {
    await page.click(`[data-pack="${k}"]`);
    await page.waitForFunction(() => !document.querySelector('[data-pack="iphone"]').disabled, null, { timeout: 120000 });
    console.log(`[${name}] ${k} status:`, await page.textContent('#dl-status'));
  }
  if (failCode) await page.screenshot({ path: `${out}/${name}_dialog.jpg`, type: 'jpeg', quality: 85 });
  const saved = await page.evaluate(() => window.__saved);
  for (const [i, k] of (failCode ? [] : packs).entries()) {
    const m = manifest[k], s = saved[i];
    const match = s && s.filename === m.file && s.size === m.size && s.sha256 === m.sha256;
    ok &&= !!match;
    console.log(`[${name}] ${k}: ${s ? `${s.filename} ${s.size} B` : 'nothing saved'} → ${match ? 'sha256 OK' : 'MISMATCH'}`);
  }
  await ctx.close();
}
await browser.close();
console.log(ok ? 'ALL OK' : 'FAILED');
