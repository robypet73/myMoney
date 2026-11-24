#!/usr/bin/env python3
"""myMoney · widget per il desktop di Windows (e anche macOS/Linux): piccola finestra sempre in primo piano con valore, rendita, rendimento
nel periodo scelto, variazione di oggi e grafico del portafoglio, come il widget Android.

Usa gli stessi portafogli (JSON) e la stessa cartella scelta nel programma (anche Google Drive), scarica da justETF i prezzi aggiornati e si
aggiorna da solo. Serve solo Python con Tkinter (incluso nell'installazione di Python per Windows). Avvio: avvia-widget.cmd

Comandi: «Port. ›» passa al portafoglio successivo (in cerchio) · «periodo ›» (per esempio «1 anno ›») passa al periodo successivo del grafico (in cerchio) · ⚙ (o tasto destro) apre le impostazioni (periodo del grafico, frequenza
di aggiornamento, dimensione, avvio con Windows) · si sposta trascinandolo con il mouse · doppio clic aggiorna subito.
"""
import bisect
import datetime
import json
import os
import sys
import threading
import time

import build
import fonti

PERIODI = [("1m", "1 mese", 31), ("3m", "3 mesi", 92), ("6m", "6 mesi", 183), ("1a", "1 anno", 365), ("3a", "3 anni", 1096), ("5a", "5 anni", 1827), ("ytd", "YTD", None), ("max", "Tutto", None)]
FREQUENZE = [(15, "15 minuti"), (30, "30 minuti"), (60, "1 ora"), (120, "2 ore"), (360, "6 ore")]
DIMENSIONI = [("p", "Piccolo", 0.85), ("m", "Medio", 1.0), ("g", "Grande", 1.3)]
LIVELLI = [("sfondo", "Dietro le finestre"), ("normale", "Normale"), ("alto", "Sempre in primo piano")]
SU, GIU = "#1f9d6b", "#d6453d"
SFONDO, SFONDO2, TESTO, TENUE, LINEA = "#0d1219", "#141b24", "#e8edf4", "#8e9bb0", "#243041"
FONT = "Segoe UI"


# ---------------------------------------------------------------- calcolo (stesso metodo della pagina)
def _ultimo_indice(date, d):
    """Indice dell'ultimo giorno non dopo `d`; -1 se d è prima dell'inizio."""
    return bisect.bisect_right(date, d) - 1


def dati_widget(doc, definizione):
    """Valori per il widget da doc {meta, funds, dates, px} e dalla definizione JSON: costo medio e rendita realizzata come nella pagina.
    Ritorna {val, cost, real, day, ds, vs, is_ (capitale versato per giorno o None)}."""
    date, px, fondi = doc["dates"], doc["px"], doc["funds"]
    T = len(date)
    sigla = {f["isin"]: f["s"] for f in fondi}
    tr = [x for x in (definizione.get("transazioni") or []) if isinstance(x, dict)]
    if not tr:  # nessun acquisto: il piano (quote intere sui pesi, ribilanciato ogni giorno) scalato sul valore di oggi
        val = sum(f["q0"] * px[f["s"]][-1] for f in fondi)
        idx = [1.0]
        for t in range(1, T):
            idx.append(idx[-1] * sum(f["w"] * px[f["s"]][t] / px[f["s"]][t - 1] for f in fondi))
        vs = [x / idx[-1] * val for x in idx]
        return {"val": val, "cost": 0.0, "real": 0.0, "day": (vs[-1] / vs[-2] - 1) if T > 1 and vs[-2] else None, "ds": list(date), "vs": vs, "is_": None}
    lotti = []
    for x in tr:
        s = sigla.get(str(x.get("isin")).upper())
        if not s:
            continue
        t = _ultimo_indice(date, str(x["data"]))
        if t < 0:
            continue
        lotti.append({"s": s, "t": t, "d": str(x["data"]), "v": x["tipo"] == "vendita", "q": float(x["quote"]), "pr": float(x["prezzo"])})
    lotti.sort(key=lambda l: (l["d"], 1 if l["v"] else 0))  # a pari data prima gli acquisti
    stato = {}  # per titolo: quote e costo medio residui
    real = 0.0
    for l in lotti:
        q, costo = stato.get(l["s"], (0.0, 0.0))
        if not l["v"]:
            q += l["q"]; costo += l["q"] * l["pr"]; l["qe"] = l["q"]; l["costo"] = l["q"] * l["pr"]
        else:
            v = min(l["q"], q); l["qe"] = v
            if v > 0:
                med = costo / q; costo -= v * med; real += v * (l["pr"] - med); q -= v
            if q < 1e-9:
                q, costo = 0.0, 0.0
        stato[l["s"]] = (q, costo)
    val = sum(q * px[s][-1] for s, (q, c) in stato.items())
    cost = sum(c for q, c in stato.values())
    if not lotti:
        return {"val": val, "cost": cost, "real": real, "day": None, "ds": [], "vs": [], "is_": None}
    i0 = min(l["t"] for l in lotti)
    vs, inv = [], []
    for t in range(i0, T):
        v = c = 0.0
        for l in lotti:
            if l["t"] <= t and l["qe"] > 0:
                sg = -1 if l["v"] else 1
                v += sg * l["qe"] * px[l["s"]][t]
                c += sg * (l["qe"] * l["pr"] if l["v"] else l["costo"])  # capitale versato = acquisti meno incassi delle vendite
        vs.append(v); inv.append(c)
    return {"val": val, "cost": cost, "real": real, "day": (vs[-1] / vs[-2] - 1) if len(vs) > 1 and vs[-2] else None, "ds": date[i0:], "vs": vs, "is_": inv}


