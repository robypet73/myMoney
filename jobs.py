"""Operazioni di scarico da Yahoo verso il database. Ogni funzione chiama progress(testo, fatti, totali) e può essere interrotta (Cancelled)."""
import bisect
import time
from datetime import datetime, timedelta

import classify as C
from db import DB, now
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
            if not (prev and prev["detail_at"]):
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
        if d:
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
        ok += 1
        if i % 10 == 9:
            db.commit()
    db.commit()
    progress(f"Storico prezzi: {len(todo)} di {len(todo)}" + (f" ({bad} senza dati)" if bad else ""), len(todo), len(todo))
    return ok
