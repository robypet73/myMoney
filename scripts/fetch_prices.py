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
SYMBOLS = {}  # ISIN -> simbolo Yahoo, per forzare la borsa
RANGE = "10y"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; myMoney/1.0)"}


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def find_symbol(isin):
    if isin in SYMBOLS:
        return SYMBOLS[isin]
    data = get_json("https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode({"q": isin, "quotesCount": 6, "newsCount": 0}))
    for q in data.get("quotes", []):
        if q.get("quoteType") in ("ETF", "MUTUALFUND", "EQUITY") and q.get("symbol"):
            return q["symbol"]
    return None


def parse_chart(payload):
    """Restituisce (valuta, [timestamp ms a mezzogiorno UTC], [chiusure], ultima quotazione) senza giorni vuoti."""
    res = payload["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    t, v = [], []
    for ts, c in zip(res.get("timestamp", []), closes):
        if c is None:
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        t.append(int(day.timestamp() * 1000))
        v.append(round(float(c), 4))
    meta = res["meta"]
    last = {"price": meta.get("regularMarketPrice") or (v[-1] if v else None), "time": meta.get("regularMarketTime")}
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
            sym = find_symbol(isin)
            if not sym:
                print(f"{ticker} {isin}: simbolo non trovato"); continue
            payload = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={RANGE}&interval=1d")
            cur, t, v, last = parse_chart(payload)
            if len(t) < 50:
                print(f"{ticker} {sym}: pochi dati ({len(t)})"); continue
            out[isin] = {"symbol": sym, "currency": cur, "source": f"https://finance.yahoo.com/quote/{urllib.parse.quote(sym)}/history", "last": last, "t": t, "v": v}
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
                    s["last"] = parse_chart(payload)[3]
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
