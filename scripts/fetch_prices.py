#!/usr/bin/env python3
"""Scarica i prezzi giornalieri degli ETF da Yahoo Finance e scrive prices.js accanto a index.html.

Solo libreria standard, nessun permesso di amministratore:
    python scripts/fetch_prices.py

    python scripts/fetch_prices.py --watch 10   # poi aggiorna le quotazioni correnti ogni 10 secondi
    python scripts/fetch_prices.py --isins IE00B5BMR087,IE00B4K48X80   # solo alcuni ETF

Per ogni ISIN cerca il simbolo su Yahoo Finance. Se la ricerca sceglie la borsa sbagliata,
indica il simbolo a mano in SYMBOLS (es. "IE00B5BMR087": "CSPX.L").
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ISINS = {
    "IE00B4L5Y983": "SWDA", "IE00BK5BQT80": "VWCE", "IE00B5BMR087": "CSPX", "IE00BTJRMP35": "XMME",
    "IE00BKM4GZ66": "EIMI", "IE00B4K48X80": "IMAE", "FR0010010827": "FMI", "LU0274209740": "XMJP",
    "IE00BYZK4552": "RBOT", "IE00B1FZS350": "IWDP", "IE00B4WXJJ64": "IEGA", "IE00B1FZS798": "IBTM",
    "IE00BDBRDM35": "AGGH", "IE00B579F325": "SGLD",
}
SYMBOLS = {}  # ISIN -> simbolo Yahoo (o elenco di simboli), per forzare la borsa
# Quotazioni in EUR da provare dopo il risultato della ricerca: il ticker con i suffissi Yahoo di Borsa Italiana, Amsterdam, Parigi e Xetra, più alcuni ticker propri di Xetra.
SUFFIXES = (".MI", ".AS", ".PA", ".DE")
EXTRA = {"IE00B4L5Y983": ["EUNL.DE"], "IE00BKM4GZ66": ["IS3N.DE"], "IE00B5BMR087": ["SXR8.DE"], "IE00BYZK4552": ["2B76.DE"], "IE00B1FZS350": ["IQQ6.DE"],
         "IE00B4WXJJ64": ["EUNH.DE"], "IE00B579F325": ["8PSG.DE"], "IE00BK5BQT80": ["VWCE.DE"]}
RANGE = "10y"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; myMoney/1.0)"}


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def candidates(isin):
    """Simboli Yahoo per l'ISIN: quello forzato in SYMBOLS, altrimenti i risultati della ricerca."""
    if isin in SYMBOLS:
        s = SYMBOLS[isin]
        return [s] if isinstance(s, str) else list(s)
    data = get_json("https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode({"q": isin, "quotesCount": 10, "newsCount": 0}))
    out = [q["symbol"] for q in data.get("quotes", []) if q.get("quoteType") in ("ETF", "MUTUALFUND", "EQUITY") and q.get("symbol")]
    out += EXTRA.get(isin, []) + [ISINS[isin] + s for s in SUFFIXES]
    return list(dict.fromkeys(out))


def best_listing(isin):
    """Scarica le serie dei simboli candidati e sceglie la quotazione in EUR con dati sufficienti (altrimenti la prima valida)."""
    found, ref = [], None
    for sym in candidates(isin):
        try:
            cur, t, v, last = parse_chart(get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={RANGE}&interval=1d"))
        except Exception:
            continue
        time.sleep(0.3)
        key = (last.get("name") or "").lower().split("ucits")[0].strip()  # stesso fondo = stesso nome fino a «UCITS»
        if ref is not None and key != ref:
            print(f"  {sym}: fondo diverso ({last.get('name')}), scartato"); continue
        if len(t) >= 50:
            ref = ref if ref is not None else key
            found.append((sym, cur, t, v, last)); print(f"  {sym} {cur}: {last.get('name')} · ultimo {v[-1]}")
            if cur == "EUR":
                break
    return found


def parse_chart(payload):
    """Restituisce (valuta, [timestamp ms a mezzogiorno UTC], [chiusure], ultima quotazione) senza giorni vuoti."""
    res = payload["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    vols = res["indicators"]["quote"][0].get("volume") or [None] * len(closes)
    t, v, tv = [], [], []
    for ts, c, vol in zip(res.get("timestamp", []), closes, vols):
        if c is None:
            continue
        tv.append(float(c) * float(vol or 0) / 1e6)
        day = datetime.fromtimestamp(ts, timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        t.append(int(day.timestamp() * 1000))
        v.append(round(float(c), 4))
    meta = res["meta"]
    last = {"price": meta.get("regularMarketPrice") or (v[-1] if v else None), "time": meta.get("regularMarketTime"),
            "adv": round(sum(tv[-60:]) / len(tv[-60:]), 2) if tv else None, "name": meta.get("longName") or meta.get("shortName")}  # volume medio giornaliero 3 mesi, in milioni di valuta
    return meta.get("currency", ""), t, v, last


def main():
    args = sys.argv[1:]
    watch = int(args[args.index("--watch") + 1]) if "--watch" in args and args.index("--watch") + 1 < len(args) else (10 if "--watch" in args else 0)
    only = set(args[args.index("--isins") + 1].split(",")) if "--isins" in args else None
    out = {}
    for isin, ticker in ISINS.items():
        if only and isin not in only:
            continue
        try:
            found = best_listing(isin)
            if not found:
                print(f"{ticker} {isin}: nessuna quotazione con dati sufficienti"); continue
            print(f"{ticker} scelto tra: " + ", ".join(f"{f[0]} {f[1]}" for f in found))
            sym, cur, t, v, last = next((f for f in found if f[1] == "EUR"), found[0])
            out[isin] = {"symbol": sym, "currency": cur, "source": f"https://finance.yahoo.com/quote/{urllib.parse.quote(sym)}/history", "name": last.pop("name", None), "adv": last.pop("adv", None), "last": last, "t": t, "v": v}
            print(f"{ticker} {sym} {cur}: {len(t)} giorni, ultimo {v[-1]}")
        except Exception as e:  # rete, formato, limiti: si prosegue con gli altri
            print(f"{ticker} {isin}: errore {e}")
        time.sleep(0.5)
    if not out:
        sys.exit("Nessun prezzo scaricato: prices.js non aggiornato")
    path = Path(__file__).resolve().parent.parent / "prices.js"
    write(path, out)
    print(f"Scritto {path} ({len(out)} ETF su {len(ISINS)})")
    if watch:
        print(f"Aggiorno le quotazioni ogni {watch} secondi (Ctrl+C per fermare)")
        while True:
            time.sleep(watch)
            for isin, s in out.items():
                try:
                    payload = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s['symbol'])}?range=1d&interval=1m")
                    s["last"] = parse_chart(payload)[3]; s["last"].pop("adv", None); s["last"].pop("name", None)
                except Exception as e:
                    print(f"{isin}: errore {e}")
            write(path, out)
            print(datetime.now().strftime("%H:%M:%S"), "aggiornato")


def write(path, out):
    tmp = path.with_suffix(".tmp")
    tmp.write_text("window.PRICES=" + json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "series": out}, separators=(",", ":")) + ";\n", encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    main()
