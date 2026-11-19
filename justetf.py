"""Client di justETF (solo urllib): elenco di tutti gli ETF con ISIN e caratteristiche (screener, chiamata dati JSON). Non legge pagine web."""
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from yahoo import Cancelled

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
PAGE = "https://www.justetf.com/en/search.html?search=ETFS"
CALL = "https://www.justetf.com/en/search.html?0-1.0-container-tabsContentContainer-tabsContentRepeater-1-container-content-etfsTablePanel&search=ETFS&_wicket=1"
COLS = ["", "name", "", "fundCurrency", "fundSize", "ter", "", "weekReturnCUR", "monthReturnCUR", "threeMonthReturnCUR", "sixMonthReturnCUR", "yearReturnCUR", "threeYearReturnCUR",
        "fiveYearReturnCUR", "ytdReturnCUR", "yearReturn1CUR", "yearReturn2CUR", "yearReturn3CUR", "yearReturn4CUR", "yearVolatilityCUR", "threeYearVolatilityCUR", "fiveYearVolatilityCUR",
        "yearReturnPerRiskCUR", "threeYearReturnPerRiskCUR", "fiveYearReturnPerRiskCUR", "yearMaxDrawdownCUR", "threeYearMaxDrawdownCUR", "fiveYearMaxDrawdownCUR", "maxDrawdownCUR",
        "inceptionDate", "distributionPolicy", "sustainable", "numberOfHoldings", "currentDividendYield", "yearDividendYield", "domicileCountry", "replicationMethod", "savingsPlanReady",
        "hasSecuritiesLending", "isin", "ticker", "wkn", "valorNumber", ""]
ASSET = {"class-equity": "Azionario", "class-bonds": "Obbligazionario", "class-commodities": "Materie prime", "class-preciousMetals": "Materie prime",
         "class-realEstate": "Immobiliare", "class-moneyMarket": "Monetario"}
REGION = {"World": "Mondo", "Europe": "Europa", "North America": "USA", "Emerging Markets": "Mercati emergenti", "Asia Pacific": "Asia-Pacifico", "Latin America": "America Latina", "Africa": "Africa"}
COUNTRY = {"Ireland": "Irlanda", "Luxembourg": "Lussemburgo", "France": "Francia", "Germany": "Germania", "Switzerland": "Svizzera", "Netherlands": "Paesi Bassi",
           "United Kingdom": "Regno Unito", "Sweden": "Svezia", "Italy": "Italia", "Spain": "Spagna", "Denmark": "Danimarca", "Finland": "Finlandia", "Belgium": "Belgio",
           "Norway": "Norvegia", "Austria": "Austria", "Jersey": "Jersey", "Liechtenstein": "Liechtenstein", "Cayman Islands": "Isole Cayman", "Canada": "Canada",
           "United States": "Stati Uniti", "Poland": "Polonia", "Hungary": "Ungheria", "Greece": "Grecia", "Portugal": "Portogallo"}


def f(s):
    """'18.70%' / '139,790' / '-' -> numero oppure None."""
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s if s is not None else ""))
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def ann(r, years):
    """Rendimento cumulato % -> annuo %."""
    return None if r is None or r <= -100 else round(((1 + r / 100) ** (1 / years) - 1) * 100, 2)


def date(s):
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{2,4})", str(s or ""))
    if not m:
        return None
    y = int(m.group(3))
    y = y + (2000 if y < 70 else 1900) if y < 100 else y
    return f"{y}-{m.group(2)}-{m.group(1)}"


def repl(s):
    s = (s or "").lower()
    return "Sintetica" if "swap" in s or "synth" in s else "Fisica a campione" if "sampl" in s else "Fisica completa" if "full" in s else "Fisica" if s else None


