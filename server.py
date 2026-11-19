"""Server locale (solo 127.0.0.1): serve la pagina web e fa da ponte verso Yahoo Finance e il database SQLite."""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
import zipfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import classify as C
import checks
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
    """Dai campi della pagina ai criteri di ricerca (f) e ai parametri del portafoglio (p). Tutti i criteri sono assenti (null) finché non li imposti."""
    caps = {c: num((d.get("class_caps") or {}).get(c)) for c in C.CLASSES}
    caps = {c: 100.0 if v is None else v for c, v in caps.items()}
    ranges = {}
    for k, v in (d.get("ranges") or {}).items():
        if k in PF.RANGE_COLS or k == "years":
            lo, hi = (num(v[0]), num(v[1])) if isinstance(v, (list, tuple)) and len(v) == 2 else (None, None)
            if lo is not None or hi is not None:
                ranges[k] = [lo, hi]
    f = {"unknown": bool(d.get("unknown")), "pool": int(num(d.get("pool")) or 150), "class_caps": caps, "ranges": ranges}
    for k in ("exchanges", "types", "currencies", "distributions", "regions", "replications", "domiciles"):
        f[k] = list(d.get(k) or [])
    f["sustainable"] = bool(d.get("sustainable"))
    p = {"amount": num(d.get("amount")) or 0.0, "kmin": int(num(d.get("kmin")) or 3), "kmax": int(num(d.get("kmax")) or 8), "cap": (num(d.get("cap")) or 35) / 100,
         "rf": (num(d.get("rf")) if num(d.get("rf")) is not None else 2) / 100, "vol_aggr": (num(d.get("vol_aggr")) or 20) / 100, "caps": {c: v / 100 for c, v in caps.items()},
         "dr_min": num(d.get("dr_min")), "corr_max": num(d.get("corr_max"))}
    return f, p


def check(p):
    if p["kmin"] > p["kmax"]:
        return "Il numero minimo di ETF supera il massimo."
    if sum(p["caps"].values()) < 1 - 1e-9:
        return "La somma dei massimi per classe è sotto il 100%: il portafoglio non può essere composto."
    if p["cap"] * p["kmax"] < 1:
        return f"Con al massimo {p['kmax']} ETF il peso massimo per ETF deve essere almeno {100 / p['kmax']:.0f}%."
    return None


# ---------------------------------------------------------------- portafogli salvati (file JSON in «portafogli/» accanto al database)
def pf_slug(name):
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")[:60] or "portafoglio"


def pf_save(folder, doc, overwrite=False):
    """Scrive portafogli/<nome>.json. Ritorna (id, esiste_già). Senza `overwrite` non sostituisce un file con lo stesso nome."""
    pf = doc.get("portfolio") or {}
    name = str(pf.get("name") or "").strip()
    if not name or not isinstance(pf.get("positions"), list) or not pf["positions"]:
        raise ValueError("Servono un nome e almeno una posizione")
    pid = pf_slug(name)
    path = os.path.join(folder, pid + ".json")
    if os.path.exists(path) and not overwrite:
        return pid, True
    os.makedirs(folder, exist_ok=True)
    pf["id"] = pid
    out = {"version": 1, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "portfolio": pf}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return pid, False


def pf_path(folder, pid):
    if not re.fullmatch(r"[a-z0-9-]{1,60}", pid or ""):
        raise ValueError("Identificativo non valido")
    return os.path.join(folder, pid + ".json")


def pf_list(folder):
    out = []
    for fn in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not fn.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(folder, fn), encoding="utf-8"))
            pf = d["portfolio"]
            out.append({"id": fn[:-5], "name": pf.get("name"), "saved_at": d.get("saved_at"), "source": pf.get("source"), "amount": pf.get("amount"), "n": len(pf.get("positions", [])),
                        "metrics": pf.get("metrics"), "description": pf.get("description")})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda x: x.get("saved_at") or "", reverse=True)


# ---------------------------------------------------------------- esportazione e importazione dell'archivio tra computer
def db_export(path, pf_folder, dest):
    """Scrive in `dest` uno zip con una copia coerente del database (etf.db) e i portafogli salvati (portafogli/*.json)."""
    tmp = path + ".snapshot"
    d = DB(path)
    try:
        d.snapshot(tmp)
    finally:
        d.close()
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(tmp, "etf.db")
            if os.path.isdir(pf_folder):
                for fn in sorted(os.listdir(pf_folder)):
                    if re.fullmatch(r"[a-z0-9-]{1,60}\.json", fn):
                        z.write(os.path.join(pf_folder, fn), "portafogli/" + fn)
            z.writestr("LEGGIMI.txt", "Archivio myMoney esportato il " + time.strftime("%Y-%m-%d %H:%M:%S") + ".\nSi importa dalla pagina (Archivio > Importa archivio) o con: python mymoney.py ripristina FILE\n")
    finally:
        os.remove(tmp)


