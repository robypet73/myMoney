#!/usr/bin/env python3
"""Server locale di myMoney: serve la pagina e scarica prezzi e caratteristiche degli ETF direttamente da Yahoo Finance e justETF,
senza GitHub e senza token. Solo libreria standard.

    python3 scripts/serve.py            # poi apri http://localhost:8000
    python3 scripts/serve.py --port 8080
    python3 scripts/serve.py --host 0.0.0.0   # raggiungibile anche dal telefono nella stessa rete (chiunque in rete può aprirlo)
    python3 scripts/serve.py --abrir          # apre subito il browser (scheda); --finestra apre una finestra senza barra (Edge o Chrome)
    python3 scripts/serve.py --solo-server    # nell'eseguibile: solo il server, nessuna finestra (prove automatiche)
    python3 scripts/serve.py --portafogli CARTELLA   # salva i portafogli come file JSON in quella cartella (per esempio la cartella di Google Drive)

Su Windows c'è anche myMoney.exe (costruito da .github/workflows/windows.yml con PyInstaller): è questo stesso server, con Python incluso,
che si apre in una finestra propria (pywebview con WebView2; se manca, una finestra di Edge o Chrome senza barra; se mancano, una scheda del browser). I file dell'app stanno nella cartella dell'eseguibile; gli scarichi girano nello stesso processo (run_inproc).

La pagina rileva il server (api/ping) e passa in modalità locale: ogni minuto chiede le quotazioni (api/update?kind=quotes) e
rilegge i file; «Aggiorna» e l'aggiunta di un ETF senza prezzi scaricano serie, indice e composizione sul momento.
I file scritti sono gli stessi dei workflow (prices.js, quotes.js, data/p/*.js, data/d/*.js, etfdata.js, catalog.js).
"""
import contextlib
import hashlib
import importlib
import io
import json
import os
import re
import shutil
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
if FROZEN and (sys.stdout is None or sys.stderr is None):  # eseguibile senza finestra nera: i messaggi vanno in un file
    try:
        _log = open(ROOT / "myMoney.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log
    except Exception:
        pass
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


# ---- Cartella dei portafogli (per esempio quella di Google Drive per desktop): un file JSON per portafoglio ----
CFG = ROOT / "myMoney-config.json"
STATE = {"folder": None}


def load_cfg():
    try:
        f = json.loads(CFG.read_text(encoding="utf-8")).get("folder")
        STATE["folder"] = f if f and Path(f).is_dir() else None
    except Exception:
        pass


def set_folder(path):
    """Imposta (o toglie, con stringa vuota) la cartella; la crea se manca ma esiste la cartella superiore."""
    if not path:
        STATE["folder"] = None
    else:
        p = Path(path).expanduser()
        if not p.is_dir():
            if not p.parent.is_dir():
                raise ValueError("la cartella non esiste")
            p.mkdir()
        STATE["folder"] = str(p)
    CFG.write_text(json.dumps({"folder": STATE["folder"]}, ensure_ascii=False), encoding="utf-8")


def drive_candidates():
    """Cartelle di Google Drive per desktop che esistono su questo PC."""
    home = Path.home()
    c = [home / n for n in ("Google Drive", "My Drive", "Il mio Drive", "GoogleDrive")]
    if os.name == "nt":
        c += [Path(f"{d}:/{n}") for d in "GHIJKLMNOPQRSTUVWXYZ" for n in ("My Drive", "Il mio Drive")]
    return [str(p) for p in c if p.is_dir()]


def pf_files():
    """[(percorso, dati)] dei file JSON validi nella cartella (esclusi quelli che iniziano con «_»)."""
    out = []
    for f in sorted(Path(STATE["folder"]).glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return out


def pf_read():
    folder = STATE["folder"]
    pfs, stamp = [], hashlib.md5()
    for f, d in pf_files():
        st = f.stat()
        stamp.update(f"{f.name}{st.st_mtime_ns}{st.st_size}".encode())
        if isinstance(d.get("portfolio"), dict):
            pfs.append(d["portfolio"])
        elif isinstance(d.get("portfolios"), list):
            pfs += [x for x in d["portfolios"] if isinstance(x, dict)]
    default = None
    try:
        default = json.loads((Path(folder) / "_impostazioni.json").read_text(encoding="utf-8")).get("default")
    except Exception:
        pass
    return {"ok": True, "folder": folder, "portfolios": pfs, "default": default, "stamp": stamp.hexdigest()}


def safe_name(name, pid):
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", str(name or "")).strip(" .-")[:60]
    return n or re.sub(r"[^A-Za-z0-9_-]+", "-", str(pid))[:40] or "portafoglio"


def write_if_changed(path, text):
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except Exception:
        pass
    path.write_text(text, encoding="utf-8")
    return True


def pf_write(pfs, default, removed):
    """Scrive i portafogli (un file ciascuno) e sposta in «_eliminati» quelli tolti dall'app: non cancella mai nulla."""
    folder = Path(STATE["folder"])
    by_id = {}
    for f, d in pf_files():
        for x in ([d["portfolio"]] if isinstance(d.get("portfolio"), dict) else d.get("portfolios") or []):
            if isinstance(x, dict) and x.get("id"):
                by_id[x["id"]] = f
    used = {f.name for f in by_id.values()}
    for pf in pfs:
        pid = str(pf.get("id") or "")
        if not pid:
            continue
        old = by_id.get(pid)
        name = safe_name(pf.get("name"), pid) + ".json"
        if old and old.name == name:
            target = old
        else:
            if name in used or (folder / name).exists():
                name = safe_name(pf.get("name"), pid) + f" ({re.sub('[^A-Za-z0-9]', '', pid)[:6]}).json"
            target = folder / name
        write_if_changed(target, json.dumps({"version": 2, "portfolio": pf}, indent=2, ensure_ascii=False))
        used.add(target.name)
        if old and old != target and old.exists():  # portafoglio rinominato: via il file col vecchio nome
            old.unlink()
    trash = folder / "_eliminati"
    for pid in removed or []:
        f = by_id.get(pid)
        if f and f.exists() and pid not in {str(p.get("id")) for p in pfs}:
            trash.mkdir(exist_ok=True)
            shutil.move(str(f), str(trash / f.name))
    if default:
        write_if_changed(folder / "_impostazioni.json", json.dumps({"default": default}, ensure_ascii=False))
    return pf_read()


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

    def same_origin(self):
        o = self.headers.get("Origin")
        return not o or urlparse(o).netloc == self.headers.get("Host")

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def api(self):
        u = urlparse(self.path)
        if u.path == "/api/ping":
            return self.reply(200, {"ok": True, "local": True, "folder": STATE["folder"]})
        if u.path in ("/api/pf", "/api/config", "/api/drive"):
            if self.command == "POST" and not self.same_origin():
                return self.reply(403, {"ok": False, "error": "origine non consentita"})
            try:
                if u.path == "/api/drive":
                    return self.reply(200, {"ok": True, "folder": STATE["folder"], "candidates": drive_candidates()})
                if u.path == "/api/config":
                    set_folder(str(self.body().get("folder") or "").strip())
                    return self.reply(200, {"ok": True, "folder": STATE["folder"]})
                if not STATE["folder"]:
                    return self.reply(200, {"ok": False, "error": "nessuna cartella scelta"})
                if self.command == "POST":
                    b = self.body()
                    return self.reply(200, pf_write(b.get("portfolios") or [], b.get("default"), b.get("removed") or []))
                return self.reply(200, pf_read())
            except Exception as e:
                return self.reply(200, {"ok": False, "error": str(e)})
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
    """Scheda del browser predefinito, oppure (app=True) finestra senza barra con Edge o Chrome se ci sono. True se ha aperto la finestra."""
    if app:
        for base in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                exe = os.path.join(os.environ.get(base, ""), rel)
                if os.environ.get(base) and os.path.exists(exe):
                    subprocess.Popen([exe, f"--app={url}"])
                    return True
    webbrowser.open(url)
    return False


def run_gui(url):
    """Finestra propria di myMoney (WebView2 tramite pywebview), senza barra del browser. Resta qui finché la finestra è aperta.
    Restituisce False se non è disponibile (pywebview o WebView2 mancanti): si ripiega su Edge/Chrome o sul browser."""
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True  # «Esporta» scarica un file
        webview.create_window("myMoney", url, width=1240, height=860, min_size=(380, 560))
        webview.start(gui="edgechromium" if os.name == "nt" else None, private_mode=False, storage_path=str(ROOT / "dati-finestra"))
        return True
    except Exception as e:
        print("Finestra propria non disponibile:", repr(e))
        return False


def message(text):
    """Finestra di avviso (Windows); altrove niente."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "myMoney", 0x40)
            return True
        except Exception:
            pass
    return False


def show(url, mode, hold):
    """Apre myMoney nel modo scelto. mode: 'gui' (finestra propria, poi Edge/Chrome, poi browser), 'finestra', 'browser'.
    hold=True: il processo tiene acceso il server e, se la finestra è del browser, aspetta che l'utente lo chiuda da qui."""
    if mode == "gui" and run_gui(url):
        return "chiusa"
    opened = open_window(url, mode in ("gui", "finestra"))
    if hold and not message("myMoney è aperto nel browser. Premi OK per spegnerlo."):
        threading.Event().wait()  # senza finestra di avviso (Linux, console): resta acceso finché non lo fermi
    return "aperto" if opened else "scheda"


def main():
    a = sys.argv[1:]
    host = a[a.index("--host") + 1] if "--host" in a else "127.0.0.1"
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8000
    load_cfg()
    if "--portafogli" in a:
        set_folder(a[a.index("--portafogli") + 1])
    mode = None if "--solo-server" in a else "browser" if "--browser" in a else "finestra" if "--finestra" in a else "gui" if FROZEN and "--abrir" not in a else "browser" if "--abrir" in a else None
    srv = None
    for p in range(port, port + 11):
        if mode and pinged(p):  # c'è già un myMoney acceso: basta aprire una finestra
            print(f"myMoney è già acceso su http://localhost:{p}")
            show(f"http://localhost:{p}", mode, hold=False)
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
    if not mode:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nFermato")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        show(url, mode, hold=True)
    except KeyboardInterrupt:
        print("\nFermato")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("Errore:", repr(e))
        if FROZEN:
            message(f"myMoney non si è avviato: {e!r}\n(vedi myMoney.log nella cartella)")
        raise