def aggiungi_prezzi_recenti(doc, recenti):
    """Come la pagina: i giorni più recenti dell'ultimo dello storico (da justETF, per i fondi che arrivano) si aggiungono a date e prezzi."""
    date, px = doc["dates"], doc["px"]
    nuove = sorted({d for serie in recenti.values() for d, _ in serie if d > date[-1]})
    if not nuove:
        return doc
    mappa = {s: dict(serie) for s, serie in recenti.items()}
    for d in nuove:
        date.append(d)
        for s in px:
            px[s].append(mappa.get(s, {}).get(d, px[s][-1]))
    return doc


def applica_live(doc, live):
    """Prezzi in tempo reale di gettex (come justETF): sostituiscono l'ultimo prezzo del grafico o aggiungono il giorno nuovo. live: {isin: {p, d}}."""
    date, px = doc["dates"], doc["px"]
    giorni = [x["d"] for x in live.values() if x.get("d")]
    if not giorni:
        return doc
    dl = max(giorni)
    if dl < date[-1]:
        return doc
    if dl > date[-1]:
        date.append(dl)
        for sg in px:
            px[sg].append(px[sg][-1])
    for f in doc["funds"]:
        x = live.get(f["isin"])
        if x and x["p"] > 0 and x["d"] >= dl:
            px[f["s"]][-1] = x["p"]
    return doc


def periodo_serie(ds, vs, iv, codice):
    """Parte della serie nel periodo scelto. Ritorna (giorni, valori, capitale versato o None)."""
    n = len(ds)
    if n < 2 or codice == "max":
        return ds, vs, iv
    ultimo = datetime.date.fromisoformat(ds[-1])
    if codice == "ytd":
        taglio = datetime.date(ultimo.year - 1, 12, 31)
    else:
        giorni = next(p[2] for p in PERIODI if p[0] == codice)
        taglio = ultimo - datetime.timedelta(days=giorni)
    k = 0
    while k < n - 2 and datetime.date.fromisoformat(ds[k]) < taglio:
        k += 1
    return ds[k:], vs[k:], (iv[k:] if iv else None)


def rendimento_periodo(vs, iv):
    """Rendimento nel periodo: guadagno (valore finale - iniziale - nuovi versamenti) sul capitale di partenza più i versamenti."""
    if len(vs) < 2 or not vs[0] > 0:
        return None
    flussi = (iv[-1] - iv[0]) if iv else 0.0
    base = vs[0] + max(0.0, flussi)
    return (vs[-1] - vs[0] - flussi) / base if base > 0 else None


