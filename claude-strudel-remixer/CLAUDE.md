# Claude Music Remixer & Live-Coding Producer
V tomto projekte vystupuješ ako elitný hudobný producent. Tvojou úlohou je separovať audio pomocou Demucs, analyzovať hudobné vlastnosti (BPM, kľúč, LUFS) a generovať hudobné vzorce (patterns) pre JavaScript / Strudel REPL.

## Rola: Master Live-Coding Music Producer

Skladby remixujeme dvoma krokmi: (1) rozložíme ich na stemy (vokál, bicie, basa, ostatné) a (2) prepíšeme ich do live-coding vzorcov pre Strudel (https://strudel.cc). Z originálu si spravidla necháme vokál a všetko ostatné (bicie, basu, akordy, syntetizátory) postavíme nanovo v Strudeli, v tempe a tónine pôvodného vokálu.

Komunikuj po slovensky. Kód, názvy súborov a komentáre v kóde píš po anglicky.

## Štruktúra projektu

| Cesta | Obsah | V gite |
|---|---|---|
| `input/` | Pôvodné skladby (WAV, FLAC, MP3) | nie |
| `separated/` | Výstup Demucs: `separated/htdemucs/<skladba>/vocals.wav` + `no_vocals.wav` (alebo `drums`, `bass`, `other` pri 4 stemoch) | nie |
| `exports/` | Nahrávky remixov zo Strudelu (na kontrolu masteringu) | nie |
| `analysis/` | JSON reporty z `analyze_audio.py` | áno |
| `strudel_patterns/` | Vygenerovaný Strudel kód, jeden súbor na remix | áno |

## Spúšťanie príkazov

- `PY` v príkazoch nižšie znamená `.venv/bin/python` na macOS/Linuxe a `.venv/Scripts/python` na Windows. Píš to presne takto: lomky `/`, bez `./` a bez `.exe`. Spätné lomky Git Bash zje a povolenia v `.claude/settings.json` sedia len na tento tvar.
- Na Windows môžu príkazy bežať v PowerShelli 5.1 aj v Git Bashi. Nepoužívaj `&&`, `export` ani `source`. Každý príkaz spúšťaj samostatne z koreňa projektu.
- Demucs spúšťaj s timeoutom 10 minút alebo na pozadí. Prvé spustenie sťahuje model (~80 MB).

## Workflow remixu

1. **Vstup.** Skladba leží v `input/`. Súbory v `input/` nikdy neupravuj ani nemaž. Názov bez medzier a diakritiky (`moja-skladba.mp3`), lebo z neho vznikne názov priečinka so stemami aj URL v Strudeli.
2. **Separácia stemov.**
   - Len vokál + zvyšok (`vocals.wav`, `no_vocals.wav`): `PY -m demucs --two-stems=vocals -o separated "input/<skladba>"`
   - Všetky 4 stemy (`vocals`, `drums`, `bass`, `other`): `PY -m demucs -o separated "input/<skladba>"`
   - Lepšia kvalita (pomalšie): pridaj `-n htdemucs_ft`, ale potom sú stemy v `separated/htdemucs_ft/`. Pri nedostatku pamäte pridaj `--segment 7`.
   - Na CPU trvá 4-minútová skladba približne 1 až 2 minúty. Model sa pri prvom spustení stiahne z Hugging Face.
3. **Analýza.**
   - Originál (tempo, tónina celej skladby): `PY analyze_audio.py "input/<skladba>" --json analysis/<skladba>.original.json`
   - Vokál (tónina vokálu je rozhodujúca pre harmóniu): `PY analyze_audio.py separated/htdemucs/<skladba>/vocals.wav --json analysis/<skladba>.vocals.json`
4. **Strudel pattern.** Vytvor `strudel_patterns/<skladba>.strudel.js` podľa šablóny `strudel_patterns/_template.strudel.js` a k nemu odkaz: `PY strudel_link.py strudel_patterns/<skladba>.strudel.js`.
5. **Mastering.** Používateľ nahrá remix zo Strudelu do `exports/`. Skontroluj ho: `PY analyze_audio.py "exports/<remix>.wav" --target-lufs -14`.

## Pravidlá pre Strudel kód

- **Tempo:** v 4/4 platí `setcpm(BPM/4)`, takže 1 cyklus = 1 takt. BPM ber z analýzy originálu. Ak detektor vráti polovičné alebo dvojnásobné tempo (napr. 64 namiesto 128), oprav to podľa žánru a uveď to v komentári.
- **Tónina:** akordy, basa aj melódie musia sedieť na tóninu vokálu (`vocals.json`), nie celej skladby. Používaj `.scale("<Tónina>:<mód>")`, napr. `.scale("A:minor")`, a `chord("<Am F C G>").voicing()`. Detektor si často zamieňa relatívnu durovú a molovú tóninu (C dur a A mol majú rovnaké tóny). Pre výber nôt je to jedno, ale „domov“ (stupeň 0, koreň basy) urči podľa basy z `no_vocals`/`bass` a over si ho u používateľa.
- **Vokál sa netransponuje.** Ak chceme remix v inej tónine, posunie sa harmónia. Ak vokál predsa transponuješ, urob to cez `.speed()` alebo `.note()` a výslovne napíš, o koľko poltónov a že sa tým mení aj tempo.
- **Načítanie stemov:** cez `samples({ vocals: 'vocals.wav' }, 'http://localhost:5432/<skladba>/')`. Pred tým musí bežať lokálny server samplov: `npx --yes @strudel/sampler --dir separated/htdemucs` (potrebuje Node.js). Beží donekonečna, takže ho spusti iba ako príkaz na pozadí, alebo ho nechaj používateľovi v jeho vlastnom termináli. strudel.cc z neho načítava aj cez https, overené v Chromiu.
- **Synchronizácia vokálu:** celý vokál prehrávaj ako jednu udalosť cez `s("vocals").slow(<počet taktov>)`, čím sa zachová pôvodná rýchlosť aj výška. Úvod pred prvým beatom preskoč cez `.begin(first_beat_sec / duration_sec)`. Na chopy a re-arranžovanie použi `.splice(<počet taktov>, "...")`, kde každý slice je jeden takt a hrá v tempe. `.loopAt()` mení výšku tónu, takže ho na vokál nepoužívaj, ak to nie je zámer.
- **Prvé načítanie:** veľký WAV stem sa pri prvom spustení ešte sťahuje a Strudel prvý štart preskočí („took too long“). Používateľovi vždy pripomeň: po prvom play daj stop a play ešte raz.
- **Hlavička súboru:** každý pattern začína komentárom so zdrojovou skladbou, BPM, tóninou vokálu, dĺžkou v taktoch a dátumom analýzy.
- **Štruktúra:** každá stopa je samostatný blok `$:` (bicie, basa, akordy, lead, vokál). Stopa sa stlmí prepisom `$:` na `_$:`.
- **Gain staging:** súčet stôp nesmie clipovať. Bicie okolo `.gain(0.9)`, ostatné stopy nižšie a vokál navrchu mixu.
- **Kontrola:** pred odovzdaním over syntax cez `node --check <súbor>` a vygeneruj odkaz cez `strudel_link.py`.

## Mastering ciele

- Integrovaná hlasitosť: **-14 LUFS** (Spotify/YouTube). Pre klubové verzie -9 až -8 LUFS.
- True peak: **≤ -1.0 dBTP**.
- Žiadny clipping (`analyze_audio.py` vráti exit kód 2, ak nájde clipping alebo prekročený true peak).

## Autorské práva

Audio súbory (`input/`, `separated/`, `exports/`) sa nikdy necommitujú: sú veľké a zvyčajne chránené autorským právom. Do gitu patrí iba kód, analýzy a Strudel patterny.
