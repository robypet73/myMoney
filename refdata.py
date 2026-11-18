"""Fonti dirette (JSON, CSV) per ISIN e cambi: registro ufficiale ESMA (FIRDS), OpenFIGI (ISIN -> ticker per borsa), cambi della BCE."""
import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from yahoo import Cancelled

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
# codice borsa OpenFIGI -> suffisso del simbolo Yahoo
FIGI_SUFFIX = {"IM": ".MI", "GY": ".DE", "GR": ".DE", "FP": ".PA", "NA": ".AS", "LN": ".L", "SW": ".SW"}


def _sleep(sec, cancel):
    end = time.time() + sec
    while time.time() < end:
        if cancel():
            raise Cancelled()
        time.sleep(min(0.2, max(0, end - time.time())))


# borsa (codice Yahoo) -> MIC del registro ESMA (FIRDS). Londra e SIX non sono nel registro UE: lì conta solo OpenFIGI.
FIRDS_MIC = {"MIL": "etfp", "GER": "xeta", "PAR": "xpar", "AMS": "xams"}
SUFFIX_MIC = {".MI": "etfp", ".DE": "xeta", ".PA": "xpar", ".AS": "xams"}
FIRDS = "https://registers.esma.europa.eu/solr/esma_registers_firds/select"


def firds_list(mics, cancel=None, log=None):
    """Registro ufficiale ESMA (FIRDS), interfaccia JSON: ISIN degli strumenti ancora attivi su ciascuna borsa. Su Borsa Italiana (ETFplus) tutti gli strumenti
    (ETF, ETC, ETN, ETP); sulle altre solo gli ETF (CFI «CE…»). Ritorna [(isin, mic, nome)]."""
    cancel = cancel or (lambda: False)
    out = []
    for mic in mics:
        start, total = 0, None
        while total is None or start < total:
            if cancel():
                raise Cancelled()
            q = [("q", "*:*"), ("fq", f"mic:{mic}"), ("fq", "latest_received_flag:1"), ("fq", "-status:term"), ("fq", "-status:canc"), ("fl", "isin,mic,gnr_full_name"),
                 ("sort", "isin asc"), ("start", start), ("rows", 1000), ("wt", "json")]
            if mic != "etfp":
                q.append(("fq", "gnr_cfi_code:ce*"))
            for k in range(5):
                try:
                    j = json.load(urllib.request.urlopen(urllib.request.Request(FIRDS + "?" + urllib.parse.urlencode(q), headers={"User-Agent": UA}), timeout=120))["response"]
                    break
                except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                    if k == 4:
                        raise RuntimeError("Registro ESMA non raggiungibile")
                    _sleep(5 * (k + 1), cancel)
            total = j["numFound"]
            out += [(d["isin"], mic, d.get("gnr_full_name")) for d in j["docs"] if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", d.get("isin") or "")]
            start += 1000
        if log:
            log(f"Registro ESMA {mic.upper()}: {total} strumenti attivi")
    return out


def ecb_fx(curs, start, cancel=None):
    """Cambi ufficiali BCE (interfaccia SDMX, CSV): {valuta: {data: EUR per 1 unità}}. Le valute che la BCE non pubblica mancano dal risultato."""
    curs = sorted({("GBP" if c == "GBp" else c) for c in curs if c and c != "EUR"})
    if not curs:
        return {}
    url = f"https://data-api.ecb.europa.eu/service/data/EXR/D.{'+'.join(curs)}.EUR.SP00.A?" + urllib.parse.urlencode({"startPeriod": start, "format": "csvdata"})
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    out = {}
    for r in csv.DictReader(io.StringIO(raw)):
        try:
            v = float(r["OBS_VALUE"])
        except (KeyError, ValueError):
            continue
        if v > 0:
            out.setdefault(r["CURRENCY"], {})[r["TIME_PERIOD"]] = 1 / v
    return out


class Figi:
    """OpenFIGI: senza chiave 25 richieste al minuto e 10 ISIN per richiesta; con la chiave gratuita 25 ogni 6 secondi e 100 ISIN."""

    def __init__(self, key=None, cancel=None, log=None):
        self.key, self.cancel, self.log = key, cancel or (lambda: False), log or (lambda m: None)
        self.batch = 100 if key else 10
        self.pause = 0.4 if key else 2.6

    def map(self, isins):
        """{isin: [(codice borsa, ticker), …]} limitato alle borse di FIGI_SUFFIX. Un ISIN sconosciuto a OpenFIGI risulta con lista vuota."""
        headers = {"Content-Type": "application/json", "User-Agent": UA}
        if self.key:
            headers["X-OPENFIGI-APIKEY"] = self.key
        body = json.dumps([{"idType": "ID_ISIN", "idValue": i} for i in isins]).encode()
        for k in range(6):
            if self.cancel():
                raise Cancelled()
            try:
                res = json.load(urllib.request.urlopen(urllib.request.Request("https://api.openfigi.com/v3/mapping", data=body, headers=headers), timeout=60))
                _sleep(self.pause, self.cancel)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    self.log("OpenFIGI: limite di richieste, attendo")
                    _sleep(int(e.headers.get("Retry-After") or 30) + 2, self.cancel)
                    continue
                if e.code in (401, 403):
                    raise RuntimeError("OpenFIGI ha rifiutato la chiave")
                _sleep(5 * (k + 1), self.cancel)
            except (urllib.error.URLError, TimeoutError, ValueError):
                _sleep(5 * (k + 1), self.cancel)
        else:
            raise RuntimeError("OpenFIGI non risponde")
        out = {}
        for isin, x in zip(isins, res):
            out[isin] = sorted({(e["exchCode"], e["ticker"]) for e in (x.get("data") or []) if e.get("exchCode") in FIGI_SUFFIX and e.get("ticker")})
        return out
