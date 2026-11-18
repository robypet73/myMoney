"""Finestra grafica (Tkinter) di myMoney."""
import csv
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import classify as C
import jobs
import portfolio as PF
from db import DB
from yahoo import EXCHANGES, Cancelled, Yahoo


def it(x, d=2):
    """Numero in formato italiano."""
    return "—" if x is None else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fnum(s, default=None):
    s = (s or "").strip().replace(".", "").replace(",", ".") if "," in (s or "") else (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return default


class Runner:
    """Esegue un'operazione lunga in un thread (con la sua connessione al database), con avanzamento e annullamento."""

    def __init__(self, root, path, on_progress, on_done):
        self.root, self.path, self.on_progress, self.on_done = root, path, on_progress, on_done
        self.q, self.cancel, self.busy = queue.Queue(), threading.Event(), False
        self.root.after(150, self.poll)

    def start(self, fn):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()

        def work():
            db = DB(self.path)
            try:
                y = Yahoo(cancel=self.cancel.is_set, log=lambda m: self.q.put(("log", m)))
                res = fn(db, y, lambda t, d=0, n=0: self.q.put(("p", t, d, n)))
                db.commit()
                self.q.put(("end", res, None))
            except Cancelled:
                db.commit()
                self.q.put(("end", None, "Interrotto: quanto scaricato è salvato"))
            except Exception as e:  # noqa: BLE001
                db.commit()
                self.q.put(("end", None, f"Errore: {e}"))
            finally:
                db.close()

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "end":
                    self.busy = False
                    self.on_done(m[1], m[2])
                else:
                    self.on_progress(*m)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)


