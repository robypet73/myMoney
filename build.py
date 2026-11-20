#!/usr/bin/env python3
"""francesca: crea l'eseguibile Windows della pagina del portafoglio (dist/francesca.exe).

Il programma, quando lo lanci, apre il browser su francesca.html e scarica i prezzi aggiornati dei fondi (Yahoo Finance; se non risponde, justETF).

Costruire l'eseguibile (serve Windows con Python 3.9 o più recente; PyInstaller si installa da solo):
    python build.py
Provare senza costruire (qualsiasi sistema):
    python build.py --esegui
Opzioni del programma (anche per francesca.exe): --minuti 5  --porta 8800  --no-browser

Un eseguibile Windows si può costruire solo su Windows. Su Mac o Linux lo stesso comando crea il programma per quel sistema.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = "francesca.html"
NOME = "francesca"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
FONTE_YAHOO = "Yahoo Finance (Borsa Italiana)"
FONTE_JETF = "justETF (quotazione di riferimento: può differire di qualche centesimo da Borsa Italiana)"


# =====================================================================================================================
# Programma che gira dentro l'eseguibile
# =====================================================================================================================
def cartella_risorse():
    """Cartella da cui leggere francesca.html: quella interna dell'eseguibile, oppure quella dello script."""
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


def cartella_dati():
    """Dove salvare l'ultimo scarico: accanto all'eseguibile se si può scrivere, altrimenti nella cartella dell'utente."""
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    try:
        prova = os.path.join(base, ".prova_scrittura")
        open(prova, "w").close()
        os.remove(prova)
        return base
    except OSError:
        alt = os.path.join(os.path.expanduser("~"), "." + NOME)
        os.makedirs(alt, exist_ok=True)
        return alt


def carica_config(percorso):
    """Fondi, ISIN, simbolo Yahoo, prezzo di riferimento e data base dell'incorporato nella pagina: la pagina è l'unica fonte."""
    t = open(percorso, encoding="utf-8").read()
    m = re.search(r'<script type="application/json" id="dati">(.*?)</script>', t, re.S)
    if not m:
        raise RuntimeError("Nella pagina non trovo i dati dei fondi.")
    d = json.loads(m.group(1))
    return {f["s"]: {"isin": f["isin"], "sym": f["sym"], "p0": float(f["p0"])} for f in d["funds"]}, d["meta"]["base"]


# ---- orario di borsa
def _ultima_domenica(anno, mese):
    d = datetime.date(anno, mese, 31)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def ora_italiana(utc=None):
    utc = utc or datetime.datetime.now(datetime.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # Windows senza il pacchetto dei fusi: ora legale dall'ultima domenica di marzo a quella di ottobre
        a = utc.year
        ini = datetime.datetime.combine(_ultima_domenica(a, 3), datetime.time(1), datetime.timezone.utc)
        fin = datetime.datetime.combine(_ultima_domenica(a, 10), datetime.time(1), datetime.timezone.utc)
        return utc.astimezone(datetime.timezone(datetime.timedelta(hours=2 if ini <= utc < fin else 1)))


def borsa_aperta(utc=None):
    t = ora_italiana(utc)
    return t.weekday() < 5 and datetime.time(9, 0) <= t.time() <= datetime.time(17, 40)


# ---- fonti dei prezzi
def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25))


def parse_yahoo(res):
    """[(data ISO, chiusura)] dal risultato 'chart' di Yahoo; l'ultima riga è il prezzo corrente se la seduta è aperta."""
    r = res["chart"]["result"][0]
    off = (r.get("meta") or {}).get("gmtoffset", 3600)
    cl = r["indicators"]["quote"][0]["close"]
    return [(datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).strftime("%Y-%m-%d"), round(float(c), 4)) for t, c in zip(r["timestamp"], cl) if c]


def yahoo(simbolo):
    errore = None
    for k in range(2):
        try:
            return parse_yahoo(get(f"https://query{1 + k}.finance.yahoo.com/v8/finance/chart/{simbolo}?range=3mo&interval=1d"))
        except Exception as e:
            errore = e
            time.sleep(2)
    raise RuntimeError(f"Yahoo: {errore}")


