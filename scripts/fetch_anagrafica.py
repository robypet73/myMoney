#!/usr/bin/env python3
"""Anagrafica fissa delle quotazioni di tutti gli ETF, ETC ed ETN su Yahoo Finance, abbinata agli ISIN del catalogo justETF. Scrive anagrafica.js.

    python scripts/fetch_anagrafica.py            # scarica dallo screener di Yahoo (≈ 70 richieste) e scrive anagrafica.js
    python scripts/fetch_anagrafica.py --raw F    # salva/riusa i dati grezzi in F (per le prove)

Lo screener di Yahoo elenca, per ogni borsa, tutti i titoli ETF con simbolo, nome, valuta, prezzo, volume medio, bid e ask. Non c'è l'ISIN: si abbina al catalogo
(`catalog.js`, justETF) dal nome del fondo. Per ogni ISIN si tengono le quotazioni (simbolo, borsa, valuta, volume medio giornaliero in Mln €, spread %), la
prima è quella preferita (Borsa Italiana in EUR se scambiata di recente, poi le altre in EUR). Servono alla pagina per i criteri su borsa, valuta di
negoziazione, liquidità e spread senza dover scaricare i prezzi di ogni ETF, e agli script dei prezzi per conoscere subito il simbolo.
"""
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_prices as fp  # noqa: E402

ROOT = Path(os.environ.get("MYMONEY_ROOT") or Path(__file__).resolve().parent.parent)
OUT = ROOT / "anagrafica.js"
# codice Yahoo → nome mostrato nella pagina (stessi nomi di EXCH_ALL in index.html)
EXCHANGES = {"MIL": "Borsa Italiana", "GER": "Xetra", "PAR": "Euronext Parigi", "AMS": "Euronext Amsterdam", "LSE": "Londra (LSE)", "EBS": "SIX Swiss"}
STOP = {"ucits", "etf", "ucit", "fund", "the", "of", "and", "plc", "ucits-etf", "etc", "etn", "etp", "ex"}


def session():
    for k in range(6):
        fp._SESSION.clear()
        fp.quotes([])  # prepara cookie e crumb
        if fp._SESSION.get("crumb"):
            return fp._SESSION["op"], fp._SESSION["crumb"]
        time.sleep(20)
    raise RuntimeError("cookie e crumb di Yahoo non ottenuti")


def screen(op, crumb, exch):
    """Tutti i titoli ETF di una borsa (250 per pagina)."""
    out, offset = [], 0
    while True:
        body = {"size": 250, "offset": offset, "sortField": "dayvolume", "sortType": "DESC", "quoteType": "ETF", "userId": "", "userIdType": "guid",
                "query": {"operator": "eq", "operands": ["exchange", exch]}}
        url = "https://query1.finance.yahoo.com/v1/finance/screener?" + urllib.parse.urlencode({"crumb": crumb, "lang": "en-US", "region": "US", "formatted": "false", "corsDomain": "finance.yahoo.com"})
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(fp.HEADERS, **{"Content-Type": "application/json"}), method="POST")
        for k in range(5):
            try:
                res = json.load(op.open(req, timeout=40))["finance"]["result"][0]
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and k < 4:
                    time.sleep(20 * (k + 1))
                    continue
                raise
        q = res.get("quotes") or []
        out += q
        offset += len(q)
        total = res.get("total") or 0
        print(f"  {exch}: {offset} di {total}", flush=True)
        if not q or offset >= total:
            return out
        time.sleep(1.0)


def fx_rates(op, crumb, curs):
    """1 unità di valuta in EUR (GBp = penny)."""
    need = sorted({("GBP" if c == "GBp" else c) for c in curs if c and c != "EUR"})
    rates = {"EUR": 1.0}
    if not need:
        return rates
    url = "https://query1.finance.yahoo.com/v7/finance/quote?" + urllib.parse.urlencode({"symbols": ",".join(f"EUR{c}=X" for c in need), "crumb": crumb})
    for r in json.load(op.open(urllib.request.Request(url, headers=fp.HEADERS), timeout=30))["quoteResponse"]["result"]:
        p = r.get("regularMarketPrice")
        if p:
            rates[r["symbol"][3:6]] = 1 / p
    if "GBP" in rates:
        rates["GBp"] = rates["GBP"] / 100
    return rates


