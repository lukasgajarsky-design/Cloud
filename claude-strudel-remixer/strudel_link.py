"""Turn a Strudel pattern file into a strudel.cc link that opens with the code loaded.

Usage:
    python strudel_link.py strudel_patterns/<track>.strudel.js [--open]
"""

import argparse
import base64
import sys
import urllib.parse
import webbrowser
from pathlib import Path


def strudel_url(code):
    # Same encoding as Strudel's own share links: base64 of the UTF-8 code, URL-escaped
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    return "https://strudel.cc/#" + urllib.parse.quote(encoded, safe="")


def main():
    parser = argparse.ArgumentParser(description="Vytvorí odkaz na strudel.cc s kódom zo súboru.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--open", action="store_true", help="otvoriť odkaz v prehliadači")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"❌ Súbor neexistuje: {args.file}", file=sys.stderr)
        return 1
    url = strudel_url(args.file.read_text(encoding="utf-8"))
    print(url)
    if args.open:
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
