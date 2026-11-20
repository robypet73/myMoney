#!/usr/bin/env python3
"""francesca: apre la pagina del portafoglio nel browser e scarica i prezzi aggiornati dei fondi.

Ogni portafoglio è un file HTML nella cartella del programma (francesca.html, e quelli salvati dalla pagina con «Salva come nuovo portafoglio»).
All'avvio si apre l'ultimo aperto; dal menu in alto nella pagina si passa a qualsiasi altro.

Prezzi da Yahoo Finance (quotazioni di Borsa Italiana); se Yahoo non risponde, da justETF. Solo libreria standard di Python (3.9 o più recente).

Avvio:  avvia.cmd  (doppio clic su Windows)   oppure   python francesca.py
Opzioni: --minuti 5  --porta 8800  --no-browser  --file nome.html (apre quel portafoglio invece dell'ultimo)

Il programma ascolta solo su 127.0.0.1 e serve soltanto i file HTML dei portafogli nella sua cartella. L'ultimo scarico è salvato nella cartella dell'utente
(Windows: %LOCALAPPDATA%\\francesca\\prezzi.json), non accanto ai file del programma.
"""
import argparse
import datetime
import html
import json
import os
import re
import tempfile
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = "francesca.html"  # portafoglio di partenza
NOME = "francesca"
NOME_PF = re.compile(r"^[A-Za-z0-9]{1,30}$")  # nome di un portafoglio: solo lettere e cifre
FILE_PF = re.compile(r"^[A-Za-z0-9_-]{1,80}\.html$")
RE_DATI = re.compile(r'(<script type="application/json" id="dati">)(.*?)(</script>)', re.S)
RE_META = re.compile(r'<script type="application/json" id="dati">\{"meta":(\{[^{}]*\})', re.S)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
FONTE_YAHOO = "Yahoo Finance (Borsa Italiana)"
FONTE_JETF = "justETF (quotazione di riferimento: può differire di qualche centesimo da Borsa Italiana)"


def cartella_dati():
    """Dove salvare l'ultimo scarico: cartella dell'utente, così il repository non si sporca."""
    base = os.environ.get("LOCALAPPDATA")
    d = os.path.join(base, NOME) if base else os.path.join(os.path.expanduser("~"), "." + NOME)
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return tempfile.gettempdir()


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

    def aggiorna(self, avanza=None):
        """Un giro di scarico. Ritorna il documento aggiornato.
        avanza(evento) riceve l'avanzamento: {"t": "inizio"|"titolo"|"dati"|"errore"|"avviso", ...}; la pagina lo mostra nella finestra di scarico."""
        def say(**ev):
            if avanza:
                try:
                    avanza(ev)
                except Exception:  # chi ascolta se n'è andato: lo scarico continua comunque
                    pass
        with self.scarico:  # un solo scarico alla volta
            vecchi = self.leggi()
            prezzi = dict(vecchi["prezzi"])
            storico = {d: dict(v) for d, v in vecchi["storico"].items()}
            avvisi, fonti, yahoo_ok, risposte = [], set(), True, 0
            say(t="inizio", n=len(self.titoli))
            for k, (sigla, t) in enumerate(self.titoli.items(), 1):
                serie, fonte = None, ""
                say(t="titolo", s=sigla, isin=t["isin"], k=k, n=len(self.titoli))
                if yahoo_ok:
                    try:
                        serie = self.yahoo(t["sym"])
                        fonti.add(FONTE_YAHOO)
                        fonte = "Yahoo Finance"
                    except Exception as e:
                        yahoo_ok = False  # Yahoo blocca: per gli altri titoli si passa subito a justETF
                        say(t="avviso", testo=f"Yahoo non risponde ({e}): passo a justETF")
                if serie is None:
                    try:
                        serie = self.justetf(t["isin"])
                        fonti.add(FONTE_JETF)
                        fonte = "justETF"
                    except Exception:
                        avvisi.append(f"{sigla}: prezzo non scaricato")
                        say(t="errore", s=sigla, testo=f"{sigla}: prezzo non scaricato")
                        continue
                risposte += 1
                say(t="dati", s=sigla, isin=t["isin"], fonte=fonte, righe=[[d, p] for d, p in serie])
                prec = (prezzi.get(sigla) or {}).get("p") or t["p0"]
                ok = True
                for d, p in serie:
                    if d <= self.base:
                        continue
                    if not 0.6 < p / prec < 1.6:
                        avvisi.append(f"{sigla}: prezzo anomalo il {d} ({p}), ignorato")
                        say(t="avviso", testo=avvisi[-1])
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
            say(t="salvato", n=len(prezzi))
            return self.leggi()


# ---- portafogli: un file HTML ciascuno nella cartella del programma
def _num_versione(v):
    m = re.fullmatch(r"V(\d+)", str(v))
    return int(m.group(1)) if m else 0


