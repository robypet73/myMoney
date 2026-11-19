"""Controllo a campione dei dati: sceglie alcuni fondi a caso dall'archivio e confronta ogni informazione con fonti indipendenti scaricate in quel momento
(Yahoo, justETF, registro ESMA, OpenFIGI, cambi BCE) e con la coerenza interna dei dati (storico, quotazioni su più borse). Non corregge nulla: riferisce."""
import bisect
import random
import re
import statistics
import time
from datetime import datetime, timedelta

import classify as C
import refdata
from justetf import JustETF
from yahoo import Cancelled

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
ORDER = {FAIL: 3, WARN: 2, OK: 1, SKIP: 0}
DOM = {"IE": "Irlanda", "LU": "Lussemburgo", "DE": "Germania", "FR": "Francia", "CH": "Svizzera", "NL": "Paesi Bassi", "GB": "Regno Unito", "SE": "Svezia", "IT": "Italia",
       "JE": "Jersey", "DK": "Danimarca", "FI": "Finlandia", "ES": "Spagna", "BE": "Belgio", "AT": "Austria", "NO": "Norvegia"}
CODE = {v: k for k, v in refdata.FIGI_SUFFIX.items() if k != "GR"}  # suffisso Yahoo -> codice borsa OpenFIGI
nop = lambda *a: None


