"""fonti: scarica da justETF i dati di un titolo (solo libreria standard).

- profilo(isin): caratteristiche (nome, TER, patrimonio, replica, domicilio…) e composizione (primi titoli, paesi, settori) dalla pagina del fondo;
- serie(isin): prezzi giornalieri in euro, solo giorni feriali;
- fondo_da_isin(isin): il record completo che la pagina del portafoglio si aspetta, più la serie dei prezzi.

Le funzioni di lettura del testo (parse_profilo, costruisci_fondo) non fanno rete: si provano con una pagina salvata.
"""
import datetime
import html as _html
import json
import re
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
PROFILO = "https://www.justetf.com/en/etf-profile.html?isin={isin}"
GRAFICO = ("https://www.justetf.com/api/etfs/{isin}/performance-chart?locale=en&currency=EUR&valuesType=MARKET_VALUE"
           "&reduceData=false&includeDividends=false&features=DIVIDENDS&dateFrom={dal}&dateTo={al}")
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def isin_valido(s):
    """Forma dell'ISIN e cifra di controllo (Luhn sulle lettere espanse in numeri)."""
    if not isinstance(s, str) or not ISIN_RE.match(s):
        return False
    cifre = "".join(str(int(c, 36)) for c in s)
    tot = 0
    for i, c in enumerate(reversed(cifre)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        tot += d
    return tot % 10 == 0


def scarica(url, json_=False, tentativi=4, pausa=3):
    ultimo = None
    for k in range(tentativi):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB"})
            corpo = urllib.request.urlopen(req, timeout=60).read()
            return json.loads(corpo) if json_ else corpo.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code == 404:
                raise LookupError("titolo non trovato su justETF")
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            ultimo = e
        time.sleep(pausa * (k + 1))
    raise RuntimeError(f"justETF non risponde ({ultimo})")


# ---- traduzioni
PAESI = {"United States": "Stati Uniti", "Japan": "Giappone", "United Kingdom": "Regno Unito", "Canada": "Canada", "Switzerland": "Svizzera", "France": "Francia",
         "Germany": "Germania", "Australia": "Australia", "Netherlands": "Paesi Bassi", "Sweden": "Svezia", "Denmark": "Danimarca", "Italy": "Italia", "Spain": "Spagna",
         "Hong Kong": "Hong Kong", "Singapore": "Singapore", "Finland": "Finlandia", "Belgium": "Belgio", "Norway": "Norvegia", "Israel": "Israele", "Ireland": "Irlanda",
         "Austria": "Austria", "Portugal": "Portogallo", "New Zealand": "Nuova Zelanda", "Luxembourg": "Lussemburgo", "Greece": "Grecia", "Poland": "Polonia",
         "China": "Cina", "Taiwan": "Taiwan", "India": "India", "South Korea": "Corea del Sud", "Korea": "Corea del Sud", "Brazil": "Brasile", "Saudi Arabia": "Arabia Saudita",
         "South Africa": "Sudafrica", "Mexico": "Messico", "Indonesia": "Indonesia", "Thailand": "Thailandia", "Malaysia": "Malesia", "Turkey": "Turchia", "Qatar": "Qatar",
         "United Arab Emirates": "Emirati Arabi Uniti", "Kuwait": "Kuwait", "Philippines": "Filippine", "Chile": "Cile", "Hungary": "Ungheria", "Czech Republic": "Repubblica Ceca",
         "Colombia": "Colombia", "Peru": "Perù", "Egypt": "Egitto", "Other": "Altri paesi", "Others": "Altri paesi", "Supranational": "Sovranazionali", "Cayman Islands": "Isole Cayman",
         "Jersey": "Jersey", "Bermuda": "Bermuda", "Slovakia": "Slovacchia", "Slovenia": "Slovenia", "Estonia": "Estonia", "Latvia": "Lettonia", "Lithuania": "Lituania",
         "Croatia": "Croazia", "Malta": "Malta", "Cyprus": "Cipro", "Romania": "Romania", "Vietnam": "Vietnam", "Argentina": "Argentina", "Russia": "Russia"}
EURO = {"Germany", "France", "Italy", "Spain", "Netherlands", "Belgium", "Austria", "Finland", "Ireland", "Portugal", "Greece", "Luxembourg", "Slovakia", "Slovenia", "Estonia",
        "Latvia", "Lithuania", "Croatia", "Malta", "Cyprus"}
EUROPA_NO_EURO = {"United Kingdom", "Switzerland", "Sweden", "Norway", "Denmark", "Jersey"}
EMERGENTI = {"China", "Taiwan", "India", "South Korea", "Korea", "Brazil", "Saudi Arabia", "South Africa", "Mexico", "Indonesia", "Thailand", "Malaysia", "Turkey", "Qatar",
             "United Arab Emirates", "Kuwait", "Philippines", "Chile", "Hungary", "Czech Republic", "Poland", "Colombia", "Peru", "Egypt", "Vietnam", "Argentina", "Russia", "Romania"}
ALTRI_SVILUPPATI = {"Canada", "Australia", "Hong Kong", "Singapore", "Israel", "New Zealand", "Cayman Islands", "Bermuda"}
VALUTE = {"United States": "USD", "Japan": "JPY", "United Kingdom": "GBP", "Canada": "CAD", "Switzerland": "CHF", "Australia": "AUD", "Sweden": "SEK", "Denmark": "DKK",
          "Norway": "NOK", "Hong Kong": "HKD", "Singapore": "SGD", "Israel": "ILS", "New Zealand": "NZD", "China": "CNY", "Taiwan": "TWD", "India": "INR", "South Korea": "KRW",
          "Korea": "KRW", "Brazil": "BRL", "Saudi Arabia": "SAR", "South Africa": "ZAR", "Mexico": "MXN", "Indonesia": "IDR", "Thailand": "THB", "Malaysia": "MYR", "Turkey": "TRY",
          "Poland": "PLN", "Hungary": "HUF", "Czech Republic": "CZK", "Qatar": "QAR", "United Arab Emirates": "AED", "Kuwait": "KWD", "Philippines": "PHP", "Chile": "CLP"}
SETTORI = {"Technology": "Tecnologia", "Information Technology": "Tecnologia", "Consumer Discretionary": "Beni voluttuari", "Consumer Cyclical": "Beni voluttuari",
           "Communication Services": "Comunicazioni", "Telecommunication": "Comunicazioni", "Telecommunications": "Comunicazioni", "Health Care": "Salute", "Healthcare": "Salute",
           "Financials": "Finanza", "Financial Services": "Finanza", "Energy": "Energia", "Consumer Staples": "Beni di prima necessità", "Consumer Defensive": "Beni di prima necessità",
           "Industrials": "Industria", "Basic Materials": "Materiali", "Materials": "Materiali", "Utilities": "Pubblica utilità", "Real Estate": "Immobiliare", "Other": "Altro"}
ISO2 = {"US": "United States", "JP": "Japan", "GB": "United Kingdom", "CA": "Canada", "CH": "Switzerland", "FR": "France", "DE": "Germany", "AU": "Australia", "NL": "Netherlands",
        "SE": "Sweden", "DK": "Denmark", "IT": "Italy", "ES": "Spain", "HK": "Hong Kong", "SG": "Singapore", "FI": "Finland", "BE": "Belgium", "NO": "Norway", "IE": "Ireland",
        "TW": "Taiwan", "CN": "China", "KR": "South Korea", "IN": "India", "BR": "Brazil", "ZA": "South Africa", "MX": "Mexico", "SA": "Saudi Arabia", "IL": "Israel", "AT": "Austria",
        "PT": "Portugal", "LU": "Luxembourg", "NZ": "New Zealand", "PL": "Poland", "ID": "Indonesia", "TH": "Thailand", "MY": "Malaysia", "TR": "Turkey", "GR": "Greece"}
MESI = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def _testo(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _campo(t, testid):
    m = re.search(r'data-testid="%s"[^>]*>(.*?)</' % re.escape(testid), t, re.S)
    return _testo(m.group(1)) if m else ""


def _num(s):
    m = re.search(r"-?\d[\d,]*\.?\d*", s or "")
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def _data(s):
    m = re.match(r"(\d{1,2}) (\w+) (\d{4})", s or "")
    return f"{m.group(3)}-{MESI[m.group(2)]:02d}-{int(m.group(1)):02d}" if m and m.group(2) in MESI else None


def _righe(t, prefisso):
    """[(nome, peso 0-1, isin o None)] delle righe di una tabella della pagina (primi titoli, paesi, settori)."""
    out = []
    for blocco in re.findall(r'<tr data-testid="etf-holdings_%s_row">(.*?)</tr>' % re.escape(prefisso), t, re.S):
        peso = _num(_campo(blocco, f"tl_etf-holdings_{prefisso}_value_percentage"))
        nome = _campo(blocco, f"tl_etf-holdings_{prefisso}_value_name")
        isin = None
        if not nome:
            m = re.search(r'href="([^"]*)"[^>]*title="([^"]*)"', blocco)
            if m:
                nome = _html.unescape(m.group(2))
                mi = re.search(r"/([A-Z]{2}[A-Z0-9]{9}\d)(?:[/?]|$)", m.group(1))
                isin = mi.group(1) if mi else None
        if nome and peso is not None:
            out.append((nome, peso / 100, isin))
    return out


def parse_profilo(t, isin):
    """Dati grezzi della pagina del fondo: caratteristiche e le tre tabelle di composizione."""
    nome = _campo(t, "etf-profile-header_etf-name") or _testo((re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S) or [None, ""])[1])
    if not nome:
        raise LookupError(f"{isin}: pagina del fondo non riconosciuta")
    repl = _campo(t, "tl_etf-basics_value_replication-method") or _campo(t, "tl_etf-basics_value_replication")
    r = repl.lower()
    repl = "Sintetica" if "swap" in r or "synth" in r else "Fisica a campione" if "sampl" in r else "Fisica completa" if "full" in r else "Fisica" if "phys" in r else (repl or None)
    return {"isin": isin, "name": nome, "ticker": _campo(t, "etf-profile-header_identifier-button-ticker") or None, "ter": _num(_campo(t, "tl_etf-basics_value_ter")),
            "aum": _num(_campo(t, "etf-profile-header_fund-size-value-wrapper")), "focus": _campo(t, "tl_etf-basics_value_investment-focus"), "repl": repl,
            "dom": _campo(t, "tl_etf-basics_value_domicile-country") or None, "emittente": _campo(t, "tl_etf-basics_value_fund-provider") or None,
            "lancio": _data(_campo(t, "tl_etf-basics_value_launch-date")), "valuta": _campo(t, "tl_etf-basics_value_fund-currency") or None,
            "n": int(_num(_campo(t, "etf-profile-header_holdings-value")) or 0) or None, "dist": _campo(t, "tl_etf-basics_value_distribution-policy"),
            "indice": _campo(t, "tl_etf-basics_value_index-name") or None,
            "top": _righe(t, "top-holdings"), "paesi": _righe(t, "countries"), "settori": _righe(t, "sectors")}


# ---- dal profilo al record della pagina
def classe(focus, nome):
    f = (focus or "").split(",")[0].strip().lower()
    if f.startswith("bond") or f.startswith("money"):
        return "Obbligazionario"
    if f.startswith("commod") or f.startswith("precious") or f.startswith("crypto"):
        return "Materie prime"
    return "Azionario"


def _oro(nome, focus):
    return bool(re.search(r"\bgold\b|\boro\b|precious", f"{nome} {focus}", re.I))


def tipo_e_ruolo(cls, focus, nome):
    f, n = (focus or "").lower(), (nome or "").lower()
    if cls == "Obbligazionario":
        tipo = "Obbligazioni · societarie" if re.search(r"corporate|credit|high yield", f + " " + n) else "Obbligazioni · titoli di Stato" if re.search(r"govern|treasur|sovereign|state", f + " " + n) else "Obbligazioni"
        return tipo, "Obbligazioni"
    if cls == "Materie prime":
        return ("Oro", "Oro") if _oro(nome, focus) else ("Materie prime", "Materie prime")
    sec = f.split(",", 1)[1].strip() if "," in f else ""
    if re.search(r"\b(emerging|asia|china|india|latin america|africa|brazil|korea|taiwan)\b", sec + " " + n):
        return "Azioni · emergenti", "Emergenti"
    if sec in ("world", "europe", "north america", "usa", "united states", "developed", "eurozone", "euro area", "global") or re.search(r"\b(world|all[- ]country|global)\b", n) and sec in ("", "world"):
        return "Azioni · mondo ed Europa", "Nucleo"
    return "Azioni · settoriali", "Satellite"


def _chiave(nome):
    return re.sub(r"[^a-z0-9]+", " ", nome.lower()).strip()


def costruisci_mix(p, cls):
    paesi_en = [(n, w) for n, w, _ in p["paesi"]]
    paesi = [[PAESI.get(n, n), round(w, 4)] for n, w in paesi_en if n not in ("Other", "Others")][:8]
    if cls == "Materie prime":
        oro = _oro(p["name"], p["focus"])
        return {"aree": {"Oro" if oro else "Materie prime": 1.0}, "settori": {}, "valute": {("Oro" if oro else "Materie prime") + " (prezzato in USD)": 1.0}, "paesi": [], "top": [], "nt": 0}
    aree, valute = {}, {}
    for n, w in paesi_en:
        a = ("Stati Uniti" if n == "United States" else "Area euro" if n in EURO else "Europa fuori dall'euro" if n in EUROPA_NO_EURO else "Giappone" if n == "Japan"
             else "Mercati emergenti" if n in EMERGENTI else "Altri sviluppati" if n in ALTRI_SVILUPPATI else "Altro")
        aree[a] = aree.get(a, 0) + w
        v = "EUR" if n in EURO else VALUTE.get(n, "Altre valute")
        valute[v] = valute.get(v, 0) + w
    if cls == "Obbligazionario":
        valute = {p["valuta"] or "EUR": 1.0}
    for d in (aree, valute):
        resto = 1 - sum(d.values())
        if resto > 0.0005 and d:
            k = "Altro" if d is aree else "Altre valute"
            d[k] = d.get(k, 0) + resto
    settori = {}
    if cls == "Azionario":
        for n, w, _ in p["settori"]:
            k = SETTORI.get(n, "Altro")
            settori[k] = settori.get(k, 0) + w
        resto = 1 - sum(settori.values())
        if settori and resto > 0.0005:
            settori["Altro"] = settori.get("Altro", 0) + resto
    top = []
    if cls == "Azionario":
        for n, w, isin in p["top"]:
            en = ISO2.get((isin or "")[:2])
            top.append([n, PAESI.get(en, en) or "", round(w, 4), _chiave(n)])
    r4 = lambda d: {k: round(v, 4) for k, v in d.items()}
    return {"aree": r4(aree), "settori": r4(settori), "valute": r4(valute), "paesi": paesi if cls != "Materie prime" else [], "top": top, "nt": len(top)}


def costruisci_fondo(p, sigla, peso=0.0):
    """Record di un fondo come lo legge la pagina (senza prezzi): s, sym, isin, name, cls, ruolo, tipo, w, q0, p0, ter, aum, adv, emittente, repl, dom, lancio, valuta, n, mix."""
    cls = classe(p["focus"], p["name"])
    tipo, ruolo = tipo_e_ruolo(cls, p["focus"], p["name"])
    return {"s": sigla, "sym": "", "isin": p["isin"], "name": p["name"], "cls": cls, "ruolo": ruolo, "tipo": tipo, "w": peso, "q0": 0, "p0": 0, "ter": p["ter"], "aum": p["aum"], "adv": None,
            "emittente": p["emittente"], "repl": p["repl"], "dom": p["dom"], "lancio": p["lancio"], "valuta": p["valuta"], "n": p["n"], "mix": costruisci_mix(p, cls)}


def sigla_proposta(p):
    """Sigla breve del titolo: il ticker di justETF, altrimenti le iniziali del nome (senza UCITS, ETF, Acc…)."""
    s = re.sub(r"[^A-Za-z0-9]", "", (p.get("ticker") or "")).upper()
    if s:
        return s[:8]
    parole = [w for w in re.findall(r"[A-Za-z0-9]+", p["name"]) if w.upper() not in ("UCITS", "ETF", "ETC", "ETN", "ACC", "DIST", "EUR", "USD", "ACCUMULATING", "DISTRIBUTING", "C", "D")]
    return ("".join(w[0] for w in parole[:5]).upper()) or re.sub(r"[^A-Z0-9]", "", p["isin"])[-6:]


# ---- rete
def profilo(isin):
    return parse_profilo(scarica(PROFILO.format(isin=isin)), isin)


def serie(isin, dal=None, al=None):
    """[(data ISO, prezzo in euro)] dei soli giorni feriali, dalla più vecchia; il valore di oggi è quello in corso."""
    oggi = datetime.date.today()
    dal = dal or (oggi - datetime.timedelta(days=365 * 10 + 3)).isoformat()
    j = scarica(GRAFICO.format(isin=isin, dal=dal, al=al or oggi.isoformat()), json_=True)
    out = []
    for x in j.get("series") or []:
        v = (x.get("value") or {}).get("raw")
        if v and datetime.date.fromisoformat(x["date"]).weekday() < 5:
            out.append((x["date"], round(float(v), 4)))
    if not out:
        raise LookupError(f"{isin}: nessun prezzo su justETF")
    return out
