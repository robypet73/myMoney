#!/usr/bin/env python3
"""Server locale di myMoney: serve la pagina e scarica prezzi e caratteristiche degli ETF direttamente da Yahoo Finance e justETF,
senza GitHub e senza token. Solo libreria standard.

    python3 scripts/serve.py            # poi apri http://localhost:8000
    python3 scripts/serve.py --port 8080
    python3 scripts/serve.py --host 0.0.0.0   # raggiungibile anche dal telefono nella stessa rete (chiunque in rete può aprirlo)
    python3 scripts/serve.py --abrir          # apre subito il browser (scheda); --finestra apre una finestra senza barra (Edge o Chrome)

Su Windows c'è anche myMoney.exe (costruito da .github/workflows/windows.yml con PyInstaller): è questo stesso server, con Python incluso,
che apre da solo il browser. I file dell'app stanno nella cartella dell'eseguibile; gli scarichi girano nello stesso processo (run_inproc).

La pagina rileva il server (api/ping) e passa in modalità locale: ogni minuto chiede le quotazioni (api/update?kind=quotes) e
rilegge i file; «Aggiorna» e l'aggiunta di un ETF senza prezzi scaricano serie, indice e composizione sul momento.
I file scritti sono gli stessi dei workflow (prices.js, quotes.js, data/p/*.js, data/d/*.js, etfdata.js, catalog.js).
"""
import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FROZEN = bool(getattr(sys, "frozen", False))  # dentro l'eseguibile di PyInstaller
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
os.environ["MYMONEY_ROOT"] = str(ROOT)  # dove gli script fetch_*.py scrivono i file
if FROZEN:
    sys.path.insert(0, str(Path(getattr(sys, "_MEIPASS", ROOT))))
PY = sys.executable
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")
LOCK = threading.Lock()

# tipo di aggiornamento -> (comando, timeout in secondi, accetta ISIN)
KINDS = {
    "quotes": ([PY, "scripts/fetch_quotes.py"], 180, False),   # ultimo prezzo, orario, bid e ask di tutti gli ETF con simbolo
    "prices": ([PY, "scripts/fetch_prices.py"], 600, False),   # i 14 ETF principali con la cronologia
    "series": ([PY, "scripts/fetch_series.py", "--force"], 900, True),          # 5 anni di prezzi degli ISIN indicati
    "info": ([PY, "scripts/fetch_etf_data.py", "--extra"], 600, True),          # indice, titoli, paesi, settori da justETF
    "catalog": ([PY, "scripts/fetch_catalog.py"], 900, False),  # elenco di tutti gli ETF (screener justETF)
}


# nell'eseguibile non c'è un Python a parte: gli script girano nello stesso processo
MODS = {"quotes": ("fetch_quotes", []), "prices": ("fetch_prices", []), "series": ("fetch_series", ["--force"]), "info": ("fetch_etf_data", ["--extra"]), "catalog": ("fetch_catalog", [])}


def run_inproc(kind, isins):
    _, _, takes = KINDS[kind]
    name, base = MODS[kind]
    if takes and not isins:
        return {"ok": False, "error": "ISIN mancanti"}
    args = list(base) + (["--isins", ",".join(isins)] if takes else [])
    for m in ("fetch_prices", "fetch_quotes", "fetch_series", "fetch_etf_data", "fetch_catalog"):
        sys.modules.pop(m, None)  # stato pulito a ogni esecuzione (cookie, scadenze, cache dei cambi)
    old, buf, t0, ok = sys.argv, io.StringIO(), time.time(), True
    sys.argv = [name + ".py"] + args
    try:
        mod = importlib.import_module(name)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            mod.main()
    except SystemExit as e:
        ok = e.code in (None, 0)
        if not ok:
            buf.write(str(e.code))
    except Exception as e:  # rete, formato, limiti
        ok = False
        buf.write(repr(e))
    finally:
        sys.argv = old
    return {"ok": ok, "seconds": round(time.time() - t0, 1), "log": buf.getvalue().strip().splitlines()[-6:]}


def run(kind, isins):
    if FROZEN:
        return run_inproc(kind, isins)
    cmd, timeout, takes = KINDS[kind]
    cmd = list(cmd)
    if takes:
        if not isins:
            return {"ok": False, "error": "ISIN mancanti"}
        cmd += ["--isins", ",".join(isins)]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tempo scaduto", "seconds": round(time.time() - t0, 1)}
    tail = (p.stdout + p.stderr).strip().splitlines()[-6:]
    return {"ok": p.returncode == 0, "seconds": round(time.time() - t0, 1), "log": tail}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # prezzi sempre freschi
        super().end_headers()

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api(self):
        u = urlparse(self.path)
        if u.path == "/api/ping":
            return self.reply(200, {"ok": True, "local": True})
        if u.path != "/api/update":
            return self.reply(404, {"ok": False, "error": "non trovato"})
        q = parse_qs(u.query)
        kind = (q.get("kind") or [""])[0]
        if kind not in KINDS:
            return self.reply(400, {"ok": False, "error": "tipo sconosciuto"})
        isins = [i for i in ",".join(q.get("isins") or []).replace(" ", "").upper().split(",") if ISIN.fullmatch(i)]
        if not LOCK.acquire(blocking=False):
            return self.reply(200, {"ok": False, "busy": True, "error": "un altro aggiornamento è in corso"})
        try:
            self.reply(200, run(kind, isins))
        finally:
            LOCK.release()

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.api()
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self.api()
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # il browser che chiude la connessione non è un errore
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def pinged(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return bool(json.load(r).get("local"))
    except Exception:
        return False


def open_window(url, app):
    """Scheda del browser predefinito, oppure (app=True) finestra senza barra con Edge o Chrome se ci sono."""
    if app:
        for base in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                exe = os.path.join(os.environ.get(base, ""), rel)
                if os.environ.get(base) and os.path.exists(exe):
                    subprocess.Popen([exe, f"--app={url}"])
                    return
    webbrowser.open(url)


def main():
    a = sys.argv[1:]
    host = a[a.index("--host") + 1] if "--host" in a else "127.0.0.1"
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8000
    abrir = "--abrir" in a or "--finestra" in a or FROZEN  # l'eseguibile apre sempre il browser
    app = "--finestra" in a
    srv = None
    for p in range(port, port + 11):
        if abrir and pinged(p):  # c'è già un myMoney acceso: basta aprire la scheda
            print(f"myMoney è già acceso su http://localhost:{p}")
            open_window(f"http://localhost:{p}", app)
            return
        try:
            srv = Server((host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"Nessuna porta libera tra {port} e {port + 10}")
    url = f"http://localhost:{port}" if host in ("127.0.0.1", "0.0.0.0") else f"http://{host}:{port}"
    print(f"myMoney locale: {url}  (Ctrl+C o chiudi questa finestra per fermare)")
    if abrir:
        threading.Timer(0.8, open_window, (url, app)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nFermato")


if __name__ == "__main__":
    main()
