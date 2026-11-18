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


class Streak:
    """Errori consecutivi: dopo n di fila si ferma con un errore chiaro invece di aspettare per ogni titolo."""

    def __init__(self, y, n=5):
        self.y, self.n, self.k = y, n, 0

    def ok(self):
        self.k = 0

    def fail(self, msg):
        self.k += 1
        self.y.warn(msg)
        if self.k >= self.n:
            raise RuntimeError(f"{self.n} errori di fila ({msg}): Yahoo non risponde, riprova più tardi")


def _examples(items, n=8):
    items = list(items)
    return ", ".join(items[:n]) + (f" e altri {len(items) - n}" if len(items) > n else "")


def _spread(bid, ask):
    return (ask - bid) / ((ask + bid) / 2) * 100 if bid and ask and bid > 0 and ask >= bid else None


def _rates(db, y, curs, rng="1mo"):
    """Cambi mancanti o vecchi di oltre 3 giorni: dalla BCE (dati ufficiali), per le valute che non pubblica da Yahoo."""
    need = []
    for c in sorted({c for c in curs if c and c != "EUR"}):
        h = db.fx(c)
        if not (h and max(h) >= (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d") and (rng == "1mo" or len(h) > 800)):
            need.append(c)
    if not need:
        return
    start = (datetime.now() - timedelta(days=45 if rng == "1mo" else 365 * 5 + 10)).strftime("%Y-%m-%d")
    try:
        ecb = refdata.ecb_fx(need, start, y.cancel)
    except Exception as e:  # noqa: BLE001
        y.warn(f"Cambi BCE non disponibili ({e}): uso Yahoo")
        ecb = {}
    for c in need:
        e = ecb.get("GBP" if c == "GBp" else c)
        if e:
            db.save_fx(c, {d: v * (0.01 if c == "GBp" else 1.0) for d, v in e.items()})
            continue
        try:
            db.save_fx(c, y.fx(c, rng))
        except (NotFound, RuntimeError):
            y.warn(f"Cambio {c}/EUR non disponibile (né BCE né Yahoo): i titoli in {c} non si convertono in euro")
    db.commit()


def _apply_quote(db, symbol, cur, price, bid, ask, vol):
    fx = db.last_fx(cur)
    pe = price * fx if price and fx else None
    db.upsert(symbol, price=price, price_eur=pe, bid=bid, ask=ask, spread_pct=_spread(bid, ask), avg_volume=vol,
              adv_eur_m=(vol * pe / 1e6 if vol and pe else None), quote_at=now())


def download_catalog(db, y, exchanges, details=False, max_details=None, progress=nop):
    """1) elenco di tutti gli ETF/ETC/ETN delle borse scelte (screener); 2) facoltativo: scheda di ogni fondo (TER, patrimonio, composizione)."""
    codes, failed = list(exchanges), []
    for k, ex in enumerate(codes):
        progress(f"Elenco {EXCHANGES.get(ex, ex)}…", k, len(codes))
        try:
            q = y.screener(ex, lambda a, b: progress(f"Elenco {EXCHANGES.get(ex, ex)}: {a} di {b}", k, len(codes)))
        except RuntimeError as e:
            y.warn(f"{EXCHANGES.get(ex, ex)}: elenco non scaricato ({e})")
            failed.append(ex)
            continue
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
            for kk, v in (("ter", num(x.get("netExpenseRatio"))), ("ret_1y", num(x.get("fiftyTwoWeekChangePercent"))),
                          ("inception", datetime.fromtimestamp(ft / 1000).strftime("%Y-%m-%d") if ft else None)):
                if v is not None and not (kk == "inception" and prev and prev["inception"]):
                    extra[kk] = v
            na = num(x.get("netAssets"))  # patrimonio, indicativo (la valuta non è dichiarata: si assume quella di quotazione)
            if na:
                extra["assets"] = na
                extra["assets_eur_m"] = na * (db.last_fx(x.get("currency")) or 1.0) / 1e6
            db.upsert(s, name=name, short_name=x.get("shortName"), group_key=C.group_key(name), type=C.type_of(name), region=C.region_of(name),
                      distribution=C.distribution_of(name), hedged=C.hedged_of(name), exchange=ex, exchange_name=EXCHANGES.get(ex, ex), currency=x.get("currency"),
                      listed_at=now(), **extra)
            _apply_quote(db, s, x.get("currency"), num(x.get("regularMarketPrice")), num(x.get("bid")), num(x.get("ask")), num(x.get("averageDailyVolume3Month")))
        db.commit()
    if len(failed) == len(codes):
        raise RuntimeError("Nessuna borsa scaricata: Yahoo non risponde, riprova più tardi")
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
    nodata, streak = [], Streak(y)
    for i, r in enumerate(reps):
        progress(f"Schede dei fondi: {i} di {len(reps)}" + (f" ({len(nodata)} senza dati)" if nodata else ""), i, len(reps))
        try:
            d = y.summary(r["symbol"])
            streak.ok()
        except NotFound:
            d = {}
        except RuntimeError as e:
            db.commit()
            streak.fail(f"{r['symbol']}: scheda non scaricata ({e})")
            continue
        if not d:
            nodata.append(r["symbol"])
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
    if nodata:
        y.warn(f"{len(nodata)} fondi senza scheda su Yahoo (TER, patrimonio e composizione restano vuoti): {_examples(nodata)}")
    progress(f"Schede dei fondi: {len(reps)} di {len(reps)}", len(reps), len(reps))


def update_quotes(db, y, symbols=None, progress=nop):
    """Prezzo attuale, bid, ask e volume medio."""
    syms = symbols or [r["symbol"] for r in db.all()]
    _rates(db, y, {r["currency"] for r in db.all()})
    missing, streak = [], Streak(y, 3)
    for i in range(0, len(syms), 200):
        progress(f"Prezzi attuali: {i} di {len(syms)}", i, len(syms))
        part = syms[i:i + 200]
        try:
            got = y.quotes(part)
            streak.ok()
        except RuntimeError as e:
            streak.fail(f"Prezzi non scaricati per {len(part)} titoli ({e})")
            continue
        for s, x in got.items():
            _apply_quote(db, s, x.get("currency"), num(x.get("regularMarketPrice")), num(x.get("bid")), num(x.get("ask")), num(x.get("averageDailyVolume3Month")))
        missing += [s for s in part if s not in got]
        db.commit()
    if missing:
        y.warn(f"{len(missing)} titoli senza quotazione su Yahoo (forse non più negoziati): {_examples(missing)}")
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
    cache, ok, bad, streak = {}, 0, [], Streak(y)
    for i, r in enumerate(todo):
        progress(f"Storico prezzi: {i} di {len(todo)}" + (f" ({len(bad)} senza dati)" if bad else ""), i, len(todo))
        try:
            cur, ser = y.history(r["symbol"])
            streak.ok()
        except NotFound:
            ser, cur = [], r["currency"]
        except RuntimeError as e:
            db.commit()
            streak.fail(f"{r['symbol']}: storico non scaricato ({e})")
            bad.append(r["symbol"])
            continue
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
            bad.append(r["symbol"])
        db.save_prices(r["symbol"], ser)
        if len(ser) >= 60:
            fill = {k: v for k, v in hist_stats(ser).items() if v is not None and r[k] is None}
            if fill:
                db.upsert(r["symbol"], **fill)
        ok += 1
        if i % 10 == 9:
            db.commit()
    db.commit()
    if bad:
        y.warn(f"{len(bad)} titoli senza storico dei prezzi (esclusi dal calcolo): {_examples(bad, 12)}")
    progress(f"Storico prezzi: {len(todo)} di {len(todo)}", len(todo), len(todo))
    return ok


def download_justetf(db, y, jt, figi_key=None, max_figi=None, progress=nop, cancel=None, log=nop):
    """Dati justETF e ISIN verificati (solo fonti dirette, nessuna pagina web).
    1) elenco justETF (caratteristiche per ISIN); 2) registro ufficiale ESMA (ISIN attivi per borsa); 3) OpenFIGI: per ogni ISIN, ticker su Milano, Xetra, Parigi,
    Amsterdam, Londra, SIX; 4) un titolo riceve l'ISIN solo se OpenFIGI lo lega al suo simbolo (ticker + suffisso di borsa), con il registro ESMA come conferma;
    5) i dati justETF si copiano solo sui titoli con ISIN verificato."""
    progress("Elenco justETF…", 0, 0)
    items = jt.catalog(lambda a, b: progress(f"Elenco justETF: {a} di {b}", a, b))
    db.save_jetf(items)
    db.guess_by_name()
    db.guess_by_ticker()
    db.commit()
    # registro ufficiale ESMA: ISIN attivi sulle borse presenti nell'archivio
    have = {r[0] for r in db.c.execute("SELECT DISTINCT exchange FROM etf")}
    mics = [m for e, m in refdata.FIRDS_MIC.items() if e in have]
    progress("Registro ufficiale ESMA…", 0, 0)
    try:
        fl = refdata.firds_list(mics, cancel, log)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001
        y.warn(f"Registro ESMA non raggiungibile ({e}): gli ISIN si verificano solo con OpenFIGI, senza la seconda conferma")
        fl = []
    db.save_firds(fl)
    db.commit()
    # OpenFIGI: gli ISIN di quelle borse (e quelli justETF se ci sono Londra o SIX, o se il registro non risponde), prima i fondi più grandi; riprendibile
    universe = [r[0] for r in db.c.execute("SELECT isin FROM jetf ORDER BY aum IS NULL, aum DESC")] if (have & {"LSE", "EBS"} or not fl) else []
    seen = set(universe)
    big = {r[0]: (r[1] or 0) for r in db.c.execute("SELECT isin, aum FROM jetf")}
    universe += sorted({i for i, _, _ in fl if i not in seen}, key=lambda i: -big.get(i, 0))
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
        try:
            res = fg.map(part)
        except RuntimeError:
            db.commit()  # quanto verificato finora resta salvato
            raise
        db.save_isin_refs([(isin, t + refdata.FIGI_SUFFIX[ex], "figi") for isin, lst in res.items() for ex, t in lst])
        db.c.executemany("INSERT OR REPLACE INTO figi_done VALUES (?,?)", [(isin, now()) for isin in part])
        db.commit()
    ok, amb = db.link_verified()
    db.apply_jetf()
    db.commit()
    tot = db.c.execute("SELECT COUNT(*) FROM etf").fetchone()[0]
    if amb:
        y.warn(f"{amb} titoli lasciati senza ISIN per dubbio (simbolo conteso tra più ISIN o nome incoerente)")
    progress(f"ISIN verificati: {ok} titoli su {tot}", 1, 1)
