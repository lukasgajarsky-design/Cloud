# Hlohovec – návrh nadchodov (3D vizualizácia)

3D model okolia kruhového objazdu v Hlohovci s dvomi navrhovanými lávkami pre peších
(ulica Hlohová a ulica SNP) a renderovanie videí z pohľadu chodca a z leteckého preletu.

## Štruktúra
- `tools/` – príprava geodát: satelitné dlaždice (Esri World Imagery), OSM budovy/cesty, terén (Terrarium),
  stromy rozpoznané zo snímky, uličné SDF textúry, dopravné trasy, zvuková stopa.
- `web/js/` – three.js scéna (`world.js`, `overpass.js`, `traffic.js`, `people.js`), réžia kamier (`director.js`),
  titulky (`overlay.js`), interaktívny prehliadač (`viewer.js`).
- `web/data/` – pripravené dáta scény, `web/data/sites.json` – poloha a orientácia nadchodov.
- `render/` – offline renderovanie snímok cez headless Chromium (`render.mjs`) a fronta render → zvuk → MP4 (`pipeline.sh`).

## Spustenie
```
npm i && cp -r node_modules/three/build node_modules/three/examples/jsm web/lib/three/   # three.js 0.170.0
python3 -m http.server 8765 --directory web    # prehliadač: http://127.0.0.1:8765/viewer_local.html
FRAMES=/tmp/frames render/pipeline.sh fpv_hlohova fpv_snp aerial
```

Podklady: © Esri, Maxar, Earthstar Geographics; © prispievatelia OpenStreetMap (ODbL). Ilustračná vizualizácia.
