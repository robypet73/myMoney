#!/usr/bin/env python3
"""myMoney: scarica da Yahoo Finance l'anagrafica e i prezzi di ETF, ETC ed ETN in un database SQLite e propone portafogli.

    python mymoney.py                       apre la pagina nel browser (http://127.0.0.1:8765)
    python mymoney.py --db DATI.db          usa un altro file di database
    python mymoney.py scarica               crea l'archivio o lo aggiorna in modo incrementale (tutto)
    python mymoney.py controlla             controllo a campione dei dati con altre fonti online
    python mymoney.py backup [file.zip]     esporta archivio e portafogli;  ripristina FILE: li importa
    python mymoney.py justetf [--max-figi N]   justETF e ISIN verificati
    python mymoney.py storico [--tutte]     storico dei prezzi: 5 anni la prima volta, poi solo i giorni nuovi
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

# programma impacchettato (PyInstaller): il database sta accanto all'eseguibile, non nella cartella temporanea
BASE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MYMONEY_DB") or os.path.join(BASE, "etf.db")


def cli(argv):
    p = argparse.ArgumentParser(prog="mymoney.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DB_PATH, help="file del database SQLite (predefinito: etf.db accanto al programma, o la variabile MYMONEY_DB)")
    p.add_argument("--porta", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("scarica", help="crea l'archivio se non c'è, altrimenti lo aggiorna in modo incrementale (tutto: elenco, justETF e ISIN, storico, schede)")
    s.add_argument("--borse", nargs="+", default=list(EXCHANGES), choices=list(EXCHANGES), metavar="BORSA", help="codici Yahoo: " + " ".join(EXCHANGES))
    s.add_argument("--chiave-figi", default=os.environ.get("OPENFIGI_KEY"), help="chiave gratuita OpenFIGI (con la chiave le verifiche degli ISIN sono molto più rapide)")
    c = sub.add_parser("controlla", help="controllo a campione: confronta 15 fondi a caso con altre fonti online")
    c.add_argument("-n", type=int, default=15)
    b = sub.add_parser("backup", help="esporta l'archivio e i portafogli salvati in uno zip da portare su un altro computer")
    b.add_argument("file", nargs="?", default="myMoney-archivio.zip")
    rs = sub.add_parser("ripristina", help="importa un archivio esportato (zip o file .db) sostituendo quello attuale")
    rs.add_argument("file")
    h = sub.add_parser("storico", help="scarica o aggiorna lo storico dei prezzi (5 anni la prima volta, poi solo i giorni nuovi)")
    h.add_argument("--tutte", action="store_true", help="tutte le quotazioni, non solo la preferita di ogni fondo")
    j = sub.add_parser("justetf", help="justETF + ISIN verificati (Xetra, OpenFIGI) e dati abbinati ai titoli")
    j.add_argument("--chiave-figi", default=os.environ.get("OPENFIGI_KEY"), help="chiave gratuita OpenFIGI (con la chiave: 100 ISIN per richiesta e molte più richieste)")
    j.add_argument("--max-figi", type=int, help="al massimo N ISIN verificati (i fondi più grandi per primi)")
    sub.add_parser("aggiorna", help="prezzi attuali, bid, ask")
    e = sub.add_parser("esporta", help="CSV di tutto il database")
    e.add_argument("file", nargs="?", default="etf.csv")
    sub.add_parser("info", help="contenuto del database")
    a = p.parse_args(argv)
    if not a.cmd:
        import server
        return server.run(a.db, a.porta, not a.no_browser)
    if a.cmd in ("backup", "ripristina"):  # prima di aprire il database: un file aperto non si può sostituire (Windows)
        import server
        pf = os.path.join(os.path.dirname(os.path.abspath(a.db)), "portafogli")
        if a.cmd == "backup":
            server.db_export(a.db, pf, a.file)
            print("Archivio esportato in", a.file)
        else:
            try:
                print(server.db_import(a.db, pf, a.file))
            except ValueError as e:
                print("Errore:", e)
                return 1
        return 0
    db = DB(a.db)
    show = lambda t, d=0, n=0: print("\r" + t.ljust(70), end="", flush=True)
    y = Yahoo(log=lambda m: print("\n" + m), warn=lambda m: print("\n⚠ " + m))
    try:
        if a.cmd == "scarica":
            from justetf import JustETF
            jobs.sync_all(db, y, JustETF(log=lambda m_: print("\n" + m_)), a.chiave_figi, show, None, lambda m_: print("\n" + m_), a.borse)
        elif a.cmd == "controlla":
            import json as _json
            import checks
            from justetf import JustETF
            rep = checks.run(db, y, JustETF(), a.n, show, None, os.environ.get("OPENFIGI_KEY"))
            print(f"\nControllati {rep['n']} fondi: senza problemi {rep['funds_ok']}, con avvisi {rep['funds_warn']}, con errori {rep['funds_fail']} (controlli: {rep['checks']})")
            for f in rep["funds"]:
                if f["status"] in ("warn", "fail"):
                    print(f"\n[{f['status'].upper()}] {f['symbol']} {f['isin'] or ''} {f['name']}")
                    for c_ in f["checks"]:
                        if c_["status"] in ("warn", "fail"):
                            print(f"   {c_['status']:<4} {c_['check']}: {c_['detail']}")
            fn = os.path.join(os.path.dirname(os.path.abspath(a.db)), "controlli", "controllo-" + rep["at"].replace(":", "").replace("-", "").replace(" ", "-") + ".json")
            os.makedirs(os.path.dirname(fn), exist_ok=True)
            open(fn, "w", encoding="utf-8").write(_json.dumps(rep, ensure_ascii=False, indent=1))
            print("\nRapporto completo:", fn)
        elif a.cmd == "storico":
            jobs.download_history_all(db, y, a.tutte, show)
        elif a.cmd == "justetf":
            from justetf import JustETF
            jobs.download_justetf(db, y, JustETF(log=lambda m_: print("\n" + m_)), a.chiave_figi, a.max_figi, show, None, lambda m_: print("\n" + m_))
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