class App:
    def __init__(self, path):
        self.path = path
        self.root = tk.Tk()
        self.root.title("myMoney")
        self.root.geometry("760x560")
        self.db = DB(path)
        self.runner = Runner(self.root, path, self.progress, self.done)
        self.after_done = None
        self.settings_path = os.path.join(os.path.dirname(os.path.abspath(path)), "impostazioni.json")
        self.settings = {}
        try:
            self.settings = json.load(open(self.settings_path, encoding="utf-8"))
        except (OSError, ValueError):
            pass
        f = ttk.Frame(self.root, padding=12)
        f.pack(fill="both", expand=True)
        self.info = ttk.Label(f, text="")
        self.info.pack(anchor="w")
        box = ttk.LabelFrame(f, text="Archivio titoli (Yahoo Finance)", padding=8)
        box.pack(fill="x", pady=8)
        self.ex = {}
        row = ttk.Frame(box)
        row.pack(fill="x")
        for code, name in EXCHANGES.items():
            self.ex[code] = tk.BooleanVar(value=True)
            ttk.Checkbutton(row, text=name, variable=self.ex[code]).pack(side="left", padx=4)
        self.det = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Scarica anche le schede dei fondi (TER, patrimonio, composizione): molto più lento, si può interrompere e riprendere", variable=self.det).pack(anchor="w", pady=4)
        b = ttk.Frame(box)
        b.pack(fill="x")
        self.btns = [ttk.Button(b, text="Scarica elenco titoli", command=self.download),
                     ttk.Button(b, text="Aggiorna prezzi attuali", command=self.quotes),
                     ttk.Button(b, text="Esporta CSV…", command=self.export)]
        for x in self.btns:
            x.pack(side="left", padx=4)
        self.create = ttk.Button(f, text="Crea portafoglio…", command=self.open_create)
        self.create.pack(anchor="w", pady=8, ipadx=10, ipady=4)
        self.bar = ttk.Progressbar(f, mode="determinate")
        self.bar.pack(fill="x")
        r = ttk.Frame(f)
        r.pack(fill="x", pady=4)
        self.status = ttk.Label(r, text="")
        self.status.pack(side="left")
        self.stop = ttk.Button(r, text="Annulla", command=self.runner.cancel.set, state="disabled")
        self.stop.pack(side="right")
        self.log = tk.Text(f, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # ---- stato ----
    def refresh(self):
        s = self.db.stats()
        self.info.config(text=f"Database: {self.path}\n{s['titoli']} titoli ({s['fondi']} fondi) · {s['con_dettagli']} con scheda · {s['con_storico']} con storico prezzi"
                              + (f" · ultimo elenco {s['ultimo']}" if s["ultimo"] else ""))

    def say(self, t):
        self.log.config(state="normal")
        self.log.insert("end", t + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def progress(self, kind, a, b=0, c=0):
        if kind == "log":
            return self.say(a)
        self.status.config(text=a)
        self.bar.config(mode="determinate", maximum=max(c, 1), value=b if c else 0)

    def run(self, fn, label, after=None):
        if self.runner.busy:
            return
        for x in (*self.btns, self.create):
            x.config(state="disabled")
        self.stop.config(state="normal")
        self.after_done = after
        self.say(label)
        self.runner.start(fn)

    def done(self, res, err):
        for x in (*self.btns, self.create):
            x.config(state="normal")
        self.stop.config(state="disabled")
        self.db.close()
        self.db = DB(self.path)
        self.refresh()
        self.status.config(text=err or "Fatto")
        self.say(err or "Fatto")
        cb, self.after_done = self.after_done, None
        if cb:
            cb(res, err)

    # ---- azioni ----
    def download(self):
        ex = [c for c, v in self.ex.items() if v.get()]
        if not ex:
            return messagebox.showinfo("myMoney", "Scegli almeno una borsa")
        det = self.det.get()
        self.run(lambda db, y, p: jobs.download_catalog(db, y, ex, det, None, p), "Scarico l'elenco dei titoli…")

    def quotes(self):
        self.run(lambda db, y, p: jobs.update_quotes(db, y, None, p), "Aggiorno i prezzi attuali…")

    def export(self):
        f = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="etf.csv", filetypes=[("CSV", "*.csv")])
        if f:
            self.say(f"{self.db.export_csv(f)} righe esportate in {f}")

    def save_settings(self):
        try:
            json.dump(self.settings, open(self.settings_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        except OSError:
            pass

    def open_create(self):
        if self.db.stats()["titoli"] == 0:
            return messagebox.showinfo("myMoney", "L'archivio è vuoto: prima premi «Scarica elenco titoli».")
        CreateDialog(self)

    def close(self):
        if self.runner.busy:
            self.runner.cancel.set()
        self.db.close()
        self.root.destroy()


class CreateDialog:
    """Parametri di ricerca e di portafoglio."""

    def __init__(self, app):
        self.app, self.s = app, app.settings.get("create", {})
        self.top = tk.Toplevel(app.root)
        self.top.title("Crea portafoglio")
        self.top.geometry("940x660")
        outer = ttk.Frame(self.top, padding=10)
        outer.pack(fill="both", expand=True)
        self.v = {}
        # portafoglio
        pf = ttk.LabelFrame(outer, text="Portafoglio", padding=8)
        pf.pack(fill="x")
        self.num(pf, 0, 0, "Importo (€)", "amount", "10000")
        self.num(pf, 0, 2, "ETF minimo", "kmin", "3")
        self.num(pf, 0, 4, "ETF massimo", "kmax", "8")
        self.num(pf, 1, 0, "Peso max per ETF (%)", "cap", "35")
        self.num(pf, 1, 2, "Tasso privo di rischio (%)", "rf", "2")
        self.num(pf, 1, 4, "Volatilità max aggressivo (%)", "vol_aggr", "20")
        # composizione
        cp = ttk.LabelFrame(outer, text="Composizione: massimo per classe (%)  —  100 = libero, 0 = esclusa", padding=8)
        cp.pack(fill="x", pady=6)
        for k, c in enumerate(C.CLASSES):
            self.num(cp, k // 4, (k % 4) * 2, c, "cls_" + c, "100", w=5)
        # criteri
        cr = ttk.LabelFrame(outer, text="Criteri di ricerca (lascia vuoto = nessun limite)", padding=8)
        cr.pack(fill="both", expand=True)
        self.txt(cr, 0, "Nome contiene", "text")
        self.multi(cr, 1, "Borse (in ordine di preferenza)", "exchanges", [(c, n) for c, n in EXCHANGES.items()])
        self.multi(cr, 2, "Tipo", "types", [(x, x) for x in ("ETF", "ETC", "ETN/ETP")])
        self.multi(cr, 3, "Valuta di negoziazione", "currencies", [(x, x) for x in ("EUR", "USD", "GBP", "CHF")])
        self.multi(cr, 4, "Distribuzione", "distributions", [(x, x) for x in ("Accumulazione", "Distribuzione")])
        self.multi(cr, 5, "Area", "regions", [(n, n) for n, _ in C.REGIONS])
        g = ttk.Frame(cr)
        g.grid(row=6, column=0, columnspan=2, sticky="w", pady=4)
        for k, (lab, key, d) in enumerate([("TER max %", "ter_max", ""), ("Patrimonio min M€", "assets_min", ""), ("Volume medio min M€/giorno", "adv_min", ""),
                                           ("Spread max %", "spread_max", ""), ("Rendimento 1 anno min %", "ret1y_min", ""), ("Volatilità max %", "vol_max", ""),
                                           ("Storia minima (anni)", "min_years", "1,5"), ("Titoli analizzati (max)", "pool", "150")]):
            self.num(g, k // 3, (k % 3) * 2, lab, key, d, w=7)
        self.unk = tk.BooleanVar(value=self.s.get("unknown", False))
        ttk.Checkbutton(cr, text="Includi i titoli senza il dato richiesto (TER, patrimonio, spread… non scaricati)", variable=self.unk).grid(row=7, column=0, columnspan=2, sticky="w")
        self.note = ttk.Label(outer, text="", foreground="#555")
        self.note.pack(anchor="w", pady=2)
        b = ttk.Frame(outer)
        b.pack(fill="x")
        ttk.Button(b, text="Calcola le proposte", command=self.calc).pack(side="left", ipadx=8, ipady=3)
        ttk.Button(b, text="Quanti titoli passano?", command=self.count).pack(side="left", padx=8)
        ttk.Button(b, text="Chiudi", command=self.top.destroy).pack(side="right")

    # ---- campi ----
    def num(self, parent, r, c, label, key, default, w=8):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="e", padx=(8, 3), pady=2)
        var = tk.StringVar(value=str(self.s.get(key, default)))
        ttk.Entry(parent, textvariable=var, width=w).grid(row=r, column=c + 1, sticky="w")
        self.v[key] = var

    def txt(self, parent, r, label, key):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="e", padx=3, pady=2)
        var = tk.StringVar(value=self.s.get(key, ""))
        ttk.Entry(parent, textvariable=var, width=40).grid(row=r, column=1, sticky="w")
        self.v[key] = var

    def multi(self, parent, r, label, key, opts):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="e", padx=3, pady=2)
        fr = ttk.Frame(parent)
        fr.grid(row=r, column=1, sticky="w")
        sel = self.s.get(key, [])
        self.v[key] = {}
        for code, name in opts:
            var = tk.BooleanVar(value=code in sel)
            ttk.Checkbutton(fr, text=name, variable=var).pack(side="left", padx=3)
            self.v[key][code] = var

    def read(self):
        g = lambda k, d=None: fnum(self.v[k].get(), d)
        f = {"text": self.v["text"].get(), "unknown": self.unk.get(), "ter_max": g("ter_max"), "assets_min": g("assets_min"), "adv_min": g("adv_min"),
             "spread_max": g("spread_max"), "ret1y_min": g("ret1y_min"), "vol_max": g("vol_max"), "min_years": g("min_years", 1.5), "pool": int(g("pool", 150) or 0),
             "class_caps": {c: g("cls_" + c, 100) for c in C.CLASSES}}
        for k in ("exchanges", "types", "currencies", "distributions", "regions"):
            f[k] = [c for c, var in self.v[k].items() if var.get()]
        p = {"amount": g("amount", 10000), "kmin": int(g("kmin", 3)), "kmax": int(g("kmax", 8)), "cap": g("cap", 35) / 100, "rf": g("rf", 2) / 100, "vol_aggr": g("vol_aggr", 20) / 100,
             "caps": {c: v / 100 for c, v in f["class_caps"].items()}}
        saved = {k: (v.get() if isinstance(v, tk.StringVar) else [c for c, x in v.items() if x.get()]) for k, v in self.v.items()}
        saved["unknown"] = self.unk.get()
        self.app.settings["create"] = saved
        self.app.save_settings()
        return f, p

    def check(self, f, p):
        if sum(p["caps"].values()) < 1 - 1e-9:
            messagebox.showwarning("myMoney", "La somma dei massimi per classe è sotto il 100%: il portafoglio non può essere composto.", parent=self.top)
            return False
        if p["cap"] * p["kmax"] < 1:
            messagebox.showwarning("myMoney", f"Con al massimo {p['kmax']} ETF il peso massimo per ETF deve essere almeno {100 / p['kmax']:.0f}%.", parent=self.top)
            return False
        return True

    def count(self):
        f, p = self.read()
        rows = PF.select(self.app.db, f)
        with_h = sum(1 for r in rows if r["hist_n"])
        self.note.config(text=f"{len(rows)} fondi passano i criteri (un titolo per fondo, al massimo {f['pool']}); {with_h} hanno già lo storico dei prezzi.")

    def calc(self):
        f, p = self.read()
        if not self.check(f, p):
            return
        rows = PF.select(self.app.db, f)
        if len(rows) < max(2, p["kmin"]):
            return messagebox.showinfo("myMoney", f"Solo {len(rows)} fondi passano i criteri: allarga la ricerca.", parent=self.top)
        syms = [r["symbol"] for r in rows]

        def job(db, y, prog):
            jobs.download_history(db, y, syms, prog)
            prog("Calcolo le proposte…", 0, 0)
            fresh = db.all(f"symbol IN ({','.join('?' * len(syms))})", syms)
            order = {s: i for i, s in enumerate(syms)}
            fresh.sort(key=lambda r: order[r["symbol"]])
            ds = PF.load_dataset(db, fresh, 3.0, f["min_years"] or 0, f["vol_max"], f["ret1y_min"])
            if ds is None:
                return ("Servono almeno 2 titoli con storico sufficiente: abbassa «Storia minima» o allarga i criteri.", None, None)
            out, fail = PF.propose(ds, **p)
            return (None, ds, (out, fail, p))

        def after(res, err):
            if err or not res:
                return
            msg, ds, extra = res
            if msg:
                return messagebox.showinfo("myMoney", msg, parent=self.top)
            ResultWindow(self.app, ds, *extra)

        self.top.destroy()
        self.app.run(job, f"Calcolo su {len(rows)} fondi (scarico prima lo storico dei prezzi mancante)…", after)


class ResultWindow:
    def __init__(self, app, ds, out, fail, p):
        top = tk.Toplevel(app.root)
        top.title("Proposte di portafoglio")
        top.geometry("980x560")
        head = f"{len(ds.rows)} fondi analizzati · periodo {ds.dates[0]} → {ds.dates[-1]} ({ds.years:.1f} anni) · rendimenti a 5 giorni, in EUR, dividendi inclusi · simulazione sul passato, non una previsione né una consulenza"
        ttk.Label(top, text=head, wraplength=950, padding=8).pack(anchor="w")
        if fail:
            ttk.Label(top, text="Proposta non calcolabile con questi vincoli: " + ", ".join(fail), foreground="#b00", padding=(8, 0)).pack(anchor="w")
        nb = ttk.Notebook(top)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for pr in out:
            fr = ttk.Frame(nb, padding=8)
            nb.add(fr, text=pr["name"])
            ttk.Label(fr, text=pr["desc"] + (" " + pr["note"] if pr["note"] else "")).pack(anchor="w")
            comp = " · ".join(f"{k} {it(v * 100, 0)}%" for k, v in sorted(pr["classes"].items(), key=lambda x: -x[1]))
            ttk.Label(fr, text=f"Rendimento storico {it(pr['ret'] * 100, 1)}% · Volatilità {it(pr['vol'] * 100, 1)}% · Sharpe {it(pr['sharpe'])} · Diversificazione {it(pr['dr'])} · "
                               f"Correlazione media {it(pr['corr'])} · TER {it(pr['ter'], 2) if pr['ter'] is not None else '—'}%\n{comp}", padding=(0, 4)).pack(anchor="w")
            cols = [("symbol", "Simbolo", 90), ("name", "Nome", 330), ("class", "Classe", 110), ("weight", "Peso", 60), ("amount", "Importo €", 90), ("qty", "Quote", 60), ("price", "Prezzo €", 80), ("ter", "TER %", 55)]
            tv = ttk.Treeview(fr, columns=[c[0] for c in cols], show="headings", height=min(12, len(pr["items"])))
            for k, t, w in cols:
                tv.heading(k, text=t)
                tv.column(k, width=w, anchor="w" if k in ("symbol", "name", "class") else "e")
            for i in pr["items"]:
                tv.insert("", "end", values=(i["symbol"], i["name"], i["class"], it(i["weight"] * 100, 1) + "%", it(i["amount"]), i["qty"], it(i["price"], 3), it(i["ter"]) if i["ter"] is not None else "—"))
            tv.pack(fill="x", pady=6)
            if p["amount"]:
                ttk.Label(fr, text=f"Con quote intere: investiti {it(pr['spent'])} € su {it(p['amount'])} €, avanzano {it(pr['cash'])} €.").pack(anchor="w")
            ttk.Button(fr, text="Salva CSV…", command=lambda pr=pr: self.save(pr)).pack(anchor="w", pady=6)

    @staticmethod
    def save(pr):
        f = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"portafoglio-{pr['name'].lower()}.csv", filetypes=[("CSV", "*.csv")])
        if not f:
            return
        with open(f, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["simbolo", "nome", "classe", "borsa", "peso_%", "importo_eur", "quote", "prezzo_eur", "costo_eur", "ter_%"])
            for i in pr["items"]:
                w.writerow([i["symbol"], i["name"], i["class"], i["exchange"], round(i["weight"] * 100, 2), round(i["amount"], 2), i["qty"], round(i["price"], 3), round(i["cost"], 2), "" if i["ter"] is None else i["ter"]])


def run(path):
    App(path).root.mainloop()
    return 0
