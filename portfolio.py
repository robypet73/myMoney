"""Selezione dei titoli con i criteri di ricerca e calcolo delle proposte di portafoglio (Sharpe, bilanciato, aggressivo)."""
import math
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize

import classify as C

AGG = 252 / 5          # rendimenti a 5 giorni sovrapposti, annualizzati
SHRINK = 0.5           # i rendimenti storici sono rumorosi: per scegliere i pesi si portano a metà strada verso la media dei titoli
MINW = 0.03            # peso minimo di un titolo scelto (sotto, si scarta)


# ------------------------------------------------------------------ criteri di ricerca
DEFAULT_FILTERS = {"text": "", "exchanges": [], "types": [], "currencies": [], "distributions": [], "regions": [], "replications": [], "domiciles": [], "sustainable": False, "class_caps": {},
                   "ter_max": None, "assets_min": None, "adv_min": None, "spread_max": None, "ret1y_min": None, "vol_max": None,
                   "min_years": 1.5, "pool": 150, "unknown": False}


def select(db, f, today=None):
    """Titoli che rispettano i criteri (un solo titolo per fondo), ordinati per patrimonio e poi per liquidità, al massimo `pool`.
    Un criterio su un dato mancante esclude il titolo, salvo `unknown`."""
    f = {**DEFAULT_FILTERS, **f}
    today = today or datetime.now()
    caps = f["class_caps"] or {}
    text = [t for t in f["text"].lower().split() if t]
    unk = f["unknown"]

    def ok(v, test):
        return (unk and v is None) or (v is not None and test(v))

    out = []
    for r in db.all("price_eur IS NOT NULL"):
        n = (r["name"] or "") + " " + r["symbol"]
        if text and not all(t in n.lower() for t in text):
            continue
        if f["exchanges"] and r["exchange"] not in f["exchanges"]:
            continue
        if f["types"] and r["type"] not in f["types"]:
            continue
        if f["currencies"] and r["currency"] not in f["currencies"]:
            continue
        if f["distributions"] and not ok(r["distribution"] or None, lambda v: v in f["distributions"]):
            continue
        if f["regions"] and not ok(r["region"] or None, lambda v: v in f["regions"]):
            continue
        if f["replications"] and not ok(r["replication"], lambda v: any(v.startswith(x) for x in f["replications"])):
            continue
        if f["domiciles"] and not ok(r["domicile"], lambda v: v in f["domiciles"]):
            continue
        if f["sustainable"] and not ok(r["sustainable"], lambda v: v == 1):
            continue
        if caps and caps.get(r["asset_class"] or "Altro", 100) <= 0:
            continue
        if f["ter_max"] is not None and not ok(r["ter"], lambda v: v <= f["ter_max"]):
            continue
        if f["assets_min"] is not None and not ok(r["assets_eur_m"], lambda v: v >= f["assets_min"]):
            continue
        if f["adv_min"] is not None and not ok(r["adv_eur_m"], lambda v: v >= f["adv_min"]):
            continue
        if f["spread_max"] is not None and not ok(r["spread_pct"], lambda v: v <= f["spread_max"]):
            continue
        if f["ret1y_min"] is not None and not ok(r["ret_1y"], lambda v: v >= f["ret1y_min"]):
            continue
        if r["inception"] and f["min_years"] and r["inception"] > (today - timedelta(days=365 * f["min_years"])).strftime("%Y-%m-%d"):
            continue
        out.append(r)
    # un solo titolo per fondo: EUR, poi la borsa preferita (ordine scelto dall'utente), poi il volume
    order = {e: i for i, e in enumerate(f["exchanges"])}
    best = {}
    for r in out:
        k = r["group_key"] or r["symbol"]
        score = (r["currency"] == "EUR", -order.get(r["exchange"], 99), r["adv_eur_m"] or 0)
        if k not in best or score > best[k][0]:
            best[k] = (score, r)
    rows = [v[1] for v in best.values()]
    rows.sort(key=lambda r: (r["assets_eur_m"] or 0, r["adv_eur_m"] or 0), reverse=True)
    return rows[: int(f["pool"])] if f["pool"] else rows


