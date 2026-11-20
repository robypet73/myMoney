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
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser

import fonti
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELLO = "portafoglio.html"  # l'unica pagina: il codice di ogni portafoglio, i dati vengono inseriti al momento
CARTELLA_PF = "portafogli"  # i JSON dei portafogli (e lo schema)
NOME = "myMoney"  # nome del programma e della sua cartella dati: non è quello di un portafoglio
NOME_VECCHIO = "francesca"  # cartella dati delle versioni precedenti: se c'è, se ne copia il contenuto
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
            nuovo = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fonte": FONTE if risposte else vecchi.get("fonte", ""),
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
        if not 0 < peso <= 100:
            raise ValueError(f"{isin}: il peso deve essere maggiore di 0 e al massimo 100.")
        righe.append((isin, peso))
    tot = sum(p for _, p in righe)
    if abs(tot - 100) > 0.5:
        raise ValueError(f"I pesi danno {round(tot, 2)}%: devono dare 100%.")
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
    return {"nome": nome, "v": v, "descrizione": descrizione, "amount": amount, "pesi": [(i, round(p / tot, 4)) for i, p in righe], "vincoli": vincoli}


def formatta_definizione(d):
    """Testo del JSON di un portafoglio, leggibile: un titolo per riga, un vincolo per riga."""
    j = lambda x: json.dumps(x, ensure_ascii=False)
    righe = []
    for k, v in {"$schema": "schema.json", **{k: v for k, v in d.items() if k != "$schema"}}.items():
        if k == "titoli":
            righe.append('  "titoli": [\n' + ",\n".join("    " + j(x) for x in v) + "\n  ]")
        elif k == "vincoli":
            sub = [f'    {j(kk)}: {{' + ("\n" + ",\n".join(f"      {j(a)}: {j(c)}" for a, c in vv.items()) + "\n    }" if vv else "}") for kk, vv in v.items()]
            righe.append('  "vincoli": {\n' + ",\n".join(sub) + "\n  }")
        else:
            righe.append(f"  {j(k)}: {j(v)}")
    return "{\n" + ",\n".join(righe) + "\n}\n"


class Portafogli:
    """Elenco dei JSON nella cartella «portafogli», ultimo aperto (ricordato nella cartella dell'utente), creazione e salvataggio dei portafogli
    e costruzione dei dati che la pagina riceve (scheda e storico di ogni titolo da justETF, in cache nella cartella dell'utente)."""

    def __init__(self, cartella, file_ultimo, dati=None):
        self.base = cartella
        self.dir = os.path.join(cartella, CARTELLA_PF)
        self.semi = os.path.join(self.dir, "titoli")  # schede dei titoli già note, nel repository: composizioni complete
        self.file_ultimo = file_ultimo
        self.cache = os.path.join(dati or os.path.dirname(file_ultimo), "titoli")  # una scheda JSON per ISIN già scaricato
        self.lock = threading.Lock()
        self.prezzi = None  # impostato da avvia_app: riceve i titoli dei portafogli aperti

    def percorso(self, nomefile):
        return os.path.join(self.dir, nomefile)

    # ---- elenco
    def definizione(self, nomefile):
        """Il JSON del portafoglio (dizionario) o None."""
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
        if df["vincoli"]:
            meta["vincoli"] = {"fondi": {sigla_di[i]: x for i, x in df["vincoli"]["fondi"].items()}, "classi": df["vincoli"]["classi"]}
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
        with self.lock:
            try:
                with open(self.percorso(nuovo), "x", encoding="utf-8") as fh:
                    fh.write(formatta_definizione(d))
            except FileExistsError:
                raise Esiste(nuovo, f"Esiste già il file {CARTELLA_PF}/{nuovo}. Cambia la versione per crearne uno nuovo.")

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
                             "titoli": [{"isin": i, "peso": round(w * 100, 2)} for i, w in df["pesi"]], **({"vincoli": df["vincoli"]} if df["vincoli"] else {})})
        try:
            return self.prepara(nuovo, avanza)
        except Exception:
            try:
                os.remove(self.percorso(nuovo))  # dati non scaricati: non resta un portafoglio a metà
            except OSError:
                pass
            raise

    def salva(self, da, nome, versione, descrizione, pesi, importo=None):
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
        titoli = [{"isin": sigla_isin[s], "peso": round(x * 100, 1)} for s, x in sorted(w.items(), key=lambda a: -a[1]) if x > 0]
        nd = {"nome": nome, "versione": versione, "descrizione": descrizione, "valore": amount, "titoli": titoli}
        if origine.get("vincoli"):
            ammessi = {t["isin"] for t in titoli}
            vv = origine["vincoli"]
            nd["vincoli"] = {"fondi": {i: x for i, x in (vv.get("fondi") or {}).items() if i in ammessi}, "classi": vv.get("classi") or {}}
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
                return self.invia(200, {"ultimo": portafogli.ultimo(), "lista": portafogli.elenco()})
            if p == "/":
                return self.vai("/" + MODELLO)
            if p == "/" + MODELLO:
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
            if percorso in ("/api/salva", "/api/elimina"):
                try:
                    r = self.corpo_json(65536)
                    if percorso == "/api/elimina":
                        return self.invia(200, portafogli.elimina(r.get("file")))
                    nuovo = portafogli.salva(r.get("da"), r.get("nome"), r.get("versione"), r.get("descrizione"), r.get("pesi"), r.get("importo"))
                except OverflowError:
                    return self.invia(413, {"errore": "richiesta troppo grande"})
                except (ValueError, LookupError) as e:  # include json.JSONDecodeError
                    return self.invia(400, {"errore": str(e) or "richiesta non valida"})
                except OSError as e:
                    return self.invia(500, {"errore": f"file non scritto: {e}"})
                return self.invia(200, nuovo)
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
    ap.add_argument("--file", help=f"apre questo portafoglio (JSON nella cartella {CARTELLA_PF}) invece dell'ultimo aperto")
    a = ap.parse_args()
    cartella = os.path.dirname(os.path.abspath(__file__))
    dati = cartella_dati()
    pf = Portafogli(cartella, os.path.join(dati, "ultimo.json"), dati=dati)
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
    print("Portafoglio aperto:", aperto or "nessuno (carica un JSON dalla pagina)", "- cartella:", os.path.join(cartella, CARTELLA_PF), flush=True)
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
