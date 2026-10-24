#!/usr/bin/env python3
"""Versione dell'app nel formato MM.mm.ppp (major.minor.patch), per esempio 01.00.000.

    python scripts/bump.py            # patch: 01.00.000 -> 01.00.001 (predefinito)
    python scripts/bump.py minor      # 01.00.007 -> 01.01.000
    python scripts/bump.py major      # 01.03.012 -> 02.00.000
    python scripts/bump.py show       # stampa la versione attuale

Aggiorna index.html (riga in alto nella pagina) e il nome della cache in sw.js; stampa la nuova versione.
Il commit si intitola «vMM.mm.ppp: …» e porta il tag git vMM.mm.ppp.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML, SW = ROOT / "index.html", ROOT / "sw.js"
RX = re.compile(r'(id="ver">v)(\d{2})\.(\d{2})\.(\d{3})(<)')


def current():
    m = RX.search(HTML.read_text(encoding="utf-8"))
    if not m:
        sys.exit("Versione non trovata in index.html")
    return int(m.group(2)), int(m.group(3)), int(m.group(4))


def fmt(v):
    return f"{v[0]:02d}.{v[1]:02d}.{v[2]:03d}"


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "patch"
    M, m, p = current()
    if kind == "show":
        print(fmt((M, m, p))); return
    new = {"patch": (M, m, p + 1), "minor": (M, m + 1, 0), "major": (M + 1, 0, 0)}.get(kind)
    if not new:
        sys.exit("Uso: bump.py [patch|minor|major|show]")
    if new[2] > 999 or new[1] > 99 or new[0] > 99:
        sys.exit("Numero di versione fuori formato")
    v = fmt(new)
    HTML.write_text(RX.sub(lambda x: f"{x.group(1)}{v}{x.group(5)}", HTML.read_text(encoding="utf-8"), count=1), encoding="utf-8")
    SW.write_text(re.sub(r'const VERSION = "[^"]*";', f'const VERSION = "mymoney-{v}";', SW.read_text(encoding="utf-8"), count=1), encoding="utf-8")
    print(v)


if __name__ == "__main__":
    main()
