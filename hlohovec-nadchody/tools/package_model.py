"""Package the exported 3D model for download.

Stamps the author into the GLB asset block, writes a Slovak README and builds two ZIPs
(iPhone: USDZ maquette only; all formats: USDZ + both GLBs). Each ZIP is also written as
base64 text parts so the artifact host (which serves text, not .zip) can hand it out.

usage: package_model.py EXPORT_DIR OUT_DIR
"""
import base64
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

AUTHOR = 'Lukáš Gajarský'
COPYRIGHT = f'© 2026 {AUTHOR}. Podklady: © Esri, Maxar, Earthstar Geographics; © prispievatelia OpenStreetMap (ODbL).'
PART = 15 * 1024 * 1024          # base64 characters per part (host limit is 16 MB per text file)

README = f"""HLOHOVEC – NÁVRH DVOCH NADCHODOV (3D MODEL)
Vytvoril: {AUTHOR}

Súbory
------
Hlohovec_nadchody_maketa_iPhone.usdz
    Model pre iPhone a iPad. Otvára sa priamo v systéme (Rýchly náhľad),
    aj v rozšírenej realite (AR). Je to maketa v mierke 1 : 400 –
    na stole má asi 66 × 67 cm. Okolie kruhového objazdu ~250 × 250 m.

Hlohovec_nadchody.glb          (iba v balíku „všetky formáty“)
    Väčší výrez mesta ~600 × 600 m v skutočnej veľkosti (1 jednotka = 1 m).
    Pre počítač: Windows „3D Viewer“ / „Prehliadač 3D“, Blender,
    https://gltf-viewer.donmccurdy.com a iné programy, ktoré čítajú glTF.

Nadchody_iba_lavky.glb         (iba v balíku „všetky formáty“)
    Len samotné dve lávky bez okolia, v skutočnej veľkosti.

Ako otvoriť na iPhone
---------------------
1. Po stlačení „Uložiť“ zvoľte „Uložiť do Súborov“ (Save to Files).
2. V aplikácii Súbory ťuknite na ZIP – rozbalí sa do priečinka.
3. Ťuknite na súbor .usdz – otvorí sa 3D náhľad.
   Hore prepnite „AR“ a namierte telefón na stôl alebo podlahu.
   Dvoma prstami model otáčate a zväčšujete.

Ako otvoriť na počítači
-----------------------
Windows: dvojklik na .glb otvorí aplikáciu 3D Viewer (Prehliadač 3D).
Mac: .usdz otvoríte medzerníkom (Rýchly náhľad) alebo v aplikácii Náhľad.
Blender: Súbor → Import → glTF 2.0 (.glb) alebo Universal Scene Description (.usdz).

Poznámky
--------
Ilustračná vizualizácia – rozmery a umiestnenie nadchodov sú orientačné.
Parametre návrhu: podjazdná výška 5,0 m, šírka lávky 3,0 m,
rozpätie Hlohová 26,0 m, rozpätie SNP 18,5 m, schody 2 × 18 stupňov po 16 cm.

Podklady: satelitná snímka © Esri, Maxar, Earthstar Geographics;
budovy a ulice © prispievatelia OpenStreetMap (licencia ODbL);
výškový model terénu: Mapzen Terrain Tiles (AWS Open Data).
"""


def stamp_glb(src: Path, dst: Path) -> None:
    """Rewrite the GLB JSON chunk with asset.copyright set; the binary chunk is copied untouched."""
    data = src.read_bytes()
    magic, version, _ = struct.unpack_from('<4sII', data, 0)
    assert magic == b'glTF' and version == 2, src
    jlen, jtype = struct.unpack_from('<II', data, 12)
    assert jtype == 0x4E4F534A
    gltf = json.loads(data[20:20 + jlen].decode('utf-8'))
    gltf['asset']['copyright'] = COPYRIGHT
    gltf['asset']['generator'] = f'{gltf["asset"].get("generator", "")} · {AUTHOR}'.strip(' ·')
    js = json.dumps(gltf, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    js += b' ' * (-len(js) % 4)
    rest = data[20 + jlen:]
    out = struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(js) + len(rest)) + struct.pack('<II', len(js), 0x4E4F534A) + js + rest
    dst.write_bytes(out)


def build_zip(path: Path, members: list[tuple[str, Path]]) -> None:
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(zipfile.ZipInfo('Hlohovec_3D_model/CITAJ_MA.txt', (2026, 10, 18, 12, 0, 0)), README.encode('utf-8'), zipfile.ZIP_DEFLATED)
        for name, src in members:
            # the USDZ is a stored zip of JPEG/USDC already; deflating it again gains nothing
            kind = zipfile.ZIP_STORED if name.endswith('.usdz') else zipfile.ZIP_DEFLATED
            z.write(src, f'Hlohovec_3D_model/{name}', compress_type=kind)


def write_parts(zip_path: Path, out: Path) -> dict:
    raw = zip_path.read_bytes()
    b64 = base64.b64encode(raw).decode('ascii')
    names = []
    for i in range(0, len(b64), PART):
        name = f'{zip_path.stem}.part{i // PART:02d}.b64.txt'
        (out / name).write_text(b64[i:i + PART], encoding='ascii')
        names.append(name)
    return {'file': zip_path.name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'parts': names}


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    stage = out / 'stage'
    stage.mkdir(exist_ok=True)
    usdz = src / 'Hlohovec_nadchody_maketa_iPhone.usdz'
    for glb in ('Hlohovec_nadchody.glb', 'Nadchody_iba_lavky.glb'):
        stamp_glb(src / glb, stage / glb)
    (stage / 'CITAJ_MA.txt').write_text(README, encoding='utf-8')

    iphone = out / 'Hlohovec_3D_model_iPhone.zip'
    full = out / 'Hlohovec_3D_model_vsetky_formaty.zip'
    build_zip(iphone, [(usdz.name, usdz)])
    build_zip(full, [(usdz.name, usdz), ('Hlohovec_nadchody.glb', stage / 'Hlohovec_nadchody.glb'),
                     ('Nadchody_iba_lavky.glb', stage / 'Nadchody_iba_lavky.glb')])
    manifest = {'iphone': write_parts(iphone, out), 'full': write_parts(full, out)}
    (out / 'model_downloads.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print(json.dumps(manifest, indent=1))


if __name__ == '__main__':
    main()
