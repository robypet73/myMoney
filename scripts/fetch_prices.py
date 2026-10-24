#!/usr/bin/env python3
"""Scarica i prezzi giornalieri degli ETF da Yahoo Finance e scrive prices.js accanto a index.html.

Solo libreria standard, nessun permesso di amministratore:
    python scripts/fetch_prices.py

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
    """Restituisce (valuta, [timestamp ms a mezzogiorno UTC], [chiusure]) senza giorni vuoti."""
    res = payload["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    t, v = [], []
    for ts, c in zip(res.get("timestamp", []), closes):
        if c is None:
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        t.append(int(day.timestamp() * 1000))
        v.append(round(float(c), 4))
    return res["meta"].get("currency", ""), t, v


def main():
    out = {}
    for isin, ticker in ISINS.items():
        try:
            sym = find_symbol(isin)
            if not sym:
                print(f"{ticker} {isin}: simbolo non trovato"); continue
            payload = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={RANGE}&interval=1d")
            cur, t, v = parse_chart(payload)
            if len(t) < 50:
                print(f"{ticker} {sym}: pochi dati ({len(t)})"); continue
            out[isin] = {"symbol": sym, "currency": cur, "source": f"https://finance.yahoo.com/quote/{urllib.parse.quote(sym)}/history", "t": t, "v": v}
            print(f"{ticker} {sym} {cur}: {len(t)} giorni, ultimo {v[-1]}")
        except Exception as e:  # rete, formato, limiti: si prosegue con gli altri
            print(f"{ticker} {isin}: errore {e}")
        time.sleep(0.5)
    if not out:
        sys.exit("Nessun prezzo scaricato: prices.js non aggiornato")
    path = Path(__file__).resolve().parent.parent / "prices.js"
    path.write_text("window.PRICES=" + json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "series": out}, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Scritto {path} ({len(out)} ETF su {len(ISINS)})")


if __name__ == "__main__":
    main()
