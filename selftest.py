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
        # intervalli: ogni estremo è facoltativo; senza criteri passano tutti
        exp = sum(1 for r in db.all() if r["ter"] <= 0.3)
        assert len(PF.select(db, {"ranges": {"ter": [None, 0.3]}, "pool": 0})) == exp
        assert len(PF.select(db, {"ranges": {"ter": [None, None]}, "pool": 0})) == 30
        assert len(PF.select(db, {"ranges": {"ter": [0.2, 0.3], "assets": [1000, None]}, "pool": 0})) == sum(1 for r in db.all() if 0.2 <= r["ter"] <= 0.3 and r["assets_eur_m"] >= 1000)
        ds = PF.load_dataset(db, rows)
        assert ds is not None and len(ds.rows) == 30
        caps = {"Azionario": 0.6, "Obbligazionario": 1.0}
        out, fail = PF.propose(ds, amount=20000, cap=0.30, kmin=3, kmax=8, caps=caps)
        assert not fail and len(out) == 3, fail
        for p in out:
            w = np.array([i["weight"] for i in p["items"]])
            assert abs(w.sum() - 1) < 1e-3 and w.max() <= 0.30 + 1e-3 and 3 <= len(w) <= 8 and w.min() >= 0.0049, (p["name"], w)
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
        # numero di ETF: sempre tra minimo e massimo, nessun titolo a peso zero
        for kmin, kmax in ((2, 3), (4, 5), (6, 10), (5, 5)):
            o, f_ = PF.propose(ds, amount=10000, cap=0.5, kmin=kmin, kmax=kmax, caps={})
            assert not f_ and len(o) == 3, (kmin, kmax, f_)
            for p in o:
                ws = [i["weight"] for i in p["items"]]
                assert kmin <= len(ws) <= kmax and min(ws) >= 0.0049, (kmin, kmax, p["name"], ws)
        # minimo per classe e peso minimo per ETF scelti dall'utente
        o, f_ = PF.propose(ds, amount=10000, cap=0.5, kmin=3, kmax=6, caps={}, cmin={"Obbligazionario": 0.4, "Materie prime": 0.1}, minw=0.08)
        assert not f_ and len(o) == 3, f_
        for p in o:
            assert p["classes"].get("Obbligazionario", 0) >= 0.4 - 3e-3 and p["classes"].get("Materie prime", 0) >= 0.1 - 3e-3 and min(i["weight"] for i in p["items"]) >= 0.0799, (p["name"], p["classes"])
        # parametri vuoti = valori predefiniti; criteri vuoti = nessun limite
        import server as _sv
        f0, p0 = _sv.parse_create({})
        assert p0["amount"] == 10000 and (p0["kmin"], p0["kmax"]) == (3, 8) and abs(p0["cap"] - 0.35) < 1e-9 and abs(p0["minw"] - 0.03) < 1e-9 and not f0["ranges"] and p0["dr_min"] is None and not p0["cmin"]
        f1, p1 = _sv.parse_create({"amount": 0, "ranges": {"ter": [None, 0.3], "assets": [None, None], "ret_1y": [-5, 12.5]}, "class_min": {"Obbligazionario": 30}, "minw": 5})
        assert p1["amount"] == 0 and f1["ranges"] == {"ter": [None, 0.3], "ret_1y": [-5, 12.5]} and abs(p1["cmin"]["Obbligazionario"] - 0.3) < 1e-9 and abs(p1["minw"] - 0.05) < 1e-9
        assert _sv.check({**p1, "cmin": {"Obbligazionario": 0.9, "Azionario": 0.2}}) and not _sv.check(p1)  # minimi che superano il 100%: errore chiaro
        # correlazione media massima e diversificazione minima
        base = PF.propose(ds, amount=10000, cap=0.5, kmin=3, kmax=8, caps={})[0]
        c0, d0 = max(p["corr"] for p in base), min(p["dr"] for p in base)
        o, f_ = PF.propose(ds, amount=10000, cap=0.5, kmin=3, kmax=8, caps={}, corr_max=0.30, dr_min=1.4)
        for p in o:
            assert p["corr"] <= 0.30 + 3e-3 and p["dr"] >= 1.4 - 3e-3, (p["name"], p["corr"], p["dr"])
        lim = PF.limits(ds, 0.5, {})
        assert lim["dr_max"] > 1.4 and lim["corr_min"] < 0.5, lim
        o, f_ = PF.propose(ds, amount=10000, cap=0.5, kmin=3, kmax=8, caps={}, dr_min=lim["dr_max"] + 1.0)
        assert not o and len(f_) == 3  # irraggiungibile: nessuna proposta (e la pagina spiega il massimo possibile)
        # storico: la prima volta 5 anni, poi solo i giorni nuovi; i dividendi usciti nel frattempo riallineano lo storico vecchio
        import jobs
        from datetime import timedelta as _td

        class FakeY:
            cancel = staticmethod(lambda: False)
            log = staticmethod(lambda m: None)
            warn = staticmethod(lambda m: warns.append(m))

            def __init__(self):
                self.calls = []

            def history(self, symbol, rng="5y", since=None):
                self.calls.append(since)
                base = [(x, 100.0 * (1 + 0.0005 * i)) for i, x in enumerate(days_all)]
                scale = 1.0 if since is None else 0.98  # dopo la prima volta esce un dividendo: i prezzi aggiustati del passato scendono del 2%
                rows = [(x, v * scale) for x, v in base if (since is None and x <= days_all[-6]) or (since is not None and x >= since)]
                return "EUR", rows

        warns = []
        days_all = [(datetime.now() - _td(days=200 - i)).strftime("%Y-%m-%d") for i in range(201)]
        db.upsert("INC.MI", name="Fondo incrementale", exchange="MIL", currency="EUR", price_eur=100.0)
        db.commit()
        fy = FakeY()
        jobs.download_history(db, fy, ["INC.MI"], max_age_days=0)
        assert fy.calls == [None] and db.get("INC.MI")["hist_n"] == 196, (fy.calls, db.get("INC.MI")["hist_n"])
        first = dict(db.prices("INC.MI"))
        jobs.download_history(db, fy, ["INC.MI"], max_age_days=0)
        assert len(fy.calls) == 2 and fy.calls[1] is not None, fy.calls  # seconda volta: solo i giorni nuovi
        now_ = db.prices("INC.MI")
        assert len(now_) == 201 and now_[-1][0] == days_all[-1], (len(now_), now_[-1])
        k = days_all[0]
        assert abs(dict(now_)[k] / first[k] - 0.98) < 1e-6, (dict(now_)[k], first[k])  # lo storico vecchio è stato riallineato
        assert db.get("INC.MI")["stats_src"] == "hist" and db.get("INC.MI")["max_dd"] is not None
        # un fondo senza sovrapposizione (storico vecchio di oltre 300 giorni) si riscarica per intero
        db.c.execute("UPDATE etf SET hist_to='2020-01-01', hist_at='2020-01-01 00:00:00' WHERE symbol='INC.MI'"); db.commit()
        jobs.download_history(db, fy, ["INC.MI"], max_age_days=0)
        assert fy.calls[-1] is None
        # archivio tra computer: esporta, importa (con controlli), copia di sicurezza, portafogli
        import server, zipfile as _zf
        folder2 = os.path.join(d, "pf2"); os.makedirs(folder2, exist_ok=True)
        server.pf_save(folder2, {"portfolio": {"name": "Uno", "positions": [{"isin": "X", "weight": 1}]}})
        z = os.path.join(d, "arch.zip")
        db.commit(); server.db_export(os.path.join(d, "t.db"), folder2, z)
        names = _zf.ZipFile(z).namelist()
        assert "etf.db" in names and "portafogli/uno.json" in names, names
        other = os.path.join(d, "altro", "etf.db"); os.makedirs(os.path.dirname(other))
        DB(other).close()
        st = server.db_import(other, os.path.join(d, "altro", "portafogli"), z)
        assert st["titoli_importati"] == db.stats()["titoli"] and st["portafogli_aggiunti"] == 1 and os.path.exists(other + ".prima-dell-importazione"), st
        assert os.path.exists(os.path.join(d, "altro", "portafogli", "uno.json")) and DB(other).stats()["titoli"] == st["titoli_importati"]
        bad = os.path.join(d, "finto.db"); open(bad, "wb").write(b"questo non e' un archivio")
        try:
            server.db_import(other, os.path.join(d, "altro", "portafogli"), bad)
            raise AssertionError("file non valido accettato")
        except ValueError:
            pass
        assert DB(other).stats()["titoli"] == st["titoli_importati"]  # l'archivio non è stato toccato
        # controllo a campione: confronti con valori noti
        import checks
        assert checks.isin_valid("IE00B4L5Y983") and not checks.isin_valid("IE00B4L5Y984") and not checks.isin_valid("")
        smp = checks.pick_sample(db, 8, seed=1)
        assert len(smp) == 8 and len({r["symbol"] for r in smp}) == 8 and [r["symbol"] for r in smp] == [r["symbol"] for r in checks.pick_sample(db, 8, seed=1)]
        row = db.get("T1.MI")
        q_ok = {"regularMarketPrice": row["price"] * 1.01, "currency": "EUR", "longName": row["name"]}
        res = checks.check_fund(db, row, q_ok, None, None, [("IM", "T1")], None, {})
        st_ = {c["check"]: c["status"] for c in res}
        assert st_["Prezzo attuale"] == "ok" and st_["Valuta di negoziazione"] == "ok" and st_["ISIN: formato e cifra di controllo"] in ("fail", "ok"), st_
        res = checks.check_fund(db, row, {"regularMarketPrice": row["price"] * 1.5, "currency": "USD", "longName": "tutt'altro"}, None, None, [("IM", "ALTRO")], None, {})
        st_ = {c["check"]: c["status"] for c in res}
        assert st_["Prezzo attuale"] == "fail" and st_["Valuta di negoziazione"] == "fail" and st_["OpenFIGI: ticker e borsa"] == "warn", st_
        res = checks.check_fund(db, row, None, False, False, None, None, {})
        # fonti non raggiungibili: «non verificabile», mai «ok» (l'ISIN inventato del test ha la cifra di controllo sbagliata: errore giusto)
        fails = {c["check"] for c in res if c["status"] == "fail"}
        assert fails == {"ISIN: formato e cifra di controllo", "Stesso fondo su Xetra (T1.DE)", "Stesso fondo su Londra (T1.L)"}, fails  # i prezzi inventati sulle altre borse non tornano: giusto
        assert {c["check"] for c in res if c["status"] == "skip"} >= {"Prezzo, valuta e nome", "OpenFIGI: ticker e borsa", "justETF"}
        # archivio di una versione precedente (ISIN assegnati per nome): gli ISIN non verificati e i dati copiati su quei titoli si azzerano all'apertura
        leg = os.path.join(d, "legacy.db")
        ld = DB(leg)
        ld.upsert("A.MI", name="Fondo A", isin="IE0000000099", ter=0.07, replication="Fisica", domicile="Irlanda", currency="EUR", price_eur=1.0)
        ld.upsert("B.MI", name="Fondo B", isin="IE0000000098", isin_src="figi", ter=0.2, currency="EUR", price_eur=1.0)
        ld.commit(); ld.close()
        ld = DB(leg)
        a_, b_ = ld.get("A.MI"), ld.get("B.MI")
        assert a_["isin"] is None and a_["isin_guess"] == "IE0000000099" and a_["ter"] is None and a_["replication"] is None, dict(a_)
        assert b_["isin"] == "IE0000000098" and b_["ter"] == 0.2  # quello verificato non si tocca
        # i dati di una scheda non passano a un altro ISIN con lo stesso nome
        ld.upsert("C.MI", name="Stesso nome", group_key="stesso nome", isin="IE0000000001", isin_src="figi", currency="EUR")
        ld.upsert("C.DE", name="Stesso nome", group_key="stesso nome", isin="IE0000000002", isin_src="figi", currency="EUR")
        ld.upsert("C.L", name="Stesso nome", group_key="stesso nome", currency="EUR")
        ld.update_group("stesso nome", "IE0000000001", ter=0.5)
        assert ld.get("C.MI")["ter"] == 0.5 and ld.get("C.DE")["ter"] is None and ld.get("C.L")["ter"] == 0.5
        ld.close()
        # scheda di un fondo: statistiche dallo storico
        import server
        ser0 = [(x, p_) for x, p_ in db.prices("T0.MI")]
        st0 = PF.fund_stats(ser0)
        v0 = np.array([p_ for _, p_ in ser0])
        from datetime import datetime as _dt, timedelta as _td2
        tgt = (_dt.strptime(ser0[-1][0], "%Y-%m-%d") - _td2(days=365)).strftime("%Y-%m-%d")
        base = [p_ for x, p_ in ser0 if x <= tgt][-1]
        assert abs(st0["periods"]["1y"] - (v0[-1] / base - 1)) < 1e-9, st0["periods"]  # ultimo prezzo non successivo a un anno fa
        assert st0["max_dd"]["value"] < 0 and st0["max_dd"]["peak"] <= st0["max_dd"]["low"] and st0["years"][-1]["partial"]
        assert abs(sum(1 for _ in st0["years"]) - (int(ser0[-1][0][:4]) - int(ser0[0][0][:4]) + 1)) == 0
        det = server.fund_detail(db, "T0.MI")
        assert det["history"]["close"][-1] == round(ser0[-1][1], 4) and det["fund"]["name"] and det["stats"]["n"] == len(ser0)
        assert server.fund_detail(db, "NONESISTE.MI") is None
        # un fondo giovane non accorcia il periodo di tutti: si esclude e lo si dice
        db.upsert("YOUNG.MI", name="Fondo giovane", exchange="MIL", currency="EUR", price_eur=10.0, asset_class="Azionario")
        import numpy as _np
        db.save_prices("YOUNG.MI", [(x, 10 + 0.001 * i) for i, x in enumerate(ds.dates[-200:])]); db.commit()
        ds2 = PF.load_dataset(db, [db.get(s) for s in ds.sym] + [db.get("YOUNG.MI")])
        assert "YOUNG.MI" not in ds2.sym and ds2.years > 2 and any("YOUNG.MI" in n_ for n_ in ds2.notes), (ds2.years, ds2.notes)
        # errori di dati: picco isolato e frazionamento non corretto
        v, n_ = PF.clean_series([100, 101, 100, 5000, 101, 102, 103, 104])
        assert n_ == 1 and v.max() < 200
        v, n_ = PF.clean_series([100, 101, 102, 103, 1, 1.01, 1.02, 1.03, 1.04])  # raggruppamento 100:1 non corretto
        assert n_ == 1 and abs(v[0] - 1.0) < 0.1 and abs(v[-1] - 1.04) < 1e-9, v
        # frontiera efficiente sui fondi delle proposte
        syms = []
        for pr in out:
            syms += [x["symbol"] for x in pr["items"] if x["symbol"] not in syms]
        order = {r["symbol"]: i for i, r in enumerate(ds.rows)}
        fr = PF.frontier(ds, [order[x] for x in syms], 0.30, {"Azionario": 0.6, "Obbligazionario": 1.0}, 0.02, 3, 6)
        pts = fr["points"]
        assert all(3 <= q["n"] <= 6 and sum(1 for x in q["w"] if x > 0) == q["n"] for q in pts), [q["n"] for q in pts]
        assert len(pts) >= 5 and all(b["vol"] >= a["vol"] - 1e-9 and b["ret"] > a["ret"] for a, b in zip(pts, pts[1:])), [(x["vol"], x["ret"]) for x in pts]
        for q in pts:
            w = np.array(q["w"])
            assert abs(w.sum() - 1) < 1e-6 and w.max() <= 0.30 + 1e-3
            ac = sum(w[i] for i, j in enumerate(fr["idx"]) if ds.cls[j] == "Azionario")
            assert ac <= 0.6 + 1e-2, ac
        # portafogli salvati: file JSON, nome unico, elenco, cancellazione
        import server
        folder = os.path.join(d, "portafogli")
        doc = {"portfolio": {"name": "Proposta Sharpe è così", "amount": 1000, "positions": [{"isin": "X", "weight": 1}], "metrics": {"ret": 0.05}}}
        pid, exists = server.pf_save(folder, doc)
        assert pid == "proposta-sharpe-e-cosi" and not exists and os.path.exists(os.path.join(folder, pid + ".json"))
        assert server.pf_save(folder, doc)[1] is True and server.pf_save(folder, doc, overwrite=True)[1] is False
        assert [x["id"] for x in server.pf_list(folder)] == [pid]
        for bad in ("../x", "A b", ""):
            try:
                server.pf_path(folder, bad)
                raise AssertionError(bad)
            except ValueError:
                pass
        try:
            server.pf_save(folder, {"portfolio": {"name": "x", "positions": []}})
            raise AssertionError("vuoto")
        except ValueError:
            pass
        os.remove(server.pf_path(folder, pid))
        assert server.pf_list(folder) == []
        print("OK")


if __name__ == "__main__":
    main()
