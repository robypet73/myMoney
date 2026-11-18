"""Fonti ufficiali per collegare ISIN e simbolo: elenco degli strumenti di Xetra (Deutsche Börse) e OpenFIGI (mappa ISIN -> ticker per ogni borsa)."""
import csv
import io
import json
import re
import time
import urllib.error
import urllib.request

from yahoo import Cancelled

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
XETRA_PAGE = "https://www.cashmarket.deutsche-boerse.com/cash-en/trading/Tradable-Instruments-Xetra"
# codice borsa OpenFIGI -> suffisso del simbolo Yahoo
FIGI_SUFFIX = {"IM": ".MI", "GY": ".DE", "GR": ".DE", "FP": ".PA", "NA": ".AS", "LN": ".L", "SW": ".SW"}


def _sleep(sec, cancel):
    end = time.time() + sec
    while time.time() < end:
        if cancel():
            raise Cancelled()
        time.sleep(min(0.2, max(0, end - time.time())))


def xetra_list(cancel=None, log=None):
    """ETF, ETC ed ETN negoziati su Xetra: lista di {isin, name, mnemonic, type}. Il file CSV ufficiale cambia indirizzo a ogni aggiornamento: si legge dalla pagina."""
    cancel = cancel or (lambda: False)
    h = urllib.request.urlopen(urllib.request.Request(XETRA_PAGE, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
    m = re.search(r'href="([^"]*t7-xetr-allTradableInstruments\.csv)"', h)
    if not m:
        raise RuntimeError("Elenco Xetra: link al file non trovato (la pagina è cambiata?)")
    url = m.group(1) if m.group(1).startswith("http") else "https://www.cashmarket.deutsche-boerse.com" + m.group(1)
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read().decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    hi = next(i for i, r in enumerate(rows) if "ISIN" in r and "Mnemonic" in r)
    ix = {k: i for i, k in enumerate(rows[hi])}
    out = []
    for r in rows[hi + 1:]:
        if len(r) <= ix["Instrument Type"] or r[ix["Instrument Type"]] not in ("ETF", "ETC", "ETN"):
            continue
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", r[ix["ISIN"]] or "") or not r[ix["Mnemonic"]]:
            continue
        out.append({"isin": r[ix["ISIN"]], "name": r[ix["Instrument"]], "mnemonic": r[ix["Mnemonic"]], "type": r[ix["Instrument Type"]]})
    if log:
        log(f"Elenco Xetra: {len(out)} strumenti ({rows[1][1] if len(rows) > 1 and len(rows[1]) > 1 else ''})")
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
