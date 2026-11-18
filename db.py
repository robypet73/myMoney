"""Database SQLite (etf.db): anagrafica dei titoli, prezzi giornalieri in EUR e cambi."""
import csv
import json
import sqlite3
import time

from classify import group_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS etf (
  symbol TEXT PRIMARY KEY, isin TEXT, isin_src TEXT, isin_guess TEXT, name TEXT, short_name TEXT, group_key TEXT,
  type TEXT, asset_class TEXT, region TEXT, distribution TEXT, hedged INTEGER,
  exchange TEXT, exchange_name TEXT, currency TEXT,
  price REAL, price_eur REAL, bid REAL, ask REAL, spread_pct REAL,
  avg_volume REAL, adv_eur_m REAL,
  assets REAL, assets_eur_m REAL, ret_1y REAL, ter REAL, family TEXT, category TEXT, inception TEXT,
  stock REAL, bond REAL, cash REAL, other REAL, yield REAL, sectors TEXT,
  class_src TEXT, replication TEXT, domicile TEXT, index_name TEXT, n_holdings INTEGER, sustainable INTEGER, div_yield REAL, ret_3y REAL, ret_5y REAL,
  vol_1y REAL, vol_3y REAL, max_dd REAL, holdings TEXT, countries TEXT,
  listed_at TEXT, quote_at TEXT, detail_at TEXT, hist_at TEXT, hist_from TEXT, hist_to TEXT, hist_n INTEGER
);
CREATE TABLE IF NOT EXISTS jetf (
  isin TEXT PRIMARY KEY, name TEXT, ticker TEXT, cur TEXT, aum REAL, ter REAL, dist TEXT, repl TEXT, dom TEXT, inc TEXT, n INTEGER, sust INTEGER, div REAL,
  r1 REAL, r3 REAL, r5 REAL, vol1 REAL, vol3 REAL, dd REAL, asset TEXT, region TEXT, index_name TEXT, holdings TEXT, countries TEXT, sectors TEXT, list_at TEXT, profile_at TEXT
);
CREATE TABLE IF NOT EXISTS isin_ref (isin TEXT, symbol TEXT, src TEXT, PRIMARY KEY (isin, symbol, src)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS figi_done (isin TEXT PRIMARY KEY, at TEXT);
CREATE TABLE IF NOT EXISTS prezzi (symbol TEXT, date TEXT, close_eur REAL, PRIMARY KEY (symbol, date)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fx (cur TEXT, date TEXT, eur_per_unit REAL, PRIMARY KEY (cur, date)) WITHOUT ROWID;
"""
COLS = [r.split()[0] for r in SCHEMA.split("CREATE TABLE IF NOT EXISTS etf (")[1].split(");")[0].replace("\n", " ").split(",") if r.strip() and not r.strip().startswith("PRIMARY")]
now = lambda: time.strftime("%Y-%m-%d %H:%M:%S")


class DB:
    def __init__(self, path="etf.db"):
        self.path = path
        self.c = sqlite3.connect(path, timeout=60)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)
        have = {r[1] for r in self.c.execute("PRAGMA table_info(etf)")}
        for col in COLS:  # database creato da una versione precedente: aggiunge le colonne nuove
            if col not in have:
                self.c.execute(f"ALTER TABLE etf ADD COLUMN {col}")
        self.c.execute("CREATE INDEX IF NOT EXISTS etf_group ON etf(group_key)")
        self.c.execute("CREATE INDEX IF NOT EXISTS etf_isin ON etf(isin)")

    def close(self):
        self.c.close()

    # ---- anagrafica ----
    def upsert(self, symbol, **kw):
        kw = {k: v for k, v in kw.items() if k in COLS and k != "symbol"}
        self.c.execute("INSERT OR IGNORE INTO etf(symbol) VALUES (?)", (symbol,))
        if kw:
            self.c.execute(f"UPDATE etf SET {', '.join(k + '=?' for k in kw)} WHERE symbol=?", [*kw.values(), symbol])

    def commit(self):
        self.c.commit()

    def get(self, symbol):
        return self.c.execute("SELECT * FROM etf WHERE symbol=?", (symbol,)).fetchone()

    def all(self, where="1", args=()):
        return self.c.execute(f"SELECT * FROM etf WHERE {where}", args).fetchall()

    def update_group(self, group_key, **kw):
        """Dati del fondo (TER, patrimonio, composizione…) uguali per tutte le quotazioni dello stesso fondo."""
        kw = {k: v for k, v in kw.items() if k in COLS}
        if kw and group_key:
            self.c.execute(f"UPDATE etf SET {', '.join(k + '=?' for k in kw)} WHERE group_key=?", [*kw.values(), group_key])

    # ---- justETF ----
    JCOLS = ["name", "ticker", "cur", "aum", "ter", "dist", "repl", "dom", "inc", "n", "sust", "div", "r1", "r3", "r5", "vol1", "vol3", "dd", "asset", "region"]
    MAP = [("ter", "ter"), ("assets_eur_m", "aum"), ("ret_1y", "r1"), ("ret_3y", "r3"), ("ret_5y", "r5"), ("vol_1y", "vol1"), ("vol_3y", "vol3"), ("max_dd", "dd"),
           ("replication", "repl"), ("domicile", "dom"), ("inception", "inc"), ("n_holdings", "n"), ("sustainable", "sust"), ("div_yield", "div"), ("distribution", "dist"),
           ("index_name", "index_name"), ("holdings", "holdings"), ("countries", "countries"), ("sectors", "sectors"), ("region", "region")]

    def save_jetf(self, items):
        for x in items:
            self.c.execute("INSERT OR IGNORE INTO jetf(isin) VALUES (?)", (x["isin"],))
            self.c.execute(f"UPDATE jetf SET {', '.join('[' + k + ']=?' for k in self.JCOLS)}, list_at=? WHERE isin=?", [*(x.get(k) for k in self.JCOLS), now(), x["isin"]])

    def set_profile(self, isin, d):
        self.c.execute("UPDATE jetf SET index_name=?, holdings=?, countries=?, sectors=?, profile_at=? WHERE isin=?",
                       (d.get("index"), json.dumps(d["holdings"], ensure_ascii=False) if d.get("holdings") else None, json.dumps(d["countries"], ensure_ascii=False) if d.get("countries") else None,
                        json.dumps(d["sectors"], ensure_ascii=False) if d.get("sectors") else None, now(), isin))

    def guess_by_name(self):
        """Ipotesi (NON verificata): l'ISIN justETF il cui nome normalizzato coincide in modo univoco. Va in `isin_guess`, mai in `isin`."""
        by = {}
        for r in self.c.execute("SELECT isin, name FROM jetf"):
            by.setdefault(group_key(r["name"]), []).append(r["isin"])
        for r in self.c.execute("SELECT DISTINCT group_key FROM etf WHERE isin_guess IS NULL AND group_key IS NOT NULL AND group_key<>''").fetchall():
            c = by.get(r["group_key"])
            if c and len(c) == 1:
                self.c.execute("UPDATE etf SET isin_guess=? WHERE group_key=? AND isin_guess IS NULL", (c[0], r["group_key"]))

    def guess_by_ticker(self):
        """Ipotesi (NON verificata): ticker justETF uguale a quello del simbolo e nomi simili."""
        by = {}
        for r in self.c.execute("SELECT isin, name, ticker FROM jetf WHERE ticker IS NOT NULL"):
            by.setdefault(r["ticker"].upper(), []).append((r["isin"], set(group_key(r["name"]).split())))
        for r in self.c.execute("SELECT symbol, group_key FROM etf WHERE isin_guess IS NULL").fetchall():
            c = by.get(r["symbol"].split(".")[0].upper())
            w = set((r["group_key"] or "").split())
            ok = [i for i, t in (c or []) if w and t and len(w & t) / len(w | t) >= 0.5]
            if len(ok) == 1:
                self.c.execute("UPDATE etf SET isin_guess=? WHERE symbol=?", (ok[0], r["symbol"]))

    def save_isin_refs(self, refs):
        self.c.executemany("INSERT OR REPLACE INTO isin_ref VALUES (?,?,?)", refs)

    def link_verified(self):
        """Assegna `isin` solo dove una fonte ufficiale (elenco Xetra, OpenFIGI) lega quell'ISIN a quel simbolo. Se due ISIN contendono lo stesso simbolo vale
        quello che coincide con l'ipotesi, altrimenti nessuno; se il nome justETF dell'ISIN non somiglia a quello del titolo, nessuno. Ritorna (verificati, scartati)."""
        # database di versioni precedenti: gli ISIN non verificati diventano ipotesi
        self.c.execute("UPDATE etf SET isin_guess=COALESCE(isin_guess, isin) WHERE isin IS NOT NULL AND isin_src IS NULL")
        self.c.execute("UPDATE etf SET isin=NULL WHERE isin_src IS NULL")
        cand = {}
        for r in self.c.execute("SELECT r.symbol, r.isin, r.src FROM isin_ref r JOIN etf e ON e.symbol=r.symbol"):
            cand.setdefault(r["symbol"], {}).setdefault(r["isin"], set()).add(r["src"])
        amb = 0
        for sym, d in cand.items():
            if len(d) > 1:
                g = self.c.execute("SELECT isin_guess FROM etf WHERE symbol=?", (sym,)).fetchone()[0]
                if g not in d:
                    amb += 1
                    continue
                d = {g: d[g]}
            (isin, srcs), = d.items()
            j = self.c.execute("SELECT name FROM jetf WHERE isin=?", (isin,)).fetchone()
            if j and j[0]:  # controllo di coerenza: il nome justETF di quell'ISIN deve somigliare a quello del titolo
                w1, w2 = set(group_key(j[0]).split()), set(group_key(self.c.execute("SELECT name FROM etf WHERE symbol=?", (sym,)).fetchone()[0]).split())
                if w1 and w2 and len(w1 & w2) / len(w1 | w2) < 0.25:
                    amb += 1
                    continue
            self.c.execute("UPDATE etf SET isin=?, isin_src=? WHERE symbol=?", (isin, "+".join(sorted(srcs)), sym))
        return self.c.execute("SELECT COUNT(*) FROM etf WHERE isin IS NOT NULL").fetchone()[0], amb

    def apply_jetf(self):
        """Copia le caratteristiche justETF (ufficiali) nei titoli con quell'ISIN: hanno la precedenza sui dati di Yahoo e sul nome."""
        for e, j in self.MAP:
            sub = f"(SELECT [{j}] FROM jetf WHERE jetf.isin=etf.isin)"
            self.c.execute(f"UPDATE etf SET [{e}]={sub} WHERE isin IS NOT NULL AND {sub} IS NOT NULL")
        sub = "(SELECT asset FROM jetf WHERE jetf.isin=etf.isin)"
        self.c.execute(f"UPDATE etf SET asset_class={sub}, class_src='justetf' WHERE isin IS NOT NULL AND {sub} IS NOT NULL")

    def fill_groups(self):
        """TER, patrimonio e data di lancio, noti per una quotazione, valgono per tutte le quotazioni dello stesso fondo."""
        for col, agg in (("ter", "MAX(t.ter)"), ("assets_eur_m", "MAX(t.assets_eur_m)"), ("inception", "MIN(t.inception)")):
            self.c.execute(f"UPDATE etf SET {col}=(SELECT {agg} FROM etf t WHERE t.group_key=etf.group_key) WHERE {col} IS NULL AND group_key IS NOT NULL AND group_key<>''")

    def stats(self):
        q = lambda s: self.c.execute(s).fetchone()[0]
        return {"titoli": q("SELECT COUNT(*) FROM etf"), "fondi": q("SELECT COUNT(DISTINCT group_key) FROM etf"),
                "con_dettagli": q("SELECT COUNT(*) FROM etf WHERE detail_at IS NOT NULL"), "con_isin": q("SELECT COUNT(*) FROM etf WHERE isin IS NOT NULL"), "con_storico": q("SELECT COUNT(*) FROM etf WHERE hist_n > 0"),
                "ultimo": self.c.execute("SELECT MAX(listed_at) FROM etf").fetchone()[0]}

    # ---- prezzi e cambi ----
    def save_prices(self, symbol, rows):
        self.c.execute("DELETE FROM prezzi WHERE symbol=?", (symbol,))
        self.c.executemany("INSERT OR REPLACE INTO prezzi VALUES (?,?,?)", [(symbol, d, p) for d, p in rows])
        self.upsert(symbol, hist_at=now(), hist_n=len(rows), hist_from=rows[0][0] if rows else None, hist_to=rows[-1][0] if rows else None)

    def prices(self, symbol):
        return self.c.execute("SELECT date, close_eur FROM prezzi WHERE symbol=? ORDER BY date", (symbol,)).fetchall()

    def save_fx(self, cur, rates):
        self.c.executemany("INSERT OR REPLACE INTO fx VALUES (?,?,?)", [(cur, d, r) for d, r in rates.items()])

    def fx(self, cur):
        return {r[0]: r[1] for r in self.c.execute("SELECT date, eur_per_unit FROM fx WHERE cur=? ORDER BY date", (cur,))}

    def last_fx(self, cur):
        if cur == "EUR":
            return 1.0
        r = self.c.execute("SELECT eur_per_unit FROM fx WHERE cur=? ORDER BY date DESC LIMIT 1", (cur,)).fetchone()
        return r[0] if r else None

    # ---- esportazione ----
    def export_csv(self, path):
        rows = self.all("1 ORDER BY assets_eur_m IS NULL, assets_eur_m DESC, adv_eur_m DESC")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: si apre bene in Excel
            w = csv.writer(f, delimiter=";")
            w.writerow(COLS)
            for r in rows:
                w.writerow(["" if r[c] is None else r[c] for c in COLS])
        return len(rows)