def isin_valid(isin):
    """Formato e cifra di controllo (Luhn) di un ISIN."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin or ""):
        return False
    s = "".join(str(int(c, 36)) for c in isin)
    tot = 0
    for k, ch in enumerate(reversed(s)):
        d = int(ch)
        if k % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        tot += d
    return tot % 10 == 0


def rel(a, b):
    return abs(a / b - 1) if a is not None and b else None


def sim(a, b):
    x, y = set(C.group_key(a).split()), set(C.group_key(b).split())
    return len(x & y) / len(x | y) if x and y else None


def pick_sample(db, n=15, seed=None):
    """Fondi a caso: in maggioranza con ISIN verificato (con almeno un paio quotati su più borse, per il confronto incrociato dei prezzi), alcuni senza ISIN."""
    rnd = random.Random(seed)
    rows = [r for r in db.c.execute("SELECT symbol, isin, n_quotazioni FROM fondo WHERE price_eur IS NOT NULL")]
    withi = [r for r in rows if r["isin"]]
    multi = [r for r in withi if r["n_quotazioni"] > 1]
    pick = rnd.sample(multi, min(len(multi), max(2, n // 5)))
    ids = {r["symbol"] for r in pick}
    rest = [r for r in withi if r["symbol"] not in ids]
    pick += rnd.sample(rest, min(len(rest), int(n * 0.6) - len(pick)))
    ids = {r["symbol"] for r in pick}
    pick += rnd.sample([r for r in rows if not r["isin"] and r["symbol"] not in ids], min(len([r for r in rows if not r["isin"]]), n // 4))
    ids = {r["symbol"] for r in pick}
    left = [r for r in rows if r["symbol"] not in ids]
    pick += rnd.sample(left, min(len(left), n - len(pick)))
    return [db.get(r["symbol"]) for r in pick][:n]


def _eur(db, ser, cur):
    if cur == "EUR" or not ser:
        return ser
    h = db.fx(cur)
    days = sorted(h)
    return [(d, p * h[days[max(0, bisect.bisect_right(days, d) - 1)]]) for d, p in ser] if days else []


def check_fund(db, r, q, esma, jet, figi, yh, info):
    """Controlli di un fondo. q = quotazione Yahoo fresca, esma = record del registro ESMA, jet = riga justETF fresca, figi = [(codice, ticker)], yh = (valuta, serie)
    scaricati ora. Ogni parametro può essere None (fonte non raggiungibile): quel controllo risulta «non verificabile»."""
    out = []

    def add(name, status, detail, mine=None, other=None, src=None):
        out.append({"check": name, "status": status, "detail": detail, "db": mine, "other": other, "source": src})

    def band(name, mine, other, ok, warn, src, vf, what="", absolute=False, worst=FAIL):
        """Confronta due valori: scarto assoluto (stessa unità) o relativo (in %). `worst` = esito più grave possibile per questo controllo."""
        if mine is None or other is None:
            return add(name, SKIP, "dato non disponibile in una delle due fonti", mine, other, src)
        d = abs(mine - other) if absolute else rel(mine, other)
        st = OK if d <= ok else WARN if d <= warn or worst == WARN else FAIL
        add(name, st, f"{vf(mine)} nell'archivio, {vf(other)} {what or 'nella fonte'}: scarto {vf(d) if absolute else f'{d * 100:.2f}%'}", mine, other, src)

    num2 = lambda v: f"{v:.2f}"
    num3 = lambda v: f"{v:.3f}"
    num0 = lambda v: f"{v:,.0f}"
    sym, isin = r["symbol"], r["isin"]
    # --- ISIN
    if isin:
        ok = isin_valid(isin)
        add("ISIN: formato e cifra di controllo", OK if ok else FAIL, isin + (" valido" if ok else " NON valido"), isin, None, "calcolo")
        dom = DOM.get(isin[:2])
        if r["domicile"] and dom:
            add("ISIN: paese e domicilio", OK if dom == r["domicile"] else WARN, f"prefisso {isin[:2]} = {dom}; domicilio nell'archivio: {r['domicile']}", r["domicile"], dom, "calcolo")
        add("ISIN: come è stato verificato", OK if (r["isin_src"] or "").find("figi") >= 0 else WARN, f"fonte: {r['isin_src']}", None, None, "archivio")
    else:
        add("ISIN", SKIP, "nessun ISIN verificato per questo titolo (può mancare: meglio nessun ISIN che uno sbagliato)", None, None, "archivio")
    # --- quotazione Yahoo
    if q:
        band("Prezzo attuale", r["price"], q.get("regularMarketPrice"), 0.03 if not _stale(r["quote_at"], 3) else 0.08, 0.08, "Yahoo (ora)", num3, "su Yahoo ora")
        add("Valuta di negoziazione", OK if (q.get("currency") == r["currency"]) else FAIL, f"{r['currency']} nell'archivio, {q.get('currency')} su Yahoo ora", r["currency"], q.get("currency"), "Yahoo (ora)")
        yn = q.get("longName") or q.get("shortName")
        s = sim(r["name"], yn) if yn else None
        add("Nome (Yahoo)", SKIP if s is None else OK if s >= 0.6 else WARN, f"«{r['name']}» / «{yn}»" + ("" if s is None else f" (somiglianza {s:.0%})"), r["name"], yn, "Yahoo (ora)")
        yt = q.get("netExpenseRatio")
        if yt is not None:
            band("TER (Yahoo, fonte poco affidabile per il TER)", r["ter"], yt, 0.01, 0.05, "Yahoo (ora)", num2, "su Yahoo ora", absolute=True, worst=WARN)
    else:
        add("Prezzo, valuta e nome", SKIP, "Yahoo non raggiungibile ora", None, None, "Yahoo (ora)")
    # --- registro ESMA
    mic = next((m for sfx, m in refdata.SUFFIX_MIC.items() if sym.endswith(sfx)), None)
    if isin and mic:
        if esma is False:
            add("Registro ESMA", SKIP, "registro non raggiungibile ora", None, None, "ESMA")
        elif esma:
            add("Registro ESMA: titolo attivo sulla borsa", OK, f"{isin} attivo su {mic.upper()} («{esma.get('gnr_full_name')}»)", None, None, "ESMA")
            s = sim(r["name"], esma.get("gnr_full_name"))
            # il registro abbrevia i nomi («XTRACK STX GL SEL DIV…»): un nome diverso non è un errore, si segnala solo se somiglia
            add("Nome (ESMA, abbreviato)", OK if (s or 0) >= 0.12 else SKIP, f"«{r['name']}» / «{esma.get('gnr_full_name')}»" + ("" if s is None else f" (somiglianza {s:.0%})") + ("" if (s or 0) >= 0.12 else ": nome abbreviato, non confrontabile"), r["name"], esma.get("gnr_full_name"), "ESMA")
            if jet and jet.get("cur") and esma.get("gnr_notional_curr_code"):
                same = jet["cur"] == esma["gnr_notional_curr_code"]  # per gli ETC il registro dà la valuta di quotazione, non quella del sottostante: se diverse non è un errore
            add("Valuta del fondo", OK if same else SKIP, f"{jet['cur']} (justETF) / {esma['gnr_notional_curr_code']} (ESMA)" + ("" if same else ": diverse, non confrontabili (il registro può dare la valuta di quotazione)"), jet["cur"], esma["gnr_notional_curr_code"], "justETF + ESMA")
        else:
            add("Registro ESMA: titolo attivo sulla borsa", WARN, f"{isin} non risulta attivo su {mic.upper()} nel registro", None, None, "ESMA")
    # --- OpenFIGI
    if isin:
        sfx = next((s for s in CODE if sym.endswith(s)), None)
        if figi is None:
            add("OpenFIGI: ticker e borsa", SKIP, "OpenFIGI non raggiungibile ora", None, None, "OpenFIGI")
        elif sfx:
            tick = sym[: -len(sfx)]
            hit = any(c == CODE[sfx] and t == tick for c, t in figi)
            add("OpenFIGI: ticker e borsa", OK if hit else WARN, f"{isin} ↔ {tick} su {CODE[sfx]}: " + ("confermato" if hit else "NON confermato (tickers noti: " + ", ".join(f"{t}@{c}" for c, t in figi[:6]) + ")"), sym, None, "OpenFIGI")
    # --- justETF
    if isin:
        if jet is False:
            add("justETF", SKIP, "justETF non raggiungibile ora", None, None, "justETF")
        elif jet is None:
            add("justETF", SKIP, "il fondo non è nell'elenco justETF (frequente per ETN/ETP)", None, None, "justETF")
        else:
            band("TER", r["ter"], jet["ter"], 0.005, 0.03, "justETF (ora)", num2, "su justETF ora", absolute=True)
            band("Patrimonio (M€)", r["assets_eur_m"], jet["aum"], 0.15, 0.4, "justETF (ora)", num0, "su justETF ora")
            band("Rendimento 1 anno (punti %)", r["ret_1y"], jet["r1"], 3, 8, "justETF (ora)", lambda v: f"{v:.1f}", "su justETF ora (rendimento totale: con i dividendi)", absolute=True)
            band("Volatilità 1 anno (punti %)", r["vol_1y"], jet["vol1"], 3, 6, "justETF (ora)", lambda v: f"{v:.1f}", "su justETF ora", absolute=True)
            for lab, a, b in (("Domicilio", r["domicile"], jet["dom"]), ("Replica", r["replication"], jet["repl"]), ("Distribuzione", r["distribution"], jet["dist"])):
                if a and b:
                    add(lab, OK if (a == b or (lab == "Replica" and a.startswith(b.split()[0]))) else WARN, f"{a} nell'archivio, {b} su justETF ora", a, b, "justETF (ora)")
            if r["inception"] and jet["inc"]:
                gap = abs((datetime.strptime(r["inception"], "%Y-%m-%d") - datetime.strptime(jet["inc"], "%Y-%m-%d")).days)
                add("Data di lancio", OK if gap <= 400 else WARN, f"{r['inception']} nell'archivio, {jet['inc']} su justETF (scarto {gap} giorni; il primo scambio può seguire il lancio)", r["inception"], jet["inc"], "justETF (ora)")
    # --- storico
    ser = [(d, p) for d, p in db.prices(sym)]
    if len(ser) < 30:
        add("Storico: disponibilità", SKIP, f"{len(ser)} punti: storico non scaricato", None, None, "archivio")
    else:
        days = [datetime.strptime(d, "%Y-%m-%d") for d, _ in ser]
        gaps = max((b - a).days for a, b in zip(days, days[1:]))
        mv = max(abs(b[1] / a[1] - 1) for a, b in zip(ser, ser[1:]))
        stale = (datetime.now() - days[-1]).days
        exp = (days[-1] - days[0]).days / 365.25 * 250
        add("Storico: completezza", OK if gaps <= 10 and len(ser) >= 0.85 * exp else WARN, f"{len(ser)} punti dal {ser[0][0]} al {ser[-1][0]} (attesi circa {exp:.0f}); buco massimo {gaps} giorni", len(ser), round(exp), "archivio")
        add("Storico: movimenti anomali", OK if mv <= 0.25 else WARN if mv <= 0.5 else FAIL, f"variazione giornaliera massima {mv * 100:.1f}%", None, None, "archivio")
        add("Storico: aggiornamento", OK if stale <= 5 else WARN, f"ultimo giorno {ser[-1][0]} ({stale} giorni fa)", None, None, "archivio")
        if stale <= 5 and r["price_eur"]:
            d = rel(r["price_eur"], ser[-1][1])
            add("Prezzo attuale e ultima chiusura", OK if d <= 0.03 else WARN if d <= 0.08 else FAIL, f"{r['price_eur']:.3f} € quotazione, {ser[-1][1]:.3f} € ultima chiusura: scarto {d * 100:.2f}%", r["price_eur"], ser[-1][1], "archivio")
        if yh:
            new = _eur(db, yh[1], yh[0] or r["currency"])
            old = dict(ser)
            ratios = [v / old[d] for d, v in new if old.get(d)]
            if len(ratios) < 5:
                add("Storico: nuovo scarico da Yahoo", SKIP, "poche date in comune", None, None, "Yahoo (ora)")
            else:
                m = statistics.median(ratios)
                dev = max(abs(v / (old[d] * m) - 1) for d, v in new if old.get(d))
                add("Storico: nuovo scarico da Yahoo (ultimi 60 giorni)", OK if dev <= 0.003 else WARN if dev <= 0.01 else FAIL,
                    f"scarto massimo {dev * 100:.2f}% sulle {len(ratios)} date in comune" + (f"; dividendi usciti dopo l'ultimo aggiornamento: storico da riallineare di {abs(m - 1) * 100:.2f}%" if abs(m - 1) > 0.001 else ""), None, None, "Yahoo (ora)")
        elif yh is None:
            add("Storico: nuovo scarico da Yahoo", SKIP, "Yahoo non raggiungibile ora", None, None, "Yahoo (ora)")
    # --- altre quotazioni dello stesso fondo
    if isin:
        for o in db.c.execute("SELECT symbol, exchange_name, currency, price_eur FROM etf WHERE isin=? AND symbol<>? AND price_eur IS NOT NULL", (isin, sym)):
            d = rel(r["price_eur"], o["price_eur"])
            if d is not None:
                add(f"Stesso fondo su {o['exchange_name']} ({o['symbol']})", OK if d <= 0.015 else WARN if d <= 0.04 else FAIL,
                    f"{r['price_eur']:.3f} € qui, {o['price_eur']:.3f} € lì: scarto {d * 100:.2f}% (controlla prezzi e cambio)", r["price_eur"], o["price_eur"], "archivio (altra borsa)")
    return out


def _stale(ts, days):
    try:
        return (datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).days > days
    except (TypeError, ValueError):
        return True


def run(db, y, jt, n=15, progress=nop, seed=None, figi_key=None):
    """Controlla n fondi a caso. Ritorna il rapporto (dizionario)."""
    seed = seed if seed is not None else random.randrange(10 ** 6)
    sample = pick_sample(db, n, seed)
    if not sample:
        raise RuntimeError("L'archivio è vuoto: niente da controllare")
    syms = [r["symbol"] for r in sample]
    progress("Prezzi attuali da Yahoo…", 0, len(sample))
    try:
        quotes = y.quotes(syms)
    except RuntimeError as e:
        y.warn(f"Yahoo non raggiungibile per le quotazioni ({e})")
        quotes = {}
    figi_map, isins = {}, [r["isin"] for r in sample if r["isin"]]
    if isins:
        progress("Ticker e borse da OpenFIGI…", 0, len(sample))
        try:
            fg = refdata.Figi(figi_key, y.cancel, y.log)
            for i in range(0, len(isins), fg.batch):
                figi_map.update(fg.map(isins[i:i + fg.batch]))
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            y.warn(f"OpenFIGI non raggiungibile ({e})")
            figi_map = None
    funds = []
    for i, r in enumerate(sample):
        progress(f"Controllo {r['symbol']} ({i + 1} di {len(sample)})…", i, len(sample))
        isin = r["isin"]
        esma = jet = yh = None
        mic = next((m for sfx, m in refdata.SUFFIX_MIC.items() if r["symbol"].endswith(sfx)), None)
        if isin and mic:
            try:
                esma = refdata.firds_lookup(isin, mic) or None
            except Cancelled:
                raise
            except Exception:  # noqa: BLE001
                esma = False
        if isin:
            try:
                jet = jt.by_isin(isin)
            except Cancelled:
                raise
            except Exception:  # noqa: BLE001
                jet = False
        try:
            last = db.get(r["symbol"])["hist_to"]
            yh = y.history(r["symbol"], since=(datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")) if last else None
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001
            yh = None
        figi = None if figi_map is None else figi_map.get(isin, []) if isin else None
        checks = check_fund(db, r, quotes.get(r["symbol"]), esma, jet, figi, yh, {})
        worst = max((c["status"] for c in checks), key=lambda s: ORDER[s], default=SKIP)
        funds.append({"symbol": r["symbol"], "isin": isin, "name": r["name"], "exchange": r["exchange_name"], "status": worst, "checks": checks})
    funds.sort(key=lambda f: -ORDER[f["status"]])
    cnt = {s: sum(1 for f in funds for c in f["checks"] if c["status"] == s) for s in (OK, WARN, FAIL, SKIP)}
    return {"seed": seed, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(funds), "checks": cnt,
            "funds_ok": sum(1 for f in funds if f["status"] == OK), "funds_warn": sum(1 for f in funds if f["status"] == WARN), "funds_fail": sum(1 for f in funds if f["status"] == FAIL),
            "funds": funds}
