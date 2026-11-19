"""Client minimale per Yahoo Finance (solo libreria standard): cookie e crumb, screener, quotazioni, scheda del fondo, storico, cambi.

Yahoo limita le richieste (429): le richieste ritentano con attesa crescente e alternano i due server (query1/query2).
"""
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; myMoney/2.0)"
HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
# codice Yahoo -> nome della borsa
EXCHANGES = {"MIL": "Borsa Italiana", "GER": "Xetra", "PAR": "Euronext Parigi", "AMS": "Euronext Amsterdam", "LSE": "Londra", "EBS": "SIX Svizzera"}


class Cancelled(Exception):
    pass


class NotFound(Exception):
    pass


def num(x):
    """Valore numerico di un campo Yahoo ({"raw": 1.2, "fmt": ...}, numero o vuoto)."""
    if isinstance(x, dict):
        x = x.get("raw")
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


class Yahoo:
    def __init__(self, pause=0.4, cancel=None, log=None, warn=None):
        self.pause, self.cancel, self.log = pause, cancel or (lambda: False), log or (lambda m: None)
        self.warn = warn or (lambda m: None)  # avvisi di scaricamento da mostrare all'utente
        self.crumb = None
        self.opener = None
        self.k = 0  # alterna i server

    # ---- utilità ----
    def sleep(self, sec):
        end = time.time() + sec
        while time.time() < end:
            if self.cancel():
                raise Cancelled()
            time.sleep(min(0.2, max(0, end - time.time())))

    def _new_opener(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.crumb = None

    def _raw(self, url, data=None, headers=None, timeout=40):
        h = {"User-Agent": UA}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
        return self.opener.open(req, timeout=timeout).read()

    def _need_crumb(self):
        if self.crumb:
            return
        if self.opener is None:
            self._new_opener()
        try:
            self._raw("https://fc.yahoo.com")
        except urllib.error.HTTPError:
            pass  # risponde 404 ma imposta il cookie
        except urllib.error.URLError:
            pass
        for k in range(10):
            host = HOSTS[k % 2]
            try:
                self.crumb = self._raw(f"https://{host}/v1/test/getcrumb", timeout=20).decode().strip()
                if self.crumb and "<" not in self.crumb:
                    return
            except urllib.error.HTTPError as e:
                self.log(f"crumb: HTTP {e.code}, riprovo")
            except urllib.error.URLError as e:
                self.log(f"crumb: {e.reason}, riprovo")
            self.sleep(min(10 * (k + 1), 60))
        raise RuntimeError("Yahoo non ha dato il crumb (troppe richieste?): riprova tra qualche minuto")

    def request(self, path, params=None, crumb=False, body=None, tries=8):
        """JSON di una richiesta (GET, o POST con `body`). Solleva NotFound per 404."""
        if self.opener is None:
            self._new_opener()
        last = None
        for k in range(tries):
            if self.cancel():
                raise Cancelled()
            if crumb:
                self._need_crumb()
            q = dict(params or {})
            if crumb:
                q["crumb"] = self.crumb
            self.k += 1
            url = f"https://{HOSTS[self.k % 2]}{path}?{urllib.parse.urlencode(q)}"
            try:
                data = None if body is None else json.dumps(body).encode()
                raw = self._raw(url, data=data, headers={"Content-Type": "application/json"} if body is not None else None)
                time.sleep(self.pause)
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    raise NotFound(path)
                if e.code in (401, 403):
                    self.crumb = None
                    self._new_opener()
                    self.sleep(3)
                elif e.code == 429:
                    self.sleep(min(5 * 2 ** k, 90))
                else:
                    self.sleep(3 * (k + 1))
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                last = e
                self.sleep(3 * (k + 1))
        raise RuntimeError(f"Yahoo non risponde ({last})")

    # ---- elenco dei titoli ----
    def screener(self, exchange, progress=None):
        """Tutti i titoli di tipo ETF di una borsa, 250 per pagina, ordinati per volume. Ritorna la lista dei dati grezzi."""
        out, offset = [], 0
        while True:
            body = {"size": 250, "offset": offset, "sortField": "dayvolume", "sortType": "DESC", "quoteType": "ETF", "userId": "", "userIdType": "guid",
                    "query": {"operator": "eq", "operands": ["exchange", exchange]}}
            res = self.request("/v1/finance/screener", {"lang": "en-US", "region": "US", "formatted": "false", "corsDomain": "finance.yahoo.com"}, crumb=True, body=body)["finance"]["result"][0]
            q = res.get("quotes") or []
            out += q
            offset += len(q)
            if progress:
                progress(offset, res.get("total") or offset)
            if not q or offset >= (res.get("total") or 0):
                return out

    # ---- quotazioni ----
    def quotes(self, symbols):
        """{simbolo: dati} per blocchi da 40."""
        out = {}
        for i in range(0, len(symbols), 40):
            r = self.request("/v7/finance/quote", {"symbols": ",".join(symbols[i:i + 40])}, crumb=True)["quoteResponse"]["result"]
            for x in r:
                out[x["symbol"]] = x
        return out

    def summary(self, symbol):
        """Scheda del fondo: TER, patrimonio, famiglia, lancio, ripartizione azioni/obbligazioni/liquidità, settori."""
        mods = "defaultKeyStatistics,fundProfile,topHoldings,summaryDetail"
        try:
            r = self.request(f"/v10/finance/quoteSummary/{urllib.parse.quote(symbol)}", {"modules": mods}, crumb=True)["quoteSummary"]["result"]
        except NotFound:
            return {}
        return parse_summary(r[0]) if r else {}

    # ---- storico e cambi ----
    def history(self, symbol, rng="5y", since=None):
        """(valuta, [(data ISO, chiusura aggiustata)]) dello storico giornaliero. La chiusura aggiustata include i dividendi.
        Con `since` (data ISO) si scarica solo da quel giorno a oggi: serve per aggiornare uno storico già presente."""
        q = {"interval": "1d", "events": "div,splits"}
        if since:
            q["period1"] = int(datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            q["period2"] = int(time.time()) + 86400
        else:
            q["range"] = rng
        r = self.request(f"/v8/finance/chart/{urllib.parse.quote(symbol)}", q)["chart"]["result"]
        if not r:
            raise NotFound(symbol)
        return parse_chart(r[0])

    def fx(self, cur, rng="5y"):
        """{data: EUR per 1 unità di valuta}."""
        if cur == "EUR":
            return {}
        c = "GBP" if cur == "GBp" else cur
        _, ser = self.history(f"EUR{c}=X", rng)
        k = 0.01 if cur == "GBp" else 1.0
        return {d: k / p for d, p in ser if p}


def parse_chart(res):
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    adj = ((ind.get("adjclose") or [{}])[0] or {}).get("adjclose")
    close = ((ind.get("quote") or [{}])[0] or {}).get("close")
    vals = adj if adj else close
    ser = []
    for t, v in zip(ts, vals or []):
        if v is not None and v > 0:
            ser.append((datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), float(v)))
    return meta.get("currency"), dedupe(ser)


def dedupe(ser):
    d = {}
    for day, v in ser:
        d[day] = v
    return sorted(d.items())


def parse_summary(r):
    ks, fp, th, sd = (r.get(k) or {} for k in ("defaultKeyStatistics", "fundProfile", "topHoldings", "summaryDetail"))
    fee = (fp.get("feesExpensesInvestment") or {})
    ter = num(fee.get("annualReportExpenseRatio")) or num(ks.get("annualReportExpenseRatio"))
    inc = num(ks.get("fundInceptionDate"))
    sect = {}
    for d in th.get("sectorWeightings") or []:
        for k, v in d.items():
            if num(v) is not None:
                sect[k] = num(v)
    return {"ter": ter * 100 if ter is not None else None,  # in %
            "assets": num(ks.get("totalAssets")),
            "family": ks.get("fundFamily") or fp.get("family"), "category": ks.get("category") or fp.get("categoryName"),
            "inception": datetime.fromtimestamp(inc, timezone.utc).strftime("%Y-%m-%d") if inc else None,
            "stock": num(th.get("stockPosition")), "bond": num(th.get("bondPosition")), "cash": num(th.get("cashPosition")), "other": num(th.get("otherPosition")),
            "yield": (num(sd.get("yield")) or num(ks.get("yield"))), "sectors": json.dumps(sect) if sect else None,
            "holdings": json.dumps([[h.get("holdingName") or h.get("symbol"), round(num(h.get("holdingPercent")) * 100, 2)] for h in (th.get("holdings") or []) if num(h.get("holdingPercent")) is not None][:10], ensure_ascii=False) or None}
