import { chromium } from 'playwright';
const qs = process.argv[2] || '';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto('http://127.0.0.1:8765/capture.html?mode=capture' + qs, { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
const run = async (label, setup, cam = [-80, 90, 60, 35, 0, -10]) => {
  const ms = await page.evaluate(async ([setup, cam]) => {
    const a = window.APP, c = a.camera;
    eval(setup);
    c.position.set(cam[0], cam[1], cam[2]); c.lookAt(cam[3], cam[4], cam[5]); c.updateProjectionMatrix();
    a.setTime(3);
    const gl = a.renderer.getContext(); const px = new Uint8Array(4);
    const times = [];
    for (let i = 0; i < 3; i++) { const t = performance.now(); a.render(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); times.push(performance.now() - t); }
    return times.slice(1).map((x) => x | 0);
  }, [setup, cam]);
  console.log(qs, label.padEnd(24), ms);
};
await run('aerial', '');
await run('street', '', [20, 160, 12, 55, 155, 32].map((v, i) => (i === 1 || i === 4) ? v - 150 + 151.5 - 150 : v));
await run('aniso4', 'a.data.textures.forEach(t=>{t.anisotropy=4;t.needsUpdate=true})');
await run('nosky', 'a.sky.visible=false');
await browser.close();