def justetf(isin):
    q = get(f"https://www.justetf.com/api/etfs/{isin}/quote?locale=it&currency=EUR&isin={isin}")
    return [(q["latestQuoteDate"], round(float(q["latestQuote"]["raw"]), 4))]


class Prezzi:
    """Ultimo scarico dei prezzi: documento {at, fonte, prezzi, storico, avvisi, risposte} che la pagina legge da /api/prezzi."""

    def __init__(self, titoli, base, file_prezzi, scarica_yahoo=yahoo, scarica_justetf=justetf):
        self.titoli, self.base, self.file = titoli, base, file_prezzi
        self.yahoo, self.justetf = scarica_yahoo, scarica_justetf
        self.lock, self.scarico = threading.Lock(), threading.Lock()
        self.dati = {"at": None, "fonte": "", "prezzi": {}, "storico": {}, "avvisi": [], "risposte": 0}
        self.ultimo_tentativo = 0.0
        try:
            d = json.load(open(self.file, encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("prezzi"), dict):
                self.dati.update(d)
        except Exception:
            pass

    def leggi(self):
        with self.lock:
            return json.loads(json.dumps(self.dati))

    def aggiorna(self):
        """Un giro di scarico. Ritorna il documento aggiornato."""
        with self.scarico:  # un solo scarico alla volta
            vecchi = self.leggi()
            prezzi = dict(vecchi["prezzi"])
            storico = {d: dict(v) for d, v in vecchi["storico"].items()}
            avvisi, fonti, yahoo_ok, risposte = [], set(), True, 0
            for sigla, t in self.titoli.items():
                serie = None
                if yahoo_ok:
                    try:
                        serie = self.yahoo(t["sym"])
                        fonti.add(FONTE_YAHOO)
                    except Exception:
                        yahoo_ok = False  # Yahoo blocca: per gli altri titoli si passa subito a justETF
                if serie is None:
                    try:
                        serie = self.justetf(t["isin"])
                        fonti.add(FONTE_JETF)
                    except Exception:
                        avvisi.append(f"{sigla}: prezzo non scaricato")
                        continue
                risposte += 1
                prec = (prezzi.get(sigla) or {}).get("p") or t["p0"]
                ok = True
                for d, p in serie:
                    if d <= self.base:
                        continue
                    if not 0.6 < p / prec < 1.6:
                        avvisi.append(f"{sigla}: prezzo anomalo il {d} ({p}), ignorato")
                        ok = False
                        break
                    storico.setdefault(d, {})[sigla] = p
                    prec = p
                ultime = [x for x in serie if x[0] > self.base]
                if ok and ultime:
                    prezzi[sigla] = {"p": ultime[-1][1], "d": ultime[-1][0]}
                time.sleep(0.3)
            nuovo = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fonte": " + ".join(sorted(fonti)) or vecchi.get("fonte", ""),
                     "prezzi": prezzi, "storico": storico, "avvisi": avvisi, "risposte": risposte}
            with self.lock:
                self.dati = nuovo
            try:
                tmp = self.file + ".tmp"
                json.dump(nuovo, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
                os.replace(tmp, self.file)
            except OSError as e:
                nuovo["avvisi"].append(f"prezzi.json non salvato: {e}")
            self.ultimo_tentativo = time.time()
            return self.leggi()


# ---- server locale: solo 127.0.0.1, un solo file servito
def crea_server(prezzi, porta, percorso_html):
    ammessi = {f"127.0.0.1:{porta}", f"localhost:{porta}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def invia(self, codice, corpo, tipo="application/json; charset=utf-8"):
            b = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
            self.send_response(codice)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(b)

        def host_ok(self):  # difesa dal DNS rebinding
            return (self.headers.get("Host") or "") in ammessi

        def origine_ok(self):
            o = self.headers.get("Origin")
            return o is None or o.replace("http://", "") in ammessi

        def do_GET(self):
            if not self.host_ok():
                return self.invia(403, {"errore": "host non ammesso"})
            p = self.path.split("?")[0]
            if p == "/api/prezzi":
                return self.invia(200, prezzi.leggi())
            if p in ("/", "/" + HTML):
                try:
                    return self.invia(200, open(percorso_html, "rb").read(), "text/html; charset=utf-8")
                except OSError:
                    return self.invia(404, {"errore": HTML + " manca"})
            return self.invia(404, {"errore": "non trovato"})

        def do_POST(self):
            if not (self.host_ok() and self.origine_ok()):
                return self.invia(403, {"errore": "richiesta non ammessa"})
            if self.path.split("?")[0] != "/api/aggiorna":
                return self.invia(404, {"errore": "non trovato"})
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if time.time() - prezzi.ultimo_tentativo < 15:  # clic ravvicinati: si riusa l'ultimo scarico
                return self.invia(200, prezzi.leggi())
            self.invia(200, prezzi.aggiorna())

    return ThreadingHTTPServer(("127.0.0.1", porta), H)


def ciclo(prezzi, minuti, ferma):
    while not ferma.is_set():
        try:
            d = prezzi.aggiorna()
            print(time.strftime("%H:%M:%S"), f"risposte {d.get('risposte', 0)}/{len(prezzi.titoli)}, prezzi nuovi {len(d['prezzi'])} -", d["fonte"] or "nessuna fonte",
                  ("- avvisi: " + "; ".join(d["avvisi"])) if d["avvisi"] else "", flush=True)
        except Exception as e:
            print("errore nello scarico:", e, flush=True)
        ferma.wait(minuti * 60 if borsa_aperta() else max(minuti, 60) * 60)


def avvia_app():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog=NOME, description="Apre la pagina del portafoglio e scarica i prezzi aggiornati.")
    ap.add_argument("--minuti", type=float, default=5, help="ogni quanti minuti scaricare con la borsa aperta (fuori orario ogni 60)")
    ap.add_argument("--porta", type=int, default=8800)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    percorso = os.path.join(cartella_risorse(), HTML)
    if not os.path.exists(percorso):
        sys.exit(f"Manca {HTML}.")
    titoli, base = carica_config(percorso)
    prezzi = Prezzi(titoli, base, os.path.join(cartella_dati(), "prezzi.json"))
    srv = None
    for porta in range(a.porta, a.porta + 20):  # se la porta è occupata prova la successiva
        try:
            srv = crea_server(prezzi, porta, percorso)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"Le porte da {a.porta} a {a.porta + 19} sono occupate.")
    ferma = threading.Event()
    threading.Thread(target=ciclo, args=(prezzi, a.minuti, ferma), daemon=True).start()
    url = f"http://127.0.0.1:{porta}/"
    print("Pagina:", url, "- lascia aperta questa finestra; chiudila o premi Ctrl+C per fermare i prezzi.", flush=True)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ferma.set()
        srv.server_close()


