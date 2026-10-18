"""Fill web/videos.html with the uploaded video asset URLs -> web/videos_page.html.

usage: build_videos_page.py [assets.json]
assets.json maps local file names (e.g. fpv_hlohova_720p.mp4, fpv_hlohova_1080p_part00.mp4) to asset urls.
"""
import json, os, sys

VIDEOS = [
    ("fpv_hlohova", "Nadchod Hlohová – pohľad chodca", "Hlohovec_nadchod_Hlohova_chodec.mp4",
     "Od kruhového objazdu, odkiaľ vidno oba nadchody, po chodníku k schodisku, hore cez medzipodestu, po lávke ponad ulicu Hlohová so zastavením nad premávkou a dole k chodníku."),
    ("fpv_snp", "Nadchod SNP – pohľad chodca", "Hlohovec_nadchod_SNP_chodec.mp4",
     "Úvod pri kruhovom objazde s oboma nadchodmi, potom chôdza po severnom chodníku, výstup po schodisku v zelenom páse, prechod ponad ulicu SNP a zostup do parku."),
    ("aerial", "Letecký prelet nad oboma nadchodmi", "Hlohovec_nadchody_prelet.mp4",
     "Prelet nad Hlohovcom ku kruhovému objazdu, oblet oboch nadchodov, prelet popod lávku na Hlohovej, detail nadchodu SNP a záverečné parametre návrhu."),
]
OUT = "out/final"
assets = json.load(open(sys.argv[1])) if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else {}

data = []
for key, title, fname, desc in VIDEOS:
    web = f"{key}_720p.mp4"
    parts = sorted(f for f in os.listdir(OUT) if f.startswith(f"{key}_1080p_part") and f.endswith(".mp4"))
    if web not in assets or not parts or any(p not in assets for p in parts):
        continue
    dur = float(open(f"{OUT}/{key}.duration").read())
    data.append({
        "key": key, "title": title, "desc": desc, "file": fname, "duration": round(dur, 1),
        "poster": f"posters/{key}.jpg",
        "web": {"url": assets[web], "parts": [assets[web]], "size": os.path.getsize(f"{OUT}/{web}")},
        "full": {"parts": [assets[p] for p in parts], "size": os.path.getsize(f"{OUT}/{key}_1080p.mp4")},
    })
page = open("web/videos.html").read().replace("/*VIDEO_DATA*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
open("web/videos_page.html", "w").write(page)
print(len(data), "videos in page")