class Portafogli:
    """Elenco dei file HTML che sono portafogli, ultimo aperto (ricordato nella cartella dell'utente) e salvataggio di un nuovo portafoglio."""

    def __init__(self, cartella, file_ultimo, predefinito=HTML):
        self.dir, self.file_ultimo, self.predefinito = cartella, file_ultimo, predefinito
        self.lock = threading.Lock()

    def percorso(self, nomefile):
        return os.path.join(self.dir, nomefile)

    def info(self, nomefile):
        """{file, nome, versione, descrizione} se nomefile è un portafoglio della cartella, altrimenti None."""
        if not FILE_PF.match(nomefile or ""):
            return None
        try:
            with open(self.percorso(nomefile), encoding="utf-8") as fh:
                m = RE_META.search(fh.read())
            if not m:
                return None
            meta = json.loads(m.group(1))
        except (OSError, ValueError):
            return None
        return {"file": nomefile, "nome": meta.get("nome") or nomefile[:-5], "versione": meta.get("versione") or "V1", "descrizione": meta.get("descrizione") or ""}

    def elenco(self):
        try:
            nomi = [n for n in os.listdir(self.dir) if FILE_PF.match(n)]
        except OSError:
            return []
        r = [i for i in (self.info(n) for n in nomi) if i]
        return sorted(r, key=lambda i: (i["nome"].lower(), _num_versione(i["versione"]), i["file"]))

    def ultimo(self):
        try:
            with open(self.file_ultimo, encoding="utf-8") as fh:
                f = json.load(fh).get("file")
            if self.info(f):
                return f
        except (OSError, ValueError, AttributeError):
            pass
        if self.info(self.predefinito):
            return self.predefinito
        e = self.elenco()
        return e[0]["file"] if e else None

    def segna(self, nomefile):
        try:
            with open(self.file_ultimo, "w", encoding="utf-8") as fh:
                json.dump({"file": nomefile}, fh)
        except OSError:
            pass

    def salva(self, da, nome, versione, descrizione, pesi):
        """Crea nome_V<n>.html partendo dal portafoglio `da` con i nuovi pesi. Ritorna info del nuovo file; ValueError con un messaggio per l'utente se qualcosa non va."""
        if not self.info(da):
            raise ValueError("Portafoglio di partenza non trovato.")
        if not isinstance(nome, str) or not NOME_PF.match(nome):
            raise ValueError("Il nome può avere solo lettere e cifre (niente spazi né simboli), al massimo 30 caratteri.")
        try:
            v = int(str(versione).lstrip("Vv"))
        except ValueError:
            v = 0
        if not 1 <= v <= 999:
            raise ValueError("La versione deve essere un numero da 1 a 999 (V1, V2, V3…).")
        descrizione = " ".join(str(descrizione or "").split())
        if not descrizione:
            raise ValueError("Scrivi una breve descrizione.")
        if len(descrizione) > 300:
            raise ValueError("La descrizione può avere al massimo 300 caratteri.")
        with open(self.percorso(da), encoding="utf-8") as fh:
            t = fh.read()
        m = RE_DATI.search(t)
        d = json.loads(m.group(2))
        if not isinstance(pesi, dict) or set(pesi) != {f["s"] for f in d["funds"]}:
            raise ValueError("I pesi non corrispondono ai fondi del portafoglio.")
        try:
            w = {k: round(float(x), 3) for k, x in pesi.items()}
        except (TypeError, ValueError):
            raise ValueError("Pesi non validi.")
        if min(w.values()) < 0 or abs(sum(w.values()) - 1) > 0.0015:
            raise ValueError("I pesi devono essere positivi e dare 100%.")
        versione = f"V{v}"
        nuovo = f"{nome}_{versione}.html"
        amount, chiave = d["meta"]["amount"], f"pf-{nome}-{versione}"
        for f in d["funds"]:
            f["w"] = w[f["s"]]
            f["q0"] = int(amount * f["w"] / f["p0"])  # quote del piano d'esempio: il piano diviso il prezzo, per difetto
        meta = {"nome": nome, "versione": versione, "descrizione": descrizione, "chiave": chiave, "da": da, "creato": datetime.date.today().isoformat()}
        meta.update({k: x for k, x in d["meta"].items() if k not in meta})
        d["meta"] = meta
        corpo = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        t = t[:m.start()] + m.group(1) + corpo + m.group(3) + t[m.end():]
        t = re.sub(r"<title>.*?</title>", lambda _: f"<title>{html.escape(nome)}</title>", t, count=1, flags=re.S)
        with self.lock:
            try:
                with open(self.percorso(nuovo), "x", encoding="utf-8") as fh:
                    fh.write(t)
            except FileExistsError:
                libere = max([_num_versione(i["versione"]) for i in self.elenco() if i["nome"] == nome] + [v]) + 1
                raise ValueError(f"Esiste già {nuovo}: usa la versione V{libere}.")
        return self.info(nuovo)