class JustETF:
    def __init__(self, cancel=None, log=None):
        self.cancel, self.log = cancel or (lambda: False), log or (lambda m: None)
        self.op = None

    def sleep(self, sec):
        end = time.time() + sec
        while time.time() < end:
            if self.cancel():
                raise Cancelled()
            time.sleep(min(0.2, max(0, end - time.time())))

    def _open(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.open(urllib.request.Request(PAGE, headers={"User-Agent": UA, "Accept-Language": "en-GB"}), timeout=60).read()

    def _post(self, start, length, params):
        if self.op is None:
            self._open()
        q = [("draw", "1")]
        for i, d in enumerate(COLS):
            q += [(f"columns[{i}][data]", d), (f"columns[{i}][name]", d or ""), (f"columns[{i}][searchable]", "true"), (f"columns[{i}][orderable]", "true" if d else "false"),
                  (f"columns[{i}][search][value]", ""), (f"columns[{i}][search][regex]", "false")]
        q += [("order[0][column]", "4"), ("order[0][dir]", "desc"), ("start", str(start)), ("length", str(length)), ("search[value]", ""), ("search[regex]", "false"),
              ("ajaxsortOrder", "desc"), ("ajaxsortField", "fundSize"), ("lang", "en"), ("country", "XE"), ("defaultCurrency", "EUR"), ("universeType", "private"), ("etfsParams", params)]
        req = urllib.request.Request(CALL, data=urllib.parse.urlencode(q).encode(), headers={
            "User-Agent": UA, "Accept-Language": "en-GB", "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": PAGE, "Wicket-Ajax": "true", "Wicket-Ajax-BaseURL": "en/search.html?search=ETFS"})
        for k in range(4):
            if self.cancel():
                raise Cancelled()
            try:
                return json.loads(self.op.open(req, timeout=90).read())
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                if k == 3:
                    raise RuntimeError(f"justETF non risponde ({e})")
                self.log(f"justETF: nuovo tentativo ({e})")
                self.sleep(5 * (k + 1))
                self.op = None

    def _all(self, params="search=ETFS&query=", step=500, progress=None):
        out, start, total = [], 0, None
        while total is None or start < total:
            j = self._post(start, step, params)
            total = j["recordsFiltered"]
            out += j["data"]
            start += step
            if progress:
                progress(min(start, total), total)
            self.sleep(1)
        return out, total

    @staticmethod
    def parse_row(x):
        pol = x.get("distributionPolicy") or ""
        return {"isin": x.get("isin"), "name": x.get("name"), "ticker": x.get("ticker") or None, "cur": (re.sub(r"<.*", "", x.get("fundCurrency") or "").strip() or None), "aum": f(x.get("fundSize")), "ter": f(x.get("ter")),
                "dist": "Accumulazione" if re.search("accum|capital", pol, re.I) else "Distribuzione" if re.search("distrib", pol, re.I) else None,
                "repl": repl(x.get("replicationMethod")), "dom": COUNTRY.get(x.get("domicileCountry"), x.get("domicileCountry") or None), "inc": date(x.get("inceptionDate")),
                "n": int(f(x.get("numberOfHoldings"))) if f(x.get("numberOfHoldings")) else None, "sust": 1 if x.get("sustainable") == "Yes" else 0, "div": f(x.get("currentDividendYield")),
                "r1": f(x.get("yearReturnCUR")), "r3": ann(f(x.get("threeYearReturnCUR")), 3), "r5": ann(f(x.get("fiveYearReturnCUR")), 5), "vol1": f(x.get("yearVolatilityCUR")),
                "vol3": f(x.get("threeYearVolatilityCUR")), "dd": f(x.get("maxDrawdownCUR"))}

    def by_isin(self, isin):
        """La riga justETF di un solo ISIN (una chiamata), o None."""
        rows_, _ = self._all(f"search=ETFS&query={isin}", step=10)
        for x in rows_:
            if x.get("isin") == isin:
                return self.parse_row(x)
        return None

    def catalog(self, progress=None):
        """Tutti gli ETF dello screener: lista di dict con i campi dello screener più asset_class e region dai filtri."""
        rows_, total = self._all(progress=progress)
        if len(rows_) < 1000:
            raise RuntimeError("Elenco justETF troppo corto")
        asset, region = {}, {}
        for key, label in ASSET.items():
            r, n = self._all(f"search=ETFS&query=&assetClass={key}")
            if n < total:  # un filtro non riconosciuto restituirebbe tutto l'elenco
                asset.update({x["isin"]: label for x in r})
        for key, label in REGION.items():
            r, n = self._all(f"search=ETFS&query=&region={urllib.parse.quote(key)}")
            if n < total:
                for x in r:
                    region.setdefault(x["isin"], label)
        out, seen = [], set()
        for x in rows_:
            isin = x.get("isin")
            if not isin or isin in seen:
                continue
            seen.add(isin)
            row = self.parse_row(x)
            row["asset"], row["region"] = asset.get(isin), region.get(isin)
            out.append(row)
        return out
