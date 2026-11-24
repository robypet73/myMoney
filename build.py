#!/usr/bin/env python3
"""build: apre nel browser la pagina portafoglio.html con l'ultimo portafoglio caricato e scarica da justETF i prezzi aggiornati.

Ogni portafoglio è un file JSON nella cartella «portafogli» (nome_V1.json, nome_V2.json…; lo schema è portafogli/schema.json).
La pagina è una sola, portafoglio.html: il programma la serve con i dati del portafoglio scelto. All'apertura si carica l'ultimo portafoglio aperto
e parte subito lo scarico dei prezzi; dal menu in alto si passa a qualsiasi altro JSON della cartella.

Tutti i dati vengono da justETF (scheda del fondo, storico e prezzi). Solo libreria standard di Python (3.9 o più recente).

Avvio:  avvia.cmd  (doppio clic su Windows)   oppure   python build.py
Opzioni: --minuti 5  --porta 8800  --no-browser  --file nome_V1.json (apre quel portafoglio invece dell'ultimo)

Il programma ascolta solo su 127.0.0.1. I dati scaricati (ultimo scarico dei prezzi, scheda e storico di ogni titolo) stanno nella cartella dell'utente
(Windows: %LOCALAPPDATA%\\myMoney), non accanto ai file del programma.
"""
import argparse
import datetime
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import fonti
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELLO = "portafoglio.html"  # l'unica pagina: il codice di ogni portafoglio, i dati vengono inseriti al momento
CARTELLA_PF = "portafogli"  # i JSON dei portafogli (e lo schema)
NOME = "myMoney"  # nome del programma e della sua cartella dati: non è quello di un portafoglio
NOME_VECCHIO = "francesca"  # cartella dati delle versioni precedenti: se c'è, se ne copia il contenuto
HOST_REMOTI = ("script.google.com", "script.googleusercontent.com")  # Google Drive «online»: una piccola web app di Google Apps Script (drive/mymoney_drive.gs) legge e scrive la cartella
FILE_SCRIPT_DRIVE = os.path.join("drive", "mymoney_drive.gs")
FILE_FINECO = "fineco_gratis.json"  # ETF a zero commissioni di acquisto su Fineco (si aggiorna con aggiorna_fineco.py)
NOME_PF = re.compile(r"^[A-Za-z0-9]{1,30}$")  # nome di un portafoglio: solo lettere e cifre
FILE_PF = re.compile(r"^[A-Za-z0-9]{1,30}_V[0-9]{1,3}\.json$")
RE_DATI = re.compile(r'(<script type="application/json" id="dati">)(.*?)(</script>)', re.S)
FONTE = "justETF"
CLASSI = ("Azionario", "Obbligazionario", "Materie prime")


def cartella_dati():
    """Dove salvare i dati scaricati: cartella dell'utente, così il repository non si sporca."""
    base = os.environ.get("LOCALAPPDATA")
    cartella = lambda n: os.path.join(base, n) if base else os.path.join(os.path.expanduser("~"), "." + n)
    d, vecchia = cartella(NOME), cartella(NOME_VECCHIO)
    try:
        os.makedirs(d, exist_ok=True)
        if os.path.isdir(vecchia) and not os.listdir(d):  # una volta sola: porta con sé prezzi.json (e l'ultimo portafoglio aperto) dalla cartella di prima
            for f in os.listdir(vecchia):
                try:
                    shutil.copy2(os.path.join(vecchia, f), os.path.join(d, f))
                except OSError:
                    pass
        return d
    except OSError:
        return tempfile.gettempdir()


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


# ---- prezzi: solo justETF
def justetf(isin):
    """[(data, prezzo in euro)] degli ultimi giorni feriali da justETF; l'ultimo è il valore in corso."""
    return fonti.serie(isin, dal=(datetime.date.today() - datetime.timedelta(days=12)).isoformat())


class Prezzi:
    """Ultimo scarico dei prezzi: documento {at, fonte, prezzi, storico, avvisi, risposte} che la pagina legge da /api/prezzi."""

    def __init__(self, titoli, base, file_prezzi, scarica=justetf):
        self.titoli, self.base, self.file = titoli, base, file_prezzi
        self.scarica = scarica
        self.lock, self.scarico = threading.Lock(), threading.Lock()
        self.dati = {"at": None, "fonte": "", "prezzi": {}, "storico": {}, "avvisi": [], "risposte": 0}
        self.ultimo_tentativo = 0.0
        try:
            d = json.load(open(self.file, encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("prezzi"), dict):
                self.dati.update(d)
        except Exception:
            pass

    def aggiungi(self, titoli, base):
        """Titoli di un portafoglio aperto o creato: da ora si scaricano anche i loro prezzi."""
        with self.scarico:
            for sigla, t in titoli.items():
                self.titoli.setdefault(sigla, t)
            if base and (not self.base or base < self.base):
                self.base = base

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
            avvisi, risposte = [], 0
            say(t="inizio", n=len(self.titoli))
            for k, (sigla, t) in enumerate(self.titoli.items(), 1):
                say(t="titolo", s=sigla, isin=t["isin"], k=k, n=len(self.titoli))
                try:
                    serie = self.scarica(t["isin"])
                except Exception:
                    avvisi.append(f"{sigla}: prezzo non scaricato")
                    say(t="errore", s=sigla, testo=f"{sigla}: prezzo non scaricato")
                    continue
                risposte += 1
                say(t="dati", s=sigla, isin=t["isin"], fonte=FONTE, righe=[[d, p] for d, p in serie])
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
            # prezzo in tempo reale di gettex (lo stesso che mostra justETF): sostituisce l'ultimo prezzo XETRA del grafico
            live = {}
            try:
                q = fonti.gettex([t["isin"] for t in self.titoli.values()])
            except Exception:
                q = {}
            for sigla, t in self.titoli.items():
                x = q.get(t["isin"])
                if not x:
                    continue
                prec = (prezzi.get(sigla) or {}).get("p") or t["p0"]
                if 0.6 < x["p"] / prec < 1.6:
                    live[sigla] = {"p": x["p"], "t": x["t"], "d": x["d"]}
                else:
                    avvisi.append(f"{sigla}: prezzo gettex anomalo ({x['p']}), ignorato")
            if self.titoli and not live:
                avvisi.append("gettex non raggiunto: restano i prezzi XETRA di justETF")
            say(t="testo", testo=f"gettex: {len(live)} prezzi in tempo reale")
            nuovo = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fonte": FONTE if risposte else vecchi.get("fonte", ""),
                     "prezzi": prezzi, "storico": storico, "avvisi": avvisi, "risposte": risposte, "live": live}
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


# ---- portafogli: un file JSON ciascuno nella cartella «portafogli»
def _num_versione(v):
    m = re.fullmatch(r"V(\d+)", str(v))
    return int(m.group(1)) if m else 0


class Esiste(Exception):
    """Il portafoglio (stesso nome e versione) c'è già: .file è il suo file."""

    def __init__(self, file, testo):
        super().__init__(testo)
        self.file = file


def _intervallo(x, cosa):
    if not (isinstance(x, list) and len(x) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x) and 0 <= x[0] <= x[1] <= 100):
        raise ValueError(f"«vincoli»: {cosa} deve essere [minimo, massimo] in percentuale, da 0 a 100.")
    return [x[0], x[1]]


TIPI_TRANSAZIONE = ("acquisto", "vendita")


