# Claude Strudel Remixer

Remixovanie skladieb s Claude Code podľa workflowu „Claude Code for Music Production: Remixing“:
Demucs oddelí vokál, `analyze_audio.py` zmeria tempo, tóninu a hlasitosť a Claude napíše nový podklad ako live-coding kód pre [Strudel](https://strudel.cc). Pravidlá pre Claude sú v [CLAUDE.md](CLAUDE.md).

## Inštalácia na Windows

Potrebuješ iba [uv](https://docs.astral.sh/uv/), ktorý už máš z trading-bota alebo yt-flac. Python 3.12, FFmpeg a Node.js doinštaluje inštalátor.

1. Stiahni najnovší kód. V Command Prompte:

   ```bat
   cd /d %USERPROFILE%\Cloud
   git pull
   ```

   Ak priečinok `Cloud` ešte nemáš: `git clone -b claude/inspiring-ramanujan-4iyy3s https://github.com/lukasgajarsky-design/Cloud.git`
2. Dvakrát klikni na `Cloud\claude-strudel-remixer\install.bat`.
3. Ak inštalátor doinštaloval FFmpeg alebo Node.js, napíše „Nainštalované“. Zatvor okno a spusti `install.bat` ešte raz, aby Windows načítal nové programy.
4. Inštalácia je hotová, keď uvidíš „🎉 Výborne! Demucs je pripravený“ a „Hotovo“.

Inštalácia stiahne asi 280 MB (z toho PyTorch 124 MB) a prvá separácia ešte 80 MB model Demucs. Ak by sa objavilo okno Windows Firewall pre `node.exe`, môžeš prístup zamietnuť, Strudel potrebuje iba `localhost`.

**Vlastný Python namiesto uv:** funguje 3.10 až 3.14. Python 3.15 zatiaľ nie, lebo PyTorch preň ešte nemá balíčky.

```bat
python -m venv .venv
.venv\Scripts\python setup_and_verify.py
```

## Inštalácia na macOS a Linuxe

```bash
cd ~/Cloud/claude-strudel-remixer
./install.sh
```

Na Macu doinštaluje FFmpeg a Node.js cez [Homebrew](https://brew.sh). Na Linuxe bez NVIDIA karty nainštaluje PyTorch bez CUDA, čo ušetrí niekoľko GB. Podporovaný je Mac s Apple Silicon (M1 a novší). Na Intel Mac nemá Demucs 4.1 hotové balíčky.

## Spustenie Claude Code

Claude Code musí bežať **priamo v priečinku `claude-strudel-remixer`**. Inak nenačíta `CLAUDE.md` ani povolenia z `.claude/settings.json` a relatívne cesty nebudú sedieť.

- **Desktopová aplikácia Claude:** záložka *Code* → *Local* → *Select folder* → `Cloud\claude-strudel-remixer`. Možnosť *worktree* nechaj vypnutú, lebo worktree neobsahuje `.venv` ani tvoje skladby.
- **Terminál:** `cd /d %USERPROFILE%\Cloud\claude-strudel-remixer` a potom `claude`. Claude Code nainštaluješ podľa [code.claude.com/docs/en/setup](https://code.claude.com/docs/en/setup).

Ak bola aplikácia Claude otvorená počas inštalácie FFmpeg alebo Node.js, úplne ju zatvor a otvor znova, inak nové programy nenájde. Pri prvom spustení potvrď dôveru priečinku. Až potom platia povolenia v `.claude/settings.json`, takže Claude sa nebude pýtať pri každej analýze.

## Prvá skladba

1. Skopíruj skladbu do `input/`, ideálne WAV alebo FLAC (ide aj MP3) a s názvom bez medzier, napr. `input/moja-skladba.wav`.
2. V Claude Code napíš: *„Remixni input/moja-skladba.wav“*. Claude oddelí vokál, analyzuje originál aj vokál, uloží pattern do `strudel_patterns/` a dá ti odkaz na strudel.cc.
3. Pre vokál v Strudeli spusti v priečinku projektu server samplov a nechaj ho bežať:

   ```bat
   npx --yes @strudel/sampler --dir separated/htdemucs
   ```

4. Otvor odkaz, stlač play, potom stop a ešte raz play (prvý štart len načíta stem).
5. Hotový remix nahraj zo Strudelu (záložka *export*) do `exports/` a nechaj Claude skontrolovať mastering.

Audio súbory sa do gitu nedostanú (`.gitignore`), commitujú sa iba skripty, analýzy a patterny.

## Skripty

| Skript | Čo robí |
|---|---|
| `install.bat` / `install.sh` | Celá inštalácia na Windows / macOS a Linuxe, dá sa spustiť opakovane |
| `setup_and_verify.py` | Kontrola FFmpeg a Pythonu (3.10 až 3.14), inštalácia knižníc, overenie Demucs a PyTorchu |
| `analyze_audio.py FILE [--json OUT] [--target-lufs -14]` | BPM, tónina, integrated LUFS, true peak, clipping. Exit kód 2 pri clippingu alebo true peaku nad -1 dBTP |
| `strudel_link.py FILE [--open]` | Odkaz na strudel.cc, ktorý otvorí kód zo súboru |
| `python -m demucs --two-stems=vocals -o separated FILE` | Separácia na `vocals.wav` + `no_vocals.wav` |

## Ako môže Claude ovládať Strudel

1. **Odkazy (hotové).** `strudel_link.py` zakóduje pattern do URL rovnako ako tlačidlo *share* v Strudeli. Netreba nič kopírovať, stačí kliknúť.
2. **Lokálne stemy (hotové).** `npx --yes @strudel/sampler --dir separated/htdemucs` sprístupní stemy na `http://localhost:5432` a pattern ich načíta cez `samples(...)`.
3. **Živé prepojenie (návrh).** Lokálna stránka s balíkom `@strudel/web`, ktorá sleduje `strudel_patterns/` a pri každej zmene súboru kód znova vyhodnotí. Claude by upravoval súbor a ty by si zmenu hneď počul, bez kopírovania a bez obnovovania stránky.
