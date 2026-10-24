#!/usr/bin/env python3
"""Scarica da Yahoo Finance le serie di prezzi (storia completa, giornaliere) degli ETF del catalogo che non sono tra i 14 di prices.js.

Quali ETF: quelli elencati in watchlist.txt (un ISIN per riga) più i primi N per patrimonio del catalogo (catalog.js).
Scrive un file per ISIN in data/p/ISIN.js (letto dalla pagina solo quando serve) e ricorda il simbolo Yahoo scelto in data/symbols.json.

    python scripts/fetch_series.py [--top 150] [--isins IE00B3RBWM25,...]
"""
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_prices as fp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "p"
SYMS = ROOT / "data" / "symbols.json"
DEADLINE = time.time() + 5 * 3600  # il job GitHub si ferma a 6 ore


def catalog():
    s = (ROOT / "catalog.js").read_text(encoding="utf-8")
    d = json.loads(s[s.index("{"): s.rindex("}") + 1])
    ix = {c: i for i, c in enumerate(d["cols"])}
    return {r[ix["isin"]]: {"ticker": r[ix["ticker"]], "aum": r[ix["aum"]] or 0, "name": r[ix["name"]]} for r in d["rows"]}


def watchlist():
    p = ROOT / "watchlist.txt"
    return [m.group(0) for l in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []) for m in [re.match(r"[A-Z]{2}[A-Z0-9]{9}\d", l.strip().upper())] if m]


FX = {}


def to_eur(cur, t, v):
    """Converte in EUR al cambio giornaliero di Yahoo (EURUSD=X = dollari per un euro), con l'ultimo cambio noto nei giorni senza quotazione."""
    if cur == "EUR":
        return t, v, None
    scale, base = (0.01, "GBP") if cur == "GBp" else (1.0, cur)
    if base == "EUR":
        return t, [round(x * scale, 4) for x in v], None
    if base not in FX:
        _, ft, fv, _ = fp.parse_chart(fp.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/EUR{base}=X?period1=0&period2={int(time.time())}&interval=1d"))
        FX[base] = (ft, fv); time.sleep(0.3)
    ft, fv = FX[base]
    out, j = [], 0
    for ti, x in zip(t, v):
        while j + 1 < len(ft) and ft[j + 1] <= ti:
            j += 1
        out.append(round(x * scale / fv[j], 4))
    return t, out, base


def write(isin, sym, cur, name, t, v, last, orig=None, quote=None):
    days = [int(x // 86400000) for x in t]
    body = {"symbol": sym, "currency": cur, "fx": orig, "name": name, "source": f"https://finance.yahoo.com/quote/{urllib.parse.quote(sym)}/history", "adv": last.get("adv"), **(quote or {}), "d": days, "v": v}
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f"{isin}.tmp"
    tmp.write_text(f'window.PX=window.PX||{{}};window.PX["{isin}"]=' + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    tmp.replace(OUT / f"{isin}.js")


def main():
    args = sys.argv[1:]
    top = int(args[args.index("--top") + 1]) if "--top" in args else 150
    only = [i for i in args[args.index("--isins") + 1].replace(" ", "").upper().split(",") if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", i)] if "--isins" in args else None
    force = "--force" in args
    cat = catalog()
    chosen = only or list(dict.fromkeys(watchlist() + [i for i, _ in sorted(cat.items(), key=lambda kv: -kv[1]["aum"]) if i not in fp.ISINS][:top]))
    chosen = [i for i in chosen if i not in fp.ISINS]
    syms = json.loads(SYMS.read_text(encoding="utf-8")) if SYMS.exists() else {}
    print(f"ETF da scaricare: {len(chosen)} (watchlist {len(watchlist())}, primi {top} per patrimonio)")
    ok = 0
    batch = {}

    def flush():
        q = fp.quotes(b[0] for b in batch.values()) if batch else {}
        for i, (sym, c, nm, t, v, last, orig, cur0) in batch.items():
            qq = dict(q.get(sym) or {})
            if orig and qq:  # bid e ask nella valuta di quotazione: stessa conversione dei prezzi
                div = FX[orig][1][-1] / (0.01 if cur0 == "GBp" else 1.0)
                for k in ("bid", "ask"):
                    qq[k] = round(qq[k] / div, 4) if qq.get(k) else None
            elif cur0 == "GBp" and qq:
                for k in ("bid", "ask"):
                    qq[k] = round(qq[k] * 0.01, 4) if qq.get(k) else None
            write(i, sym, c, nm, t, v, last, orig, qq or None)
        batch.clear()

    for n, isin in enumerate(chosen, 1):
        if time.time() > DEADLINE:
            print("Tempo esaurito: riprendo alla prossima esecuzione"); break
        info = cat.get(isin, {})
        try:
            known = syms.get(isin)
            if known and known.get("symbol"):
                cur, t, v, last = fp.parse_chart(fp.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(known['symbol'])}?period1=0&period2={int(time.time())}&interval=1d"))
                sym = known["symbol"]
                if len(t) < 50:
                    raise ValueError("pochi dati")
            else:
                if not force and known and known.get("failed") and time.time() - known["failed"] < 30 * 86400:
                    continue  # già provato di recente senza successo
                tk = info.get("ticker")
                found = fp.best_listing(isin, None if tk in (None, "-", isin) else tk, rng="max")
                if not found:
                    syms[isin] = {"symbol": None, "failed": int(time.time())}
                    print(f"[{n}/{len(chosen)}] {isin} {info.get('name', '')[:40]}: nessuna quotazione")
                    continue
                sym, cur, t, v, last = next((f for f in found if f[1] == "EUR"), found[0])
                syms[isin] = {"symbol": sym}
            t, v, orig = to_eur(cur, t, v)
            batch[isin] = (sym, "EUR", last.pop("name", None), t, v, last, orig, cur)
            ok += 1
            print(f"[{n}/{len(chosen)}] {isin} {sym} {cur}{" → EUR" if orig else ""}: {len(t)} giorni, ultimo {v[-1]}")
        except Exception as e:
            print(f"[{n}/{len(chosen)}] {isin}: errore {e}")
        time.sleep(0.4)
        if n % 25 == 0:
            flush()
            SYMS.parent.mkdir(parents=True, exist_ok=True); SYMS.write_text(json.dumps(syms, indent=0, sort_keys=True), encoding="utf-8")
    flush()
    SYMS.parent.mkdir(parents=True, exist_ok=True)
    SYMS.write_text(json.dumps(syms, indent=0, sort_keys=True), encoding="utf-8")
    print(f"Scritti {ok} file in {OUT}")


if __name__ == "__main__":
    main()