def valida_transazioni(tr, isin_ammessi):
    """Controlla le transazioni (facoltative): [{isin, data, tipo: acquisto|vendita, quote, prezzo}]. Ritorna la lista normalizzata e in ordine di data; ValueError con un messaggio chiaro se non va."""
    if tr is None:
        return []
    if not isinstance(tr, list) or len(tr) > 5000:
        raise ValueError("«transazioni»: un elenco (al massimo 5000) di {\"isin\", \"data\", \"tipo\", \"quote\", \"prezzo\"}.")
    out = []
    for k, x in enumerate(tr, 1):
        if not isinstance(x, dict):
            raise ValueError(f"«transazioni» n. {k}: deve essere un oggetto.")
        isin = str(x.get("isin") or "").strip().upper()
        if isin not in isin_ammessi:
            raise ValueError(f"«transazioni» n. {k}: l'ISIN «{isin}» non è tra i titoli del portafoglio (aggiungilo con peso 0 se l'hai già venduto).")
        data = x.get("data")
        try:
            datetime.date.fromisoformat(str(data))
        except ValueError:
            raise ValueError(f"«transazioni» n. {k} ({isin}): «data» deve essere AAAA-MM-GG.")
        tipo = x.get("tipo")
        if tipo not in TIPI_TRANSAZIONE:
            raise ValueError(f"«transazioni» n. {k} ({isin}): «tipo» deve essere «acquisto» o «vendita».")
        try:
            quote, prezzo = float(x.get("quote")), float(x.get("prezzo"))
        except (TypeError, ValueError):
            raise ValueError(f"«transazioni» n. {k} ({isin}): «quote» e «prezzo» devono essere numeri.")
        if not (quote > 0 and prezzo > 0):
            raise ValueError(f"«transazioni» n. {k} ({isin}): «quote» e «prezzo» devono essere maggiori di 0 (la vendita ha tipo «vendita», non quote negative).")
        if x.get("pianificata") not in (None, True, False):
            raise ValueError(f"«transazioni» n. {k} ({isin}): «pianificata» deve essere true o false.")
        nuova = {"isin": isin, "data": str(data), "tipo": tipo, "quote": int(quote) if quote == int(quote) else round(quote, 6), "prezzo": round(prezzo, 6)}
        if x.get("pianificata"):  # solo pianificata: non conta come investito, compare come «da investire»
            nuova["pianificata"] = True
        out.append(nuova)
    out.sort(key=lambda t: (t["data"], 0 if t["tipo"] == "acquisto" else 1))  # a pari data prima gli acquisti
    possedute = {}
    for t in (x for x in out if not x.get("pianificata")):  # il controllo sulle vendite vale per quelle eseguite
        q = possedute.get(t["isin"], 0) + (t["quote"] if t["tipo"] == "acquisto" else -t["quote"])
        if q < -1e-9:
            raise ValueError(f"Vendita di {t['isin']} del {t['data']}: stai vendendo più quote di quelle che avevi.")
        possedute[t["isin"]] = q
    return out


def valida_obiettivo(ob, isin_ammessi):
    """Quote obiettivo del piano proposto (facoltative): [{isin, quote}], quote >= 0. «Da investire» = quote obiettivo - quote che hai davvero (dalle transazioni)."""
    if ob is None:
        return []
    if not isinstance(ob, list) or len(ob) > 100:
        raise ValueError("«obiettivo»: un elenco di {\"isin\", \"quote\"}.")
    out, visti = [], set()
    for k, x in enumerate(ob, 1):
        isin = str((x or {}).get("isin") or "").strip().upper() if isinstance(x, dict) else ""
        if isin not in isin_ammessi:
            raise ValueError(f"«obiettivo» n. {k}: l'ISIN «{isin}» non è tra i titoli del portafoglio.")
        if isin in visti:
            raise ValueError(f"«obiettivo»: ISIN ripetuto ({isin}).")
        visti.add(isin)
        try:
            q = float(x.get("quote"))
        except (TypeError, ValueError):
            raise ValueError(f"«obiettivo» n. {k} ({isin}): «quote» deve essere un numero.")
        if not q >= 0:
            raise ValueError(f"«obiettivo» n. {k} ({isin}): «quote» non può essere negativo.")
        out.append({"isin": isin, "quote": int(q) if q == int(q) else round(q, 6)})
    return out


PESO_NUOVO = 1  # peso (%) di un titolo aggiunto senza indicare il peso: gli altri si riducono in proporzione


def valida_definizione(d):
    """Controlla il JSON di un portafoglio. Ritorna {nome, v, descrizione, amount, pesi: [(isin, peso 0-1)], vincoli}; ValueError con un messaggio chiaro se non va."""
    if not isinstance(d, dict):
        raise ValueError("Il JSON deve essere un oggetto con nome, versione, descrizione e titoli.")
    nome = d.get("nome")
    if not isinstance(nome, str) or not NOME_PF.match(nome):
        raise ValueError("«nome»: solo lettere e cifre, niente spazi né simboli, al massimo 30 caratteri.")
    try:
        v = int(str(d.get("versione")).strip().lstrip("Vv"))
    except ValueError:
        v = 0
    if not 1 <= v <= 999:
        raise ValueError("«versione»: V1, V2, V3… (un numero da 1 a 999).")
    descrizione = " ".join(str(d.get("descrizione") or "").split())
    if not descrizione:
        raise ValueError("«descrizione»: scrivi una breve descrizione.")
    if len(descrizione) > 300:
        raise ValueError("«descrizione»: al massimo 300 caratteri.")
    valore = d.get("valore")
    if valore is None:
        amount = 10000
    else:
        try:
            amount = round(float(valore), 2)
        except (TypeError, ValueError):
            raise ValueError("«valore»: un numero in euro (facoltativo).")
        if not 100 <= amount <= 1e9:
            raise ValueError("«valore»: tra 100 e 1.000.000.000 euro.")
        amount = int(amount) if amount == int(amount) else amount
    tit = d.get("titoli")
    if not isinstance(tit, list) or not 1 <= len(tit) <= 30:
        raise ValueError("«titoli»: da 1 a 30 elementi {\"isin\": …, \"peso\": …}.")
    visti, righe = set(), []
    for x in tit:
        isin = str(x.get("isin") or "").strip().upper() if isinstance(x, dict) else ""
        if not fonti.isin_valido(isin):
            raise ValueError(f"ISIN non valido: «{isin or x}».")
        if isin in visti:
            raise ValueError(f"ISIN ripetuto: {isin}.")
        visti.add(isin)
        try:
            peso = float(x.get("peso"))
        except (TypeError, ValueError):
            raise ValueError(f"{isin}: «peso» deve essere un numero (percentuale).")
        if not 0 <= peso <= 100:
            raise ValueError(f"{isin}: il peso deve essere tra 0 e 100 (0 per un titolo già venduto, che serve solo alle transazioni).")
        righe.append((isin, peso))
    tot = sum(p for _, p in righe)
    if abs(tot - 100) > 0.5:
        raise ValueError(f"I pesi danno {round(tot, 2)}%: devono dare 100%.")
    transazioni = valida_transazioni(d.get("transazioni"), visti)
    obiettivo = valida_obiettivo(d.get("obiettivo"), visti)
    vincoli = None
    if d.get("vincoli") is not None:
        vv = d["vincoli"]
        if not isinstance(vv, dict):
            raise ValueError("«vincoli»: un oggetto con «fondi» (per ISIN) e «classi».")
        fondi = {}
        for isin, x in (vv.get("fondi") or {}).items():
            if isin not in visti:
                raise ValueError(f"«vincoli»: {isin} non è tra i titoli del portafoglio.")
            fondi[isin] = _intervallo(x, isin)
        classi = {}
        for c, x in (vv.get("classi") or {}).items():
            if c not in CLASSI:
                raise ValueError(f"«vincoli»: classe «{c}» sconosciuta (ammesse: {', '.join(CLASSI)}).")
            classi[c] = _intervallo(x, c)
        vincoli = {"fondi": fondi, "classi": classi}
    frontiera = None  # come è stata calcolata la frontiera (anni di storico, rendimenti prudenti): riaprendo il portafoglio si ritrova la stessa curva
    if d.get("frontiera") is not None:
        fr = d["frontiera"]
        if not isinstance(fr, dict) or fr.get("finestra") not in (1, 3, 5) or not isinstance(fr.get("prudente"), bool):
            raise ValueError("«frontiera»: {\"finestra\": 1, 3 o 5 (anni di storico), \"prudente\": true o false}.")
        frontiera = {"finestra": fr["finestra"], "prudente": fr["prudente"]}
    return {"nome": nome, "v": v, "descrizione": descrizione, "amount": amount, "pesi": [(i, round(p / tot, 4)) for i, p in righe], "vincoli": vincoli, "transazioni": transazioni, "obiettivo": obiettivo, "frontiera": frontiera}