def db_import(path, pf_folder, upload):
    """Sostituisce il database con quello del file caricato (zip di `db_export` o file SQLite). Prima lo controlla; tiene una copia del database precedente
    accanto («.prima-dell-importazione»). I portafogli salvati nello zip si aggiungono a quelli presenti (senza sostituirli). Ritorna le statistiche."""
    tmp = path + ".import"
    try:
        if zipfile.is_zipfile(upload):
            with zipfile.ZipFile(upload) as z:
                name = next((n for n in z.namelist() if n == "etf.db" or (n.endswith(".db") and "/" not in n)), None)
                if not name:
                    raise ValueError("Lo zip non contiene un archivio etf.db")
                with z.open(name) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                pfs = [n for n in z.namelist() if re.fullmatch(r"portafogli/[a-z0-9-]{1,60}\.json", n)]
                payload = {n: z.read(n) for n in pfs}
        else:
            shutil.copyfile(upload, tmp)
            payload = {}
        try:
            c = sqlite3.connect(tmp)
            ok = c.execute("PRAGMA integrity_check").fetchone()[0]
            tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            cols = {r[1] for r in c.execute("PRAGMA table_info(etf)")} if "etf" in tabs else set()
            n = c.execute("SELECT COUNT(*) FROM etf").fetchone()[0] if cols else 0
            c.close()
        except sqlite3.DatabaseError:
            raise ValueError("Il file non è un archivio myMoney valido")
        if ok != "ok" or not {"etf", "prezzi"} <= tabs or "symbol" not in cols:
            raise ValueError("Il file non è un archivio myMoney valido o è danneggiato")
        if os.path.exists(path):
            shutil.copy2(path, path + ".prima-dell-importazione")
        os.replace(tmp, path)
        for sfx in ("-wal", "-shm", "-journal"):
            if os.path.exists(path + sfx):
                os.remove(path + sfx)
        added = 0
        for name, data in payload.items():
            target = os.path.join(pf_folder, os.path.basename(name))
            if not os.path.exists(target):
                os.makedirs(pf_folder, exist_ok=True)
                open(target, "wb").write(data)
                added += 1
        d = DB(path)  # apre e aggiorna lo schema di un archivio creato da una versione precedente
        try:
            st = d.stats()
        finally:
            d.close()
        return dict(st, portafogli_aggiunti=added, titoli_importati=n)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fund_detail(db, symbol):
    """Tutto ciò che l'archivio sa di un titolo: anagrafica, altre quotazioni dello stesso fondo, storico e statistiche."""
    r = db.get(symbol)
    if not r:
        return None
    f = {k: r[k] for k in r.keys()}
    for k in ("holdings", "sectors"):
        try:
            f[k] = json.loads(f[k]) if f[k] else None
        except ValueError:
            f[k] = None
    if r["isin"]:
        others = db.c.execute("SELECT symbol, exchange_name, currency, price, price_eur, spread_pct, adv_eur_m, hist_n FROM etf WHERE isin=? AND symbol<>? ORDER BY adv_eur_m IS NULL, adv_eur_m DESC", (r["isin"], symbol)).fetchall()
    else:
        others = []
    ser = [(d, p) for d, p in db.prices(symbol)]
    out = {"fund": f, "others": [{k: o[k] for k in o.keys()} for o in others], "history": None, "stats": None}
    if len(ser) >= 30:
        out["history"] = {"dates": [d for d, _ in ser], "close": [round(p, 4) for _, p in ser]}
        out["stats"] = PF.fund_stats(ser)
    return out


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if hasattr(o, "item"):
        return o.item()
    return o


