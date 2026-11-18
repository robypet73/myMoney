"""Prova senza rete: database temporaneo con titoli sintetici, selezione, tre proposte e controllo dei vincoli.  python selftest.py"""
import os
import tempfile
from datetime import datetime, timedelta

import numpy as np

import classify as C
import portfolio as PF
from db import DB


def make_db(path):
    rng = np.random.default_rng(1)
    db = DB(path)
    n_days = 1000
    days = [(datetime.now() - timedelta(days=n_days - i)).strftime("%Y-%m-%d") for i in range(n_days) if (datetime.now() - timedelta(days=n_days - i)).weekday() < 5]
    mkt = rng.normal(0.0003, 0.010, len(days))
    spec = [("World Equity", "Azionario", 0.9, 0.0003, 0.010), ("USA Equity", "Azionario", 0.85, 0.0004, 0.012), ("Europe Equity", "Azionario", 0.8, 0.0002, 0.012),
            ("Emerging Equity", "Azionario", 0.6, 0.0002, 0.013), ("Tech Equity", "Azionario", 0.8, 0.0006, 0.016), ("Gov Bond", "Obbligazionario", -0.1, 0.0001, 0.004),
            ("Corporate Bond", "Obbligazionario", 0.2, 0.0001, 0.004), ("High Yield Bond", "Obbligazionario", 0.4, 0.0002, 0.006), ("Gold", "Materie prime", 0.05, 0.0003, 0.008),
            ("Real Estate", "Immobiliare", 0.5, 0.0001, 0.011)]
    for i in range(30):
        nm, cl, beta, drift, vol = spec[i % len(spec)]
        name = f"Fondo {i} {nm} UCITS ETF (Acc)"
        r = beta * mkt + rng.normal(drift, vol * 0.6, len(days))
        p = 100 * np.cumprod(1 + r)
        s = f"T{i}.MI"
        db.upsert(s, name=name, group_key=C.group_key(name), type="ETF", asset_class=C.asset_class(name), region=C.region_of(name), distribution="Accumulazione",
                  exchange="MIL", exchange_name="Borsa Italiana", currency="EUR", price=float(p[-1]), price_eur=float(p[-1]), adv_eur_m=float(rng.uniform(0.2, 20)),
                  assets_eur_m=float(rng.uniform(50, 5000)), ter=float(rng.uniform(0.1, 0.5)), spread_pct=0.1, inception="2015-01-01")
        db.save_prices(s, list(zip(days, p.tolist())))
    db.commit()
    return db


