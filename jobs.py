"""Operazioni di scarico da Yahoo verso il database. Ogni funzione chiama progress(testo, fatti, totali) e può essere interrotta (Cancelled)."""
import bisect
import time

import numpy as np
from datetime import datetime, timedelta

import classify as C
from db import DB, now
import refdata
from justetf import JustETF
from yahoo import Cancelled, NotFound, Yahoo, EXCHANGES, num

nop = lambda *a: None


def _spread(bid, ask):
    return (ask - bid) / ((ask + bid) / 2) * 100 if bid and ask and bid > 0 and ask >= bid else None


def _rates(db, y, curs, rng="1mo"):
    """Aggiorna i cambi mancanti o vecchi di oltre 3 giorni."""
    for c in sorted({c for c in curs if c and c != "EUR"}):
        h = db.fx(c)
        if h and max(h) >= (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d") and (rng == "1mo" or len(h) > 800):
            continue
        try:
            db.save_fx(c, y.fx(c, rng))
        except NotFound:
            pass
    db.commit()


def _apply_quote(db, symbol, cur, price, bid, ask, vol):
    fx = db.last_fx(cur)
    pe = price * fx if price and fx else None
    db.upsert(symbol, price=price, price_eur=pe, bid=bid, ask=ask, spread_pct=_spread(bid, ask), avg_volume=vol,
              adv_eur_m=(vol * pe / 1e6 if vol and pe else None), quote_at=now())


def download_catalog(db, y, exchanges, details=False, max_details=None, progress=nop):
    """1) elenco di tutti gli ETF/ETC/ETN delle borse scelte (screener); 2) facoltativo: scheda di ogni fondo (TER, patrimonio, composizione)."""
    codes = list(exchanges)
    for k, ex in enumerate(codes):
        progress(f"Elenco {EXCHANGES.get(ex, ex)}…", k, len(codes))
        q = y.screener(ex, lambda a, b: progress(f"Elenco {EXCHANGES.get(ex, ex)}: {a} di {b}", k, len(codes)))
        curs = {x.get("currency") for x in q}
        _rates(db, y, curs)
        for x in q:
            s = x.get("symbol")
            if not s:
                continue
            name = x.get("longName") or x.get("shortName") or s
            prev = db.get(s)
            extra = {}
            if not (prev and (prev["detail_at"] or prev["class_src"] == "justetf")):
                extra["asset_class"] = C.asset_class(name)
            ft = num(x.get("firstTradeDateMilliseconds"))
            for k, v in (("ter", num(x.get("netExpenseRatio"))), ("ret_1y", num(x.get("fiftyTwoWeekChangePercent"))),
                         ("inception", datetime.fromtimestamp(ft / 1000).strftime("%Y-%m-%d") if ft else None)):
                if v is not None and not (k == "inception" and prev and prev["inception"]):
                    extra[k] = v
            na = num(x.get("netAssets"))  # patrimonio, indicativo (la valuta non è dichiarata: si assume quella di quotazione)
            if na:
                extra["assets"] = na
                extra["assets_eur_m"] = na * (db.last_fx(x.get("currency")) or 1.0) / 1e6
            db.upsert(s, name=name, short_name=x.get("shortName"), group_key=C.group_key(name), type=C.type_of(name), region=C.region_of(name),
                      distribution=C.distribution_of(name), hedged=C.hedged_of(name), exchange=ex, exchange_name=EXCHANGES.get(ex, ex), currency=x.get("currency"),
                      listed_at=now(), **extra)
            _apply_quote(db, s, x.get("currency"), num(x.get("regularMarketPrice")), num(x.get("bid")), num(x.get("ask")), num(x.get("averageDailyVolume3Month")))
        db.commit()
    db.fill_groups()
    db.commit()
    if details:
        download_details(db, y, max_details, progress)


def download_details(db, y, limit=None, progress=nop, max_age_days=60):
    """Scheda di un solo titolo per fondo (il rappresentante più scambiato, in EUR se possibile); i dati valgono per tutte le sue quotazioni. Riprendibile."""
    old = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.all("(detail_at IS NULL OR detail_at < ?) ORDER BY (currency='EUR') DESC, adv_eur_m IS NULL, adv_eur_m DESC", (old,))
    reps, seen = [], set()
    for r in rows:
        if r["group_key"] not in seen:
            seen.add(r["group_key"])
            reps.append(r)
    if limit:
        reps = reps[:limit]
    fail = 0
    for i, r in enumerate(reps):
        progress(f"Schede dei fondi: {i} di {len(reps)}" + (f" ({fail} senza dati)" if fail else ""), i, len(reps))
        try:
            d = y.summary(r["symbol"])
        except NotFound:
            d = {}
        if not d:
            fail += 1
        fx = db.last_fx(r["currency"]) or 1.0
        upd = {k: v for k, v in d.items() if v is not None}
        if d and r["class_src"] != "justetf":
            upd["asset_class"] = C.asset_class(r["name"], d.get("stock"), d.get("bond"), d.get("cash"), d.get("other"))
            if d.get("assets"):
                upd["assets_eur_m"] = d["assets"] * fx / 1e6
        upd["detail_at"] = now()
        db.update_group(r["group_key"], **upd)
        if i % 25 == 24:
            db.commit()
    db.commit()
    progress(f"Schede dei fondi: {len(reps)} di {len(reps)}", len(reps), len(reps))


def update_quotes(db, y, symbols=None, progress=nop):
    """Prezzo attuale, bid, ask e volume medio."""
    syms = symbols or [r["symbol"] for r in db.all()]
    _rates(db, y, {r["currency"] for r in db.all()})
    for i in range(0, len(syms), 200):
        progress(f"Prezzi attuali: {i} di {len(syms)}", i, len(syms))
        for s, x in y.quotes(syms[i:i + 200]).items():
            _apply_quote(db, s, x.get("currency"), num(x.get("regularMarketPrice")), num(x.get("bid")), num(x.get("ask")), num(x.get("averageDailyVolume3Month")))
        db.commit()
    progress(f"Prezzi attuali: {len(syms)} di {len(syms)}", len(syms), len(syms))


def hist_stats(ser):
    """Rendimenti (1, 3, 5 anni annui), volatilità e massima perdita dallo storico in EUR: servono solo dove justETF non ha il dato."""
    p = np.array([v for _, v in ser])
    last = datetime.strptime(ser[-1][0], "%Y-%m-%d")

    def ago(y):  # prezzo di y anni fa, solo se lo storico arriva fin lì
        t = (last - timedelta(days=365 * y)).strftime("%Y-%m-%d")
        if ser[0][0] > (last - timedelta(days=365 * y - 10)).strftime("%Y-%m-%d"):
            return None
        k = bisect.bisect_right([d for d, _ in ser], t) - 1
        return ser[max(k, 0)][1]

    out = {}
    for y, k in ((1, "ret_1y"), (3, "ret_3y"), (5, "ret_5y")):
        a = ago(y)
        out[k] = ((p[-1] / a) ** (1 / y) - 1) * 100 if a else None
    r = p[1:] / p[:-1] - 1
    out["vol_1y"] = float(np.std(r[-252:]) * np.sqrt(252) * 100) if len(r) >= 200 else None
    out["vol_3y"] = float(np.std(r[-756:]) * np.sqrt(252) * 100) if len(r) >= 700 else None
    out["max_dd"] = float((p / np.maximum.accumulate(p) - 1).min() * 100)
    return out


def download_history(db, y, symbols, progress=nop, max_age_days=3):
    """Storico giornaliero di 5 anni in EUR (chiusure aggiustate dei dividendi). Salta i titoli scaricati da meno di `max_age_days` giorni."""
    fresh = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y-%m-%d %H:%M:%S")
    todo = []
    for s in symbols:
        r = db.get(s)
        if r and not (r["hist_at"] and r["hist_at"] > fresh and r["hist_n"]):
            todo.append(r)
    if not todo:
        return 0
    _rates(db, y, {r["currency"] for r in todo}, "5y")
    cache, ok, bad = {}, 0, 0
    for i, r in enumerate(todo):
        progress(f"Storico prezzi: {i} di {len(todo)}", i, len(todo))
        try:
            cur, ser = y.history(r["symbol"])
        except NotFound:
            ser, cur = [], r["currency"]
        cur = cur or r["currency"]
        if cur != "EUR" and ser:
            if cur not in cache:
                h = db.fx(cur)
                cache[cur] = (sorted(h), [h[d] for d in sorted(h)])
            days, vals = cache[cur]
            if not days:
                ser = []
            else:
                ser = [(d, p * vals[max(0, bisect.bisect_right(days, d) - 1)]) for d, p in ser]
        if len(ser) < 30:
            bad += 1
        db.save_prices(r["symbol"], ser)
        if len(ser) >= 60:
            fill = {k: v for k, v in hist_stats(ser).items() if v is not None and r[k] is None}
            if fill:
                db.upsert(r["symbol"], **fill)
        ok += 1
        if i % 10 == 9:
            db.commit()
    db.commit()
    progress(f"Storico prezzi: {len(todo)} di {len(todo)}" + (f" ({bad} senza dati)" if bad else ""), len(todo), len(todo))
    return ok


def download_justetf(db, y, jt, figi_key=None, profiles=False, max_figi=None, max_profiles=None, progress=nop, cancel=None, log=nop):
    """Dati justETF e ISIN verificati.
    1) elenco justETF (caratteristiche per ISIN); 2) elenco ufficiale di Xetra (ISIN e ticker di ETF, ETC, ETN); 3) OpenFIGI: per ogni ISIN, ticker su Milano, Xetra, Parigi,
    Amsterdam, Londra, SIX; 4) un titolo riceve l'ISIN solo se una di queste fonti lo lega al suo simbolo (ticker + suffisso di borsa); 5) i dati justETF si copiano solo
    sui titoli con ISIN verificato; 6) facoltativo: scheda di ogni fondo (indice, titoli, paesi, settori)."""
    progress("Elenco justETF…", 0, 0)
    items = jt.catalog(lambda a, b: progress(f"Elenco justETF: {a} di {b}", a, b))
    db.save_jetf(items)
    db.guess_by_name()
    db.guess_by_ticker()
    db.commit()
    # Xetra: ISIN e mnemonico (= simbolo Yahoo senza .DE)
    progress("Elenco ufficiale Xetra…", 0, 0)
    xl = refdata.xetra_list(cancel, log)
    db.save_isin_refs([(x["isin"], x["mnemonic"] + ".DE", "xetra") for x in xl])
    db.commit()
    # OpenFIGI: tutti gli ISIN (prima i fondi più grandi), riprendibile
    universe = [r[0] for r in db.c.execute("SELECT isin FROM jetf ORDER BY aum IS NULL, aum DESC")]
    seen = set(universe)
    universe += [x["isin"] for x in xl if x["isin"] not in seen and not seen.add(x["isin"])]
    cut = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    done = {r[0] for r in db.c.execute("SELECT isin FROM figi_done WHERE at > ?", (cut,))}
    todo = [i for i in universe if i not in done]
    if max_figi:
        todo = todo[:max_figi]
    fg = refdata.Figi(figi_key, cancel, log)
    for i in range(0, len(todo), fg.batch):
        part = todo[i:i + fg.batch]
        left = (len(todo) - i) / fg.batch * fg.pause / 60
        progress(f"Verifica degli ISIN su OpenFIGI: {i} di {len(todo)}" + (f" (circa {left:.0f} min)" if left >= 2 else ""), i, len(todo))
        res = fg.map(part)
        db.save_isin_refs([(isin, t + refdata.FIGI_SUFFIX[ex], "figi") for isin, lst in res.items() for ex, t in lst])
        db.c.executemany("INSERT OR REPLACE INTO figi_done VALUES (?,?)", [(isin, now()) for isin in part])
        db.commit()
    ok, amb = db.link_verified()
    db.apply_jetf()
    db.commit()
    tot = db.c.execute("SELECT COUNT(*) FROM etf").fetchone()[0]
    progress(f"ISIN verificati: {ok} titoli su {tot}" + (f" ({amb} dubbi lasciati senza ISIN: simbolo conteso o nome incoerente)" if amb else ""), 1, 1)
    if profiles:
        todo = [r[0] for r in db.c.execute(
            "SELECT j.isin FROM jetf j JOIN etf e ON e.isin=j.isin WHERE j.profile_at IS NULL GROUP BY j.isin ORDER BY MAX(e.assets_eur_m) IS NULL, MAX(e.assets_eur_m) DESC")]
        if max_profiles:
            todo = todo[:max_profiles]
        for i, isin in enumerate(todo):
            progress(f"Schede justETF (indice, titoli, paesi, settori): {i} di {len(todo)}", i, len(todo))
            db.set_profile(isin, jt.profile(isin))
            jt.sleep(1.0)
            if i % 20 == 19:
                db.apply_jetf()
                db.commit()
        db.apply_jetf()
        db.commit()
    progress("Fatto", 1, 1)
