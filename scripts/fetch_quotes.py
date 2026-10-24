#!/usr/bin/env python3
"""Bid e ask (in EUR) di tutti gli ETF con prezzi scaricati: i 14 di prices.js e quelli di data/symbols.json. Scrive quotes.js.

    python scripts/fetch_quotes.py

Valori non attendibili (lontani oltre il 3% dall'ultimo prezzo: fuori orario sono vecchi) si scartano; i simboli non in EUR si convertono al cambio del momento.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_prices as fp  # noqa: E402
import urllib.parse  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def symbols():
    out = {}
    s = (ROOT / "prices.js").read_text(encoding="utf-8")
    if "{" in s:
        for isin, v in json.loads(s[s.index("{"): s.rindex("}") + 1]).get("series", {}).items():
            out[isin] = v["symbol"]
    p = ROOT / "data" / "symbols.json"
    if p.exists():
        for isin, v in json.loads(p.read_text(encoding="utf-8")).items():
            if v.get("symbol"):
                out.setdefault(isin, v["symbol"])
    return out


def raw_quotes(syms):
    """Come fp.quotes ma con valuta e ultimo prezzo."""
    import urllib.request
    fp.quotes([])  # prepara cookie e crumb
    op, crumb = fp._SESSION.get("op"), fp._SESSION.get("crumb")
    if not op:
        return {}
    res = {}
    syms = list(syms)
    for i in range(0, len(syms), 40):
        url = "https://query1.finance.yahoo.com/v7/finance/quote?" + urllib.parse.urlencode({"symbols": ",".join(syms[i:i + 40]), "crumb": crumb, "fields": "bid,ask,currency,regularMarketPrice"})
        for r in json.load(op.open(urllib.request.Request(url, headers=fp.HEADERS), timeout=30))["quoteResponse"]["result"]:
            res[r["symbol"]] = r
        time.sleep(0.5)
    return res


def main():
    sy = symbols()
    print(f"ETF con simbolo: {len(sy)}")
    try:
        q = raw_quotes(set(sy.values()))
        cur = {r.get("currency") for r in q.values()} - {"EUR", None}
        fx = raw_quotes({f"EUR{('GBP' if c == 'GBp' else c)}=X" for c in cur})
    except Exception as e:
        sys.exit(f"Quotazioni non disponibili: {e}")
    out = {}
    for isin, sym in sy.items():
        r = q.get(sym)
        if not r:
            continue
        c = r.get("currency")
        div = 1.0
        if c and c != "EUR":
            rate = (fx.get(f"EUR{('GBP' if c == 'GBp' else c)}=X") or {}).get("regularMarketPrice")
            if not rate:
                continue
            div = rate / (0.01 if c == "GBp" else 1.0)
        b, a, p = r.get("bid"), r.get("ask"), r.get("regularMarketPrice")
        if not (b and a and p and a > b):
            continue
        if abs((a + b) / 2 / p - 1) > 0.03:  # valore vecchio (mercato chiuso)
            continue
        out[isin] = {"bid": round(b / div, 4), "ask": round(a / div, 4), "sym": sym}
    path = ROOT / "quotes.js"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("window.QUOTES=" + json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "q": out}, separators=(",", ":")) + ";\n", encoding="utf-8")
    tmp.replace(path)
    print(f"Scritto {path}: bid/ask attendibili per {len(out)} ETF su {len(sy)}")


if __name__ == "__main__":
    main()
