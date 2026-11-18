"""Server locale (solo 127.0.0.1): serve la pagina web e fa da ponte verso Yahoo Finance e il database SQLite."""
import json
import os
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import classify as C
import jobs
from justetf import JustETF
import portfolio as PF
from db import DB
from yahoo import EXCHANGES, Cancelled, Yahoo

WEB = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "web")


class Job:
    """Un solo lavoro alla volta (scarico o calcolo), con avanzamento e annullamento."""

    def __init__(self, path):
        self.path, self.lock, self.cancel = path, threading.Lock(), threading.Event()
        self.s = {"busy": False, "text": "", "done": 0, "total": 0, "log": [], "warnings": [], "error": None, "result": None, "kind": None, "finished": None}

    def status(self):
        with self.lock:
            return dict(self.s, log=self.s["log"][-40:], warnings=self.s["warnings"][:200])

    def _set(self, **kw):
        with self.lock:
            self.s.update(kw)

    def _log(self, m):
        with self.lock:
            self.s["log"].append(m)

    def _warn(self, m):
        """Avviso di scaricamento: resta in elenco e si mostra all'utente a lavoro finito."""
        with self.lock:
            self.s["warnings"].append(m)
            self.s["log"].append("⚠ " + m)

    def start(self, kind, fn):
        with self.lock:
            if self.s["busy"]:
                return False
            self.s.update(busy=True, kind=kind, text="Avvio…", done=0, total=0, error=None, result=None, log=[], warnings=[], finished=None)
        self.cancel.clear()

        def prog(t, d=0, n=0):
            self._set(text=t, done=d, total=n)

        def work():
            db = DB(self.path)
            try:
                y = Yahoo(cancel=self.cancel.is_set, log=self._log, warn=self._warn)
                res = fn(db, y, prog)
                db.commit()
                self._set(result=res, text="Fatto", done=1, total=1)
            except Cancelled:
                db.commit()
                self._set(error="Interrotto: quanto scaricato è salvato")
            except Exception as e:  # noqa: BLE001
                db.commit()
                self._set(error=f"Errore: {e}")
            finally:
                db.close()
                self._set(busy=False, finished=time.strftime("%Y-%m-%d %H:%M:%S"))

        threading.Thread(target=work, daemon=True).start()
        return True


