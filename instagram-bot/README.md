# Instagram Bot – Meta Graph API + Claude Opus 5.5

Produkčný bot pre Instagram biznis/creator účet. Hlavným „mozgom“ je **Claude Opus 5.5**
(`claude-opus-5-5`, 1M kontext, adaptívne premýšľanie). Bot má dva režimy:

| Režim | Príkaz | Čo robí |
|---|---|---|
| **Učenie z videa** | `python main.py --learn --video video.mp4` | ffmpeg rozseká video na snímky (detekcia strihov + 1 fps), odstráni duplicity, prepíše reč s časovými značkami a v **jednej multimodálnej požiadavke** pošle všetko do Claude. Výsledný **Video Style Blueprint** zapíše do `config/style_guide.txt`. |
| **Automatizácia** | `python main.py --run` | V slučke odpovedá na komentáre, odpovedá na DM a publikuje príspevky z `queue/`. Pred každým volaním Claude načíta `config/style_guide.txt` a vloží ho do system promptu s inštrukciou *„Generuj všetok textový aj štruktúrovaný výstup striktne podľa tohto vizuálno-textového štýlu. Nemeň tón ani dynamiku.“* |

Ďalšie príkazy: `--script "téma"` (scenár videa podľa blueprintu), `--check` (overenie
nastavení), `--refresh-token` (predĺženie Instagram tokenu).

---

## Obsah