def eur(v):
    return (f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")) + " €"


def pct(v):
    return f"{v * 100:+.2f}%".replace(".", ",")


def compatto(v):
    return f"{v / 1000:.1f}k".replace(".", ",") if abs(v) >= 1000 else f"{v:.0f}"


# ---------------------------------------------------------------- impostazioni
class Impostazioni:
    def __init__(self, dati):
        self.file = os.path.join(dati, "widget.json")
        self.d = {"x": None, "y": None, "periodo": "1a", "freq": 60, "file": None, "dim": "m", "livello": "sfondo"}
        try:
            with open(self.file, encoding="utf-8") as fh:
                self.d.update(json.load(fh))
        except (OSError, ValueError):
            pass

    def salva(self):
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            with open(self.file, "w", encoding="utf-8") as fh:
                json.dump(self.d, fh)
        except OSError:
            pass


def cartella_avvio_windows():
    base = os.environ.get("APPDATA")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup") if base else None


def avvio_attivo():
    c = cartella_avvio_windows()
    return bool(c) and (os.path.exists(os.path.join(c, "myMoney-widget.vbs")) or os.path.exists(os.path.join(c, "myMoney-widget.cmd")))


def imposta_avvio(attivo):
    c = cartella_avvio_windows()
    if not c or os.name != "nt":
        return False
    p = os.path.join(c, "myMoney-widget.vbs")
    for vecchio in (p, os.path.join(c, "myMoney-widget.cmd")):  # (il .cmd è la versione precedente)
        try:
            os.remove(vecchio)
        except OSError:
            pass
    if not attivo:
        return True
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.exists(pyw):
        py = pyw
    here = os.path.dirname(os.path.abspath(__file__))
    try:  # Windows Script Host: avvia pythonw senza nessuna finestra
        with open(p, "w", encoding="mbcs", newline="\r\n") as fh:
            fh.write('Set s = CreateObject("WScript.Shell")\n')
            fh.write(f's.CurrentDirectory = "{here}"\n')
            fh.write('s.Run """' + py + '"" ""' + os.path.join(here, "widget.py") + '""", 0, False\n')
        return True
    except (OSError, UnicodeEncodeError, LookupError):
        return False


# ---------------------------------------------------------------- finestra
class Widget:
    def __init__(self, radice, pf, imp):
        import tkinter as tk
        self.tk = tk
        self.r, self.pf, self.imp = radice, pf, imp
        self.dati = {}  # file -> {"w": dati_widget, "nome": ..., "at": ts}
        self.msg = "Carico…"
        self.lock = threading.Lock()
        self.in_corso = set()
        self.da_ridisegnare = False
        self.diag = ""
        self.sposta = None
        radice.overrideredirect(True)
        try:
            radice.attributes("-alpha", 0.97)
        except Exception:
            pass
        radice.configure(bg=SFONDO)
        self.c = tk.Canvas(radice, bg=SFONDO, highlightthickness=1, highlightbackground=LINEA, bd=0)
        self.c.pack(fill="both", expand=True)
        self.dimensiona()
        self.c.bind("<ButtonPress-1>", self.inizio_trascina)
        self.c.bind("<B1-Motion>", self.trascina)
        self.c.bind("<ButtonRelease-1>", self.fine_trascina)
        radice.bind("<FocusIn>", lambda e: self.livello_dopo())
        self.c.bind("<Double-Button-1>", lambda e: self.aggiorna(True))
        self.c.bind("<Button-3>", lambda e: self.impostazioni())
        radice.bind("<Escape>", lambda e: None)
        self.disegna()
        self.applica_livello()
        self.aggiorna(True)
        self.pianifica()
        self._poll()

    # -- livello: sempre in primo piano, normale, oppure dietro alle altre finestre (come un widget sul desktop)
    def applica_livello(self):
        liv = self.imp.d.get("livello", "sfondo")
        try:
            self.r.attributes("-topmost", liv == "alto")
        except Exception:
            pass
        if liv == "sfondo":
            self.manda_dietro()

    def manda_dietro(self):
        """In fondo a tutte le finestre (ma sopra lo sfondo del desktop), senza prendere il fuoco. Si usano insieme Tk e, su Windows, l'API di sistema
        sulla finestra principale; l'esito dell'ultimo tentativo resta in self.diag (e nel file widget.log se qualcosa non va)."""
        try:
            self.r.attributes("-topmost", False)  # niente «sempre in primo piano»
        except Exception:
            pass
        try:
            self.r.lower()
        except Exception:
            pass
        if os.name != "nt":
            self.diag = "ok (Tk)"
            return
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.WinDLL("user32", use_last_error=True)
            u.GetParent.argtypes = [wintypes.HWND]; u.GetParent.restype = wintypes.HWND
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]; u.GetAncestor.restype = wintypes.HWND
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            u.SetWindowPos.restype = wintypes.BOOL
            figlio = self.r.winfo_id()
            # la finestra vera è quella che contiene quella di Tk: si prova con le due strade e, per sicurezza, con entrambe
            candidati = []
            for h in (u.GetAncestor(figlio, 2), u.GetParent(figlio), figlio):
                if h and h not in candidati:
                    candidati.append(h)
            esiti = []
            for h in candidati:
                u.SetWindowPos(h, wintypes.HWND(-2), 0, 0, 0, 0, 0x0013)  # HWND_NOTOPMOST: toglie un eventuale «sempre in primo piano»
                ok = u.SetWindowPos(h, wintypes.HWND(1), 0, 0, 0, 0, 0x0013)  # HWND_BOTTOM; NOSIZE | NOMOVE | NOACTIVATE
                esiti.append(f"{h}:{'ok' if ok else 'errore ' + str(ctypes.get_last_error())}")
            self.diag = "finestre " + ", ".join(esiti)
        except Exception as e:
            self.diag = "non riuscito: " + str(e)[:80]
        if not self.diag.startswith("finestre") or "errore" in self.diag:
            self.registra(self.diag)

    def registra(self, testo):
        """Una riga in widget.log (cartella dati dell'utente), per capire cosa non va."""
        try:
            with open(os.path.join(os.path.dirname(self.imp.file), "widget.log"), "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%d/%m/%Y %H:%M:%S ") + testo + "\n")
        except OSError:
            pass

    def livello_dopo(self):
        if self.imp.d.get("livello", "sfondo") == "sfondo":
            self.r.after(150, self.manda_dietro)  # dopo un clic (spostamento, cambio portafoglio) torna dietro

    # -- dimensioni e posizione
    def scala(self):
        return next(d[2] for d in DIMENSIONI if d[0] == self.imp.d["dim"]) if any(d[0] == self.imp.d["dim"] for d in DIMENSIONI) else 1.0

    def dimensiona(self):
        s = self.scala()
        w, h = int(350 * s), int(230 * s)
        x, y = self.imp.d.get("x"), self.imp.d.get("y")
        if x is None or y is None:
            x = self.r.winfo_screenwidth() - w - 40
            y = 60
        x = max(0, min(int(x), self.r.winfo_screenwidth() - 60))
        y = max(0, min(int(y), self.r.winfo_screenheight() - 40))
        self.r.geometry(f"{w}x{h}+{x}+{y}")
        self.r.update_idletasks()

    def inizio_trascina(self, e):
        self.sposta = (e.x_root - self.r.winfo_x(), e.y_root - self.r.winfo_y(), e.x_root, e.y_root)

    def trascina(self, e):
        if self.sposta and (abs(e.x_root - self.sposta[2]) > 3 or abs(e.y_root - self.sposta[3]) > 3):
            self.r.geometry(f"+{e.x_root - self.sposta[0]}+{e.y_root - self.sposta[1]}")

    def fine_trascina(self, e):
        if self.sposta and (abs(e.x_root - self.sposta[2]) > 3 or abs(e.y_root - self.sposta[3]) > 3):
            self.imp.d["x"], self.imp.d["y"] = self.r.winfo_x(), self.r.winfo_y()
            self.imp.salva()
        self.sposta = None
        self.livello_dopo()

    # -- portafogli
    def elenco(self):
        try:
            return [i["file"] for i in self.pf.elenco()]
        except Exception:
            return []

    def corrente(self):
        el = self.elenco()
        f = self.imp.d.get("file")
        if f in el:
            return f
        u = None
        try:
            u = self.pf.ultimo()
        except Exception:
            pass
        return u if u in el else (el[0] if el else None)

    def prossimo(self):
        el = self.elenco()
        if len(el) < 2:
            return
        f = self.corrente()
        self.imp.d["file"] = el[(el.index(f) + 1) % len(el)] if f in el else el[0]
        self.imp.salva()
        self.disegna()
        if self.imp.d["file"] not in self.dati:
            self.aggiorna(True)

    # -- dati
    def aggiorna(self, forza=False):
        f = self.corrente()
        if not f or f in self.in_corso:
            return
        self.in_corso.add(f)
        if f not in self.dati:
            self.msg = "Carico i dati…"
            self.disegna()
        threading.Thread(target=self._lavoro, args=(f,), daemon=True).start()

    def _lavoro(self, f):
        try:
            d = self.pf.definizione(f)
            if d is None:
                raise ValueError("portafoglio non trovato")
            doc = self.pf.costruisci(f, scarica=True)  # scheda e storico di oggi (una volta al giorno), poi cache
            recenti = {}
            tenuti = {x["isin"] for x in (d.get("transazioni") or [])} or {x["isin"] for x in d.get("titoli") or []}
            oggi = (datetime.date.today() - datetime.timedelta(days=12)).isoformat()
            for fo in doc["funds"]:
                if fo["isin"] in tenuti:
                    try:
                        recenti[fo["s"]] = [(a, p) for a, p in fonti.serie(fo["isin"], dal=oggi)]
                    except Exception:
                        pass
            aggiungi_prezzi_recenti(doc, recenti)
            live = {}
            try:
                live = fonti.gettex([fo["isin"] for fo in doc["funds"] if fo["isin"] in tenuti])
            except Exception:
                pass
            applica_live(doc, live)
            w = dati_widget(doc, d)
            with self.lock:
                self.dati[f] = {"w": w, "nome": f"{doc['meta']['nome']} {doc['meta']['versione']}", "at": time.time(), "gettex": bool(live)}
            self.msg = ""
        except Exception as e:  # rete assente o dati non disponibili: restano quelli già mostrati
            self.msg = "" if f in self.dati else "Dati non disponibili: " + str(e)[:60]
        finally:
            self.in_corso.discard(f)
            self.da_ridisegnare = True  # il disegno lo fa il thread principale (Tkinter non è sicuro tra thread)

    def _poll(self):
        if self.da_ridisegnare:
            self.da_ridisegnare = False
            self.disegna()
        self.giro = getattr(self, "giro", 0) + 1
        if self.imp.d.get("livello", "sfondo") == "sfondo" and self.giro % 3 == 0:
            self.manda_dietro()  # circa una volta al secondo: resta dietro anche se un'altra finestra viene aperta o spostata
        self.r.after(300, self._poll)

    def pianifica(self):
        self.r.after(max(1, int(self.imp.d.get("freq", 60))) * 60000, self._tick)

    def _tick(self):
        self.aggiorna(True)
        self.pianifica()

    # -- disegno
    def disegna(self):
        c, s = self.c, self.scala()
        c.delete("all")
        W, H = int(350 * s), int(230 * s)
        f = self.corrente()
        fo = lambda n, b=False: (FONT, max(6, int(n * s)), "bold" if b else "normal")
        el = self.elenco()
        per = self.imp.d["periodo"]
        nomeper = next((p[1] for p in PERIODI if p[0] == per), "")
        x1 = W - 10
        # barra in alto: nome, «Port. ›», rotella
        e = self.dati.get(f)
        c.create_text(12 * s, 14 * s, text=e["nome"] if e else "myMoney", anchor="w", fill=TENUE, font=fo(9))
        self._tasti(x1, 14 * s, s, fo, len(el) > 1)
        if not e:
            c.create_text(W / 2, H / 2, text=self.msg or ("Nessun portafoglio nella cartella" if not f else "…"), fill=TENUE, font=fo(10), width=W - 40, justify="center")
            return
        w = e["w"]
        c.create_text(12 * s, 44 * s, text=eur(w["val"]), anchor="w", fill=TESTO, font=fo(22, True))
        ds, vs, iv = periodo_serie(w["ds"], w["vs"], w["is_"], per)
        # riga della rendita (sull'investito) a sinistra; periodo e oggi a destra
        if w["cost"] > 0:
            roi, profit, eti = (w["val"] - w["cost"] + w["real"]) / w["cost"], w["val"] - w["cost"] + w["real"], "sull'investito"
        elif len(vs) >= 2 and vs[0] > 0:
            roi, profit, eti = w["val"] / vs[0] - 1, w["val"] - vs[0], "in " + nomeper
        else:
            roi = profit = eti = None
        y = 74 * s
        # a destra: rendimento nel periodo scelto e, dopo, la variazione di oggi; a sinistra la rendita sull'investito (la scritta solo se c'è posto)
        rp = rendimento_periodo(vs, iv)
        xr = x1
        if w["day"] is not None:
            t2 = c.create_text(xr, y, text="Oggi " + pct(w["day"]), anchor="e", fill=SU if w["day"] >= 0 else GIU, font=fo(9))
            xr = c.bbox(t2)[0] - 10 * s
        if rp is not None:
            t3 = c.create_text(xr, y, text=f"{nomeper} {pct(rp)}", anchor="e", fill=SU if rp >= 0 else GIU, font=fo(9, True))
            xr = c.bbox(t3)[0] - 10 * s
        if roi is not None:
            t1 = c.create_text(12 * s, y, text=f"{pct(roi)}  {'+' if profit >= 0 else ''}{eur(profit)}", anchor="w", fill=SU if roi >= 0 else GIU, font=fo(11, True))
            bb = c.bbox(t1)
            t4 = c.create_text(bb[2] + 6 * s, y + 1, text=eti, anchor="w", fill=TENUE, font=fo(8))
            if c.bbox(t4)[2] > xr:  # non c'è posto: resta solo la rendita
                c.delete(t4)
        # grafico
        top, bot, left = 92 * s, H - 30 * s, 40 * s
        self._grafico(ds, vs, left, top, x1, bot, s, fo)
        agg = time.strftime("%H:%M", time.localtime(e["at"]))
        c.create_text(x1, H - 9 * s, text="agg. " + agg + (" · gettex" if e.get("gettex") else "") + ("  ·  aggiorno…" if f in self.in_corso else ""), anchor="e", fill=TENUE, font=fo(7))

    def periodo_succ(self):
        """«Per. ›»: passa al periodo successivo del grafico, in cerchio."""
        cod = [p[0] for p in PERIODI]
        cur = self.imp.d.get("periodo", "1a")
        self.imp.d["periodo"] = cod[(cod.index(cur) + 1) % len(cod)] if cur in cod else cod[0]
        self.imp.salva()
        self.disegna()

    def _tasti(self, x1, y, s, fo, molti):
        c = self.c
        g = c.create_text(x1, y, text="⚙", anchor="e", fill=TENUE, font=fo(12))
        c.tag_bind(g, "<Button-1>", lambda e: self.impostazioni())
        c.tag_bind(g, "<Enter>", lambda e: c.config(cursor="hand2")); c.tag_bind(g, "<Leave>", lambda e: c.config(cursor=""))
        sinistra = c.bbox(g)[0]
        if molti:
            xp = sinistra - 12 * s
            fr = c.create_text(xp, y, text="›", anchor="e", fill=TENUE, font=fo(15))
            pt = c.create_text(c.bbox(fr)[0] - 2 * s, y, text="Port.", anchor="e", fill=TENUE, font=fo(9))
            for t in (fr, pt):
                c.tag_bind(t, "<Button-1>", lambda e: self.prossimo())
                c.tag_bind(t, "<Enter>", lambda e: c.config(cursor="hand2")); c.tag_bind(t, "<Leave>", lambda e: c.config(cursor=""))
            sinistra = c.bbox(pt)[0]
        # «periodo ›»: un clic passa al periodo successivo del grafico (1 mese, 3 mesi … YTD, Tutto), in cerchio
        nome = next((p[1] for p in PERIODI if p[0] == self.imp.d.get("periodo")), PERIODI[3][1])
        fr2 = c.create_text(sinistra - 12 * s, y, text="›", anchor="e", fill=TENUE, font=fo(15))
        pe = c.create_text(c.bbox(fr2)[0] - 2 * s, y, text=nome, anchor="e", fill=TENUE, font=fo(9))
        for t in (fr2, pe):
            c.tag_bind(t, "<Button-1>", lambda e: self.periodo_succ())
            c.tag_bind(t, "<Enter>", lambda e: c.config(cursor="hand2")); c.tag_bind(t, "<Leave>", lambda e: c.config(cursor=""))

    def _grafico(self, ds, vs, x0, y0, x1, y1, s, fo):
        c = self.c
        if len(vs) < 2:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="grafico non disponibile", fill=TENUE, font=fo(8))
            return
        mn, mx = min(vs), max(vs)
        if mx - mn < 1e-9:
            mx, mn = mx + 1, mn - 1
        pad = (mx - mn) * 0.08
        mn, mx = mn - pad, mx + pad
        n = len(vs)
        X = lambda i: x0 + (x1 - x0) * i / (n - 1)
        Y = lambda v: y1 - (y1 - y0) * (v - mn) / (mx - mn)
        col = SU if vs[-1] >= vs[0] else GIU
        for v in (mn + pad, (mn + mx) / 2, mx - pad):
            c.create_line(x0, Y(v), x1, Y(v), fill=LINEA)
            c.create_text(x0 - 4 * s, Y(v), text=compatto(v), anchor="e", fill=TENUE, font=fo(6))
        # per non appesantire il disegno si campiona al massimo un punto ogni 2 pixel
        passo = max(1, int(n / max(1, (x1 - x0) / 2)))
        idx = list(range(0, n, passo)) + ([n - 1] if (n - 1) % passo else [])
        punti = [(X(i), Y(vs[i])) for i in idx]
        poly = [(x0, y1)] + punti + [(x1, y1)]
        c.create_polygon([k for p in poly for k in p], fill=SFONDO2, outline="")
        c.create_line([k for p in punti for k in p], fill=col, width=max(1, int(1.6 * s)), joinstyle="round")
        # asse x: anni o mesi
        d0, d1 = datetime.date.fromisoformat(ds[0]), datetime.date.fromisoformat(ds[-1])
        mesi_it = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
        etichette = []
        if (d1 - d0).days > 800:
            for a in range(d0.year + 1, d1.year + 1):
                etichette.append((datetime.date(a, 1, 1), str(a)))
        else:
            k = max(1, int(((d1 - d0).days / 30) // 6) + (1 if (d1 - d0).days > 200 else 0)) if (d1 - d0).days > 60 else 0
            if k:
                a, m = d0.year, d0.month + 1
                while True:
                    if m > 12:
                        a, m = a + 1, m - 12
                    dd = datetime.date(a, m, 1)
                    if dd > d1:
                        break
                    etichette.append((dd, mesi_it[m - 1]))
                    m += k
            else:
                for j in range(0, (d1 - d0).days + 1, max(1, (d1 - d0).days // 4)):
                    dd = d0 + datetime.timedelta(days=j)
                    etichette.append((dd, f"{dd.day}/{dd.month}"))
        tot = max(1, (d1 - d0).days)
        for dd, et in etichette:
            xx = x0 + (x1 - x0) * (dd - d0).days / tot
            if x0 + 10 * s < xx < x1 - 10 * s:
                c.create_text(xx, y1 + 9 * s, text=et, fill=TENUE, font=fo(6))

    # -- impostazioni
    def impostazioni(self):
        tk = self.tk
        if getattr(self, "fin", None) and self.fin.winfo_exists():
            self.fin.lift()
            return
        w = self.fin = tk.Toplevel(self.r)
        w.title("Impostazioni del widget")
        w.configure(bg=SFONDO2)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.geometry(f"+{self.r.winfo_x()}+{self.r.winfo_y() + self.r.winfo_height() + 8}")
        pv, fv, dv = tk.StringVar(value=self.imp.d["periodo"]), tk.IntVar(value=int(self.imp.d["freq"])), tk.StringVar(value=self.imp.d["dim"])
        lv = tk.StringVar(value=self.imp.d.get("livello", "sfondo"))
        av = tk.BooleanVar(value=avvio_attivo())
        def blocco(titolo, righe, var, comando):
            fr = tk.LabelFrame(w, text=titolo, bg=SFONDO2, fg=TENUE, bd=1, padx=8, pady=4)
            fr.pack(fill="x", padx=10, pady=(8, 0))
            for k, (val, eti) in enumerate(righe):
                tk.Radiobutton(fr, text=eti, value=val, variable=var, command=comando, bg=SFONDO2, fg=TESTO, selectcolor=SFONDO, activebackground=SFONDO2, activeforeground=TESTO, anchor="w").grid(row=k // 4, column=k % 4, sticky="w", padx=4)
        def cambia():
            self.imp.d["periodo"], self.imp.d["freq"], self.imp.d["dim"], self.imp.d["livello"] = pv.get(), int(fv.get()), dv.get(), lv.get()
            self.imp.salva()
            self.dimensiona()
            self.applica_livello()
            self.r.after(50, self.disegna)
        blocco("Periodo del grafico", [(p[0], p[1]) for p in PERIODI], pv, cambia)
        blocco("Aggiornamento ogni", [(f[0], f[1]) for f in FREQUENZE], fv, cambia)
        blocco("Dimensione", [(d[0], d[1]) for d in DIMENSIONI], dv, cambia)
        blocco("Posizione rispetto alle altre finestre", LIVELLI, lv, cambia)
        tk.Label(w, text="Esito: " + (self.diag or "—"), bg=SFONDO2, fg=TENUE, anchor="w", justify="left", wraplength=360).pack(fill="x", padx=12, pady=(4, 0))
        riga = tk.Frame(w, bg=SFONDO2)
        riga.pack(fill="x", padx=10, pady=8)
        if os.name == "nt":
            tk.Checkbutton(riga, text="Avvia con Windows", variable=av, command=lambda: imposta_avvio(av.get()), bg=SFONDO2, fg=TESTO, selectcolor=SFONDO, activebackground=SFONDO2, activeforeground=TESTO).pack(side="left")
        tk.Button(riga, text="Aggiorna ora", command=lambda: self.aggiorna(True), bg=SFONDO, fg=TESTO, relief="flat", padx=10).pack(side="right")
        tk.Button(riga, text="Chiudi il widget", command=self.r.destroy, bg=SFONDO, fg=GIU, relief="flat", padx=10).pack(side="right", padx=6)


def avvia():
    import argparse
    ap = argparse.ArgumentParser(prog="widget", description="Widget myMoney per il desktop.")
    ap.add_argument("--prova", action="store_true", help="calcola e stampa i valori senza aprire la finestra")
    ap.add_argument("--avvio", choices=["on", "off"], help="attiva o disattiva l'avvio automatico del widget con Windows")
    a = ap.parse_args()
    if a.avvio:
        if os.name != "nt":
            sys.exit("L'avvio automatico è previsto solo per Windows.")
        ok = imposta_avvio(a.avvio == "on")
        print(("Avvio automatico " + ("attivato: il widget partirà all'accesso a Windows." if a.avvio == "on" else "disattivato.")) if ok else "Non sono riuscito a modificare l'avvio automatico.")
        return
    cartella = os.path.dirname(os.path.abspath(__file__))
    dati = build.cartella_dati()
    pf = build.Portafogli(cartella, os.path.join(dati, "ultimo.json"), dati=dati)
    imp = Impostazioni(dati)
    if a.prova:
        for i in pf.elenco():
            d = pf.definizione(i["file"])
            doc = pf.costruisci(i["file"], scarica=True)
            w = dati_widget(doc, d)
            ds, vs, iv = periodo_serie(w["ds"], w["vs"], w["is_"], imp.d["periodo"])
            rp = rendimento_periodo(vs, iv)
            print(i["file"], eur(w["val"]), "investito", eur(w["cost"]), "oggi", None if w["day"] is None else pct(w["day"]), imp.d["periodo"], None if rp is None else pct(rp))
        return
    try:
        import tkinter as tk
    except ImportError:
        sys.exit("Serve Tkinter: reinstalla Python da python.org lasciando spuntata l'opzione «tcl/tk and IDLE».")
    radice = tk.Tk()
    radice.title("myMoney")
    Widget(radice, pf, imp)
    radice.mainloop()


if __name__ == "__main__":
    avvia()