def num(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_create(d):
    """Dai campi della pagina ai criteri di ricerca (f) e ai parametri del portafoglio (p)."""
    caps = {c: num((d.get("class_caps") or {}).get(c)) for c in C.CLASSES}
    caps = {c: 100.0 if v is None else v for c, v in caps.items()}
    f = {"text": d.get("text") or "", "unknown": bool(d.get("unknown")), "ter_max": num(d.get("ter_max")), "assets_min": num(d.get("assets_min")),
         "adv_min": num(d.get("adv_min")), "spread_max": num(d.get("spread_max")), "ret1y_min": num(d.get("ret1y_min")), "vol_max": num(d.get("vol_max")),
         "min_years": num(d.get("min_years")) or 0, "pool": int(num(d.get("pool")) or 150), "class_caps": caps}
    for k in ("exchanges", "types", "currencies", "distributions", "regions", "replications", "domiciles"):
        f[k] = list(d.get(k) or [])
    f["sustainable"] = bool(d.get("sustainable"))
    p = {"amount": num(d.get("amount")) or 0.0, "kmin": int(num(d.get("kmin")) or 3), "kmax": int(num(d.get("kmax")) or 8), "cap": (num(d.get("cap")) or 35) / 100,
         "rf": (num(d.get("rf")) if num(d.get("rf")) is not None else 2) / 100, "vol_aggr": (num(d.get("vol_aggr")) or 20) / 100, "caps": {c: v / 100 for c, v in caps.items()}}
    return f, p


def check(p):
    if sum(p["caps"].values()) < 1 - 1e-9:
        return "La somma dei massimi per classe è sotto il 100%: il portafoglio non può essere composto."
    if p["cap"] * p["kmax"] < 1:
        return f"Con al massimo {p['kmax']} ETF il peso massimo per ETF deve essere almeno {100 / p['kmax']:.0f}%."
    return None


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if hasattr(o, "item"):
        return o.item()
    return o


def make_handler(path, job):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json", extra=None):
            b = body if isinstance(body, bytes) else json.dumps(jsonable(body), ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ""))
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path).path
            if u in ("/", "/index.html"):
                return self.send(200, open(os.path.join(WEB, "index.html"), "rb").read(), "text/html")
            if u == "/api/info":
                db = DB(path)
                try:
                    return self.send(200, {"path": os.path.abspath(path), "stats": db.stats(), "exchanges": EXCHANGES, "classes": C.CLASSES, "regions": [r for r, _ in C.REGIONS], "rules": {"minw": PF.MINW, "shrink": PF.SHRINK, "dr_gain": PF.DR_GAIN, "window": PF.WINDOW_YEARS},
                                     "domiciles": [x[0] for x in db.c.execute("SELECT DISTINCT domicile FROM etf WHERE domicile IS NOT NULL ORDER BY 1")]})
                finally:
                    db.close()
            if u == "/api/status":
                return self.send(200, job.status())
            if u == "/api/export":
                db = DB(path)
                try:
                    tmp = tempfile.mktemp(suffix=".csv")
                    db.export_csv(tmp)
                    data = open(tmp, "rb").read()
                    os.remove(tmp)
                finally:
                    db.close()
                return self.send(200, data, "text/csv", {"Content-Disposition": 'attachment; filename="etf.csv"'})
            self.send(404, {"error": "non trovato"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                return self.send(403, {"error": "origine non consentita"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self.send(400, {"error": "JSON non valido"})
            u = urlparse(self.path).path
            if u == "/api/cancel":
                job.cancel.set()
                return self.send(200, {"ok": True})
            if u == "/api/download":
                ex = [c for c in d.get("exchanges", []) if c in EXCHANGES]
                if not ex:
                    return self.send(400, {"error": "Scegli almeno una borsa"})
                det = bool(d.get("details"))
                ok = job.start("download", lambda db, y, p: jobs.download_catalog(db, y, ex, det, None, p))
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/quotes":
                ok = job.start("quotes", lambda db, y, p: jobs.update_quotes(db, y, None, p))
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/justetf":
                key = os.environ.get("OPENFIGI_KEY") or None

                def run(db, y, prog):
                    jobs.download_justetf(db, y, JustETF(cancel=job.cancel.is_set, log=job._log), key, None, prog, job.cancel.is_set, job._log)

                ok = job.start("justetf", run)
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/search":
                f, _ = parse_create(d)
                db = DB(path)
                try:
                    allr, pool, by = PF.search_summary(db, f)
                    cols = ("symbol", "isin", "name", "asset_class", "region", "exchange_name", "currency", "ter", "assets_eur_m", "adv_eur_m", "spread_pct", "ret_1y", "ret_3y", "vol_1y",
                            "replication", "domicile", "sustainable", "hist_n")
                    return self.send(200, {"n_all": len(allr), "n_pool": len(pool), "with_history": sum(1 for r in pool if r["hist_n"]), "by_class": by, "titoli": db.stats()["titoli"],
                                           "rows": [{k: r[k] for k in cols} for r in pool[:300]]})
                finally:
                    db.close()
            if u == "/api/propose":
                f, p = parse_create(d)
                err = check(p)
                if err:
                    return self.send(400, {"error": err})
                db = DB(path)
                try:
                    rows = PF.select(db, f)
                finally:
                    db.close()
                if len(rows) < max(2, p["kmin"]):
                    return self.send(400, {"error": f"Solo {len(rows)} fondi passano i criteri: allarga la ricerca."})
                syms = [r["symbol"] for r in rows]

                def run(db, y, prog):
                    jobs.download_history(db, y, syms, prog)
                    prog("Calcolo le proposte…", 0, 0)
                    order = {s: i for i, s in enumerate(syms)}
                    fresh = sorted(db.all(f"symbol IN ({','.join('?' * len(syms))})", syms), key=lambda r: order[r["symbol"]])
                    ds = PF.load_dataset(db, fresh, PF.WINDOW_YEARS, f["min_years"], f["vol_max"], f["ret1y_min"])
                    if ds is None:
                        return {"message": "Servono almeno 2 titoli con storico sufficiente: abbassa «Storia minima» o allarga i criteri."}
                    out, fail = PF.propose(ds, **p)
                    return {"proposals": out, "fail": fail, "n": len(ds.rows), "from": ds.dates[0], "to": ds.dates[-1], "years": ds.years, "amount": p["amount"]}

                ok = job.start("propose", run)
                return self.send(200 if ok else 409, {"ok": ok, "n": len(rows)})
            self.send(404, {"error": "non trovato"})

    return H


def run(path, port=8765, open_browser=True):
    job = Job(path)
    srv = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(path, job))
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit("Nessuna porta libera")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"myMoney in funzione su {url}\nDatabase: {os.path.abspath(path)}\nCtrl+C per chiudere")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        job.cancel.set()
        print("\nChiuso")
    return 0
