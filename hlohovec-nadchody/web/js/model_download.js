// "Stiahnuť 3D model": the ZIPs ship as base64 text parts (the host serves text, not .zip);
// they are fetched, decoded into one Blob and handed to the downloads capability.
const $ = (s) => document.querySelector(s);
const open = $('#dl-open'), dlg = $('#dl'), status = $('#dl-status'), bar = $('#dl-bar'), fill = bar.querySelector('i');
const buttons = [...dlg.querySelectorAll('[data-pack]')];
const mb = (b) => `${Math.max(1, Math.round(b / 1048576))} MB`;

async function fetchPack(pack, onProgress) {
  const total = Math.ceil(pack.size / 3) * 4;
  const parts = [];
  let got = 0;
  for (const name of pack.parts) {
    const res = await fetch(`dl/${name}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    let text;
    if (res.body && res.body.getReader) {
      const reader = res.body.getReader(), chunks = [];
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        got += value.byteLength;
        onProgress(Math.min(1, got / total));
      }
      text = await new Blob(chunks).text();
    } else {
      text = await res.text();
      got += text.length;
      onProgress(Math.min(1, got / total));
    }
    // every part is a whole number of base64 quads, so each decodes on its own
    const raw = atob(text.trim());
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    parts.push(bytes);
  }
  const blob = new Blob(parts, { type: 'application/zip' });
  if (blob.size !== pack.size) throw new Error('size mismatch');
  return blob;
}

async function start(downloads, pack) {
  buttons.forEach((b) => { b.disabled = true; });
  bar.hidden = false; fill.style.width = '0%';
  status.textContent = 'Pripravujem súbor… 0 %';
  try {
    const blob = await fetchPack(pack, (f) => {
      fill.style.width = `${(f * 100).toFixed(1)}%`;
      status.textContent = `Pripravujem súbor… ${Math.floor(f * 100)} %`;
    });
    status.textContent = 'Potvrďte uloženie súboru.';
    await downloads.save({ filename: pack.file, data: blob });
    status.textContent = 'Uložené. Na iPhone ZIP otvorte v aplikácii Súbory.';
  } catch (e) {
    const code = e && e.code;
    if (code === 'declined') status.textContent = '';
    else if (code === 'rate_limited') status.textContent = 'Otvorené je iné uloženie. Skúste to o chvíľu znova.';
    else if (code === 'extension_not_enabled' || code === 'rejected_extension') status.textContent = 'Súbory ZIP sa v tomto zobrazení uložiť nedajú.';
    else if (code === 'too_large') status.textContent = 'Táto aplikácia taký veľký súbor neuloží. Skúste balík pre iPhone.';
    else if (code === 'unavailable' || code === 'not_granted' || code === 'capability_disabled' || code === 'capability_removed') {
      status.textContent = 'Sťahovanie v tomto zobrazení nie je dostupné.';
      buttons.forEach((b) => { b.hidden = true; });
    } else if (code) status.textContent = 'Tento súbor sa tu uložiť nedá.';
    else status.textContent = 'Súbor sa nepodarilo pripraviť. Skontrolujte pripojenie a skúste to znova.';
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
    bar.hidden = true;
  }
}

const ready = window.claude && window.claude.use ? window.claude.use('downloads') : Promise.resolve(null);
Promise.all([ready, fetch('dl/model_downloads.json').then((r) => r.json())]).then(([downloads, packs]) => {
  if (!downloads) return;
  for (const b of buttons) {
    const pack = packs[b.dataset.pack];
    b.textContent = `Stiahnuť ZIP · ${mb(pack.size)}`;
    b.addEventListener('click', () => start(downloads, pack));
  }
  open.hidden = false;
  open.addEventListener('click', () => { status.textContent = ''; dlg.showModal(); });
  dlg.querySelector('[data-close]').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
}).catch(() => {});