def make_handler(path, job):
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), "portafogli")

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
                    return self.send(200, {"path": os.path.abspath(path), "stats": db.stats(), "exchanges": EXCHANGES, "classes": C.CLASSES, "regions": [r for r, _ in C.REGIONS], "rules": {"minw": PF.MINW, "shrink": PF.SHRINK, "dr_gain": PF.DR_GAIN, "window": PF.WINDOW_YEARS, "min_window": PF.MIN_WINDOW_YEARS},
                                     "domiciles": [x[0] for x in db.c.execute("SELECT DISTINCT domicile FROM etf WHERE domicile IS NOT NULL ORDER BY 1")]})
                finally:
                    db.close()
            if u == "/api/status":
                return self.send(200, job.status())
            if u == "/api/fund":
                q = parse_qs(urlparse(self.path).query)
                db = DB(path)
                try:
                    det = fund_detail(db, (q.get("symbol") or [""])[0])
                finally:
                    db.close()
                return self.send(200 if det else 404, det or {"error": "titolo non presente nell'archivio"})
            if u == "/api/pf/list":
                return self.send(200, {"folder": folder, "items": pf_list(folder)})
            if u == "/api/pf/get":
                q = parse_qs(urlparse(self.path).query)
                try:
                    fp = pf_path(folder, (q.get("id") or [""])[0])
                    data = open(fp, "rb").read()
                except (ValueError, OSError):
                    return self.send(404, {"error": "portafoglio non trovato"})
                return self.send(200, data, "application/json", {"Content-Disposition": f'attachment; filename="{os.path.basename(fp)}"'} if q.get("dl") else None)
            if u == "/api/db/export":
                if job.status()["busy"]:
                    return self.send(409, {"error": "Un lavoro è in corso: aspetta che finisca"})
                dest = path + ".export.zip"
                try:
                    db_export(path, folder, dest)
                    size = os.path.getsize(dest)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(size))
                    self.send_header("Content-Disposition", f'attachment; filename="myMoney-archivio-{time.strftime("%Y%m%d-%H%M")}.zip"')
                    self.end_headers()
                    with open(dest, "rb") as f:
                        shutil.copyfileobj(f, self.wfile, 1 << 20)
                finally:
                    if os.path.exists(dest):
                        os.remove(dest)
                return
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
            if urlparse(self.path).path == "/api/db/import":
                if job.status()["busy"]:
                    return self.send(409, {"error": "Un lavoro è in corso: aspetta che finisca"})
                up = path + ".upload"
                try:
                    with open(up, "wb") as f:
                        left = n
                        while left > 0:
                            chunk = self.rfile.read(min(1 << 20, left))
                            if not chunk:
                                break
                            f.write(chunk)
                            left -= len(chunk)
                    return self.send(200, {"ok": True, "stats": db_import(path, folder, up)})
                except ValueError as e:
                    return self.send(400, {"error": str(e)})
                except OSError as e:
                    return self.send(500, {"error": f"Importazione non riuscita: {e}"})
                finally:
                    if os.path.exists(up):
                        os.remove(up)
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self.send(400, {"error": "JSON non valido"})
            u = urlparse(self.path).path
            if u == "/api/pf/save":
                try:
                    pid, exists = pf_save(folder, d.get("doc") or {}, bool(d.get("overwrite")))
                except ValueError as e:
                    return self.send(400, {"error": str(e)})
                except OSError as e:
                    return self.send(500, {"error": f"Salvataggio non riuscito: {e}"})
                return self.send(409 if exists else 200, {"ok": not exists, "exists": exists, "id": pid, "file": os.path.join(folder, pid + ".json")})
            if u == "/api/pf/delete":
                try:
                    os.remove(pf_path(folder, d.get("id")))
                except (ValueError, OSError):
                    return self.send(404, {"error": "portafoglio non trovato"})
                return self.send(200, {"ok": True})
            if u == "/api/cancel":
                job.cancel.set()
                return self.send(200, {"ok": True})
            if u == "/api/download":
                ex = [c for c in d.get("exchanges", []) if c in EXCHANGES]
                if not ex:
                    return self.send(400, {"error": "Scegli almeno una borsa"})
                det, hist = bool(d.get("details")), bool(d.get("history"))

                def run(db, y, p):
                    jobs.download_catalog(db, y, ex, det, None, p)
                    if hist:
                        jobs.download_history_all(db, y, False, p)

                ok = job.start("download", run)
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/sync":
                key = os.environ.get("OPENFIGI_KEY") or None
                ok = job.start("sync", lambda db, y, p: jobs.sync_all(db, y, JustETF(cancel=job.cancel.is_set, log=job._log), key, p, job.cancel.is_set, job._log))
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/check":
                key = os.environ.get("OPENFIGI_KEY") or None

                def run(db, y, prog):
                    rep_ = checks.run(db, y, JustETF(cancel=job.cancel.is_set, log=job._log), 15, prog, None, key)
                    cf = os.path.join(os.path.dirname(os.path.abspath(path)), "controlli")
                    os.makedirs(cf, exist_ok=True)
                    fn = os.path.join(cf, "controllo-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
                    with open(fn, "w", encoding="utf-8") as f:
                        json.dump(rep_, f, ensure_ascii=False, indent=1)
                    rep_["file"] = fn
                    return rep_

                ok = job.start("check", run)
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/fund/history":
                sym = str(d.get("symbol") or "")
                ok = job.start("fundhist", lambda db, y, p: jobs.download_history(db, y, [sym], p, 0))
                return self.send(200 if ok else 409, {"ok": ok})
            if u == "/api/history":
                allq = bool(d.get("all_listings"))
                ok = job.start("history", lambda db, y, p: jobs.download_history_all(db, y, allq, p))
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
                    allr, pool, by, cov = PF.search_summary(db, f)
                    cols = ("symbol", "isin", "name", "asset_class", "region", "exchange_name", "currency", "ter", "assets_eur_m", "adv_eur_m", "spread_pct", "ret_1y", "ret_3y", "ret_5y",
                            "vol_1y", "max_dd", "replication", "domicile", "sustainable", "hist_n")
                    return self.send(200, {"n_all": len(allr), "n_pool": len(pool), "with_history": sum(1 for r in pool if r["hist_n"]), "by_class": by, "titoli": db.stats()["titoli"],
                                           "coverage": cov, "rows": [{k: r[k] for k in cols} for r in pool[:300]]})
                finally:
                    db.close()
            if u == "/api/returns":
                f, _ = parse_create(d)
                db = DB(path)
                try:
                    base = PF.select(db, {**f, "pool": 0}, skip=tuple(PF.RETURN_KEYS))
                    todo = [r["symbol"] for r in base if not r["hist_n"] and r["ret_3y"] is None]
                finally:
                    db.close()
                if not todo:
                    return self.send(200, {"ok": True, "n": 0})
                ok = job.start("returns", lambda db, y, prog: jobs.download_history(db, y, todo, prog))
                return self.send(200 if ok else 409, {"ok": ok, "n": len(todo)})
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
                    yr = (f["ranges"].get("years") or [None, None])[0]
                    ds = PF.load_dataset(db, fresh, PF.WINDOW_YEARS, yr or 0.0)
                    if ds is None:
                        return {"message": "Servono almeno 2 titoli con storico sufficiente e dati affidabili: allarga i criteri o abbassa la storia minima."}
                    out, fail = PF.propose(ds, **p)
                    if not out:
                        caps = {k: v for k, v in p["caps"].items() if v < 1.0}
                        room = PF.capacity(list(range(len(ds.cls))), ds.cls, caps, p["cap"])
                        lim = PF.limits(ds, p["cap"], p["caps"]) if (p["dr_min"] or p["corr_max"] is not None) else {}
                        if len(ds.rows) < p["kmin"]:
                            msg = f"Solo {len(ds.rows)} fondi analizzati hanno dati sufficienti, meno del minimo di {p['kmin']} ETF: allarga i criteri."
                        elif room < 1:
                            have = ", ".join(sorted(set(ds.cls)))
                            msg = (f"I {len(ds.rows)} fondi analizzati sono di classi ({have}) che i massimi per classe limitano al {room * 100:.0f}% del portafoglio: "
                                   "alza i massimi o allarga i criteri così entrano fondi delle altre classi.")
                        elif p["dr_min"] and lim.get("dr_max") is not None and p["dr_min"] > lim["dr_max"] + 1e-3:
                            msg = f"Diversificazione minima {p['dr_min']:.2f} non raggiungibile: con questi fondi il massimo è {lim['dr_max']:.2f}. Abbassala o allarga i criteri."
                        elif p["corr_max"] is not None and lim.get("corr_min") is not None and p["corr_max"] < lim["corr_min"] - 1e-3:
                            msg = f"Correlazione massima {p['corr_max']:.2f} non raggiungibile: con questi fondi il minimo è {lim['corr_min']:.2f}. Alzala o allarga i criteri."
                        else:
                            msg = ("Nessuna proposta calcolabile con questi vincoli (" + ", ".join(fail) + f"): non riesco a comporre da {p['kmin']} a {p['kmax']} ETF "
                                   "rispettando peso massimo, classi, correlazione e diversificazione. Alza il peso massimo o il numero massimo di ETF, o rilassa i vincoli.")
                        return {"message": msg, "notes": ds.notes}
                    # frontiera efficiente sui fondi delle tre proposte
                    order = {r["symbol"]: i for i, r in enumerate(ds.rows)}
                    fsyms = []
                    for pr in out:
                        fsyms += [x["symbol"] for x in pr["items"] if x["symbol"] not in fsyms]
                    fr = PF.frontier(ds, [order[s_] for s_ in fsyms], p["cap"], p["caps"], p["rf"], p["kmin"], p["kmax"], p["dr_min"], p["corr_max"])
                    front = None
                    if fr and len(fr["points"]) >= 2:
                        funds = []
                        for i in fr["idx"]:
                            r = ds.rows[i]
                            funds.append({"symbol": r["symbol"], "isin": r["isin"], "name": r["name"], "class": ds.cls[i], "exchange": r["exchange_name"], "price": r["price_eur"], "ter": r["ter"],
                                          "replication": r["replication"], "domicile": r["domicile"], "vol": float(ds.sd[i]), "ret": float(ds.mu[i])})
                        front = {"funds": funds, "points": fr["points"], "rf": p["rf"]}
                    return {"proposals": out, "frontier": front, "fail": fail, "n": len(ds.rows), "from": ds.dates[0], "to": ds.dates[-1], "years": ds.years, "amount": p["amount"], "criteria": d, "notes": ds.notes, "kmin": p["kmin"], "kmax": p["kmax"]}

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
