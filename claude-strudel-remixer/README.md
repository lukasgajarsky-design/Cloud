# Claude Strudel Remixer

Remixovanie skladieb s Claude Code podľa workflowu „Claude Code for Music Production: Remixing“:
Demucs oddelí vokál, `analyze_audio.py` zmeria tempo, tóninu a hlasitosť a Claude napíše nový podklad ako live-coding kód pre [Strudel](https://strudel.cc). Pravidlá pre Claude sú v [CLAUDE.md](CLAUDE.md).

## Inštalácia

Potrebuješ Python 3.10+, [FFmpeg](https://ffmpeg.org) a pre lokálne stemy v Strudeli [Node.js](https://nodejs.org).

```bash
cd claude-strudel-remixer
python3 -m venv .venv
.venv/bin/python setup_and_verify.py
```

Na Windows použi `py -m venv .venv` a `.venv\Scripts\python setup_and_verify.py`.
Skript skontroluje FFmpeg, nainštaluje Demucs, numpy, scipy, librosa, pyloudnorm a soundfile a overí import Demucs. Spolu s Demucs sa stiahne PyTorch, čo na Windows a Linuxe môže byť 1 až 3 GB.

## Prvá skladba

1. Skopíruj skladbu do `input/`, ideálne WAV alebo FLAC (ide aj MP3) a s názvom bez medzier, napr. `input/moja-skladba.wav`.
2. V Claude Code napíš: *„Remixni input/moja-skladba.wav“*. Claude oddelí vokál, analyzuje originál aj vokál, uloží pattern do `strudel_patterns/` a dá ti odkaz na strudel.cc.
3. Pre vokál v Strudeli spusti server samplov a nechaj ho bežať:

   ```bash
   cd separated/htdemucs
   npx @strudel/sampler
   ```

4. Otvor odkaz, stlač play, potom stop a ešte raz play (prvý štart len načíta stem).
5. Hotový remix nahraj zo Strudelu (záložka *export*) do `exports/` a nechaj Claude skontrolovať mastering.

Audio súbory sa do gitu nedostanú (`.gitignore`), commitujú sa iba skripty, analýzy a patterny.

## Skripty

| Skript | Čo robí |
|---|---|
| `setup_and_verify.py` | Kontrola FFmpeg a Pythonu, inštalácia knižníc, overenie Demucs |
| `analyze_audio.py FILE [--json OUT] [--target-lufs -14]` | BPM, tónina, integrated LUFS, true peak, clipping. Exit kód 2 pri clippingu alebo true peaku nad -1 dBTP |
| `strudel_link.py FILE [--open]` | Odkaz na strudel.cc, ktorý otvorí kód zo súboru |
| `python -m demucs --two-stems=vocals -o separated FILE` | Separácia na `vocals.wav` + `no_vocals.wav` |

## Ako môže Claude ovládať Strudel

1. **Odkazy (hotové).** `strudel_link.py` zakóduje pattern do URL rovnako ako tlačidlo *share* v Strudeli. Netreba nič kopírovať, stačí kliknúť.
2. **Lokálne stemy (hotové).** `npx @strudel/sampler` sprístupní stemy na `http://localhost:5432` a pattern ich načíta cez `samples(...)`.
3. **Živé prepojenie (návrh).** Lokálna stránka s balíkom `@strudel/web`, ktorá sleduje `strudel_patterns/` a pri každej zmene súboru kód znova vyhodnotí. Claude by upravoval súbor a ty by si zmenu hneď počul, bez kopírovania a bez obnovovania stránky.
