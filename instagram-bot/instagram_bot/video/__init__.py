"""Pipeline učenia vizuálneho a strihového štýlu z videa (režim ``--learn``).

Postup::

    video.mp4 ──ffmpeg──► snímky pri zmene scény + pravidelné vzorky ──► deduplikácia (dHash)
        │                                                                     │
        └──ffmpeg──► audio (mono 16 kHz) ──ASR──► prepis s časovými značkami   │
                                                                              ▼
              strihové metriky + metriky reči + snímky (base64) + prepis ──► Claude Opus 5.5
                                                                              │
                                                     config/style_guide.txt ◄─┘ (Video Style Blueprint)
"""
