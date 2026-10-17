import { chromium } from 'playwright';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on('requestfailed', (r) => console.log('FAILED', r.url()));
page.on('response', (r) => { if (r.status() >= 400) console.log('HTTP', r.status(), r.url()); });
await page.goto('http://127.0.0.1:8765/capture.html?mode=capture' + (process.argv[2] || ''), { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
const info = await page.evaluate(() => {
  const a = window.APP, gl = a.renderer.getContext();
  const ext = gl.getExtension('EXT_texture_filter_anisotropic');
  let tris = 0; a.scene.traverse((o) => { if (o.isMesh && o.geometry) { const g = o.geometry; const n = (g.index ? g.index.count : g.attributes.position.count) / 3; tris += n * (o.isInstancedMesh ? o.count : 1); } });
  return { maxTex: a.renderer.capabilities.maxTextureSize, aniso: a.renderer.capabilities.getMaxAnisotropy(), renderer: gl.getParameter(gl.RENDERER), tris, l0: a.data.textures[0].image.width };
});
console.log(info);
const test = async (label, setup) => {
  const ms = await page.evaluate(async (setup) => {
    const a = window.APP, T = window.THREE, c = a.camera;
    eval(setup);
    c.position.set(-80, 90, 60); c.lookAt(35, 0, -10); c.updateProjectionMatrix();
    a.setTime(3);
    const gl = a.renderer.getContext(); const px = new Uint8Array(4);
    const times = [];
    for (let i = 0; i < 3; i++) { const t = performance.now(); a.render(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); times.push(performance.now() - t); }
    return times.map((x) => x | 0);
  }, setup);
  console.log(label.padEnd(28), ms);
};
await test('full', '');
await page.evaluate(() => { const a = window.APP; a.camera.position.set(-80, 90, 60); a.camera.lookAt(35, 0, -10); a.camera.updateMatrixWorld(); a.render(); });
await page.screenshot({ path: '/tmp/claude-0/-home-user-Cloud/ef2568bc-86b6-5912-89f2-d53efe4eedb7/scratchpad/prev/perf.jpg', type: 'jpeg' });
await test('no shadows', 'a.renderer.shadowMap.enabled=false; a.scene.traverse(o=>{if(o.material) o.material.needsUpdate=true})');
await test('no trees', "a.scene.getObjectByName('trees').visible=false");
await test('no people', "a.scene.getObjectByName('people').visible=false");
await test('no buildings', "a.scene.getObjectByName('walls').visible=false; a.scene.getObjectByName('roofs').visible=false");
await test('terrain only', "a.scene.getObjectByName('traffic').visible=false; a.sky.visible=false");
const t = Date.now(); const durl = await page.evaluate(() => window.APP.renderer.domElement.toDataURL('image/jpeg', 0.92).length); console.log('toDataURL ms', Date.now() - t, durl);
const t2 = Date.now(); await page.screenshot({ path: '/tmp/x.jpg', type: 'jpeg' }); console.log('screenshot ms', Date.now() - t2);
await browser.close();