def formatta_definizione(d):
    """Testo del JSON di un portafoglio, leggibile: un titolo per riga, un vincolo per riga."""
    j = lambda x: json.dumps(x, ensure_ascii=False)
    righe = []
    for k, v in {"$schema": "schema.json", **{k: v for k, v in d.items() if k != "$schema"}}.items():
        if k == "titoli":
            righe.append('  "titoli": [\n' + ",\n".join("    " + j(x) for x in v) + "\n  ]")
        elif k in ("transazioni", "obiettivo"):
            righe.append(f'  {j(k)}: [\n' + ",\n".join("    " + j(x) for x in v) + "\n  ]")
        elif k == "vincoli":
            sub = [f'    {j(kk)}: {{' + ("\n" + ",\n".join(f"      {j(a)}: {j(c)}" for a, c in vv.items()) + "\n    }" if vv else "}") for kk, vv in v.items()]
            righe.append('  "vincoli": {\n' + ",\n".join(sub) + "\n  }")
        else:
            righe.append(f"  {j(k)}: {j(v)}")
    return "{\n" + ",\n".join(righe) + "\n}\n"


def _url_remoto(url):
    """Controlla l'indirizzo della web app di Google Apps Script (con ?key=…). Ritorna (indirizzo senza chiave, chiave); ValueError se non va."""
    u = urllib.parse.urlsplit((url or "").strip())
    if u.scheme != "https" or (u.hostname or "") not in HOST_REMOTI:
        raise ValueError("L'indirizzo deve essere quello della web app di Google (https://script.google.com/macros/s/…/exec?key=la-tua-chiave).")
    chiave = (urllib.parse.parse_qs(u.query).get("key") or [""])[0]
    if not chiave:
        raise ValueError("Manca la chiave: aggiungi in fondo all'indirizzo ?key= e la chiave scritta nello script.")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", "")), chiave


def _chiama_remoto(base, chiave, corpo=None):
    """GET (elenco) o POST (scrittura) alla web app. Ritorna il JSON della risposta; RuntimeError con un messaggio per l'utente se non va."""
    try:
        if corpo is None:
            rich = urllib.request.Request(base + "?" + urllib.parse.urlencode({"key": chiave}), headers={"User-Agent": "myMoney"})
        else:
            dati = json.dumps({**corpo, "key": chiave}, ensure_ascii=False).encode("utf-8")
            rich = urllib.request.Request(base, data=dati, headers={"Content-Type": "text/plain;charset=utf-8", "User-Agent": "myMoney"})
        with urllib.request.urlopen(rich, timeout=40) as r:
            r_json = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google Drive ha risposto con errore {e.code}: controlla che la distribuzione sia «App web», accesso «Chiunque».")
    except (urllib.error.URLError, OSError):
        raise RuntimeError("Non riesco a raggiungere Google Drive: controlla la connessione.")
    except ValueError:
        raise RuntimeError("La risposta di Google non è quella dello script: controlla l'indirizzo e che la distribuzione sia «App web», accesso «Chiunque».")
    if not isinstance(r_json, dict):
        raise RuntimeError("Risposta di Google Drive non valida.")
    if r_json.get("errore"):
        raise RuntimeError("Google Drive: " + str(r_json["errore"]))
    return r_json


def cartelle_suggerite():
    """Cartelle dove tenere i portafogli: Google Drive per desktop (Windows: unità virtuale G:, H:…; macOS: CloudStorage; cartella Google Drive nella home) e Documenti."""
    home = os.path.expanduser("~")
    nomi = ("Il mio Drive", "My Drive")
    radici = []
    if os.name == "nt":
        for lettera in "DEFGHIJKLMNOPQRSTUVWXYZ":
            for n in nomi:
                radici.append(f"{lettera}:\\{n}")
    cs = os.path.join(home, "Library", "CloudStorage")
    if os.path.isdir(cs):
        try:
            for d in sorted(os.listdir(cs)):
                if d.startswith("GoogleDrive"):
                    radici += [os.path.join(cs, d, n) for n in nomi]
        except OSError:
            pass
    for n in ("Google Drive", "GoogleDrive", "My Drive", "Il mio Drive"):
        base = os.path.join(home, n)
        sotto = [os.path.join(base, m) for m in nomi if os.path.isdir(os.path.join(base, m))]
        radici += sotto if sotto else [base]
    visti, out = set(), []
    for r in radici:
        k = os.path.normcase(os.path.abspath(r))
        if k not in visti and os.path.isdir(r):
            visti.add(k)
            out.append({"tipo": "drive", "percorso": os.path.join(os.path.abspath(r), "portafogli")})
    for n in ("Documents", "Documenti"):
        d = os.path.join(home, n)
        if os.path.isdir(d):
            out.append({"tipo": "documenti", "percorso": os.path.join(d, "portafogli")})
            break
    return out


_dialogo = threading.Lock()


def finestra_cartella(iniziale=""):
    """Apre la finestra di scelta di una cartella del computer (stessa del sistema); ritorna il percorso scelto, o "" se si annulla."""
    nonvalida = "La finestra di scelta non è disponibile su questo computer: scrivi il percorso della cartella."
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:
        raise ValueError(nonvalida)
    with _dialogo:
        try:
            root = tkinter.Tk()
        except Exception:
            raise ValueError(nonvalida)
        try:
            root.withdraw()
            root.attributes("-topmost", True)
            scelta = filedialog.askdirectory(initialdir=iniziale if iniziale and os.path.isdir(iniziale) else os.path.expanduser("~"), title="Cartella dei portafogli", parent=root)
        finally:
            root.destroy()
    return os.path.normpath(scelta) if scelta else ""


