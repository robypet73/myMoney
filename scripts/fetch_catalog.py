#!/usr/bin/env python3
"""Scarica l'elenco completo degli ETF (tutto l'universo quotato in Europa, ~5.000) dallo screener di justETF e scrive catalog.js.

Solo libreria standard:
    python scripts/fetch_catalog.py

Per ogni ETF: nome, ISIN, ticker, valuta, patrimonio, TER, dividendi, replica, domicilio, lancio, numero di titoli,
rendimenti (1 settimana … 5 anni, da inizio anno, in EUR), volatilità, max drawdown. Categoria e area si ricavano
con gli stessi filtri dello screener. Sono i dati che justETF mostra a ogni visitatore: poche richieste a pagine da 500.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from datetime import datetime, timezone
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
PAGE = "https://www.justetf.com/en/search.html?search=ETFS"
CALL = "https://www.justetf.com/en/search.html?0-1.0-container-tabsContentContainer-tabsContentRepeater-1-container-content-etfsTablePanel&search=ETFS&_wicket=1"
COLS = [["", "selectCheckbox"], ["name", "name"], ["", "sparkline"], ["fundCurrency", "fundCurrency"], ["fundSize", "fundSize"], ["ter", "ter"], ["", "bullet"],
        ["weekReturnCUR", "weekReturn"], ["monthReturnCUR", "monthReturn"], ["threeMonthReturnCUR", "threeMonthReturn"], ["sixMonthReturnCUR", "sixMonthReturn"],
        ["yearReturnCUR", "yearReturn"], ["threeYearReturnCUR", "threeYearReturn"], ["fiveYearReturnCUR", "fiveYearReturn"], ["ytdReturnCUR", "ytdReturn"],
        ["yearReturn1CUR", "yearReturn1"], ["yearReturn2CUR", "yearReturn2"], ["yearReturn3CUR", "yearReturn3"], ["yearReturn4CUR", "yearReturn4"],
        ["yearVolatilityCUR", "yearVolatility"], ["threeYearVolatilityCUR", "threeYearVolatility"], ["fiveYearVolatilityCUR", "fiveYearVolatility"],
        ["yearReturnPerRiskCUR", "yearReturnPerRisk"], ["threeYearReturnPerRiskCUR", "threeYearReturnPerRisk"], ["fiveYearReturnPerRiskCUR", "fiveYearReturnPerRisk"],
        ["yearMaxDrawdownCUR", "yearMaxDrawdown"], ["threeYearMaxDrawdownCUR", "threeYearMaxDrawdown"], ["fiveYearMaxDrawdownCUR", "fiveYearMaxDrawdown"],
        ["maxDrawdownCUR", "maxDrawdown"], ["inceptionDate", "inceptionDate"], ["distributionPolicy", "distributionPolicy"], ["sustainable", "sustainable"],
        ["numberOfHoldings", "numberOfHoldings"], ["currentDividendYield", "currentDividendYield"], ["yearDividendYield", "yearDividendYield"],
        ["domicileCountry", "domicileCountry"], ["replicationMethod", "replicationMethod"], ["savingsPlanReady", "savingsPlanReady"],
        ["hasSecuritiesLending", "hasSecuritiesLending"], ["isin", "isin"], ["ticker", "ticker"], ["wkn", "wkn"], ["valorNumber", "valorNumber"], ["", "addButton"]]
ASSET = {"class-equity": "Azionario", "class-bonds": "Obbligazionario", "class-commodities": "Materie prime", "class-preciousMetals": "Materie prime",
         "class-realEstate": "Immobiliare", "class-moneyMarket": "Monetario"}
REGION = {"World": "Globale", "Europe": "Europa", "North America": "Nord America", "Emerging Markets": "Mercati emergenti", "Asia Pacific": "Asia-Pacifico",
          "Latin America": "America Latina", "Africa": "Africa"}
COUNTRY = {"Ireland": "Irlanda", "Luxembourg": "Lussemburgo", "France": "Francia", "Germany": "Germania", "Switzerland": "Svizzera", "Netherlands": "Paesi Bassi",
           "United Kingdom": "Regno Unito", "Sweden": "Svezia", "Italy": "Italia", "Spain": "Spagna", "Denmark": "Danimarca", "Finland": "Finlandia",
           "Belgium": "Belgio", "Norway": "Norvegia", "Austria": "Austria", "Jersey": "Jersey", "Liechtenstein": "Liechtenstein", "Cayman Islands": "Isole Cayman",
           "Canada": "Canada", "United States": "Stati Uniti", "Poland": "Polonia", "Hungary": "Ungheria", "Greece": "Grecia", "Portugal": "Portogallo"}
PROVIDERS2 = ["Global X", "Legal & General", "State Street", "BNP Paribas", "Goldman Sachs", "First Trust", "Franklin Templeton", "Morgan Stanley", "Bank of America",
              "Royal London", "Vontobel", "Tabula", "Man", "BlackRock", "SPDR", "Source", "UBS", "Credit Suisse", "Deutsche Bank", "Lyxor", "Amundi", "Xtrackers", "HANetf",
              "WisdomTree", "VanEck", "Invesco", "iShares", "Vanguard", "HSBC", "JPMorgan", "Fidelity", "Ossiam", "Expat", "Deka", "Comstage", "Leverage Shares", "GraniteShares"]


# Area per gli ETF che i filtri di justETF non classificano (paese singolo): si deduce dal nome del fondo o dell'indice.
GUESS = [("Stati Uniti", r"S&P ?(500|400|600)|nasdaq|\bUSA?\b|U\.S\.|United States|russell|dow jones|treasur|\bTIPS\b|\$"), ("Giappone", r"japan|nikkei|topix|\bJPX\b"),
         ("Cina", r"china|CSI ?300|hang seng|chinese"), ("India", r"\bindia|nifty"), ("Regno Unito", r"FTSE ?(100|250)\b|\bUK\b|united kingdom|\bgilt|sterling"),
         ("Germania", r"\bDAX\b|germany|MDAX|bund"), ("Svizzera", r"swiss|switzerland|\bSMI\b|\bSPI\b"), ("Eurozona", r"euro ?stoxx|eurozone|\bEMU\b|euro area|euro (govt|gov|corp|aggregate|inflation|high)|EUR (govt|gov|corp)|€"),
         ("Italia", r"italy|italian|\bMIB\b|\bBTP\b"), ("Francia", r"france|\bCAC\b|\bOAT\b"), ("Spagna", r"spain|\bIBEX\b"), ("Corea del Sud", r"korea"),
         ("Taiwan", r"taiwan"), ("Brasile", r"brazil"), ("Canada", r"canad"), ("Australia", r"australia"), ("Europa", r"europe|stoxx|\bEU\b"),
         ("Mercati emergenti", r"emerging|\bEM\b"), ("Asia-Pacifico", r"asia|pacific|apac"), ("Globale", r"world|global|all[- ]country|\bACWI\b|international|developed")]


def guess_region(name):
    for label, rx in GUESS:
        if re.search(rx, name, re.I):
            return label
    return None


class Je:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.open(urllib.request.Request(PAGE, headers={"User-Agent": UA, "Accept-Language": "en-GB"}), timeout=60).read()

    def post(self, start, length, params="search=ETFS&query="):
        q = [("draw", "1")]
        for i, (d, n) in enumerate(COLS):
            q += [(f"columns[{i}][data]", d), (f"columns[{i}][name]", n), (f"columns[{i}][searchable]", "true"), (f"columns[{i}][orderable]", "true" if d else "false"),
                  (f"columns[{i}][search][value]", ""), (f"columns[{i}][search][regex]", "false")]
        q += [("order[0][column]", "4"), ("order[0][dir]", "desc"), ("start", str(start)), ("length", str(length)), ("search[value]", ""), ("search[regex]", "false"),
              ("ajaxsortOrder", "desc"), ("ajaxsortField", "fundSize"), ("lang", "en"), ("country", "XE"), ("defaultCurrency", "EUR"), ("universeType", "private"), ("etfsParams", params)]
        req = urllib.request.Request(CALL, data=urllib.parse.urlencode(q).encode(), headers={
            "User-Agent": UA, "Accept-Language": "en-GB", "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": PAGE, "Wicket-Ajax": "true", "Wicket-Ajax-BaseURL": "en/search.html?search=ETFS"})
        for k in range(3):
            try:
                return json.loads(self.op.open(req, timeout=90).read())
            except Exception as e:
                if k == 2:
                    raise
                print("  nuovo tentativo:", e); time.sleep(5)

    def all(self, params="search=ETFS&query=", step=500):
        out, start, total = [], 0, None
        while total is None or start < total:
            j = self.post(start, step, params)
            total = j["recordsFiltered"]
            out += j["data"]
            start += step
            time.sleep(1)
        return out, total


def f(s, pct=True):
    """'18.70%' / '139,790' / '-' -> numero oppure None."""
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def date(s):
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{2,4})", str(s or ""))
    if not m:
        return None
    y = int(m.group(3)); y = y + (2000 if y < 70 else 1900) if y < 100 else y
    return f"{y}-{m.group(2)}-{m.group(1)}"


def provider(name):
    for p in PROVIDERS2:
        if name.lower().startswith(p.lower()):
            return p
    return name.split()[0] if name else None


def repl(s):
    s = (s or "").lower()
    return "Sintetica" if "swap" in s or "synth" in s else "Fisica a campione" if "sampl" in s else "Fisica completa" if "full" in s else "Fisica" if s else None


def main():
    je = Je()
    rows, total = je.all()
    print(f"Elenco: {len(rows)} ETF su {total}")
    if len(rows) < 1000:
        sys.exit("Elenco troppo corto: catalog.js non aggiornato")
    asset, region = {}, {}
    for key, label in ASSET.items():
        r, n = je.all(f"search=ETFS&query=&assetClass={key}")
        if n < total:  # un filtro non riconosciuto restituirebbe tutto l'elenco
            for x in r:
                asset[x["isin"]] = label
        print(" ", key, n)
    for key, label in REGION.items():
        r, n = je.all(f"search=ETFS&query=&region={urllib.parse.quote(key)}")
        if n < total:
            for x in r:
                region.setdefault(x["isin"], label)
        print(" ", key, n)
    cols = ["isin", "name", "ticker", "cur", "aum", "ter", "dist", "repl", "dom", "inc", "n", "sust", "div", "rw", "r1m", "r3m", "r6m", "r1", "r3", "r5", "ytd", "vol1", "vol3", "vol5", "dd1", "dd", "sh1", "prov", "asset", "region"]
    out, seen = [], set()
    for x in rows:
        isin = x.get("isin")
        if not isin or isin in seen:
            continue
        seen.add(isin)
        name = x.get("name") or ""
        pol = x.get("distributionPolicy") or ""
        out.append([isin, name, x.get("ticker") or None, x.get("fundCurrency") or None, f(x.get("fundSize")), f(x.get("ter")),
                    "Accumulazione" if re.search("accum|capital", pol, re.I) else "Distribuzione" if re.search("distrib", pol, re.I) else None,
                    repl(x.get("replicationMethod")), COUNTRY.get(x.get("domicileCountry"), x.get("domicileCountry") or None), date(x.get("inceptionDate")),
                    int(f(x.get("numberOfHoldings"))) if f(x.get("numberOfHoldings")) else None, x.get("sustainable") == "Yes", f(x.get("currentDividendYield")),
                    f(x.get("weekReturnCUR")), f(x.get("monthReturnCUR")), f(x.get("threeMonthReturnCUR")), f(x.get("sixMonthReturnCUR")), f(x.get("yearReturnCUR")),
                    f(x.get("threeYearReturnCUR")), f(x.get("fiveYearReturnCUR")), f(x.get("ytdReturnCUR")), f(x.get("yearVolatilityCUR")), f(x.get("threeYearVolatilityCUR")),
                    f(x.get("fiveYearVolatilityCUR")), f(x.get("yearMaxDrawdownCUR")), f(x.get("maxDrawdownCUR")), f(x.get("yearReturnPerRiskCUR")), provider(name),
                    asset.get(isin) or ("Criptovalute" if re.search(r"bitcoin|crypto|ether|solana|\bXRP\b|blockchain|digital asset", name, re.I) else "Altro"), region.get(isin) or guess_region(name) or ("Globale" if asset.get(isin) in ("Materie prime", "Monetario") or re.search(r"bitcoin|crypto|ether|solana|\bXRP\b|digital asset", name, re.I) else "Altro")])
    path = Path(__file__).resolve().parent.parent / "catalog.js"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("window.CATALOG=" + json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "justETF", "cols": cols, "rows": out},
                                                  ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    tmp.replace(path)
    print(f"Scritto {path} ({len(out)} ETF, {path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
