"""Instagram Bot – automatizácia Instagram biznis účtu cez Meta Graph API a Claude.

Balík je rozdelený do modulov podľa zodpovednosti (každý modul robí jednu vec):

- ``config``         – načítanie a validácia nastavení z ``.env``
- ``logging_setup``  – logovanie do ``instagram_bot.log`` s maskovaním tajomstiev
- ``retry``          – výpočet exponenciálneho vyčkávania (backoff) s jitterom
- ``graph_client``   – nízkoúrovňový HTTP klient pre Meta Graph API (retries, rate limiting)
- ``instagram_api``  – vysokoúrovňové operácie nad Instagramom (komentáre, DM, publikovanie)
- ``claude_client``  – volania Claude (štruktúrované odpovede, analýza videa, scenáre)
- ``prompts``        – texty systémových promptov a JSON schémy výstupov
- ``knowledge``      – načítanie brand voice a Video Style Blueprintu (``config/style_guide.txt``)
- ``storage``        – SQLite databáza stavov (ochrana proti duplicitným odpovediam)
- ``post_queue``     – fronta príspevkov v priečinku ``queue/``
- ``media_host``     – sprístupnenie lokálnych médií cez verejnú URL (vyžaduje to Meta API)
- ``video``          – pipeline učenia štýlu z videa (ffmpeg, prepis reči, deduplikácia snímok)
- ``bot``            – trieda ``InstagramBot``, ktorá všetko orchestruje
"""

__version__ = "1.0.0"