# ------------------------------------------------------------------ dati per il calcolo
class Dataset:
    def __init__(self, rows, dates, P):
        self.rows, self.dates, self.P = rows, dates, P
        self.sym = [r["symbol"] for r in rows]
        R = P[5:] / P[:-5] - 1
        self.mu = R.mean(axis=0) * AGG
        self.cov = np.cov(R, rowvar=False).reshape(len(rows), len(rows)) * AGG
        self.sd = np.sqrt(np.diag(self.cov))
        self.cls = [r["asset_class"] or "Altro" for r in rows]
        self.years = len(dates) / 252


def load_dataset(db, rows, years=3.0, min_years=1.5, vol_max=None, ret1y_min=None, today=None):
    """Allinea gli storici in EUR (ultimi `years` anni, finestra in comune) e scarta chi ha troppo poca storia o non rispetta rendimento/volatilità."""
    today = today or datetime.now()
    cut = (today - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    need = (today - timedelta(days=365 * min_years)).strftime("%Y-%m-%d")
    ser = {}
    for r in rows:
        s = db.prices(r["symbol"])
        if len(s) >= 60 and s[0][0] <= need:
            ser[r["symbol"]] = {d: p for d, p in s if d >= cut}
    keep = []
    for r in rows:
        s = ser.get(r["symbol"])
        if not s:
            continue
        v = np.array([s[d] for d in sorted(s)])
        a = v[-253:]
        r1 = a[-1] / a[0] - 1 if len(a) > 200 else None
        vol = np.std(a[5:] / a[:-5] - 1) * math.sqrt(AGG) if len(a) > 200 else None
        if ret1y_min is not None and (r1 is None or r1 * 100 < ret1y_min):
            continue
        if vol_max is not None and (vol is None or vol * 100 > vol_max):
            continue
        keep.append(r)
    if len(keep) < 2:
        return None
    start = max(min(ser[r["symbol"]]) for r in keep)
    dates = sorted({d for r in keep for d in ser[r["symbol"]] if d >= start})
    darr = np.array(dates)
    P = np.empty((len(dates), len(keep)))
    for j, r in enumerate(keep):  # valore dell'ultimo giorno di quotazione (festività diverse tra le borse)
        ds_ = np.array(sorted(ser[r["symbol"]]))
        vs = np.array([ser[r["symbol"]][d] for d in ds_])
        P[:, j] = vs[np.clip(np.searchsorted(ds_, darr, side="right") - 1, 0, len(vs) - 1)]
    if len(dates) < 120:
        return None
    return Dataset(keep, dates, P)


# ------------------------------------------------------------------ ottimizzazione
def _cons(n, cls_idx, cls_cap):
    c = [{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(n)}]
    for idx, cap in zip(cls_idx, cls_cap):
        c.append({"type": "ineq", "fun": lambda w, i=idx, cap=cap: cap - w[i].sum(), "jac": lambda w, i=idx: -np.isin(np.arange(n), i).astype(float)})
    return c


def _check(w, cap, cls_idx, cls_cap):
    return abs(w.sum() - 1) < 1e-4 and (w > -1e-6).all() and (w < cap + 1e-4).all() and all(w[i].sum() <= c + 1e-3 for i, c in zip(cls_idx, cls_cap))


def solve(kind, mu, cov, cap, cls, class_caps, rf=0.02, vol_cap=None, w0=None):
    """Pesi di un portafoglio solo lungo: kind = sharpe | minvar | aggr | erc. Ritorna None se i vincoli non sono rispettabili."""
    n = len(mu)
    cap = max(cap, 1.02 / n)
    cls_idx = [np.array([i for i, c in enumerate(cls) if c == k]) for k in class_caps if any(c == k for c in cls)]
    cls_cap = [class_caps[k] for k in class_caps if any(c == k for c in cls)]
    cons = _cons(n, cls_idx, cls_cap)
    x0 = np.full(n, 1 / n) if w0 is None else w0
    if kind == "sharpe":
        def f(w):
            v = max(w @ cov @ w, 1e-12)
            return -(w @ mu - rf) / math.sqrt(v)

        def g(w):
            v = max(w @ cov @ w, 1e-12)
            s = math.sqrt(v)
            return -mu / s + (w @ mu - rf) * (cov @ w) / s ** 3
    elif kind == "minvar":
        f = lambda w: w @ cov @ w
        g = lambda w: 2 * cov @ w
    elif kind == "aggr":
        f = lambda w: -(w @ mu)
        g = lambda w: -mu
        cons.append({"type": "ineq", "fun": lambda w: vol_cap ** 2 - w @ cov @ w, "jac": lambda w: -2 * cov @ w})
    else:  # erc: ogni titolo contribuisce in modo uguale al rischio
        def f(w):
            rc = w * (cov @ w)
            return float(((rc - rc.mean()) ** 2).sum()) * 1e6
        g = None
    r = minimize(f, x0, jac=g, bounds=[(0, cap)] * n, constraints=cons, method="SLSQP", options={"maxiter": 400, "ftol": 1e-10})
    w = np.clip(r.x, 0, None)
    if w.sum() <= 0:
        return None
    w = w / w.sum()
    return w if _check(w, cap, cls_idx, cls_cap) else None


def capacity(idx, cls, caps, cap):
    """Quanto del portafoglio possono ospitare i titoli idx rispettando tetto per titolo e massimi per classe (>= 1: fattibile)."""
    by = {}
    for i in idx:
        by[cls[i]] = by.get(cls[i], 0) + cap
    return sum(min(v, caps.get(k, 1.0)) for k, v in by.items())


def prune(kind, ds, mu, kmin, kmax, cap, caps, rf, vol_cap=None, start=None):
    """Parte da tutti i titoli (o da `start`) e toglie via via quello di peso minore finché ce ne sono al massimo kmax e nessuno pesa meno di MINW."""
    idx = list(range(len(mu))) if start is None else list(start)
    best = None
    while True:
        w = solve(kind, mu[idx], ds.cov[np.ix_(idx, idx)], cap, [ds.cls[i] for i in idx], caps, rf, vol_cap)
        if w is None:
            return best
        best = (list(idx), w)
        if len(idx) > 2 * kmax:  # primo passo grossolano
            keep = np.argsort(-w)[: 2 * kmax]
        elif len(idx) > kmax or (w.min() < MINW and len(idx) > kmin):
            keep = np.delete(np.arange(len(idx)), int(np.argmin(w)))
        else:
            return best
        idx = [idx[k] for k in sorted(keep)]


def greedy_dr(ds, mu, kmin, kmax, cap, caps, rf):
    """Sceglie i titoli che aggiungono più diversificazione (rapporto di diversificazione, Choueifaty–Coignard 2008), partendo dal miglior rendimento/rischio."""
    n = len(mu)
    sd = ds.sd

    def dr(s):
        w = 1 / sd[s]
        w = w / w.sum()
        return (w @ sd[s]) / math.sqrt(w @ ds.cov[np.ix_(s, s)] @ w)

    sel = [int(np.argmax((mu - rf) / sd))]
    cur = 1.0
    while len(sel) < kmax:
        cand = [(dr(sel + [j]), j) for j in range(n) if j not in sel]
        if not cand:
            break
        if capacity(sel, ds.cls, caps, cap) < 1:  # servono altre classi: si sceglie solo tra quelle che aumentano la capacità
            cand = [c for c in cand if capacity(sel + [c[1]], ds.cls, caps, cap) > capacity(sel, ds.cls, caps, cap) + 1e-9] or cand
        d, j = max(cand)
        if len(sel) >= kmin and capacity(sel, ds.cls, caps, cap) >= 1 and d < cur * 1.02:
            break
        sel.append(j)
        cur = d
    return sel


def metrics(ds, idx, w, rf):
    mu, cov, sd = ds.mu[idx], ds.cov[np.ix_(idx, idx)], ds.sd[idx]
    vol = math.sqrt(w @ cov @ w)
    ret = float(w @ mu)
    cc = cov / np.outer(sd, sd)
    off = cc[~np.eye(len(idx), dtype=bool)]
    return {"ret": ret, "vol": vol, "sharpe": (ret - rf) / vol if vol else 0.0, "dr": float(w @ sd) / vol if vol else 1.0, "corr": float(off.mean()) if off.size else 1.0}


def build(ds, idx, w, amount, rf, name, desc, note=""):
    items, spent = [], 0.0
    order = np.argsort(-w)
    for k in order:
        r = ds.rows[idx[k]]
        price = r["price_eur"] or ds.P[-1, idx[k]]
        amt = w[k] * amount
        qty = int(amt // price) if amount and price else 0
        spent += qty * price
        items.append({"symbol": r["symbol"], "isin": r["isin"], "replication": r["replication"], "domicile": r["domicile"], "name": r["name"], "class": ds.cls[idx[k]], "exchange": r["exchange_name"], "weight": float(w[k]), "amount": amt, "qty": qty,
                      "price": price, "cost": qty * price, "ter": r["ter"], "assets": r["assets_eur_m"]})
    comp = {}
    for k in range(len(idx)):
        comp[ds.cls[idx[k]]] = comp.get(ds.cls[idx[k]], 0) + float(w[k])
    m = metrics(ds, idx, w, rf)
    ter = sum(i["weight"] * i["ter"] for i in items if i["ter"] is not None)
    known = sum(i["weight"] for i in items if i["ter"] is not None)
    return {"name": name, "desc": desc, "items": items, "classes": comp, "spent": spent, "cash": amount - spent if amount else 0.0, "note": note,
            "ter": ter / known if known > 0.5 else None, **m}


def propose(ds, amount=10000.0, cap=0.35, kmin=3, kmax=8, rf=0.02, vol_aggr=0.20, caps=None):
    """Tre proposte sugli stessi titoli e criteri: massimo Sharpe, bilanciato (parità di rischio) e aggressivo (massimo rendimento con volatilità limitata)."""
    caps = {k: v for k, v in (caps or {}).items() if v < 1.0}
    kmax = max(kmin, min(kmax, len(ds.rows)))
    kmin = min(kmin, kmax)
    mus = (1 - SHRINK) * ds.mu + SHRINK * ds.mu.mean()  # rendimenti prudenti, solo per scegliere i pesi
    out, fail = [], []

    r = prune("sharpe", ds, mus, kmin, kmax, cap, caps, rf)
    if r:
        out.append(build(ds, *r, amount, rf, "Sharpe", "Massimo rendimento per unità di rischio (rapporto di Sharpe)."))
    else:
        fail.append("Sharpe")

    sel = greedy_dr(ds, mus, kmin, kmax, cap, caps, rf)
    w = solve("erc", mus[sel], ds.cov[np.ix_(sel, sel)], cap, [ds.cls[i] for i in sel], caps, rf)
    if w is not None:
        out.append(build(ds, sel, w, amount, rf, "Bilanciato", "Ogni titolo contribuisce in modo uguale al rischio (parità di rischio), con i titoli più diversificanti."))
    else:
        fail.append("Bilanciato")

    allw = solve("minvar", ds.mu, ds.cov, cap, ds.cls, caps, rf)
    note = ""
    if allw is not None:
        vmin = math.sqrt(allw @ ds.cov @ allw)
        vc = max(vol_aggr, vmin * 1.05)
        if vc > vol_aggr:
            note = f"Volatilità richiesta {vol_aggr * 100:.0f}% non raggiungibile: portata a {vc * 100:.1f}%."
        r = prune("aggr", ds, mus, kmin, kmax, cap, caps, rf, vol_cap=vc)
        if r:
            out.append(build(ds, *r, amount, rf, "Aggressivo", f"Massimo rendimento atteso con volatilità fino al {vc * 100:.0f}%.", note))
        else:
            fail.append("Aggressivo")
    else:
        fail.append("Aggressivo")
    return out, fail
