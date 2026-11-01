#!/usr/bin/env python3
"""Server locale di myMoney: serve la pagina e scarica prezzi e caratteristiche degli ETF direttamente da Yahoo Finance e justETF,
senza GitHub e senza token. Solo libreria standard.

    python3 scripts/serve.py            # poi apri http://localhost:8000
    python3 scripts/serve.py --port 8080
    python3 scripts/serve.py --host 0.0.0.0   # raggiungibile anche dal telefono nella stessa rete (chiunque in rete può aprirlo)

La pagina rileva il server (api/ping) e passa in modalità locale: ogni minuto chiede le quotazioni (api/update?kind=quotes) e
rilegge i file; «Aggiorna» e l'aggiunta di un ETF senza prezzi scaricano serie, indice e composizione sul momento.
I file scritti sono gli stessi dei workflow (prices.js, quotes.js, data/p/*.js, data/d/*.js, etfdata.js, catalog.js).
"""
import json
import re
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
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


def run(kind, isins):
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


def main():
    a = sys.argv[1:]
    host = a[a.index("--host") + 1] if "--host" in a else "127.0.0.1"
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8000
    srv = Server((host, port), Handler)
    print(f"myMoney locale: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}  (Ctrl+C per fermare)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nFermato")


if __name__ == "__main__":
    main()
