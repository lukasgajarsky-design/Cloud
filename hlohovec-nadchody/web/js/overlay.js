// HTML overlay drawn over the WebGL canvas: titles, captions, 3D-anchored labels, minimap, attribution.
import * as THREE from 'three';

const CSS = `
#overlay { font-family: 'Inter', 'DejaVu Sans', sans-serif; color: #fff; }
#overlay .title { position: absolute; left: 6%; bottom: 13%; max-width: 70%; }
#overlay .title h1 { margin: 0; font-weight: 800; font-size: 72px; letter-spacing: -1px; line-height: 1.02; text-shadow: 0 3px 24px rgba(0,0,0,.45); }
#overlay .title p { margin: 14px 0 0; font-weight: 500; font-size: 30px; opacity: .95; text-shadow: 0 2px 14px rgba(0,0,0,.5); }
#overlay .title .bar { width: 120px; height: 7px; background: #c7773d; border-radius: 4px; margin-bottom: 22px; }
#overlay .caption { position: absolute; left: 50%; bottom: 7%; transform: translateX(-50%); background: rgba(16,20,26,.62); padding: 14px 30px; border-radius: 40px; font-size: 30px; font-weight: 600; white-space: nowrap; border: 1px solid rgba(255,255,255,.18); }
#overlay .label { position: absolute; transform: translate(-50%, -100%); text-align: center; }
#overlay .label .pill { background: #fff; color: #1d232b; font-weight: 700; font-size: 26px; padding: 9px 20px; border-radius: 30px; box-shadow: 0 6px 24px rgba(0,0,0,.35); white-space: nowrap; }
#overlay .label .pill i { display: inline-block; width: 14px; height: 14px; border-radius: 50%; background: #c7773d; margin-right: 10px; vertical-align: 1px; }
#overlay .label .stem { width: 3px; height: 46px; margin: 0 auto; background: linear-gradient(#fff, rgba(255,255,255,.2)); }
#overlay .mini { position: absolute; right: 30px; top: 30px; border-radius: 18px; overflow: hidden; box-shadow: 0 8px 30px rgba(0,0,0,.4); border: 3px solid rgba(255,255,255,.85); }
#overlay .attr { position: absolute; right: 18px; bottom: 10px; font-size: 15px; opacity: .8; text-shadow: 0 1px 4px rgba(0,0,0,.8); }
#overlay .brand { position: absolute; left: 22px; top: 20px; font-size: 20px; font-weight: 700; letter-spacing: .5px; text-shadow: 0 1px 8px rgba(0,0,0,.6); opacity: .92; }
#overlay .brand span { color: #f0a46b; }
#overlay .end { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); background: rgba(14,18,24,.72); border-radius: 26px; padding: 40px 56px; width: 980px; border: 1px solid rgba(255,255,255,.2); }
#overlay .fade { position: absolute; inset: 0; background: #000; opacity: 0; }
#overlay .end h2 { margin: 0 0 18px; font-size: 52px; font-weight: 800; }
#overlay .end ul { margin: 0; padding-left: 30px; font-size: 28px; line-height: 1.55; font-weight: 500; }
#overlay .end .note { margin-top: 18px; font-size: 20px; opacity: .75; }
`;

const LABELS = { hlohova: 'Nadchod Hlohová', snp: 'Nadchod SNP' };

export class Overlay {
  constructor(root, app, director, opts = {}) {
    this.root = root; this.app = app; this.dir = director;
    this.scale = opts.scale || 1;
    const st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    root.innerHTML = `
      <div class="brand">HLOHOVEC · <span>návrh nadchodov</span></div>
      <div class="title"><div class="bar"></div><h1></h1><p></p></div>
      <div class="caption"></div>
      <div class="label" data-k="hlohova"><div class="pill"><i></i>${LABELS.hlohova}</div><div class="stem"></div></div>
      <div class="label" data-k="snp"><div class="pill"><i></i>${LABELS.snp}</div><div class="stem"></div></div>
      <canvas class="mini" width="300" height="276"></canvas>
      <div class="end"><h2>Návrh dvoch nadchodov</h2><ul>
        <li>ulica Hlohová a ulica SNP, hneď za kruhovým objazdom</li>
        <li>lávka šírky 3,0 m s drevenou pochôdznou plochou</li>
        <li>podjazdná výška 5,0 m nad vozovkou</li>
        <li>schodiská s medzipodestou (2 × 18 schodov), oceľové zábradlie</li></ul>
        <div class="note">Ilustračná vizualizácia – rozmery a umiestnenie sú orientačné.</div></div>
      <div class="fade"></div>
      <div class="attr">Podklady: © Esri, Maxar, Earthstar Geographics · © prispievatelia OpenStreetMap · vizualizácia návrhu</div>`;
    this.el = {
      title: root.querySelector('.title'), h1: root.querySelector('.title h1'), sub: root.querySelector('.title p'),
      caption: root.querySelector('.caption'), mini: root.querySelector('.mini'), end: root.querySelector('.end'),
      labels: Object.fromEntries([...root.querySelectorAll('.label')].map((e) => [e.dataset.k, e])),
    };
    this.miniImg = null;
    this.miniMeta = null;
    this.anchors = {
      hlohova: director.deckC(app.overpasses.hlohova).setY(app.overpasses.hlohova.paths.yTop + 3.2),
      snp: director.deckC(app.overpasses.snp).setY(app.overpasses.snp.paths.yTop + 3.2),
    };
  }