def main():
    with tempfile.TemporaryDirectory() as d:
        db = make_db(os.path.join(d, "t.db"))
        assert db.export_csv(os.path.join(d, "t.csv")) == 30
        rows = PF.select(db, {"class_caps": {"Azionario": 100}, "pool": 40})
        assert len(rows) == 30, len(rows)
        assert len(PF.select(db, {"text": "gold"})) == 3
        ds = PF.load_dataset(db, rows)
        assert ds is not None and len(ds.rows) == 30
        caps = {"Azionario": 0.6, "Obbligazionario": 1.0}
        out, fail = PF.propose(ds, amount=20000, cap=0.30, kmin=3, kmax=8, caps=caps)
        assert not fail and len(out) == 3, fail
        for p in out:
            w = np.array([i["weight"] for i in p["items"]])
            assert abs(w.sum() - 1) < 1e-3 and w.max() <= 0.30 + 1e-3 and 3 <= len(w) <= 8, (p["name"], w)
            assert p["classes"].get("Azionario", 0) <= 0.6 + 1e-3, (p["name"], p["classes"])
            assert p["spent"] <= 20000
            print(f"{p['name']:<11} n={len(w)} rend={p['ret']*100:5.1f}% vol={p['vol']*100:5.1f}% sharpe={p['sharpe']:.2f} DR={p['dr']:.2f} classi={ {k: round(v, 2) for k, v in p['classes'].items()} }")
        s, b, a = out
        assert a["vol"] >= b["vol"] - 1e-6 and a["ret"] >= s["ret"] - 0.02
        # ISIN: solo se una fonte ufficiale lega ISIN e simbolo; i simboli contesi restano senza
        db.save_jetf([{"isin": "IE0000000001", "name": "Fondo 1 USA Equity UCITS ETF (Acc)", "ter": 0.1, "repl": "Fisica completa", "dom": "Irlanda", "asset": "Azionario"},
                      {"isin": "IE0000000002", "name": "Fondo 2 qualunque", "repl": "Sintetica"}])
        db.guess_by_name()
        db.save_isin_refs([("IE0000000001", "T1.MI", "figi"), ("IE0000000002", "T2.MI", "figi"), ("IE0000000009", "T2.MI", "figi"), ("IE0000000003", "NOSYM.MI", "figi")])
        db.save_firds([("IE0000000001", "etfp", "x"), ("IE0000000009", "etfp", "y")])
        ok, amb = db.link_verified()
        db.apply_jetf()
        assert (ok, amb) == (2, 0), (ok, amb)
        r = db.get("T1.MI")
        assert r["isin"] == "IE0000000001" and r["isin_src"] == "figi+firds" and r["replication"] == "Fisica completa" and r["ter"] == 0.1
        # T2: due ISIN contesi, vale quello presente nel registro ESMA (…009, sconosciuto a justETF: nessun dato justETF applicato)
        assert db.get("T2.MI")["isin"] == "IE0000000009" and db.get("T2.MI")["replication"] is None
        db.save_firds([("IE0000000002", "etfp", "z")])
        db.c.execute("UPDATE etf SET isin=NULL, isin_src=NULL WHERE symbol='T2.MI'")
        assert db.link_verified()[1] == 1  # ora entrambi nel registro: conteso, nessuno
        assert db.get("T3.MI")["isin"] is None and db.get("T2.MI")["isin"] is None
        # scheda unica per fondo: lo stesso ISIN su due borse = una riga, con la quotazione preferita (EUR, Milano) e l'elenco di tutte
        db.upsert("T1.DE", name="Fondo 1 USA Equity UCITS ETF (Acc)", exchange="GER", exchange_name="Xetra", currency="EUR", price_eur=50.0, isin="IE0000000001", isin_src="figi", adv_eur_m=99.0)
        db.upsert("T1.L", name="Fondo 1 USA Equity UCITS ETF (Acc)", exchange="LSE", exchange_name="Londra", currency="GBp", price_eur=0.5, isin="IE0000000001", isin_src="figi")
        db.commit()
        f = db.c.execute("SELECT * FROM fondo WHERE isin='IE0000000001'").fetchall()
        assert len(f) == 1 and f[0]["symbol"] == "T1.MI" and f[0]["n_quotazioni"] == 3 and set(f[0]["quotazioni"].split()) == {"T1.MI", "T1.DE", "T1.L"}, [dict(x) for x in f]
        assert f[0]["ter"] == 0.1 and f[0]["replication"] == "Fisica completa" and "justetf" in f[0]["fonti"] and "openfigi" in f[0]["fonti"]
        assert db.export_csv(os.path.join(d, "fondi.csv")) == db.c.execute("SELECT COUNT(*) FROM fondo").fetchone()[0]
        # il pool tiene conto dei massimi per classe: senza, i fondi più grandi sarebbero tutti azionari
        rows = PF.select(db, {"pool": 0})
        stra = PF.pick_pool(rows, {"pool": 6, "class_caps": {"Azionario": 40, "Obbligazionario": 100, "Materie prime": 100, "Immobiliare": 100}})
        cls = {r["asset_class"] for r in stra}
        assert {"Azionario", "Obbligazionario", "Materie prime"} <= cls, cls
        assert len(PF.pick_pool(rows, {"pool": 6})) == 6  # nessun limite di classe: i più grandi e basta
        print("OK")


if __name__ == "__main__":
    main()