def norm(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def core(s):
    return " ".join(w for w in norm(s).split() if w not in STOP)


def load_catalog():
    t = (ROOT / "catalog.js").read_text(encoding="utf-8")
    d = json.loads(t[t.index("{"): t.rindex("}") + 1])
    cols = d["cols"]
    return [dict(zip(cols, r)) for r in d["rows"]]


def previous():
    """Abbinamenti ISIN → simboli già trovati (anagrafica.js precedente) e ISIN senza quotazione provati di recente."""
    prev, miss = {}, {}
    if OUT.exists():
        t = OUT.read_text(encoding="utf-8")
        try:
            prev = {i: [x[0] for x in v] for i, v in json.loads(t[t.index("{"): t.rindex("}") + 1]).get("d", {}).items()}
        except Exception:
            pass
    mf = ROOT / "data" / "anag-miss.json"
    if mf.exists():
        try:
            miss = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            pass
    return prev, miss


def search_isin(isin):
    """Simboli Yahoo con quell'ISIN (la ricerca di Yahoo accetta l'ISIN)."""
    for k in range(4):
        try:
            data = fp.get_json("https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode({"q": isin, "quotesCount": 15, "newsCount": 0}))
            return [q["symbol"] for q in data.get("quotes", []) if q.get("symbol")]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(15 * (k + 1))
                continue
            return []
        except Exception:
            time.sleep(3)
    return None  # non riuscito: si riprova la prossima volta


def listings(S, rates, symbols):
    """Quotazioni dettagliate (simbolo, borsa, valuta, volume medio in Mln €, spread %) dei simboli presenti nello screener, la preferita per prima."""
    now, ls, seen = time.time(), [], set()
    for sym in symbols:
        q = S.get(sym)
        if not q or sym in seen:
            continue
        seen.add(sym)
        price, cur = q.get("regularMarketPrice"), q.get("currency")
        if not price:
            continue
        rate = rates.get(cur)
        vol = q.get("averageDailyVolume3Month") or q.get("regularMarketVolume")
        adv = round(vol * price * rate / 1e6, 3) if vol and rate else None
        bid, ask = q.get("bid"), q.get("ask")
        spr = None
        if bid and ask and bid > 0 and ask >= bid and abs((bid + ask) / 2 / price - 1) < 0.05:
            spr = round((ask - bid) / ((ask + bid) / 2) * 100, 3)
        fresh = (now - (q.get("regularMarketTime") or 0)) < 5 * 86400  # Yahoo riempie le barre degli ETF poco scambiati: conta l'ultimo scambio
        ls.append((0 if (q.get("exchange") == "MIL" and cur == "EUR" and fresh) else 1 if cur == "EUR" and fresh else 2 if fresh else 3, -(adv or 0), [sym, q.get("exchange"), cur, adv, spr]))
    ls.sort(key=lambda x: x[:2])
    return [x[2] for x in ls[:8]]


def expand_listings(S, mapping):
    """Altre quotazioni dello stesso fondo: i titoli di Yahoo con lo stesso nome di uno dei simboli già abbinati (stesso ETF su un'altra borsa), se non sono di un altro ISIN."""
    by_name = {}
    for sym, q in S.items():
        by_name.setdefault(norm(q.get("longName") or q.get("shortName") or ""), []).append(sym)
    claimed = {}
    for isin, syms in mapping.items():
        for sy in syms:
            claimed.setdefault(sy, isin)
    for isin, syms in mapping.items():
        for sy in list(syms):
            q = S.get(sy)
            if not q:
                continue
            for other in by_name.get(norm(q.get("longName") or q.get("shortName") or ""), []):
                if other not in syms and claimed.get(other, isin) == isin:
                    syms.append(other)
                    claimed[other] = isin


def write_out(S, rates, mapping):
    out = {}
    for isin, syms in mapping.items():
        ls = listings(S, rates, syms)
        if ls:
            out[isin] = ls
    payload = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Yahoo Finance (screener e ricerca per ISIN)", "x": EXCHANGES, "d": out}
    OUT.write_text("window.ANAG=" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n", encoding="utf-8")
    return out


def save_miss(miss):
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "anag-miss.json").write_text(json.dumps(miss, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def main():
    rawf = Path(sys.argv[sys.argv.index("--raw") + 1]) if "--raw" in sys.argv else None
    max_search = int(sys.argv[sys.argv.index("--max-search") + 1]) if "--max-search" in sys.argv else 4000
    op = crumb = None
    if rawf and rawf.exists():
        raw = json.loads(rawf.read_text(encoding="utf-8"))
    else:
        op, crumb = session()
        raw = {}
        for ex in EXCHANGES:
            print(f"Borsa {ex} ({EXCHANGES[ex]})", flush=True)
            raw[ex] = screen(op, crumb, ex)
        if rawf:
            rawf.write_text(json.dumps(raw), encoding="utf-8")
    if op is None:
        op, crumb = session()
    S = {q["symbol"]: dict(q, exchange=ex) for ex, qs in raw.items() for q in qs if q.get("symbol")}
    rates = fx_rates(op, crumb, {q.get("currency") for q in S.values()})
    cat = load_catalog()
    prev, miss = previous()
    # 1) abbinamento per nome, 2) simboli già trovati in precedenza, 3) ricerca per ISIN di Yahoo per gli altri
    mapping = {}
    by_norm, by_core = {}, {}
    for c in cat:
        by_norm.setdefault(norm(c["name"]), []).append(c["isin"])
        by_core.setdefault(core(c["name"]), []).append(c["isin"])
    for sym, q in S.items():
        nm = q.get("longName") or q.get("shortName") or ""
        c = by_norm.get(norm(nm)) or by_core.get(core(nm))
        if c and len(c) == 1:
            mapping.setdefault(c[0], []).append(sym)
    for isin, syms in prev.items():
        mapping.setdefault(isin, [])
        mapping[isin] += [s for s in syms if s not in mapping[isin]]
    print(f"Abbinati per nome o dal file precedente: {sum(1 for v in mapping.values() if v)} ISIN su {len(cat)}", flush=True)
    now = int(time.time())
    todo = [c["isin"] for c in cat if not any(s in S for s in mapping.get(c["isin"], [])) and now - miss.get(c["isin"], 0) > 60 * 86400]
    print(f"Da cercare per ISIN: {len(todo)} (al massimo {max_search})", flush=True)
    found = 0
    for n, isin in enumerate(todo[:max_search], 1):
        syms = search_isin(isin)
        if syms is None:
            continue
        keep = [s for s in syms if s in S]
        if keep:
            mapping[isin] = keep
            found += 1
        else:
            miss[isin] = now
        time.sleep(0.35)
        if n % 250 == 0:
            out = write_out(S, rates, mapping)
            save_miss(miss)
            print(f"  ricerca {n} di {len(todo)}: trovati {found}; ISIN con quotazione: {len(out)}", flush=True)
    expand_listings(S, mapping)
    out = write_out(S, rates, mapping)
    save_miss(miss)
    print(f"Titoli su Yahoo: {len(S)}; ISIN del catalogo con almeno una quotazione: {len(out)} su {len(cat)}")
    print(f"Scritto {OUT} ({OUT.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    main()