1. [Štruktúra projektu](#1-štruktúra-projektu)
2. [Inštalácia](#2-inštalácia)
3. [Ako získať Meta Access Token](#3-ako-získať-meta-access-token)
4. [Ostatné kľúče (Anthropic, OpenAI)](#4-ostatné-kľúče-anthropic-openai)
5. [Verejná URL pre médiá (publikovanie)](#5-verejná-url-pre-médiá-publikovanie)
6. [Spustenie](#6-spustenie)
7. [Fronta príspevkov `queue/`](#7-fronta-príspevkov-queue)
8. [Bezpečnosť a ochrana proti duplicitám](#8-bezpečnosť-a-ochrana-proti-duplicitám)
9. [Riešenie problémov](#9-riešenie-problémov)
10. [Vývoj a testy](#10-vývoj-a-testy)

---

## 1. Štruktúra projektu

```
instagram-bot/
├── main.py                    # CLI: --run / --learn / --script / --check / --refresh-token
├── .env.example               # šablóna konfigurácie (skopíruj na .env)
├── requirements.txt           # requests, anthropic, python-dotenv, pillow
├── requirements-local-asr.txt # voliteľný lokálny prepis reči (faster-whisper)
├── config/
│   ├── brand_voice.md         # TY vyplníš: tón, fakty, FAQ, čo bot nesmie
│   └── style_guide.txt        # vygeneruje --learn (Video Style Blueprint)
├── queue/                     # sem dávaš príspevky (obrázok/video + .txt prompt)
│   ├── published/             # publikované (s result.json)
│   └── failed/                # zamietnuté/chybné (s error.txt)
├── data/instagram_bot.db      # SQLite – spracované komentáre, DM, posty, analýzy videí
├── instagram_bot.log          # log (rotuje sa po 5 MB)
├── output/scripts/            # scenáre z --script
├── instagram_bot/
│   ├── bot.py                 # trieda InstagramBot (orchestrátor)
│   ├── config.py              # načítanie a validácia .env
│   ├── graph_client.py        # HTTP klient Meta API: retries, backoff, rate limiting
│   ├── instagram_api.py       # komentáre, DM, publikovanie (Instagram aj Facebook Login)
│   ├── claude_client.py       # Claude Opus 5.5: structured outputs, streaming, fallback
│   ├── prompts.py             # system prompty a JSON schémy
│   ├── knowledge.py           # načítanie brand voice + blueprintu (bez reštartu)
│   ├── storage.py             # SQLite (claim → act → finish)
│   ├── post_queue.py          # fronta, plánovanie (publish_at), archivácia
│   ├── media_host.py          # verejná URL médií + overenie dostupnosti
│   ├── logging_setup.py       # rotujúci log s maskovaním tokenov
│   ├── process_lock.py        # zámok proti súbežnému behu (cron)
│   └── video/
│       ├── ffmpeg.py          # ffprobe, snímky (scény + fps), audio – cez subprocess
│       ├── frames.py          # deduplikácia (SHA-256 + dHash) a výber snímok
│       ├── metrics.py         # rytmus strihu, tempo reči
│       ├── transcription.py   # prepis reči: OpenAI whisper-1 / faster-whisper / none
│       └── style_learner.py   # celá pipeline --learn
└── tests/                     # 48 testov (Meta aj Claude sú v testoch falošné)
```

## 2. Inštalácia

Potrebuješ **Python 3.10+** a **ffmpeg** (len pre `--learn`).

```bash
# 1) ffmpeg
sudo apt update && sudo apt install -y ffmpeg      # Ubuntu/Debian
brew install ffmpeg                                # macOS
winget install --id Gyan.FFmpeg                    # Windows (potom nový terminál)

# 2) Python prostredie a závislosti
cd instagram-bot
python3 -m venv .venv
source .venv/bin/activate                          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# voliteľne lokálny prepis reči bez cloudu:
# pip install -r requirements-local-asr.txt

# 3) Konfigurácia
cp .env.example .env
chmod 600 .env                                     # súbor s tajomstvami čitateľný len pre teba
```

Ak ffmpeg chýba, `--learn` sa ukončí so zrozumiteľnou hláškou a návodom na inštaláciu
pre tvoj systém.

## 3. Ako získať Meta Access Token

Instagram API funguje len pre **profesionálny účet** (Business alebo Creator).
V aplikácii Instagram: *Nastavenia → Typ účtu a nástroje → Prepnúť na profesionálny účet*.

Meta ponúka dve oficiálne cesty. **Odporúčam variant A** – je jednoduchší a nepotrebuje
Facebook stránku.

### Variant A – Instagram Login (`graph.instagram.com`) ✅ odporúčané

1. Choď na <https://developers.facebook.com/apps> → **Create App**.
   Ako prípad použitia (use case) zvoľ **„Manage messaging & content on Instagram“**
   (ak ho nevidíš, zvoľ typ **Business**) a dokonči vytvorenie aplikácie.
2. V ľavom menu aplikácie otvor **Instagram → API setup with Instagram login**.
3. V sekcii **1. Generate access tokens** klikni **Add account**, prihlás sa do svojho
   Instagram účtu a povoľ prístup.
4. Pri účte klikni **Generate token**, potvrď oprávnenia a **skopíruj token**
   (je to long-lived token platný 60 dní). Hneď vedľa vidíš aj číselné
   **Instagram account ID** – to je `INSTAGRAM_BUSINESS_ACCOUNT_ID`.
5. Skontroluj, že aplikácia má tieto oprávnenia (sekcia *Permissions*):
   `instagram_business_basic`, `instagram_business_manage_comments`,
   `instagram_business_manage_messages`, `instagram_business_content_publish`.
6. **Povoľ prístup k správam (pre DM):** v aplikácii Instagram v telefóne
   *Nastavenia → Správy a odpovede na príbehy → Nástroje na správu správ (Connected tools)
   → Povoliť prístup k správam*.
7. Do `.env` zapíš:

   ```ini
   META_GRAPH_HOST=graph.instagram.com
   META_ACCESS_TOKEN=<skopírovaný token>
   INSTAGRAM_BUSINESS_ACCOUNT_ID=<Instagram account ID>
   ```

8. Over: `python main.py --check` – vypíše tvoje používateľské meno a ID z API.
9. **Predlžovanie tokenu:** token platí 60 dní. Príkaz `python main.py --refresh-token`
   ho predĺži o ďalších 60 dní a sám ho zapíše do `.env` (token musí byť starší ako 24 h
   a ešte platný). Odporúčam cron raz týždenne – pozri [Spustenie](#6-spustenie).

> **Režim aplikácie:** pre tvoj vlastný účet (má rolu v aplikácii) zvyčajne stačí
> vývojový režim (Development). Ak má bot odpovedať v DM **cudzím zákazníkom**, Meta
> vyžaduje *Advanced Access* pre `instagram_business_manage_messages` (App Review)
> a prepnutie aplikácie do režimu **Live**. Meta pravidlá občas mení – aktuálny stav
> vidíš v App Dashboarde v sekcii *App Review → Permissions and Features*.

### Variant B – Facebook Login (`graph.facebook.com`, Page token)

Použi, ak už máš Instagram účet prepojený s Facebook stránkou a aplikáciu s Facebook Login.

1. Instagram účet prepoj s Facebook stránkou (Meta Business Suite → Nastavenia → Účty Instagram).
2. V <https://developers.facebook.com/tools/explorer> vyber svoju aplikáciu, klikni
   **Generate Access Token** a pridaj oprávnenia: `instagram_basic`,
   `instagram_manage_comments`, `instagram_content_publish`, `instagram_manage_messages`,
   `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `business_management`.
3. Vymeň krátkodobý token za dlhodobý (App ID a App Secret nájdeš v *App settings → Basic*):

   ```
   GET https://graph.facebook.com/v23.0/oauth/access_token
       ?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET
       &fb_exchange_token=KRÁTKODOBÝ_TOKEN
   ```

4. S dlhodobým tokenom zavolaj v Graph API Exploreri
   `me/accounts?fields=id,name,access_token,instagram_business_account`.
   Z odpovede použi `access_token` stránky (**Page token – pri tomto postupe neexpiruje**),
   `id` stránky a `instagram_business_account.id`.
5. Do `.env`:

   ```ini
   META_GRAPH_HOST=graph.facebook.com
   META_ACCESS_TOKEN=<Page access token>
   META_PAGE_ID=<ID stránky>
   INSTAGRAM_BUSINESS_ACCOUNT_ID=<instagram_business_account.id>
   META_APP_SECRET=<App Secret>   # bot posiela appsecret_proof; zapni "Require App Secret"
   ```

> Tokeny nikdy nevkladaj do kódu, chatu ani gitu. Ak omylom unikne, v App Dashboarde ho
> zneplatníš resetom App Secret alebo odobratím prístupu aplikácie v nastaveniach Instagramu.

## 4. Ostatné kľúče (Anthropic, OpenAI)

- **Anthropic API key:** <https://console.anthropic.com> → *API Keys* → *Create Key* →
  `ANTHROPIC_API_KEY`. Model je predvolene `claude-opus-5-5` (`ANTHROPIC_MODEL`).
- **Úsilie premýšľania (adaptive thinking effort)** je oddelené pre jednotlivé úlohy:
  `ANTHROPIC_EFFORT_REPLIES=medium` (komentáre, DM), `ANTHROPIC_EFFORT_CONTENT=high`
  (popisy, scenáre), `ANTHROPIC_EFFORT_LEARN=high` (analýza videa). Povolené:
  `low | medium | high | xhigh | max`.
- **Prepis reči (`--learn`):**
  - `ASR_PROVIDER=openai` – OpenAI Audio API, model `whisper-1`, segmenty s časovými
    značkami. Kľúč: <https://platform.openai.com/api-keys> → `OPENAI_API_KEY`.
    Dlhé audio sa automaticky delí na časti (limit OpenAI je 25 MB na súbor).
  - `ASR_PROVIDER=faster-whisper` – lokálne, zadarmo a súkromne
    (`pip install -r requirements-local-asr.txt`; prvé spustenie stiahne model).
  - `ASR_PROVIDER=none` – bez prepisu (analýza len z obrazu a strihov).

**Orientačné náklady** (ceny Claude Opus 5.5: 4 $/1M vstupných, 20 $/1M výstupných tokenov):
jedna analýza 60 s videa s ~240 snímkami 768 px ≈ 110 tis. vstupných tokenov + blueprint
a premýšľanie ≈ **0,5 – 1,5 $**; jedna odpoveď na komentár/DM ≈ **0,02 – 0,06 $**
(spoločná časť system promptu sa cachuje). Presnú spotrebu každého volania vidíš v logu.

## 5. Verejná URL pre médiá (publikovanie)

Instagram API **neprijíma súbor priamo** – pri publikovaní mu bot pošle verejnú HTTPS
adresu a Meta si médium stiahne. Preto musí byť priečinok `queue/` dostupný z internetu:

```ini
MEDIA_PUBLIC_BASE_URL=https://cdn.mojadomena.sk/ig-queue-8f3k2
# queue/jesen.jpg  →  https://cdn.mojadomena.sk/ig-queue-8f3k2/jesen.jpg
```

Príklad pre nginx – sprístupní **len** médiá (nie .txt prompty) pod ťažko uhádnuteľnou cestou:

```nginx
# len .jpg/.jpeg/.mp4/.mov priamo v queue/ – všetko ostatné (prompty .txt, podpriečinky) vráti 404
location ~* ^/ig-queue-8f3k2/([^/]+\.(?:jpe?g|mp4|mov))$ {
    alias /home/bot/instagram-bot/queue/$1;
}
location /ig-queue-8f3k2/ {
    return 404;
}
```

Alternatíva: synchronizuj `queue/` do bucketu (S3, Cloudflare R2) napr. cez `rclone`.
Bot pred publikovaním overí HEAD požiadavkou, že súbor je dostupný a má správnu veľkosť.
Ak publikovanie nepotrebuješ, nastav `ENABLE_POSTS=false`.

## 6. Spustenie

```bash
source .venv/bin/activate

# 0) Over nastavenia, token a prístupy
python main.py --check

# 1) Nauč bota štýl z videa → config/style_guide.txt (predchádzajúci sa prepíše, záloha .bak)
python main.py --learn --video ~/Videos/najlepsi-reel.mp4
python main.py --learn --video ~/Videos/dalsi.mov --merge     # zlúči s existujúcim blueprintom
python main.py --learn --video video.mp4 --force              # znova analyzuj to isté video

# 2) Najprv nasucho – nič neodošle, v logu uvidíš, čo by bot napísal
python main.py --run --once --dry-run

# 3) Ostrá prevádzka v slučke (Ctrl+C = bezpečné ukončenie)
python main.py --run
python main.py --run --tasks comments,dms                     # len vybrané úlohy

# Scenár nového videa presne podľa blueprintu → output/scripts/
python main.py --script "3 chyby pri výbere kávy" --notes "max 30 s, CTA na e-shop"
```

**Cron** (namiesto slučky; zámok zabráni prekrývaniu behov):

```cron
*/5 * * * * cd /home/bot/instagram-bot && .venv/bin/python main.py --run --once >/dev/null 2>&1
0 4 * * 1  cd /home/bot/instagram-bot && .venv/bin/python main.py --refresh-token >/dev/null 2>&1
```

**systemd** (`/etc/systemd/system/instagram-bot.service`):

```ini
[Unit]
Description=Instagram bot (Claude Opus 5.5)
After=network-online.target

[Service]
User=bot
WorkingDirectory=/home/bot/instagram-bot
ExecStart=/home/bot/instagram-bot/.venv/bin/python main.py --run
Restart=on-failure
RestartSec=60
# kód 2 = neplatný token/kľúč → nereštartovať dookola, kým to neopravíš
RestartPreventExitStatus=2

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now instagram-bot` a log sleduj cez `tail -f instagram_bot.log`.

Návratové kódy: `0` OK, `1` chyba konfigurácie/vstupu, `2` neplatný token alebo kľúč
(vďaka `RestartPreventExitStatus=2` ho systemd nereštartuje dookola), `3` bot už beží, `4` iná chyba.

## 7. Fronta príspevkov `queue/`

Dvojica súborov s rovnakým názvom:

```
queue/2026-10-05_jesen.jpg     # obrázok JPEG, alebo video .mp4/.mov (publikuje sa ako Reels)
queue/2026-10-05_jesen.txt     # prompt pre Claude
```

Obsah `.txt` (hlavička s časom je voliteľná – bez nej sa publikuje hneď):

```
publish_at: 2026-10-05 18:00
---
Jesenná akcia: -20 % na všetky sviečky do nedele. Chcem hravý tón a otázku na konci.
```

Claude text skontroluje (fakty voči `brand_voice.md`, vhodnosť), vylepší štruktúru
**hook → body → CTA** podľa blueprintu a doplní 5–15 hashtagov. Ak obsah zamietne,
súbory sa presunú do `queue/failed/` s dôvodom v `error.txt`. Publikované príspevky
skončia v `queue/published/` s `result.json` (ID, odkaz, výsledný popis).
Obrázky musia byť **JPEG** – iné formáty Instagram API nepodporuje.

## 8. Bezpečnosť a ochrana proti duplicitám

- **Tajomstvá len z `.env`** (python-dotenv); log ich maskuje (`***`) aj v traceback-u.
  Meta token sa posiela v hlavičke `Authorization`, nie v URL.
- **Žiadna odpoveď dvakrát:** každý komentár/správa sa pred odoslaním atomicky
  „zaberie“ v SQLite (`claim`). Pri neistom výsledku (timeout po odoslaní) sa operácia
  **neopakuje**. Bot navyše preskočí komentáre, na ktoré už vlastník odpovedal ručne.
  Rovnaký post (podľa SHA-256 obsahu) sa nepublikuje dvakrát ani po premenovaní súborov.
- **Rate limiting:** exponenciálny backoff s jitterom pri 429/5xx a pri kódoch Meta
  4/17/32/613/800xx; čítanie hlavičiek `X-App-Usage` / `X-Business-Use-Case-Usage`
  a preventívne spomalenie od 75 % limitu; pri dlhom zablokovaní bot počká celý interval.
  Anthropic SDK opakuje 429/5xx samo (`ANTHROPIC_MAX_RETRIES`).
- **Prompt injection:** komentáre a DM sa vkladajú ako nedôveryhodné dáta; Claude má
  pravidlá nesľubovať zľavy, nepísať cudzie odkazy a citlivé veci **eskalovať človeku**
  (v logu `ESKALÁCIA`, prehľad cez `--check`). Odmietnutie modelom sa nikdy nepublikuje.
- **Prvé spustenie:** na komentáre staršie ako `COMMENT_MAX_AGE_HOURS` (48 h) bot neodpovedá.
- **DM okno 24 h:** Instagram povoľuje odpovedať do 24 h od poslednej správy zákazníka.

Kontrola databázy: `sqlite3 data/instagram_bot.db "SELECT status, COUNT(*) FROM processed_comments GROUP BY status"`.

## 9. Riešenie problémov

| Hláška | Príčina a riešenie |
|---|---|
| `Meta access token je neplatný alebo expiroval` (kód 190) | Vygeneruj nový token (kap. 3) alebo spusti `--refresh-token` ešte pred expiráciou. |
| `(#10)` / `(#200)` chýba oprávnenie | Doplň oprávnenia v App Dashboarde; pre DM povoľ „Prístup k správam“ v Instagrame. |
| `Médium nie je dostupné na …` | `MEDIA_PUBLIC_BASE_URL` nesmeruje na `queue/` alebo server ešte nemá súbor. |
| `Meta nevedela spracovať médium: ERROR` | Nevhodný formát/rozmer – video ulož ako MP4 (H.264 + AAC) na výšku 9:16; presné limity sú v dokumentácii Meta (*Reels specifications*). |
| `Prekročený limit volaní Meta API` | Bot sám počká; zníž `MAX_*_PER_CYCLE` alebo zvýš `POLL_INTERVAL_SECONDS`. |
| `ffmpeg/ffprobe nie je nainštalovaný` | Nainštaluj podľa návodu v hláške alebo nastav `FFMPEG_BINARY`/`FFPROBE_BINARY`. |
| `Neplatný ANTHROPIC_API_KEY` / `Model … neexistuje` | Skontroluj kľúč a `ANTHROPIC_MODEL=claude-opus-5-5`. |
| Bot neodpovedá na DM | Konverzácia je staršia ako 24 h, alebo aplikácia nemá Advanced Access (kap. 3). |

## 10. Vývoj a testy

```bash
pip install -r requirements-dev.txt
pytest            # 48 testov; video testy použijú skutočný ffmpeg, API sú falošné
ruff check .      # linter
mypy              # striktná kontrola typov
```
