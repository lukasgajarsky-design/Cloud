#!/usr/bin/env python3
"""Vstupný bod Instagram bota (CLI). Príklady použitia: ``python main.py --help``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from instagram_bot.bot import VALID_TASKS, InstagramBot
from instagram_bot.config import RunMode, Settings
from instagram_bot.exceptions import (
    AlreadyRunningError,
    ClaudeAuthError,
    ConfigError,
    FFmpegNotFoundError,
    InstagramBotError,
    MetaAuthError,
    StyleLearningError,
)
from instagram_bot.logging_setup import setup_logging

EXAMPLES = """\
príklady:
  python main.py --check                               # overí token, prístupy a súbory
  python main.py --learn --video ukazka.mp4            # naučí sa štýl z videa → config/style_guide.txt
  python main.py --learn --video dalsie.mov --merge    # zlúči štýl ďalšieho videa s existujúcim
  python main.py --run                                 # beží v slučke (komentáre, DM, posty)
  python main.py --run --once                          # jeden cyklus (pre cron)
  python main.py --run --dry-run                       # nič neodošle, len zapíše do logu, čo by urobil
  python main.py --script "3 chyby pri výbere kávy"    # nový scenár videa podľa blueprintu
  python main.py --refresh-token                       # predĺži Instagram token o 60 dní

návratové kódy: 0 = OK, 1 = chyba konfigurácie/vstupu, 2 = neplatný token alebo kľúč,
                3 = bot už beží, 4 = iná chyba
"""

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_AUTH = 2
EXIT_ALREADY_RUNNING = 3
EXIT_ERROR = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instagram-bot",
        description="Produkčný Instagram bot: Meta Graph API + Claude Opus 5.5 (učenie štýlu z videa).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true", help="režim automatizácie a generovania (slučka)")
    mode.add_argument("--learn", action="store_true", help="režim učenia štýlu z videa (vyžaduje --video)")
    mode.add_argument("--script", metavar="TÉMA", help="vygeneruje scenár nového videa podľa blueprintu")
    mode.add_argument("--check", action="store_true", help="overí konfiguráciu, token a prístupy")
    mode.add_argument("--refresh-token", action="store_true", help="predĺži Instagram token (Instagram Login)")

    parser.add_argument("--video", type=Path, metavar="CESTA", help="video .mp4/.mov pre --learn")
    parser.add_argument("--force", action="store_true", help="--learn: analyzuj aj už analyzované video")
    parser.add_argument("--merge", action="store_true", help="--learn: zlúč s existujúcim blueprintom")
    parser.add_argument("--keep-temp", action="store_true", help="--learn: nemaž dočasné snímky (ladenie)")
    parser.add_argument("--once", action="store_true", help="--run: len jeden cyklus (pre cron)")
    parser.add_argument(
        "--tasks",
        default=",".join(VALID_TASKS),
        help=f"--run: čiarkou oddelené úlohy z {', '.join(VALID_TASKS)} (predvolene všetky)",
    )
    parser.add_argument("--dry-run", action="store_true", help="--run: nič neodosielaj ani nepublikuj")
    parser.add_argument("--notes", help="--script: doplňujúce poznámky k scenáru")
    parser.add_argument("--env-file", type=Path, help="cesta k .env (predvolene .env v priečinku projektu)")
    return parser


def resolve_mode(args: argparse.Namespace) -> RunMode:
    if args.run:
        return RunMode.RUN
    if args.learn:
        return RunMode.LEARN
    if args.script:
        return RunMode.SCRIPT
    if args.refresh_token:
        return RunMode.REFRESH_TOKEN
    return RunMode.CHECK


def parse_tasks(raw: str, parser: argparse.ArgumentParser) -> list[str]:
    tasks = [task.strip().lower() for task in raw.split(",") if task.strip()]
    unknown = [task for task in tasks if task not in VALID_TASKS]
    if unknown or not tasks:
        parser.error(f"Neznáme úlohy v --tasks: {', '.join(unknown) or '(prázdne)'}")
    return list(dict.fromkeys(tasks))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = resolve_mode(args)

    if mode is RunMode.LEARN and args.video is None:
        parser.error("--learn vyžaduje --video <cesta_k_videu>")
    if args.video is not None and mode is not RunMode.LEARN:
        parser.error("--video sa používa len spolu s --learn")
    tasks = parse_tasks(args.tasks, parser)

    try:
        settings = Settings.load(args.env_file)
        settings.validate_for(mode)
    except ConfigError as exc:
        print(f"CHYBA KONFIGURÁCIE: {exc}", file=sys.stderr)
        print("Tip: skopíruj .env.example na .env a doplň hodnoty (návod je v README.md).", file=sys.stderr)
        return EXIT_CONFIG

    logger = setup_logging(settings.log_file, settings.log_level, settings.secret_values())
    for warning in settings.security_warnings():
        logger.warning(warning)

    bot = InstagramBot(settings, dry_run=True if args.dry_run else None)
    try:
        if mode is RunMode.RUN:
            if args.once:
                report = bot.run_once(tasks)
                return EXIT_ERROR if report.errors else EXIT_OK
            bot.run_forever(tasks)
        elif mode is RunMode.LEARN:
            result = bot.learn_style_from_video(
                args.video, force=args.force, keep_temp=args.keep_temp, merge=args.merge
            )
            if result.skipped:
                print(f"Video už bolo analyzované – blueprint: {result.output_path} (pre novú analýzu: --force)")
            else:
                metrics = result.cut_metrics
                print(f"✔ Video Style Blueprint uložený: {result.output_path}")
                print(
                    f"  snímky: {result.frames_extracted} extrahovaných → {result.frames_sent} odoslaných, "
                    f"segmenty prepisu: {result.transcript_segments}"
                )
                if metrics:
                    print(f"  strihy: {metrics.cut_count}, priemerný záber {metrics.average_shot:.2f} s")
                print(f"  tokeny: vstup {result.input_tokens}, výstup {result.output_tokens} (model {result.model})")
        elif mode is RunMode.SCRIPT:
            path = bot.generate_video_script(args.script, args.notes)
            print(f"✔ Scenár uložený: {path}")
        elif mode is RunMode.REFRESH_TOKEN:
            days = bot.refresh_token()
            print(f"✔ Token obnovený a uložený do .env (platnosť {days} dní).")
        else:
            for line in bot.check():
                print(line)
        return EXIT_OK
    except FFmpegNotFoundError as exc:
        logger.error("ffmpeg chýba: %s", exc)
        print(f"\nCHYBA: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except (ConfigError, StyleLearningError) as exc:
        logger.error("%s", exc)
        return EXIT_CONFIG
    except (MetaAuthError, ClaudeAuthError) as exc:
        logger.critical("Autentifikácia zlyhala – bot sa zastavuje: %s", exc)
        return EXIT_AUTH
    except AlreadyRunningError as exc:
        logger.error("%s", exc)
        return EXIT_ALREADY_RUNNING
    except InstagramBotError as exc:
        logger.error("Chyba: %s", exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        logger.info("Prerušené používateľom.")
        return EXIT_OK
    except Exception:  # posledná poistka – zalogujeme celý traceback
        logging.getLogger("instagram_bot").exception("Neočakávaná chyba.")
        return EXIT_ERROR
    finally:
        bot.close()


if __name__ == "__main__":
    sys.exit(main())
