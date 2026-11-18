"""Database SQLite (etf.db): anagrafica dei titoli, prezzi giornalieri in EUR e cambi."""
import csv
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS etf (
  symbol TEXT PRIMARY KEY, name TEXT, short_name TEXT, group_key TEXT,
  type TEXT, asset_class TEXT, region TEXT, distribution TEXT, hedged INTEGER,
  exchange TEXT, exchange_name TEXT, currency TEXT,
  price REAL, price_eur REAL, bid REAL, ask REAL, spread_pct REAL,
  avg_volume REAL, adv_eur_m REAL,
  assets REAL, assets_eur_m REAL, ret_1y REAL, ter REAL, family TEXT, category TEXT, inception TEXT,
  stock REAL, bond REAL, cash REAL, other REAL, yield REAL, sectors TEXT,
  listed_at TEXT, quote_at TEXT, detail_at TEXT, hist_at TEXT, hist_from TEXT, hist_to TEXT, hist_n INTEGER
);
CREATE INDEX IF NOT EXISTS etf_group ON etf(group_key);
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

    def fill_groups(self):
        """TER, patrimonio e data di lancio, noti per una quotazione, valgono per tutte le quotazioni dello stesso fondo."""
        for col, agg in (("ter", "MAX(t.ter)"), ("assets_eur_m", "MAX(t.assets_eur_m)"), ("inception", "MIN(t.inception)")):
            self.c.execute(f"UPDATE etf SET {col}=(SELECT {agg} FROM etf t WHERE t.group_key=etf.group_key) WHERE {col} IS NULL AND group_key IS NOT NULL AND group_key<>''")

    def stats(self):
        q = lambda s: self.c.execute(s).fetchone()[0]
        return {"titoli": q("SELECT COUNT(*) FROM etf"), "fondi": q("SELECT COUNT(DISTINCT group_key) FROM etf"),
                "con_dettagli": q("SELECT COUNT(*) FROM etf WHERE detail_at IS NOT NULL"), "con_storico": q("SELECT COUNT(*) FROM etf WHERE hist_n > 0"),
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