  async load(base) {
    this.miniMeta = await fetch(`${base}/minimap.json`).then((r) => r.json());
    this.miniImg = await new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.src = `${base}/minimap.jpg`; });
    return this;
  }

  update(name, t, W, H) {
    const v = this.dir.videos[name];
    const op = (c) => { const r = Math.min(0.7, (c.t1 - c.t0) / 3); return Math.min(Math.max(0, (t - c.t0) / r), Math.max(0, (c.t1 - t) / r), 1); };
    let title = null, caption = null, end = 0, fade = 0;
    const labelOp = { hlohova: 0, snp: 0 };
    for (const c of v.cues) {
      if (t < c.t0 || t > c.t1) continue;
      const o = op(c);
      if (c.type === 'title') title = [c, o];
      else if (c.type === 'caption') caption = [c, o];
      else if (c.type === 'label') labelOp[c.key] = Math.max(labelOp[c.key], o);
      else if (c.type === 'endcard') end = o;
      else if (c.type === 'fade') fade = Math.max(fade, 1 - Math.abs(t - (c.t0 + c.t1) / 2) / ((c.t1 - c.t0) / 2));
    }
    this.el.title.style.opacity = title ? title[1] : 0;
    if (title) { this.el.h1.textContent = title[0].title; this.el.sub.textContent = title[0].sub; }
    this.el.caption.style.opacity = caption ? caption[1] : 0;
    if (caption) this.el.caption.textContent = caption[0].text;
    this.el.end.style.opacity = end;
    this.root.querySelector('.fade').style.opacity = Math.min(1, fade * 1.6);
    // 3D anchored labels
    const cam = this.app.camera;
    for (const [k, el] of Object.entries(this.el.labels)) {
      const p = this.anchors[k].clone().project(cam);
      const vis = p.z < 1 && Math.abs(p.x) < 1.1 && Math.abs(p.y) < 1.1;
      el.style.opacity = vis ? labelOp[k] : 0;
      if (vis) { el.style.left = `${((p.x + 1) / 2) * W}px`; el.style.top = `${((1 - p.y) / 2) * H}px`; }
    }
    // minimap with walker position and view cone
    const mini = this.el.mini;
    mini.style.display = v.minimap ? 'block' : 'none';
    if (v.minimap && this.miniImg) {
      const g = mini.getContext('2d'), m = this.miniMeta;
      const cx = cam.position.x, cn = -cam.position.z;
      const span = 95; // metres shown across the minimap
      const sx = mini.width / span;
      const ix = (cx - m.west) * m.ppm, iy = (m.north - cn) * m.ppm;
      const srcW = span * m.ppm, srcH = srcW * mini.height / mini.width;
      g.fillStyle = '#222'; g.fillRect(0, 0, mini.width, mini.height);
      g.drawImage(this.miniImg, ix - srcW / 2, iy - srcH / 2, srcW, srcH, 0, 0, mini.width, mini.height);
      const dir = new THREE.Vector3(); cam.getWorldDirection(dir);
      const yaw = Math.atan2(dir.x, -dir.z);
      const px = mini.width / 2, py = mini.height / 2;
      g.save(); g.translate(px, py); g.rotate(yaw);
      const grd = g.createRadialGradient(0, 0, 4, 0, 0, 70);
      grd.addColorStop(0, 'rgba(90,170,255,.75)'); grd.addColorStop(1, 'rgba(90,170,255,0)');
      g.fillStyle = grd; g.beginPath(); g.moveTo(0, 0); g.arc(0, 0, 70, -Math.PI / 2 - 0.5, -Math.PI / 2 + 0.5); g.closePath(); g.fill();
      g.restore();
      g.fillStyle = '#fff'; g.beginPath(); g.arc(px, py, 9, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#2f7de1'; g.beginPath(); g.arc(px, py, 6, 0, Math.PI * 2); g.fill();
      g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(0, mini.height - 30, mini.width, 30);
      g.fillStyle = '#fff'; g.font = '600 16px Inter, sans-serif';
      g.fillText('S ↑   10 m', 12, mini.height - 10);
      g.fillRect(mini.width - 12 - 10 * sx, mini.height - 17, 10 * sx, 4);
    }
  }
}