# ---- server locale: solo 127.0.0.1, solo i file dei portafogli
def crea_server(prezzi, porta, portafogli):
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
            if p == "/api/portafogli":
                return self.invia(200, {"ultimo": portafogli.ultimo(), "lista": portafogli.elenco()})
            if p == "/":  # apre l'ultimo portafoglio aperto
                f = portafogli.ultimo()
                if not f:
                    return self.invia(404, {"errore": "nessun portafoglio nella cartella"})
                self.send_response(302)
                self.send_header("Location", "/" + f)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            f = p[1:]
            if portafogli.info(f):
                try:
                    corpo = open(portafogli.percorso(f), "rb").read()
                except OSError:
                    return self.invia(404, {"errore": f + " manca"})
                portafogli.segna(f)
                return self.invia(200, corpo, "text/html; charset=utf-8")
            return self.invia(404, {"errore": "non trovato"})

        def do_POST(self):
            if not (self.host_ok() and self.origine_ok()):
                return self.invia(403, {"errore": "richiesta non ammessa"})
            percorso = self.path.split("?")[0]
            if percorso == "/api/salva":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 65536:
                    return self.invia(413, {"errore": "richiesta troppo grande"})
                try:
                    r = json.loads(self.rfile.read(n))
                    if not isinstance(r, dict):
                        raise ValueError("richiesta non valida")
                    nuovo = portafogli.salva(r.get("da"), r.get("nome"), r.get("versione"), r.get("descrizione"), r.get("pesi"))
                except ValueError as e:  # include json.JSONDecodeError
                    return self.invia(400, {"errore": str(e) or "richiesta non valida"})
                except OSError as e:
                    return self.invia(500, {"errore": f"file non scritto: {e}"})
                return self.invia(200, nuovo)
            if percorso != "/api/aggiorna":
                return self.invia(404, {"errore": "non trovato"})
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            # risposta a flusso: una riga JSON per ogni passo dello scarico, l'ultima {"t": "fine", "dati": {...}}
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            def riga(ev):
                self.wfile.write(json.dumps(ev, ensure_ascii=False).encode() + b"\n")
                self.wfile.flush()

            try:
                if time.time() - prezzi.ultimo_tentativo < 15:  # clic ravvicinati: si riusa l'ultimo scarico
                    riga({"t": "riuso"})
                    dati = prezzi.leggi()
                else:
                    try:
                        dati = prezzi.aggiorna(riga)
                    except (BrokenPipeError, ConnectionError):
                        raise
                    except Exception as e:  # un errore imprevisto non deve lasciare la pagina senza risposta
                        print("errore nello scarico:", e, flush=True)
                        riga({"t": "errore", "testo": f"errore nello scarico: {e}"})
                        dati = prezzi.leggi()
                        dati["avvisi"] = list(dati.get("avvisi") or []) + [f"errore nello scarico: {e}"]
                        dati["risposte"] = 0
                riga({"t": "fine", "dati": dati})
            except (BrokenPipeError, ConnectionError):
                pass  # la pagina ha chiuso la finestra: lo scarico è già salvato

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
    ap.add_argument("--file", help="apre questo portafoglio (file HTML nella cartella) invece dell'ultimo aperto")
    a = ap.parse_args()
    cartella = os.path.dirname(os.path.abspath(__file__))
    dati = cartella_dati()
    pf = Portafogli(cartella, os.path.join(dati, "ultimo.json"))
    if a.file:
        if not pf.info(os.path.basename(a.file)):
            sys.exit(f"{a.file} non è un portafoglio presente nella cartella del programma.")
        pf.segna(os.path.basename(a.file))
    aperto = pf.ultimo()
    if not aperto:
        sys.exit(f"Nella cartella non c'è nessun portafoglio ({HTML} manca).")
    titoli, base = carica_config(pf.percorso(aperto))
    file_prezzi = os.path.join(dati, "prezzi.json")
    prezzi = Prezzi(titoli, base, file_prezzi)
    srv = None
    for porta in range(a.porta, a.porta + 20):  # se la porta è occupata prova la successiva
        try:
            srv = crea_server(prezzi, porta, pf)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"Le porte da {a.porta} a {a.porta + 19} sono occupate.")
    ferma = threading.Event()
    threading.Thread(target=ciclo, args=(prezzi, a.minuti, ferma), daemon=True).start()
    url = f"http://127.0.0.1:{porta}/"
    print("Pagina:", url, "- lascia aperta questa finestra; chiudila o premi Ctrl+C per fermare i prezzi.", flush=True)
    print("Portafoglio aperto:", aperto, "- nella pagina puoi passare agli altri:", ", ".join(i["file"] for i in pf.elenco()), flush=True)
    print("Ultimo scarico salvato in:", file_prezzi, flush=True)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ferma.set()
        srv.server_close()


if __name__ == "__main__":
    avvia_app()