class Portafogli:
    """Elenco dei JSON nella cartella «portafogli», ultimo aperto (ricordato nella cartella dell'utente), creazione e salvataggio dei portafogli
    e costruzione dei dati che la pagina riceve (scheda e storico di ogni titolo da justETF, in cache nella cartella dell'utente)."""

    def __init__(self, cartella, file_ultimo, dati=None):
        self.base = cartella
        self.predefinita = os.path.join(cartella, CARTELLA_PF)
        self.dir = self.predefinita
        self.semi = os.path.join(self.dir, "titoli")  # schede dei titoli già note, nel repository: composizioni complete
        self.file_ultimo = file_ultimo
        self.bozze = {}  # token -> definizione di un portafoglio modificato e non ancora salvato
        self.cache = os.path.join(dati or os.path.dirname(file_ultimo), "titoli")  # una scheda JSON per ISIN già scaricato
        self.lock = threading.Lock()
        self.prezzi = None  # impostato da avvia_app: riceve i titoli dei portafogli aperti
        self.copiati = 0  # portafogli copiati nell'ultima cartella scelta
        self.file_config = os.path.join(dati or os.path.dirname(file_ultimo), "config.json")
        self.remoto = None  # (indirizzo, chiave) della cartella su Google Drive online; la copia di lavoro è nella cartella dell'utente
        self.ultima_lettura = 0
        self.dir_lavoro = os.path.join(dati or os.path.dirname(file_ultimo), "drive")
        conf = self._json(self.file_config) or {}
        scelta = conf.get("cartella")
        if conf.get("remoto"):
            try:
                self.remoto = _url_remoto(conf["remoto"])
                self.dir = self.dir_lavoro
                os.makedirs(self.dir, exist_ok=True)
                self.leggi_remoto(True)
            except (ValueError, RuntimeError, OSError) as e:
                print("Google Drive online non raggiungibile, uso la copia già scaricata:", e, flush=True)
        elif scelta and os.path.isdir(scelta):  # cartella scelta dall'utente (anche di Google Drive per desktop); se non c'è più si torna a quella del programma
            self.dir = scelta

    def leggi_remoto(self, forza=False):
        """Scarica da Google Drive i portafogli nella copia di lavoro (quelli che non ci sono più online si tolgono). Al massimo ogni 20 secondi."""
        if not self.remoto or (not forza and time.time() - self.ultima_lettura < 20):
            return
        r = _chiama_remoto(self.remoto[0], self.remoto[1])
        files = r.get("files")
        if not isinstance(files, list):
            raise RuntimeError("Risposta di Google Drive non valida.")
        with self.lock:
            os.makedirs(self.dir, exist_ok=True)
            presenti = set()
            for f in files:
                n, testo = (f or {}).get("name"), (f or {}).get("text")
                if isinstance(n, str) and isinstance(testo, str) and FILE_PF.match(n):
                    presenti.add(n)
                    with open(self.percorso(n), "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(testo)
            for n in os.listdir(self.dir):
                if FILE_PF.match(n) and n not in presenti:
                    os.remove(self.percorso(n))
            schema = os.path.join(self.predefinita, "schema.json")
            if os.path.exists(schema) and not os.path.exists(os.path.join(self.dir, "schema.json")):
                shutil.copy2(schema, os.path.join(self.dir, "schema.json"))
        self.ultima_lettura = time.time()

    def _scrivi_remoto(self, scrivi=(), togli=()):
        """Riporta su Google Drive file scritti (nome, testo) o tolti. Senza cartella online non fa nulla; RuntimeError se non riesce."""
        if self.remoto:
            _chiama_remoto(self.remoto[0], self.remoto[1], {"write": [{"name": n, "text": x} for n, x in scrivi], "trash": list(togli)})
            self.ultima_lettura = time.time()

    def imposta_remoto(self, url):
        """Sceglie come cartella dei portafogli quella su Google Drive online (web app di Google Apps Script). Ritorna cartella_info()."""
        base, chiave = _url_remoto(url)
        try:
            r = _chiama_remoto(base, chiave)
        except RuntimeError as e:
            raise ValueError(str(e))
        online = {f.get("name") for f in (r.get("files") or []) if isinstance(f, dict) and FILE_PF.match(str(f.get("name")))}
        prima = self.dir if not self.remoto else None
        self.remoto = (base, chiave)
        with self.lock:
            self.dir = self.dir_lavoro
        os.makedirs(self.dir, exist_ok=True)
        copiati = 0
        try:
            if prima and not online:  # cartella online vuota: riceve una copia dei portafogli di prima (che restano dove sono)
                nomi = [n for n in sorted(os.listdir(prima)) if FILE_PF.match(n)]
                testi = []
                for n in nomi:
                    with open(os.path.join(prima, n), encoding="utf-8") as fh:
                        testi.append((n, fh.read()))
                if testi:
                    _chiama_remoto(base, chiave, {"write": [{"name": n, "text": x} for n, x in testi], "trash": []})
                    copiati = len(testi)
            self.leggi_remoto(True)
        except (RuntimeError, OSError) as e:
            raise ValueError(str(e))
        self.copiati = copiati
        self._salva_config()
        if self.prezzi is not None:
            self.prezzi.titoli, self.prezzi.base = self.titoli_noti()
        return self.cartella_info()

    def _salva_config(self):
        try:
            os.makedirs(os.path.dirname(self.file_config), exist_ok=True)
            with open(self.file_config, "w", encoding="utf-8") as fh:
                json.dump({"cartella": "" if self.remoto or self.dir == self.predefinita else self.dir,
                           **({"remoto": self.remoto[0] + "?" + urllib.parse.urlencode({"key": self.remoto[1]})} if self.remoto else {})}, fh, ensure_ascii=False)
        except OSError as e:
            raise ValueError(f"Cartella scelta ma non memorizzata: {e}")

    def cartella_info(self):
        return {"cartella": "Google Drive (online)" if self.remoto else self.dir, "remoto": bool(self.remoto), "predefinita": self.predefinita, "personalizzata": bool(self.remoto) or os.path.abspath(self.dir) != os.path.abspath(self.predefinita), "suggerite": cartelle_suggerite(), "copiati": self.copiati}

    def imposta_cartella(self, percorso, crea=False):
        """Sceglie la cartella dei JSON dei portafogli (percorso del computer, per esempio quello di Google Drive per desktop). Vuoto = quella del programma.
        Ritorna cartella_info(); ValueError con un messaggio per l'utente se non va."""
        percorso = (percorso or "").strip().strip('"')
        if not percorso:
            nuova = self.predefinita
        else:
            nuova = os.path.abspath(os.path.expanduser(percorso))
            if crea and not os.path.isdir(nuova) and os.path.isdir(os.path.dirname(nuova)):  # una cartella suggerita (per esempio «portafogli» dentro Google Drive) si crea al primo uso; solo l'ultimo livello
                try:
                    os.mkdir(nuova)
                except OSError as e:
                    raise ValueError(f"Non riesco a creare la cartella «{nuova}»: {e}")
            if not os.path.isdir(nuova):
                raise ValueError(f"La cartella «{nuova}» non esiste.")
            if not os.access(nuova, os.R_OK | os.W_OK):
                raise ValueError(f"Non posso leggere e scrivere in «{nuova}».")
        schema = os.path.join(self.predefinita, "schema.json")
        if nuova != self.predefinita and os.path.exists(schema) and not os.path.exists(os.path.join(nuova, "schema.json")):
            try:
                shutil.copy2(schema, os.path.join(nuova, "schema.json"))  # i JSON puntano a «schema.json» accanto a loro
            except OSError:
                pass
        prima = self.dir
        self.remoto = None
        with self.lock:
            self.dir = nuova
        copiati = 0
        try:
            if os.path.abspath(prima) != os.path.abspath(nuova) and not any(FILE_PF.match(n) for n in os.listdir(nuova)):
                for n in sorted(os.listdir(prima)):
                    if FILE_PF.match(n):
                        shutil.copy2(os.path.join(prima, n), os.path.join(nuova, n))  # i portafogli della cartella di prima restano dove sono: se ne mette una copia
                        copiati += 1
        except OSError:
            pass
        self.copiati = copiati
        self._salva_config()
        if self.prezzi is not None:
            self.prezzi.titoli, self.prezzi.base = self.titoli_noti()
        return self.cartella_info()

    def percorso(self, nomefile):
        return os.path.join(self.dir, nomefile)

    # ---- elenco
    def definizione(self, nomefile):
        """Il JSON del portafoglio (dizionario) o None. «bozza:TOKEN» è una bozza in memoria (titoli cambiati, non ancora salvata)."""
        if isinstance(nomefile, str) and nomefile.startswith("bozza:"):
            return self.bozze.get(nomefile[6:])
        if not FILE_PF.match(nomefile or ""):
            return None
        try:
            with open(self.percorso(nomefile), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) and isinstance(d.get("titoli"), list) else None

    def info(self, nomefile):
        """{file, nome, versione, descrizione} se nomefile è un portafoglio della cartella, altrimenti None."""
        d = self.definizione(nomefile)
        if not d:
            return None
        m = re.match(r"^([A-Za-z0-9]+)_V(\d+)\.json$", nomefile)
        return {"file": nomefile, "nome": d.get("nome") or m.group(1), "versione": "V" + str(d.get("versione") or m.group(2)).lstrip("Vv"), "descrizione": d.get("descrizione") or ""}

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
        e = self.elenco()  # nessun portafoglio aperto prima: l'ultimo JSON caricato nella cartella (il più recente)
        if not e:
            return None
        def recente(i):
            try:
                return os.path.getmtime(self.percorso(i["file"]))
            except OSError:
                return 0
        return max(e, key=recente)["file"]

    def segna(self, nomefile):
        try:
            with open(self.file_ultimo, "w", encoding="utf-8") as fh:
                json.dump({"file": nomefile}, fh)
        except OSError:
            pass

    def elimina(self, nomefile):
        """Cancella il JSON di un portafoglio. Ritorna {eliminato, ultimo}; ValueError con un messaggio per l'utente se non si può."""
        if not self.info(nomefile):
            raise ValueError("Portafoglio non trovato.")
        try:
            self._scrivi_remoto(togli=[nomefile])
        except RuntimeError as e:
            raise ValueError(str(e))
        with self.lock:
            os.remove(self.percorso(nomefile))
        return {"eliminato": nomefile, "ultimo": self.ultimo()}

    # ---- dati dei titoli: schede note (repository), cache dell'utente, justETF
    def _json(self, percorso):
        try:
            with open(percorso, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _scheda(self, isin):
        return self._json(os.path.join(self.cache, isin + ".json"))

    def _salva_scheda(self, isin, scheda):
        try:
            os.makedirs(self.cache, exist_ok=True)
            tmp = os.path.join(self.cache, isin + ".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(scheda, fh, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.cache, isin + ".json"))
        except OSError:
            pass

    def _fondo_noto(self, isin):
        """Il record del fondo già noto (scheda nel repository o in cache), senza rete; None se manca."""
        s = self._json(os.path.join(self.semi, isin + ".json"))
        if s and s.get("fondo"):
            return dict(s["fondo"])
        sc = self._scheda(isin)
        return dict(sc["fondo"]) if sc and sc.get("fondo") else None

    def _sigle_usate(self):
        usate = set()
        for d in (self.semi, self.cache):
            try:
                for n in os.listdir(d):
                    s = self._json(os.path.join(d, n)) if n.endswith(".json") else None
                    if s and s.get("fondo"):
                        usate.add(s["fondo"]["s"])
            except OSError:
                pass
        return usate

    def titolo(self, isin, usate, say, scarica=True):
        """(record del fondo, serie [(data, prezzo)]) di un ISIN. Con scarica=False solo ciò che è già in cache di oggi: altrimenti LookupError."""
        oggi = datetime.date.today().isoformat()
        sc = self._scheda(isin)
        fondo = self._fondo_noto(isin)
        if sc and sc.get("scaricato") == oggi and sc.get("serie") and fondo:
            say(t="testo", testo=f"{isin}: dati scaricati oggi, li riuso ({len(sc['serie'])} prezzi)")
            return fondo, [tuple(x) for x in sc["serie"]]
        if not scarica:
            raise LookupError(f"{isin}: dati da scaricare")
        if fondo:
            say(t="testo", testo=f"{isin}: profilo già noto ({fondo['name']}), aggiorno i prezzi")
        else:
            say(t="testo", testo=f"{isin}: scarico la scheda del fondo da justETF…")
            p = fonti.profilo(isin)
            sigla, k = fonti.sigla_proposta(p), 1
            base_sigla = sigla
            while sigla in usate:
                k += 1
                sigla = f"{base_sigla[:6]}{k}"
            usate.add(sigla)
            fondo = fonti.costruisci_fondo(p, sigla)
            say(t="testo", testo=f"{fondo['name']} · {fondo['tipo']} · TER {fondo['ter']}% · patrimonio {fondo['aum']} mln €", c="t")
        say(t="testo", testo=f"{isin}: scarico lo storico dei prezzi in euro da justETF…")
        serie = fonti.serie(isin)
        self._salva_scheda(isin, {"scaricato": oggi, "fondo": fondo, "serie": serie})
        return fondo, serie

    def costruisci(self, nomefile, avanza=None, scarica=True):
        """Documento {meta, funds, dates, px} del portafoglio, per la pagina. Con scarica=False usa solo i dati di oggi già in cache (LookupError se mancano)."""
        def say(**ev):
            if avanza:
                try:
                    avanza(ev)
                except Exception:
                    pass
        d = self.definizione(nomefile)
        if d is None:
            raise ValueError("Portafoglio non trovato.")
        df = valida_definizione(d)
        nome, versione, amount = df["nome"], f"V{df['v']}", df["amount"]
        say(t="inizio", n=len(df["pesi"]))
        usate = self._sigle_usate()
        fondi, serie_tot, sigla_di = [], {}, {}
        for k, (isin, w) in enumerate(df["pesi"], 1):
            say(t="titolo", s=isin, isin=isin, k=k, n=len(df["pesi"]))
            try:
                f, serie = self.titolo(isin, usate, say, scarica)
            except (LookupError, RuntimeError) as e:
                if not scarica:
                    raise
                raise ValueError(f"{isin}: {e}")
            if f["s"] in {x["s"] for x in fondi}:
                raise ValueError(f"{isin}: sigla {f['s']} già usata nel portafoglio")
            f.pop("sym", None)  # nessun simbolo di borsa: i prezzi vengono tutti da justETF
            f["w"] = w
            fondi.append(f)
            serie_tot[f["s"]] = serie
            sigla_di[isin] = f["s"]
            say(t="dati", s=f["s"], isin=isin, fonte=FONTE, righe=[list(x) for x in serie[-40:]])
        # calendario comune: dal più recente degli inizi al più vecchio delle fini; i giorni mancanti ripetono l'ultimo prezzo
        inizio = max(x[0][0] for x in serie_tot.values())
        fine = min(x[-1][0] for x in serie_tot.values())
        date = sorted({dd for x in serie_tot.values() for dd, _ in x if inizio <= dd <= fine})
        if len(date) < 60:
            raise ValueError(f"Lo storico in comune è troppo breve ({len(date)} giorni, dal {inizio} al {fine}): togli il titolo più recente.")
        px = {}
        for sigla, x in serie_tot.items():
            ultimo, j, col = None, 0, []
            xs = sorted(x)
            for dd in date:
                while j < len(xs) and xs[j][0] <= dd:
                    ultimo = xs[j][1]
                    j += 1
                col.append(ultimo)
            px[sigla] = col
        for f in fondi:
            f["p0"] = px[f["s"]][-1]
            f["q0"] = int(amount * f["w"] / f["p0"])
        meta = {"nome": nome, "versione": versione, "descrizione": df["descrizione"], "chiave": f"pf-{nome}-{versione}", "file": nomefile, "base": date[-1], "from": date[0],
                "amount": amount, "rf": 0.02, "origine": "json"}
        if nomefile.startswith("bozza:"):  # acquisti e limiti salvati nel browser non devono mescolarsi con quelli del portafoglio da cui si parte
            meta["chiave"] += "-bozza-" + nomefile[6:]
            meta["bozza"] = True
            if d.get("_da"):
                meta["bozza_da"] = d["_da"]
        if df["frontiera"]:
            meta["frontiera"] = df["frontiera"]
        if df["vincoli"]:
            meta["vincoli"] = {"fondi": {sigla_di[i]: x for i, x in df["vincoli"]["fondi"].items()}, "classi": df["vincoli"]["classi"]}
        if df["transazioni"]:  # i movimenti reali (eseguiti): la pagina li usa al posto degli acquisti d'esempio; quelli solo pianificati vanno in «pianificate»
            conv = lambda t: {"s": sigla_di[t["isin"]], "d": t["data"], "t": "a" if t["tipo"] == "acquisto" else "v", "q": t["quote"], "p": t["prezzo"]}
            meta["transazioni"] = [conv(t) for t in df["transazioni"] if not t.get("pianificata")]
            if any(t.get("pianificata") for t in df["transazioni"]):
                meta["pianificate"] = [conv(t) for t in df["transazioni"] if t.get("pianificata")]
        if df["obiettivo"]:  # quote del piano proposto: la pagina ne ricava «da investire» e il punto «Piano proposto»
            meta["obiettivo"] = {sigla_di[x["isin"]]: x["quote"] for x in df["obiettivo"]}
        if self.prezzi is not None:
            self.prezzi.aggiungi({f["s"]: {"isin": f["isin"], "p0": f["p0"]} for f in fondi}, date[-1])
        say(t="salvato", n=len(fondi))
        return {"meta": meta, "funds": fondi, "dates": date, "px": px}

    # ---- la pagina
    def _modello(self):
        with open(os.path.join(self.base, MODELLO), encoding="utf-8") as fh:
            return fh.read()

    def pagina(self, doc, titolo=None):
        """Testo HTML di portafoglio.html con `doc` al posto dei dati."""
        base = self._modello()
        m = RE_DATI.search(base)
        if not m:
            raise ValueError(f"Manca il modello {MODELLO}.")
        corpo = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        t = base[:m.start()] + m.group(1) + corpo + m.group(3) + base[m.end():]
        if titolo:
            import html as _h
            t = re.sub(r"<title>.*?</title>", lambda _: f"<title>{_h.escape(titolo)}</title>", t, count=1, flags=re.S)
        return t

    def pagina_portafoglio(self, nomefile):
        """Pagina del portafoglio se i suoi dati di oggi sono già in cache; altrimenti il modello con la richiesta di scaricarli («autocarica»). None se il file non c'è."""
        if nomefile.startswith("bozza:"):
            if self.definizione(nomefile) is None:
                return None
            try:
                doc = self.costruisci(nomefile, scarica=False)
            except LookupError:
                return None
            return self.pagina(doc, doc["meta"]["nome"] + " · " + doc["meta"]["versione"] + " (bozza)")
        if not self.info(nomefile):
            return None
        try:
            doc = self.costruisci(nomefile, scarica=False)
            return self.pagina(doc, doc["meta"]["nome"] + " · " + doc["meta"]["versione"])
        except LookupError:
            base = json.loads(RE_DATI.search(self._modello()).group(2))
            base["meta"]["autocarica"] = nomefile
            return self.pagina(base)

    def pagina_vuota(self):
        return self.pagina(json.loads(RE_DATI.search(self._modello()).group(2)))

    def prepara(self, nomefile, avanza=None):
        """Scarica da justETF ciò che manca per aprire un portafoglio già nella cartella. Ritorna info."""
        self.costruisci(nomefile, avanza, scarica=True)
        return self.info(nomefile)

    def titoli_noti(self):
        """(titoli per lo scarico dei prezzi, data base) dei portafogli della cartella, dai dati già in cache."""
        titoli, base = {}, ""
        for i in self.elenco():
            try:
                for isin, _ in valida_definizione(self.definizione(i["file"]))["pesi"]:
                    f, sc = self._fondo_noto(isin), self._scheda(isin)
                    if f and sc and sc.get("serie"):
                        titoli.setdefault(f["s"], {"isin": isin, "p0": sc["serie"][-1][1]})
                        b = sc["serie"][-1][0]
                        base = b if not base or b < base else base
            except (ValueError, KeyError, TypeError):
                continue
        return titoli, base

    # ---- scrittura
    def _scrivi(self, nuovo, d):
        os.makedirs(self.dir, exist_ok=True)
        testo = formatta_definizione(d)
        with self.lock:
            try:
                with open(self.percorso(nuovo), "x", encoding="utf-8") as fh:
                    fh.write(testo)
            except FileExistsError:
                raise Esiste(nuovo, f"Esiste già il file {CARTELLA_PF}/{nuovo}. Cambia la versione per crearne uno nuovo.")
        try:
            self._scrivi_remoto(scrivi=[(nuovo, testo)])
        except RuntimeError as e:
            try:
                os.remove(self.percorso(nuovo))  # non è arrivato su Google Drive: non resta solo sul computer
            except OSError:
                pass
            raise ValueError(str(e))

    def crea(self, definizione, avanza=None):
        """Scrive nome_Vn.json nella cartella «portafogli» dalla definizione {nome, versione, descrizione, valore?, titoli, vincoli?} e scarica i dati da justETF. Ritorna info.
        Con {"file": "nome_Vn.json"} apre un portafoglio già presente: scarica solo i dati che mancano."""
        if isinstance(definizione, dict) and set(definizione) == {"file"}:
            if not self.info(definizione["file"]):
                raise ValueError("Portafoglio non trovato.")
            return self.prepara(definizione["file"], avanza)
        df = valida_definizione(definizione)
        versione = f"V{df['v']}"
        nuovo = f"{df['nome']}_{versione}.json"
        for i in self.elenco():
            if i["nome"] == df["nome"] and i["versione"] == versione:
                raise Esiste(i["file"], f"Esiste già il portafoglio {df['nome']} {versione} ({i['file']}). Cambia la versione nel JSON per crearne uno nuovo.")
        self._scrivi(nuovo, {"nome": df["nome"], "versione": versione, "descrizione": df["descrizione"], "valore": df["amount"],
                             "titoli": [{"isin": i, "peso": round(w * 100, 2)} for i, w in df["pesi"]], **({"vincoli": df["vincoli"]} if df["vincoli"] else {}),
                             **({"transazioni": df["transazioni"]} if df["transazioni"] else {}), **({"obiettivo": df["obiettivo"]} if df["obiettivo"] else {}), **({"frontiera": df["frontiera"]} if df["frontiera"] else {})})
        try:
            return self.prepara(nuovo, avanza)
        except Exception:
            try:
                os.remove(self.percorso(nuovo))  # dati non scaricati: non resta un portafoglio a metà
            except OSError:
                pass
            raise

    def bozza(self, da, titoli, avanza=None, valore=None, transazioni=None, obiettivo=None):
        """Bozza del portafoglio `da` con i titoli cambiati. `titoli`: [{isin, peso?}] (peso in %; se manca resta quello di prima, 1 per un titolo nuovo).
        I pesi vengono riportati a 100; un titolo nuovo senza peso entra all'1% e gli altri si riducono in proporzione. Scarica i dati dei titoli nuovi. Ritorna {token}. Gli acquisti e le vendite restano solo per i titoli rimasti."""
        origine = self.definizione(da)
        if origine is None:
            raise ValueError("Portafoglio di partenza non trovato.")
        if not isinstance(titoli, list) or not 1 <= len(titoli) <= 30:
            raise ValueError("Servono da 1 a 30 titoli.")
        prima = {t.get("isin"): t.get("peso") for t in origine["titoli"] if isinstance(t, dict)}
        nuovi, visti = [], set()
        for t in titoli:
            isin = str((t or {}).get("isin") or "").strip().upper() if isinstance(t, dict) else ""
            if not isin:
                raise ValueError("C'è un titolo senza ISIN.")
            if isin in visti:
                raise ValueError(f"{isin}: ISIN ripetuto.")
            visti.add(isin)
            peso, fisso = t.get("peso"), False
            if peso in (None, ""):
                if prima.get(isin) is not None:
                    peso = prima[isin]
                else:
                    peso, fisso = PESO_NUOVO, True  # titolo nuovo senza peso: entra all'1%
            try:
                peso = float(peso)
            except (TypeError, ValueError):
                raise ValueError(f"{isin}: peso non valido.")
            if not 0 <= peso <= 100:
                raise ValueError(f"{isin}: il peso deve essere tra 0 e 100.")
            nuovi.append([isin, peso, fisso])
        fissi = sum(p for _, p, f in nuovi if f)
        altri = sum(p for _, p, f in nuovi if not f)
        if altri > 0 and fissi < 100:  # gli altri titoli si riducono (o, se ne è stato tolto uno, crescono) in proporzione fino a fare 100
            for x in nuovi:
                if not x[2]:
                    x[1] = x[1] * (100 - fissi) / altri
        tot = sum(p for _, p, _f in nuovi)
        if tot <= 0:
            raise ValueError("Almeno un titolo deve avere un peso maggiore di 0.")
        for x in nuovi:
            x[1] = round(x[1] * 100 / tot, 2)
        resto = round(100 - sum(x[1] for x in nuovi), 2)
        max(nuovi, key=lambda x: x[1])[1] = round(max(nuovi, key=lambda x: x[1])[1] + resto, 2)
        if valore in (None, ""):
            valore = origine.get("valore") or 10000
        else:
            try:
                valore = round(float(valore), 2)
            except (TypeError, ValueError):
                raise ValueError("Il valore dell'investimento deve essere un numero.")
            if not 100 <= valore <= 1e9:
                raise ValueError("Il valore dell'investimento deve essere tra 100 e 1.000.000.000 euro.")
            valore = int(valore) if valore == int(valore) else valore
        d = {"nome": origine.get("nome"), "versione": origine.get("versione"), "descrizione": origine.get("descrizione") or "bozza",
             "valore": valore, "titoli": [{"isin": i, "peso": p} for i, p, _f in nuovi],
             "_da": origine.get("_da") if da.startswith("bozza:") else da}
        if transazioni is not None:  # acquisti e vendite inseriti nella schermata di modifica: sostituiscono quelli di prima
            tr = valida_transazioni(transazioni, visti)
        else:
            tr = [x for x in (origine.get("transazioni") or []) if isinstance(x, dict) and x.get("isin") in visti]
        if tr:
            d["transazioni"] = tr
        ob = valida_obiettivo(obiettivo, visti) if obiettivo is not None else [x for x in (origine.get("obiettivo") or []) if isinstance(x, dict) and x.get("isin") in visti]  # le quote del piano proposto restano finché la pagina non dice altrimenti
        if ob:
            d["obiettivo"] = ob
        valida_definizione(d)
        token = secrets.token_urlsafe(9)
        self.bozze[token] = d
        try:
            self.costruisci("bozza:" + token, avanza, scarica=True)
        except Exception:
            self.bozze.pop(token, None)
            raise
        while len(self.bozze) > 20:  # poche bozze in memoria: le più vecchie vengono dimenticate
            self.bozze.pop(next(iter(self.bozze)))
        return {"token": token}

    def salva_titoli(self, da, titoli, nome, versione, descrizione, avanza=None, valore=None, transazioni=None, obiettivo=None):
        """Scrive nome_V<n>.json partendo da `da` con i titoli cambiati ([{isin, peso?}], come in bozza()): scarica i dati dei titoli nuovi e salva i pesi così come sono (a 100).
        Ritorna info; ValueError con un messaggio per l'utente se qualcosa non va."""
        token = self.bozza(da, titoli, avanza, valore, transazioni, obiettivo)["token"]
        try:
            doc = self.costruisci("bozza:" + token, scarica=False)
            w = {f["s"]: round(f["w"], 3) for f in doc["funds"]}
            grande = max(w, key=lambda s: w[s])
            w[grande] = round(w[grande] + (1 - sum(w.values())), 3)  # l'arrotondamento a tre decimali non deve far uscire la somma da 100%
            return self.salva("bozza:" + token, nome, versione, descrizione, w)
        finally:
            self.bozze.pop(token, None)

    def modifica(self, nomefile, nome, versione, descrizione):
        """Cambia nome, versione e descrizione di un portafoglio: stesso file se nome e versione restano, altrimenti il file viene rinominato. Ritorna info (+ chiave per gli acquisti nel browser)."""
        d = self.definizione(nomefile)
        if d is None:
            raise ValueError("Portafoglio non trovato.")
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
        nuovo = f"{nome}_V{v}.json"
        if nuovo != nomefile and os.path.exists(self.percorso(nuovo)):
            raise ValueError(f"Esiste già {nuovo}: scegli un'altra versione.")
        nd = {**d, "nome": nome, "versione": f"V{v}", "descrizione": descrizione}
        testo = formatta_definizione(nd)
        valida_definizione(json.loads(testo))  # il file riscritto deve restare valido
        try:
            self._scrivi_remoto(scrivi=[(nuovo, testo)], togli=[nomefile] if nuovo != nomefile else [])
        except RuntimeError as e:
            raise ValueError(str(e))
        with self.lock:
            tmp = self.percorso(nuovo) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(testo)
            os.replace(tmp, self.percorso(nuovo))
            if nuovo != nomefile:
                os.remove(self.percorso(nomefile))
        if nuovo != nomefile and self.ultimo() != nuovo:
            self.segna(nuovo)
        return {**self.info(nuovo), "chiave": f"pf-{nome}-V{v}"}

    def annulla_proposte(self, nomefile):
        """Toglie dal file le proposte (quote obiettivo di un ribilanciamento): stesso file, pesi e transazioni restano. Ritorna info."""
        d = self.definizione(nomefile)
        if d is None or str(nomefile).startswith("bozza:"):
            raise ValueError("Portafoglio non trovato.")
        if not d.get("obiettivo") and not any(isinstance(t, dict) and t.get("pianificata") for t in (d.get("transazioni") or [])):
            return self.info(nomefile)  # niente da annullare
        resto = [t for t in (d.get("transazioni") or []) if not (isinstance(t, dict) and t.get("pianificata"))]  # anche le operazioni solo pianificate sono proposte
        nd = {k: v for k, v in d.items() if k not in ("obiettivo", "transazioni")}
        if resto:
            nd["transazioni"] = resto
        testo = formatta_definizione(nd)
        valida_definizione(json.loads(testo))  # il file riscritto deve restare valido
        try:
            self._scrivi_remoto(scrivi=[(nomefile, testo)], togli=[])
        except RuntimeError as e:
            raise ValueError(str(e))
        with self.lock:
            tmp = self.percorso(nomefile) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(testo)
            os.replace(tmp, self.percorso(nomefile))
        return self.info(nomefile)

    def salva(self, da, nome, versione, descrizione, pesi, importo=None, transazioni=None, vincoli=None, frontiera=None, obiettivo=None):
        """Scrive nome_V<n>.json partendo dal portafoglio `da` con i nuovi pesi (per sigla). Ritorna info; ValueError con un messaggio per l'utente se qualcosa non va."""
        origine = self.definizione(da)
        if origine is None:
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
        doc = self.costruisci(da, scarica=False)
        sigla_isin = {f["s"]: f["isin"] for f in doc["funds"]}
        if not isinstance(pesi, dict) or set(pesi) != set(sigla_isin):
            raise ValueError("I pesi non corrispondono ai fondi del portafoglio.")
        try:
            w = {k: round(float(x), 3) for k, x in pesi.items()}
        except (TypeError, ValueError):
            raise ValueError("Pesi non validi.")
        if min(w.values()) < 0 or abs(sum(w.values()) - 1) > 0.0015:
            raise ValueError("I pesi devono essere positivi e dare 100%.")
        amount = origine.get("valore") or doc["meta"]["amount"]
        if importo is not None:
            try:
                amount = round(float(importo), 2)
            except (TypeError, ValueError):
                raise ValueError("Importo non valido.")
            if not 100 <= amount <= 1e9:
                raise ValueError("L'importo deve essere tra 100 e 1.000.000.000 euro.")
            amount = int(amount) if amount == int(amount) else amount
        versione = f"V{v}"
        nuovo = f"{nome}_{versione}.json"
        if transazioni is None:
            transazioni = origine.get("transazioni") or []
        tr = valida_transazioni(transazioni, set(sigla_isin.values()))
        con_mov = {t["isin"] for t in tr}  # un titolo già venduto resta nel file con peso 0: serve ai suoi movimenti
        titoli = [{"isin": sigla_isin[s], "peso": round(x * 100, 1)} for s, x in sorted(w.items(), key=lambda a: -a[1]) if x > 0 or sigla_isin[s] in con_mov]
        nd = {"nome": nome, "versione": versione, "descrizione": descrizione, "valore": amount, "titoli": titoli}
        if tr:
            nd["transazioni"] = tr
        if obiettivo is None:  # senza indicazioni si porta dietro solo quelle di una bozza; un piano nuovo parte senza «da investire»
            obiettivo = origine.get("obiettivo") if da.startswith("bozza:") else []
        ob = valida_obiettivo(obiettivo, {t["isin"] for t in titoli})
        if ob:
            nd["obiettivo"] = ob
        vv = vincoli if isinstance(vincoli, dict) and (vincoli.get("fondi") or vincoli.get("classi")) else origine.get("vincoli")  # i limiti usati per trovare il punto sulla frontiera
        if vv:
            ammessi = {t["isin"] for t in titoli}
            nd["vincoli"] = {"fondi": {i: x for i, x in (vv.get("fondi") or {}).items() if i in ammessi}, "classi": vv.get("classi") or {}}
        fr = frontiera if isinstance(frontiera, dict) else origine.get("frontiera")
        if fr:
            nd["frontiera"] = fr
        valida_definizione(nd)  # il file scritto deve restare valido
        try:
            self._scrivi(nuovo, nd)
        except Esiste:
            libere = max([_num_versione(i["versione"]) for i in self.elenco() if i["nome"] == nome] + [v]) + 1
            raise ValueError(f"Esiste già {nuovo}: usa la versione V{libere}.")
        return self.info(nuovo)


# ---- server locale: solo 127.0.0.1
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

        def vai(self, dove):
            self.send_response(302)
            self.send_header("Location", dove)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def host_ok(self):  # difesa dal DNS rebinding
            return (self.headers.get("Host") or "") in ammessi

        def origine_ok(self):
            o = self.headers.get("Origin")
            return o is None or o.replace("http://", "") in ammessi

        def do_GET(self):
            if not self.host_ok():
                return self.invia(403, {"errore": "host non ammesso"})
            u = urllib.parse.urlsplit(self.path)
            p = u.path
            if p == "/api/prezzi":
                return self.invia(200, prezzi.leggi())
            if p == "/api/portafogli":
                try:
                    portafogli.leggi_remoto()  # con la cartella su Google Drive online: aggiorna la copia di lavoro
                except (RuntimeError, OSError):
                    pass
                return self.invia(200, {"ultimo": portafogli.ultimo(), "lista": portafogli.elenco()})
            if p == "/api/fineco":
                try:
                    with open(os.path.join(portafogli.base, FILE_FINECO), "rb") as fh:
                        return self.invia(200, fh.read())
                except OSError:
                    return self.invia(404, {"errore": "lista Fineco non trovata (aggiorna_fineco.py la crea)"})
            if p == "/api/drive-script":
                try:
                    with open(os.path.join(portafogli.base, FILE_SCRIPT_DRIVE), encoding="utf-8") as fh:
                        return self.invia(200, fh.read().encode("utf-8"), "text/plain; charset=utf-8")
                except OSError:
                    return self.invia(404, {"errore": "script non trovato"})
            if p == "/api/cartella":
                return self.invia(200, portafogli.cartella_info())
            if p == "/":
                return self.vai("/" + MODELLO)
            if p == "/" + MODELLO:
                bz = (urllib.parse.parse_qs(u.query).get("bozza") or [""])[0]
                if bz:  # bozza con i titoli cambiati, non ancora salvata
                    try:
                        testo = portafogli.pagina_portafoglio("bozza:" + bz)
                    except (OSError, ValueError) as e:
                        return self.invia(500, {"errore": str(e)})
                    if testo is None:
                        return self.invia(404, {"errore": "La bozza non c'è più: riaprila dal portafoglio."})
                    return self.invia(200, testo.encode(), "text/html; charset=utf-8")
                pf = (urllib.parse.parse_qs(u.query).get("pf") or [""])[0]
                if not pf:  # nessun portafoglio indicato: l'ultimo aperto
                    ultimo = portafogli.ultimo()
                    if ultimo:
                        return self.vai("/" + MODELLO + "?pf=" + urllib.parse.quote(ultimo))
                    return self.invia(200, portafogli.pagina_vuota().encode(), "text/html; charset=utf-8")
                try:
                    testo = portafogli.pagina_portafoglio(pf)
                except (OSError, ValueError) as e:
                    return self.invia(500, {"errore": str(e)})
                if testo is None:
                    return self.invia(404, {"errore": pf + " non c'è nella cartella " + CARTELLA_PF})
                portafogli.segna(pf)
                return self.invia(200, testo.encode(), "text/html; charset=utf-8")
            return self.invia(404, {"errore": "non trovato"})

        def corpo_json(self, massimo):
            n = int(self.headers.get("Content-Length") or 0)
            if n > massimo:
                raise OverflowError
            r = json.loads(self.rfile.read(n))
            if not isinstance(r, dict):
                raise ValueError("richiesta non valida")
            return r

        def do_POST(self):
            if not (self.host_ok() and self.origine_ok()):
                return self.invia(403, {"errore": "richiesta non ammessa"})
            percorso = self.path.split("?")[0]
            if percorso in ("/api/salva", "/api/elimina", "/api/cartella", "/api/modifica", "/api/annulla-proposte"):
                try:
                    r = self.corpo_json(65536)
                    if percorso == "/api/annulla-proposte":
                        return self.invia(200, portafogli.annulla_proposte(r.get("file")))
                    if percorso == "/api/modifica":
                        return self.invia(200, portafogli.modifica(r.get("file"), r.get("nome"), r.get("versione"), r.get("descrizione")))
                    if percorso == "/api/cartella":
                        if r.get("sfoglia"):  # solo la scelta con la finestra del sistema: l'applica poi la pagina
                            return self.invia(200, {"scelta": finestra_cartella(str(r.get("iniziale") or ""))})
                        if "remoto" in r:  # cartella su Google Drive online
                            return self.invia(200, {**portafogli.imposta_remoto(r.get("remoto")), "ultimo": portafogli.ultimo(), "lista": portafogli.elenco()})
                        info = portafogli.imposta_cartella(r.get("cartella"), bool(r.get("crea")))
                        return self.invia(200, {**info, "ultimo": portafogli.ultimo(), "lista": portafogli.elenco()})
                    if percorso == "/api/elimina":
                        return self.invia(200, portafogli.elimina(r.get("file")))
                    nuovo = portafogli.salva(r.get("da"), r.get("nome"), r.get("versione"), r.get("descrizione"), r.get("pesi"), r.get("importo"), r.get("transazioni"), r.get("vincoli"), r.get("frontiera"), r.get("obiettivo"))
                except OverflowError:
                    return self.invia(413, {"errore": "richiesta troppo grande"})
                except (ValueError, LookupError) as e:  # include json.JSONDecodeError
                    return self.invia(400, {"errore": str(e) or "richiesta non valida"})
                except OSError as e:
                    return self.invia(500, {"errore": f"file non scritto: {e}"})
                return self.invia(200, nuovo)
            if percorso == "/api/salva-titoli":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 65536:
                    return self.invia(413, {"errore": "richiesta troppo grande"})
                corpo = self.rfile.read(n)

                def salva_titoli(riga):
                    try:
                        r = json.loads(corpo)
                        info = portafogli.salva_titoli(r.get("da"), r.get("titoli"), r.get("nome"), r.get("versione"), r.get("descrizione"), riga, r.get("valore"), r.get("transazioni"), r.get("obiettivo"))
                    except (ValueError, LookupError, RuntimeError, OSError, AttributeError) as e:
                        return riga({"t": "fallito", "testo": str(e) or "richiesta non valida"})
                    riga({"t": "salvato_pf", **info})

                return self.flusso(salva_titoli)
            if percorso == "/api/bozza":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 65536:
                    return self.invia(413, {"errore": "richiesta troppo grande"})
                corpo = self.rfile.read(n)

                def bozza(riga):
                    try:
                        r = json.loads(corpo)
                        info = portafogli.bozza(r.get("da"), r.get("titoli"), riga, r.get("valore"), r.get("transazioni"), r.get("obiettivo"))
                    except (ValueError, LookupError, RuntimeError, OSError, AttributeError) as e:
                        return riga({"t": "fallito", "testo": str(e) or "richiesta non valida"})
                    riga({"t": "pronta", **info})

                return self.flusso(bozza)
            if percorso == "/api/crea":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 65536:
                    return self.invia(413, {"errore": "richiesta troppo grande"})
                corpo = self.rfile.read(n)

                def crea(riga):
                    try:
                        info = portafogli.crea(json.loads(corpo), riga)
                    except Esiste as e:
                        return riga({"t": "esiste", "file": e.file, "testo": str(e)})
                    except (ValueError, LookupError, RuntimeError, OSError) as e:  # include i JSON non validi e gli errori di rete
                        return riga({"t": "fallito", "testo": str(e) or "richiesta non valida"})
                    riga({"t": "creato", **info})

                return self.flusso(crea)
            if percorso != "/api/aggiorna":
                return self.invia(404, {"errore": "non trovato"})
            self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def aggiorna(riga):
                if time.time() - prezzi.ultimo_tentativo < 15:  # aperture o clic ravvicinati: si riusa l'ultimo scarico
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

            self.flusso(aggiorna)

        def flusso(self, lavoro):
            """Risposta a flusso: una riga JSON per ogni passo di `lavoro(riga)`; l'ultima riga è l'evento finale."""
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
                lavoro(riga)
            except (BrokenPipeError, ConnectionError):
                pass  # la pagina ha chiuso la finestra: quello che era già salvato resta

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
    ap = argparse.ArgumentParser(prog=NOME, description="Apre la pagina del portafoglio e scarica i prezzi aggiornati da justETF.")
    ap.add_argument("--minuti", type=float, default=5, help="ogni quanti minuti scaricare con la borsa aperta (fuori orario ogni 60)")
    ap.add_argument("--porta", type=int, default=8800)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--cartella", help="cartella dei JSON dei portafogli (anche di Google Drive per desktop): viene ricordata; vuota (\"\") per tornare a quella del programma")
    ap.add_argument("--file", help=f"apre questo portafoglio (JSON nella cartella {CARTELLA_PF}) invece dell'ultimo aperto")
    a = ap.parse_args()
    cartella = os.path.dirname(os.path.abspath(__file__))
    dati = cartella_dati()
    pf = Portafogli(cartella, os.path.join(dati, "ultimo.json"), dati=dati)
    if a.cartella is not None:
        try:
            pf.imposta_cartella(a.cartella)
        except ValueError as e:
            sys.exit(str(e))
    if a.file:
        if not pf.info(os.path.basename(a.file)):
            sys.exit(f"{a.file} non è un portafoglio presente nella cartella {CARTELLA_PF}.")
        pf.segna(os.path.basename(a.file))
    aperto = pf.ultimo()
    titoli, base = pf.titoli_noti()  # i titoli dei portafogli già scaricati
    file_prezzi = os.path.join(dati, "prezzi.json")
    prezzi = Prezzi(titoli, base, file_prezzi)
    pf.prezzi = prezzi
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
    print("Portafoglio aperto:", aperto or "nessuno (carica un JSON dalla pagina)", "- cartella:", pf.dir, flush=True)
    print("Dati scaricati in:", dati, flush=True)
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