# =====================================================================================================================
# Costruzione dell'eseguibile
# =====================================================================================================================
def costruisci():
    aqui = os.path.dirname(os.path.abspath(__file__))
    html = os.path.join(aqui, HTML)
    if not os.path.exists(html):
        sys.exit(f"Manca {HTML} accanto a build.py.")
    carica_config(html)  # controlla che la pagina contenga i dati dei fondi
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installo PyInstaller...", flush=True)
        if subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"]) != 0:
            sys.exit("Non riesco a installare PyInstaller: prova 'pip install pyinstaller' e rilancia build.py.")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", NOME, "--exclude-module", "tkinter",
           "--add-data", f"{html}{os.pathsep}.", "--distpath", os.path.join(aqui, "dist"), "--workpath", os.path.join(aqui, "build"), "--specpath", os.path.join(aqui, "build"),
           os.path.abspath(__file__)]
    if subprocess.call(cmd, cwd=aqui) != 0:
        sys.exit("La costruzione non è riuscita: guarda i messaggi sopra.")
    exe = os.path.join(aqui, "dist", NOME + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(exe):
        sys.exit("PyInstaller non ha creato il programma atteso: " + exe)
    print(f"\nFatto: {exe}\nLancialo con un doppio clic: apre il browser e scarica i prezzi.", flush=True)


if __name__ == "__main__":
    if getattr(sys, "frozen", False) or "--esegui" in sys.argv:
        sys.argv = [x for x in sys.argv if x != "--esegui"]
        avvia_app()
    else:
        costruisci()
