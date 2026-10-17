// Interactive viewer: orbit the 3D model, jump to either overpass, or play the walk-throughs and the flight.
import * as THREE from 'three';
import { createApp } from './main.js';
import { buildDirector } from './director.js';

const $ = (s) => document.querySelector(s);
const canvas = $('#scene');
const status = $('#status');

const ease = (x) => (x < 0 ? 0 : x > 1 ? 1 : x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

createApp(canvas).then((app) => {
  const dir = buildDirector(app);
  const { renderer, camera, controls } = app;
  const resize = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  window.addEventListener('resize', resize);
  resize();

  const H = app.overpasses.hlohova, S = app.overpasses.snp;
  const deck = (o) => dir.deckC(o).setY(o.paths.yTop - 2);
  const views = {
    overview: { pos: new THREE.Vector3(-150, 150, 175), target: new THREE.Vector3(35, 0, 0) },
    hlohova: { pos: H.W(-38, -36).setY(H.paths.yTop + 16), target: deck(H) },
    snp: { pos: S.W(-34, -30).setY(S.paths.yTop + 15), target: deck(S) },
  };
  let fly = null;            // camera transition
  let tour = null;           // { name, t0 }
  const flyTo = (key) => {
    stopTour();
    const v = views[key];
    fly = { t0: performance.now(), dur: 1800, p0: camera.position.clone(), t0v: controls.target.clone(), p1: v.pos.clone(), t1v: v.target.clone() };
    setActive(key);
  };
  const startTour = (name) => {
    fly = null;
    tour = { name, t0: performance.now(), dur: dir.videos[name].duration };
    controls.enabled = false;
    document.body.classList.add('touring');
    setActive(name);
  };
  function stopTour() {
    if (!tour) return;
    tour = null;
    controls.enabled = true;
    document.body.classList.remove('touring');
    const fwd = new THREE.Vector3(); camera.getWorldDirection(fwd);
    controls.target.copy(camera.position).addScaledVector(fwd, 30);
    camera.fov = 50; camera.near = 0.5; camera.updateProjectionMatrix();
    setActive(null);
  }
  const setActive = (key) => document.querySelectorAll('[data-go]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.go === key)));
  document.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.go;
    if (views[k]) flyTo(k); else startTour(k);
  }));
  $('#stop').addEventListener('click', () => { stopTour(); flyTo('overview'); });

  // floating labels above both decks
  const labels = [[H, $('#lab-h')], [S, $('#lab-s')]].map(([o, el]) => [dir.deckC(o).setY(o.paths.yTop + 3.5), el]);

  camera.position.copy(views.overview.pos);
  controls.target.copy(views.overview.target);
  controls.minDistance = 4; controls.maxDistance = 2500;
  controls.update();

  const clock = new THREE.Clock();
  let simT = 0;
  const loop = () => {
    const dt = Math.min(0.05, clock.getDelta());
    simT += dt;
    if (tour) {
      const t = (performance.now() - tour.t0) / 1000;
      if (t >= tour.dur) { stopTour(); flyTo('overview'); }
      else {
        dir.apply(tour.name, t);
        $('#progress').style.width = `${(t / tour.dur) * 100}%`;
      }
    } else {
      if (fly) {
        const k = ease((performance.now() - fly.t0) / fly.dur);
        camera.position.lerpVectors(fly.p0, fly.p1, k);
        controls.target.lerpVectors(fly.t0v, fly.t1v, k);
        if (k >= 1) fly = null;
      }
      controls.update();
      const h = camera.position.y - app.ground(camera.position.x, camera.position.z);
      camera.near = Math.min(3, Math.max(0.2, h * 0.02));
      camera.updateProjectionMatrix();
      app.setShadowFocus(controls.target, Math.min(420, Math.max(40, camera.position.distanceTo(controls.target) * 0.8)));
      app.setTime(simT, camera.position);
    }
    camera.updateMatrixWorld();
    for (const [p, el] of labels) {
      const q = p.clone().project(camera);
      const vis = !tour && q.z < 1 && Math.abs(q.x) < 1.05 && Math.abs(q.y) < 1.05;
      el.hidden = !vis;
      if (vis) el.style.transform = `translate(${((q.x + 1) / 2) * canvas.clientWidth}px, ${((1 - q.y) / 2) * canvas.clientHeight}px) translate(-50%, -100%)`;
    }
    app.render();
    requestAnimationFrame(loop);
  };
  document.body.classList.add('ready');
  status.hidden = true;
  loop();
}).catch((e) => {
  status.textContent = 'Model sa nepodarilo načítať. Skúste stránku obnoviť alebo otvoriť v prehliadači s podporou WebGL 2.';
  console.error(e);
});
