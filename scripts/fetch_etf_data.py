#!/usr/bin/env python3
"""Scarica anagrafica e composizione degli ETF da justETF e scrive etfdata.js accanto a index.html.

Solo libreria standard:
    python scripts/fetch_etf_data.py
    python scripts/fetch_etf_data.py --isins IE00B4L5Y983,IE00B5BMR087

Per ogni ISIN legge la scheda inglese (TER, patrimonio, replica, distribuzione, domicilio, lancio, valuta, indice,
numero di titoli, primi 10 titoli) e quella italiana (paesi e settori con i nomi in italiano).
Se un campo non si trova resta fuori dal file e l'app usa il valore già presente in index.html.
"""
import html as htmllib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ISINS = ["IE00B4L5Y983", "IE00BK5BQT80", "IE00B5BMR087", "IE00BTJRMP35", "IE00BKM4GZ66", "IE00B4K48X80", "FR0010010827",
         "LU0274209740", "IE00BYZK4552", "IE00B1FZS350", "IE00B4WXJJ64", "IE00B1FZS798", "IE00BDBRDM35", "IE00B579F325"]
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def page(isin, lang):
    url = f"https://www.justetf.com/{lang}/etf-profile.html?isin={isin}"
    req = urllib.request.Request(url, headers={**HEADERS, "Accept-Language": lang})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace"), url


def clean(s):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def tid(h, name):
    m = re.search(r'data-testid="%s"[^>]*>(.*?)</' % re.escape(name), h, re.S)
    return clean(m.group(1)) if m else None


def num(s, decimal="."):
    """'0.20% p.a.' / '1,252' / '132.896' -> numero; il separatore decimale dipende dalla lingua della scheda."""
    m = re.search(r"-?\d[\d.,]*", s or "")
    if not m:
        return None
    t = m.group(0)
    t = t.replace(",", "") if decimal == "." else t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def rows(h, table_id, name_id, pct_id, dec):
    """Righe nome/percentuale di una tabella (titoli, paesi o settori), senza duplicati."""
    out, seen = [], set()
    for block in re.findall(r'data-testid="%s".*?</tr>' % re.escape(table_id), h, re.S):
        n, p = tid(block, name_id), num(tid(block, pct_id), dec)
        if n and p is not None and n not in seen:
            seen.add(n); out.append([n, round(p, 2)])
    return out


def top_n(lst, k=5):
    """Primi k più un «Altri» con il resto, come nelle ripartizioni di index.html."""
    head = lst[:k]
    rest = round(100 - sum(x[1] for x in head), 1)
    return head + ([["Altri", rest]] if rest >= 0.5 and len(lst) > k else [])


def parse(isin):
    out = {}
    h, url = page(isin, "en")
    ter = num(tid(h, "tl_etf-basics_value_ter"))
    if ter is not None and 0 <= ter < 3:
        out["ter"] = ter
    m = re.search(r'etf-basics_label_fund-size".*?(?:EUR|USD|GBP|CHF)\s*([\d.,]+)\s*(m|bn)', h, re.S)
    if m:
        v = num(m.group(1))
        out["aum"] = round(v * (1000 if m.group(2) == "bn" else 1))
    rep, how = (tid(h, "tl_etf-basics_value_replication") or ""), (tid(h, "tl_etf-basics_value_replication-method") or "")
    if rep:
        out["repl"] = "Sintetica" if re.search(r"synth|swap", rep + how, re.I) else "Fisica a campione" if re.search(r"sampl", how, re.I) else "Fisica completa" if re.search(r"full", how, re.I) else "Fisica"
    pol = tid(h, "tl_etf-basics_value_distribution-policy") or ""
    if pol:
        out["dist"] = "Accumulazione" if re.search(r"accum", pol, re.I) else "Distribuzione" if re.search(r"distrib", pol, re.I) else None
    d = tid(h, "tl_etf-basics_value_launch-date") or ""
    m = re.search(r"(\d{1,2}) (%s) (\d{4})" % "|".join(MONTHS), d)
    if m:
        out["inception"] = f"{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
    cur = tid(h, "tl_etf-basics_value_fund-currency")
    if cur and re.fullmatch(r"[A-Z]{3}", cur):
        out["cur"] = cur
    idx = tid(h, "tl_etf-basics_value_index-name")
    if idx:
        out["index"] = idx.replace("®", "").strip()
    n = num(tid(h, "tl_etf-holdings_top-holdings_count"))
    if n:
        out["n"] = int(n)
    top = rows(h, "etf-holdings_top-holdings_row", "tl_etf-holdings_top-holdings_link_name", "tl_etf-holdings_top-holdings_value_percentage", ".")
    if top:
        out["top"] = top[:10]
    m = re.search(r"\d{2}/\d{2}/\d{4}", tid(h, "tl_etf-holdings_reference-date") or "")
    if m:
        out["holdingsDate"] = m.group(0)
    dom = tid(h, "tl_etf-basics_value_domicile-country")
    if dom:
        out["domEn"] = dom
    out["source"] = url
    time.sleep(1)
    hi, urli = page(isin, "it")
    countries = rows(hi, "etf-holdings_countries_row", "tl_etf-holdings_countries_value_name", "tl_etf-holdings_countries_value_percentage", ",")
    sectors = rows(hi, "etf-holdings_sectors_row", "tl_etf-holdings_sectors_value_name", "tl_etf-holdings_sectors_value_percentage", ",")
    if countries:
        out["countries"] = top_n(countries)
    if sectors:
        out["sectors"] = top_n(sectors)
    dom_it = tid(hi, "tl_etf-basics_value_domicile-country")
    if dom_it:
        out["dom"] = dom_it
    out["sourceIt"] = urli
    return out


