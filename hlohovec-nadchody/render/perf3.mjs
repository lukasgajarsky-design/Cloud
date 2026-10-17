import { chromium } from 'playwright';
const qs = process.argv[2] || '';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto('http://127.0.0.1:8765/capture.html?mode=capture' + qs, { waitUntil: 'load' });
await page.waitForFunction(() => window.APP_READY || window.APP_ERROR, null, { timeout: 600000 });
console.log(await page.evaluate(() => {
  const a = window.APP; const out = {};
  a.scene.traverse((o) => { if (o.isMesh && o.geometry) { const g = o.geometry; const n = (g.index ? g.index.count : g.attributes.position.count) / 3; const top = o.parent && o.parent !== a.scene ? (o.parent.name || o.parent.parent?.name || '?') : o.name; out[top] = (out[top] || 0) + Math.round(n * (o.isInstancedMesh ? o.count : 1)); } });
  return JSON.stringify(out);
}));
const cams = { aerial: [-80, 90, 60, 35, 0, -10], street: [20, 1.7, 12, 55, 5, 32], deck: [30, 7.5, -45, 60, 6, -45] };
for (const [name, cam] of Object.entries(cams)) for (const [label, setup] of [['full', ''], ['noShadow', 'a.renderer.shadowMap.enabled=false;a.scene.traverse(o=>{if(o.material)o.material.needsUpdate=true})'], ['noTrees', "a.trees.group.visible=false"], ['noPeople', "a.people.group.visible=false"], ['noTraffic', "a.traffic.group.visible=false"], ['noBuild', "a.scene.getObjectByName('walls').visible=false;a.scene.getObjectByName('roofs').visible=false"], ['noOverpass', "a.overpasses.hlohova.group.visible=false;a.overpasses.snp.group.visible=false"], ['bare', 'a.sky.visible=false']]) {
  const ms = await page.evaluate(async ([setup, cam]) => {
    const a = window.APP, c = a.camera;
    eval(setup);
    const y0 = a.ground(cam[0], cam[2]);
    c.position.set(cam[0], y0 + cam[1], cam[2]); c.lookAt(cam[3], y0 + cam[4], cam[5]); c.near = 0.3; c.updateProjectionMatrix();
    a.setTime(3);
    const gl = a.renderer.getContext(); const px = new Uint8Array(4);
    let best = 1e9;
    for (let i = 0; i < 2; i++) { const t = performance.now(); a.render(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); best = Math.min(best, performance.now() - t); }
    return best | 0;
  }, [setup, cam]);
  console.log(name.padEnd(8), label.padEnd(12), ms);
  if (label === 'bare') await page.evaluate(() => { const a = window.APP; a.renderer.shadowMap.enabled = true; a.scene.traverse((o) => { o.visible = true; if (o.material) o.material.needsUpdate = true; }); });
}
await browser.close();
