# Rituál kontroly

Psychologická dráma o 33-ročnom synovi a otcovi, ktorý ovláda bez kriku: šesťkrát povie „už idem“ a neodíde, polhodinu kontroluje kľučky po synovej trase a syn ten hnev napokon obráti proti sebe.

- [scena-1.md](scena-1.md): literárny scenár scény 1 („Zlomená pamäť a tiché stroje“) a prompty pre AI video generátory.
- [generate_movie.py](generate_movie.py): vyrenderuje záber cez Runway, Lumu, Soru alebo Replicate a stiahne ho ako `.mp4`.

## Renderovanie

Potrebuješ Python 3.9+ s `requests` a API kľúč pre jedného providera v premennej prostredia:

| Provider | Premenná | Predvolený model | Dĺžka | Pomer strán |
|---|---|---|---|---|
| Runway | `RUNWAYML_API_SECRET` alebo `RUNWAY_API_KEY` | `gen4.5` | 2–10 s | 16:9 |
| Luma | `LUMAAI_API_KEY` alebo `LUMA_API_KEY` | `ray-2` | 5 alebo 9 s | 21:9 |
| Sora | `OPENAI_API_KEY` | `sora-2` | 4, 8 alebo 12 s | 16:9 |
| Replicate | `REPLICATE_API_TOKEN` | `google/veo-3` | podľa modelu | podľa modelu |

```bash
python generate_movie.py                     # master klip -> ritual_kontroly.mp4
python generate_movie.py --shot 3            # jeden záber zo zoznamu
python generate_movie.py --shot all          # zábery 1, 2, 3, 4, 5a, 5b
python generate_movie.py --provider sora --shot 5   # celý 12 s záber 5
python generate_movie.py --list              # vypíše všetky prompty
python generate_movie.py --dry-run           # ukáže, čo by sa poslalo, bez volania API
```

Ak je nastavených viac kľúčov, skript vezme prvý v poradí z tabuľky; iného providera vyberieš cez `--provider`. Skript sa pýta na stav úlohy každých 10 sekúnd, najviac 30 minút. Hotové video uloží vedľa seba (alebo do `--out-dir`) a overí, že ide naozaj o MP4.

Žiadny z providerov nevracia 2.39:1 priamo. Luma dá 21:9, ostatní 16:9, takže na širokouhlý formát treba video orezať pri strihu. Ak Replicate model potrebuje ďalšie vstupy, zadaj ich ako JSON v `REPLICATE_EXTRA_INPUT`, napríklad `{"aspect_ratio": "16:9"}`.