def extra_targets():
    """ISIN monitorati oltre ai 14 di prices.js: watchlist.txt più i primi per patrimonio del catalogo (la stessa scelta di fetch_series.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fetch_series as fs
    cat = fs.catalog()
    top = [i for i, _ in sorted(cat.items(), key=lambda kv: -kv[1]["aum"]) if i not in ISINS][:150]
    return [i for i in dict.fromkeys(fs.watchlist() + top) if i not in ISINS]


def run_extra(missing_only, only=None):
    """Scrive data/d/ISIN.js (indice, titoli principali, paesi, settori) per gli ETF monitorati."""
    out = Path(__file__).resolve().parent.parent / "data" / "d"
    out.mkdir(parents=True, exist_ok=True)
    targets = [i for i in only if i not in ISINS] if only else extra_targets()
    todo = [i for i in targets if not (missing_only and (out / f"{i}.js").exists())]
    print(f"Dettagli da scaricare: {len(todo)}")
    deadline = time.time() + 5 * 3600
    ok = 0
    for n, isin in enumerate(todo, 1):
        if time.time() > deadline:
            print("Tempo esaurito: riprendo alla prossima esecuzione"); break
        try:
            d = parse(isin)
            body = {k: d[k] for k in ("index", "n", "top", "countries", "sectors", "holdingsDate", "source") if k in d}
            if not any(k in body for k in ("index", "top", "countries", "sectors")):
                print(f"[{n}/{len(todo)}] {isin}: nessun dato"); continue
            tmp = out / f"{isin}.tmp"
            tmp.write_text(f'window.DX=window.DX||{{}};window.DX["{isin}"]=' + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
            tmp.replace(out / f"{isin}.js")
            ok += 1
            print(f"[{n}/{len(todo)}] {isin}: indice {body.get('index')}, titoli {len(body.get('top', []))}, paesi {len(body.get('countries', []))}, settori {len(body.get('sectors', []))}")
        except Exception as e:
            print(f"[{n}/{len(todo)}] {isin}: errore {e}")
        time.sleep(1.5)
    print(f"Scritti {ok} file in {out}")


def main():
    args = sys.argv[1:]
    if "--extra" in args:
        only = [i for i in args[args.index("--isins") + 1].replace(" ", "").upper().split(",") if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", i)] if "--isins" in args else None
        return run_extra("--missing" in args, only)
    only = set(args[args.index("--isins") + 1].split(",")) if "--isins" in args else None
    path = Path(__file__).resolve().parent.parent / "etfdata.js"
    data = {}
    for isin in ISINS:
        if only and isin not in only:
            continue
        try:
            d = parse(isin)
            data[isin] = d
            print(isin, "ok:", ", ".join(k for k in d if not k.startswith("source")), "| TER", d.get("ter"), "AUM", d.get("aum"), "inizio", d.get("inception"), "repl", d.get("repl"), "dist", d.get("dist"), "dom", d.get("dom"), "titoli", d.get("n"), "paesi", len(d.get("countries", [])), "settori", len(d.get("sectors", [])))
        except Exception as e:
            print(isin, "errore", e)
        time.sleep(1.5)
    if not data:
        sys.exit("Nessun dato scaricato: etfdata.js non aggiornato")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("window.ETFDATA=" + json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "justETF", "etfs": data}, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    tmp.replace(path)
    print(f"Scritto {path} ({len(data)} ETF su {len(ISINS)})")


if __name__ == "__main__":
    main()
