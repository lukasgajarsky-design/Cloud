// Offline frame renderer: node render/render.mjs VIDEO OUTDIR [fps] [from] [to] [step]
import { chromium } from 'playwright';
import fs from 'node:fs';
const [, , video, outDir, fpsArg = '25', fromArg, toArg, stepArg = '1'] = process.argv;
const fps = +fpsArg, step = +stepArg;
const W = +(process.env.W || 1600), H = +(process.env.H || 900);
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(`http://127.0.0.1:8765/capture.html?mode=capture&w=${W}&h=${H}&shadow=${process.env.SHADOW || 2048}`, { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
const err = await page.evaluate(() => window.APP_ERROR);
if (err) { console.log('APP ERROR', err); process.exit(1); }
const dur = (await page.evaluate(() => window.durations))[video];
const total = Math.round(dur * fps);
const from = fromArg ? +fromArg : 0, to = toArg ? Math.min(+toArg, total) : total;
console.log(video, 'duration', dur, 's', total, 'frames; rendering', from, '..', to - 1);
const metaFile = `${outDir}/meta_${from}_${to}.json`;
const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : {};
const tStart = Date.now();
let done = 0;
for (let f = from; f < to; f += step) {
  const file = `${outDir}/${String(f).padStart(5, '0')}.jpg`;
  if (fs.existsSync(file) && meta[f]) continue;
  const info = await page.evaluate(([v, t]) => window.renderFrame(v, t), [video, f / fps]);
  await page.screenshot({ path: file, type: 'jpeg', quality: 93 });
  meta[f] = info;
  done++;
  if (done % 10 === 0 || f + step >= to) {
    fs.writeFileSync(metaFile, JSON.stringify(meta));
    const el = (Date.now() - tStart) / 1000;
    console.log(`frame ${f}/${total} · ${(el / done).toFixed(2)} s/frame · eta ${(((to - f) / step) * el / done / 60).toFixed(1)} min`);
  }
}
fs.writeFileSync(metaFile, JSON.stringify(meta));
await browser.close();
console.log('done');
