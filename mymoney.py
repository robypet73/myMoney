#!/usr/bin/env python3
"""myMoney: scarica da Yahoo Finance l'anagrafica e i prezzi di ETF, ETC ed ETN in un database SQLite e propone portafogli.

    python mymoney.py                       finestra grafica
    python mymoney.py scarica [--borse MIL GER ...] [--schede] [--max-schede N]
    python mymoney.py aggiorna              prezzi attuali, bid, ask
    python mymoney.py esporta [file.csv]    tutto il database in CSV
    python mymoney.py info
"""
import argparse
import os
import sys

import jobs
from db import DB
from yahoo import EXCHANGES, Yahoo, Cancelled

DB_PATH = os.environ.get("MYMONEY_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "etf.db")


def cli(argv):
    p = argparse.ArgumentParser(prog="mymoney.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("scarica", help="elenco di tutti i titoli delle borse scelte")
    s.add_argument("--borse", nargs="+", default=list(EXCHANGES), choices=list(EXCHANGES), metavar="BORSA", help="codici Yahoo: " + " ".join(EXCHANGES))
    s.add_argument("--schede", action="store_true", help="scarica anche la scheda di ogni fondo (TER, patrimonio, composizione): lento, riprendibile")
    s.add_argument("--max-schede", type=int, help="al massimo N schede (i fondi più scambiati)")
    sub.add_parser("aggiorna", help="prezzi attuali, bid, ask")
    e = sub.add_parser("esporta", help="CSV di tutto il database")
    e.add_argument("file", nargs="?", default="etf.csv")
    sub.add_parser("info", help="contenuto del database")
    a = p.parse_args(argv)
    if not a.cmd:
        from app import run
        return run(DB_PATH)
    db = DB(DB_PATH)
    show = lambda t, d=0, n=0: print("\r" + t.ljust(70), end="", flush=True)
    y = Yahoo(log=lambda m: print("\n" + m))
    try:
        if a.cmd == "scarica":
            jobs.download_catalog(db, y, a.borse, a.schede, a.max_schede, show)
        elif a.cmd == "aggiorna":
            jobs.update_quotes(db, y, progress=show)
        elif a.cmd == "esporta":
            print(f"{db.export_csv(a.file)} righe in {a.file}")
        print("\n" + "  ".join(f"{k}: {v}" for k, v in db.stats().items()))
    except Cancelled:
        print("\nInterrotto")
    except KeyboardInterrupt:
        db.commit()
        print("\nInterrotto: quanto scaricato è salvato, rilancia per riprendere")
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
