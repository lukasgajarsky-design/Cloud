# Rituál kontroly

Psychologická dráma o 33-ročnom synovi a otcovi, ktorý ovláda bez kriku: šesťkrát povie „už idem“ a neodíde, polhodinu kontroluje kľučky po synovej trase a syn ten hnev napokon obráti proti sebe.

- [scenar.md](scenar.md): sekvencia 1 ako filmový scenár s postavami, pravidlami filmu, šiestimi odchodmi s časmi a poznámkami pre réžiu.
- [scena-1.md](scena-1.md): iná verzia scény 1 („Zlomená pamäť a tiché stroje“), literárny scenár v druhej osobe s časovými značkami a prompty pre AI video generátory.
- [generate_movie.py](generate_movie.py): vyrenderuje záber cez Runway, Lumu, Soru alebo Replicate a stiahne ho ako `.mp4`.

## Renderovanie

Potrebuješ Python 3.9+ s `requests` a API kľúč pre jedného providera v premennej prostredia:

| Provider | Premenná | Predvolený model | Dĺžka | Pomer strán |
|---|---|---|---|---|
| Runway (`runway`) | `RUNWAYML_API_SECRET` alebo `RUNWAY_API_KEY` | `gen4.5` | 2–10 s | 16:9 |
| Luma Agents API (`luma-agents`) | `LUMA_AGENTS_API_KEY` | `ray-3.2` | 5 alebo 10 s | 16:9, 1080p |
| Luma Dream Machine API (`luma`) | `LUMAAI_API_KEY` alebo `LUMA_API_KEY` | `ray-2` | 5 alebo 9 s | 21:9 |
| Sora (`sora`) | `OPENAI_API_KEY` | `sora-2` | 4, 8 alebo 12 s | 16:9 |
| Replicate (`replicate`) | `REPLICATE_API_TOKEN` | `google/veo-3.1` (alebo `REPLICATE_MODEL`) | podľa modelu | podľa modelu |

```bash
python generate_movie.py                     # master klip -> ritual_kontroly.mp4
python generate_movie.py --shot 3            # jeden záber zo zoznamu
python generate_movie.py --shot all          # zábery 1, 2, 3, 4, 5a, 5b
python generate_movie.py --provider sora --shot 5   # celý 12 s záber 5
python generate_movie.py --provider luma-agents --duration 5 --output test.mp4
python generate_movie.py --list              # vypíše všetky prompty
python generate_movie.py --dry-run           # ukáže, čo by sa poslalo, bez volania API
```

Ak je nastavených viac kľúčov, skript vezme prvý v poradí z tabuľky; iného providera vyberieš cez `--provider`. Skript sa pýta na stav úlohy každých 10 sekúnd, najviac 30 minút. Hotové video uloží vedľa seba (alebo do `--out-dir`) a overí, že ide naozaj o MP4.

Žiadny z providerov nevracia 2.39:1 priamo. Luma dá 21:9, ostatní 16:9, takže na širokouhlý formát treba video orezať pri strihu. Replicate modely majú rôzne vstupy, preto skript posiela dĺžku iba vtedy, keď ju zadáš cez `--duration`. Ďalšie vstupy zadaj ako JSON v `REPLICATE_EXTRA_INPUT`, napríklad `{"aspect_ratio": "16:9"}`.
