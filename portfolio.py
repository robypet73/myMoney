"""Selezione dei titoli con i criteri di ricerca e calcolo delle proposte di portafoglio (Sharpe, bilanciato, aggressivo)."""
import math
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize

import classify as C

AGG = 252 / 5          # rendimenti a 5 giorni sovrapposti, annualizzati
SHRINK = 0.5           # i rendimenti storici sono rumorosi: per scegliere i pesi si portano a metà strada verso la media dei titoli
MINW = 0.03            # peso minimo di un titolo scelto (sotto, si scarta)
DR_GAIN = 1.02         # nella scelta per diversificazione si smette di aggiungere titoli se il rapporto di diversificazione migliora meno del 2%
WINDOW_YEARS = 3.0     # finestra massima dei rendimenti: gli ultimi 3 anni (o meno, se i titoli hanno meno storia in comune)
MIN_WINDOW_YEARS = 2.0 # se alcuni fondi giovani accorciano la finestra comune sotto 2 anni, i più recenti si escludono (finché restano almeno 8 fondi e il 60%)


# ------------------------------------------------------------------ criteri di ricerca
# Tutti i criteri sono assenti (null) finché non li imposti. Gli intervalli hanno estremi facoltativi: [minimo o None, massimo o None].
RANGE_COLS = {"ter": "ter", "assets": "assets_eur_m", "adv": "adv_eur_m", "spread": "spread_pct", "ret_1y": "ret_1y", "ret_3y": "ret_3y", "ret_5y": "ret_5y",
              "vol_1y": "vol_1y", "vol_3y": "vol_3y", "max_dd": "max_dd"}
DEFAULT_FILTERS = {"exchanges": [], "types": [], "currencies": [], "distributions": [], "regions": [], "replications": [], "domiciles": [], "sustainable": False,
                   "class_caps": {}, "ranges": {}, "pool": 150, "unknown": False}


def _years(r, today):
    """Anni dalla data di lancio (o di primo scambio)."""
    if not r["inception"]:
        return None
    try:
        return (today - datetime.strptime(r["inception"], "%Y-%m-%d")).days / 365.25
    except ValueError:
        return None


def select(db, f, today=None, skip=()):
    """Titoli che rispettano i criteri (un solo titolo per fondo), ordinati per patrimonio e poi per liquidità, al massimo `pool`.
    Un criterio su un dato mancante esclude il titolo, salvo `unknown`. `skip` = chiavi di `ranges` da ignorare."""
    f = {**DEFAULT_FILTERS, **f}
    today = today or datetime.now()
    caps = f["class_caps"] or {}
    unk = f["unknown"]
    ranges = {k: v for k, v in (f["ranges"] or {}).items() if k not in skip and v and (v[0] is not None or v[1] is not None)}

    def ok(v, test):
        return (unk and v is None) or (v is not None and test(v))

    out = []
    for r in db.all("price_eur IS NOT NULL"):
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
        bad = False
        for k, (lo, hi) in ranges.items():
            v = _years(r, today) if k == "years" else r[RANGE_COLS[k]]
            if not ok(v, lambda x: (lo is None or x >= lo) and (hi is None or x <= hi)):
                bad = True
                break
        if bad:
            continue
        out.append(r)
    # un solo titolo per fondo: EUR, poi la borsa preferita (ordine scelto dall'utente), poi il volume
    order = {e: i for i, e in enumerate(f["exchanges"])}
    best = {}
    by_group = {}  # un gruppo di nomi con un solo ISIN verificato: le quotazioni senza ISIN dello stesso gruppo sono lo stesso fondo
    for r in db.all("isin IS NOT NULL"):
        by_group.setdefault(r["group_key"], set()).add(r["isin"])
    for r in out:
        g = by_group.get(r["group_key"])
        k = r["isin"] or (next(iter(g)) if g and len(g) == 1 else None) or r["group_key"] or r["symbol"]
        score = (r["currency"] == "EUR", -order.get(r["exchange"], 99), r["adv_eur_m"] or 0)
        if k not in best or score > best[k][0]:
            best[k] = (score, r)
    rows = [v[1] for v in best.values()]
    rows.sort(key=lambda r: (r["assets_eur_m"] or 0, r["adv_eur_m"] or 0), reverse=True)
    return pick_pool(rows, f) if f["pool"] else rows


MIN_PER_CLASS = 3  # se i massimi per classe limitano il portafoglio, ogni classe ammessa porta almeno questi fondi nel calcolo


def pick_pool(rows, f):
    """I fondi da analizzare: i `pool` più grandi. Se i massimi per classe sono limitati (< 100%), il numero di fondi per classe è proporzionale al massimo
    (almeno MIN_PER_CLASS): senza questo i fondi più grandi sarebbero tutti di una classe e il portafoglio non si potrebbe comporre."""
    n = int(f.get("pool") or DEFAULT_FILTERS["pool"])
    caps = {k: v / 100 for k, v in (f.get("class_caps") or {}).items() if v is not None}
    if len(rows) <= n or not any(0 < c < 1 for c in caps.values()):
        return rows[:n]
    by = {}
    for r in rows:
        by.setdefault(r["asset_class"] or "Altro", []).append(r)
    w = {k: min(caps.get(k, 1.0), 1.0) for k in by}
    tot = sum(w.values()) or 1.0
    keep = set()
    for k, lst in by.items():
        q = max(MIN_PER_CLASS, round(n * w[k] / tot)) if w[k] > 0 else 0
        keep.update(r["symbol"] for r in lst[:q])
    return [r for r in rows if r["symbol"] in keep]


def search_summary(db, f):
    """Per la schermata di creazione: tutti i fondi che passano i criteri (senza il limite `pool`), quelli analizzati (primi `pool`), il conteggio per classe e
    la disponibilità dei dati di rendimento tra i fondi che passano i criteri diversi dai rendimenti (per sapere quanti storici mancano)."""
    allr = select(db, {**f, "pool": 0})
    pool = pick_pool(allr, {**DEFAULT_FILTERS, **f})
    by = {}
    for r in allr:
        by[r["asset_class"] or "Altro"] = by.get(r["asset_class"] or "Altro", 0) + 1
    base = select(db, {**f, "pool": 0}, skip=tuple(RETURN_KEYS))
    cover = {k: sum(1 for r in base if r[RANGE_COLS[k]] is not None) for k in RETURN_KEYS}
    return allr, pool, by, {"base": len(base), "cover": cover, "missing_hist": sum(1 for r in base if not r["hist_n"] and r["ret_3y"] is None)}


RETURN_KEYS = ("ret_1y", "ret_3y", "ret_5y", "vol_1y", "vol_3y", "max_dd")


# ------------------------------------------------------------------ dati per il calcolo
class Dataset:
    def __init__(self, rows, dates, P, notes=()):
        self.rows, self.dates, self.P, self.notes = rows, dates, P, list(notes)
        self.sym = [r["symbol"] for r in rows]
        R = P[5:] / P[:-5] - 1
        self.mu = R.mean(axis=0) * AGG
        self.cov = np.cov(R, rowvar=False).reshape(len(rows), len(rows)) * AGG
        self.sd = np.sqrt(np.diag(self.cov))
        self.cls = [r["asset_class"] or "Altro" for r in rows]
        self.years = len(dates) / 252


def clean_series(v):
    """Corregge gli errori di dati di Yahoo: un punto isolato fuori scala (picco che torna normale) si sostituisce con il precedente; un salto permanente oltre
    2,5 volte (o sotto 0,4) è un frazionamento non corretto e si riporta sullo storico. Ritorna (serie, numero di correzioni)."""
    v = np.array(v, float)
    fixes = 0
    for t in range(1, len(v)):
        r = v[t] / v[t - 1]
        if r > 2.5 or r < 0.4:
            nxt = v[t + 1: t + 4]
            if len(nxt) and np.all(np.abs(nxt / v[t - 1] - 1) < 0.25):
                v[t] = v[t - 1]  # picco isolato
            elif len(nxt) and np.all(np.abs(nxt / v[t] - 1) < 0.25):
                v[:t] *= r  # salto permanente: frazionamento non corretto
            else:
                continue
            fixes += 1
    return v, fixes


MAX_MOVE = 0.5  # dopo la correzione, un movimento giornaliero oltre il 50% = dato inaffidabile: il fondo si esclude


def load_dataset(db, rows, years=WINDOW_YEARS, min_years=0.0, today=None):
    """Allinea gli storici in EUR (ultimi `years` anni, finestra in comune). Corregge gli errori di dati, scarta i fondi con troppa poca storia o con movimenti
    giornalieri anomali e riporta cosa ha fatto in `notes`."""
    today = today or datetime.now()
    cut = (today - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    need = (today - timedelta(days=365 * min_years)).strftime("%Y-%m-%d") if min_years else None
    ser, notes, fixed, dropped = {}, [], [], []
    for r in rows:
        s = db.prices(r["symbol"])
        if len(s) < 60 or (need and s[0][0] > need):
            continue
        days = [d for d, _ in s if d >= cut]
        vals, nfix = clean_series([p for d, p in s if d >= cut])
        if len(vals) < 60:
            continue
        if np.max(np.abs(vals[1:] / vals[:-1] - 1)) > MAX_MOVE:
            dropped.append(r["symbol"])
            continue
        if nfix:
            fixed.append(r["symbol"])
        ser[r["symbol"]] = dict(zip(days, vals.tolist()))
    # un fondo giovane accorcerebbe il periodo di tutti: si escludono i più recenti finché la finestra comune arriva ad almeno MIN_WINDOW_YEARS
    target = (today - timedelta(days=365 * MIN_WINDOW_YEARS)).strftime("%Y-%m-%d")
    firsts = sorted(((min(v), s) for s, v in ser.items()), reverse=True)
    n0, young = len(ser), []
    while firsts and firsts[0][0] > target and len(ser) - len(young) > max(8, int(0.6 * n0)):
        young.append(firsts.pop(0)[1])
    for s in young:
        del ser[s]
    keep = [r for r in rows if r["symbol"] in ser]
    fixed = [s for s in fixed if s in ser]
    if young:
        notes.append(f"{len(young)} fondi con meno di {MIN_WINDOW_YEARS:.0f} anni di storia esclusi per non accorciare il periodo di tutti gli altri: {', '.join(young[:8])}{'…' if len(young) > 8 else ''}")
    if fixed:
        notes.append(f"{len(fixed)} fondi con errori nei dati di Yahoo corretti (picchi isolati o frazionamenti): {', '.join(fixed[:8])}{'…' if len(fixed) > 8 else ''}")
    if dropped:
        notes.append(f"{len(dropped)} fondi esclusi per movimenti giornalieri oltre il {MAX_MOVE * 100:.0f}% (dati inaffidabili o prodotti estremi): {', '.join(dropped[:8])}{'…' if len(dropped) > 8 else ''}")
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
    return Dataset(keep, dates, P, notes)


# ------------------------------------------------------------------ ottimizzazione
def wcorr(w, cov, sd):
    """Correlazione media pesata sui pesi: media delle correlazioni tra coppie di titoli, ognuna pesata con w_i·w_j·σ_i·σ_j."""
    own = float((w * sd) @ (w * sd))
    den = float(w @ sd) ** 2 - own
    return 1.0 if den < 1e-12 else float((w @ cov @ w - own) / den)


def _cons(n, cls_idx, cls_cap):
    c = [{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(n)}]
    for idx, cap in zip(cls_idx, cls_cap):
        c.append({"type": "ineq", "fun": lambda w, i=idx, cap=cap: cap - w[i].sum(), "jac": lambda w, i=idx: -np.isin(np.arange(n), i).astype(float)})
    return c


def _check(w, cap, lb, cls_idx, cls_cap, cov, dr_min, corr_max):
    sd = np.sqrt(np.diag(cov))
    ok = abs(w.sum() - 1) < 1e-4 and (w > lb - 1e-4).all() and (w < cap + 1e-4).all() and all(w[i].sum() <= c + 1e-3 for i, c in zip(cls_idx, cls_cap))
    if ok and dr_min:
        ok = float(w @ sd) / math.sqrt(max(float(w @ cov @ w), 1e-18)) >= dr_min - 2e-3
    if ok and corr_max is not None:
        ok = wcorr(w, cov, sd) <= corr_max + 2e-3
    return ok


def solve(kind, mu, cov, cap, cls, class_caps, rf=0.02, vol_cap=None, w0=None, lb=0.0, dr_min=None, corr_max=None):
    """Pesi di un portafoglio solo lungo: kind = sharpe | minvar | aggr | erc | maxdr | mincorr. `lb` = peso minimo di ogni titolo scelto; `dr_min` e `corr_max` =
    diversificazione minima e correlazione media pesata massima. Ritorna None se i vincoli non sono rispettabili."""
    n = len(mu)
    cap = max(cap, 1.02 / n)
    lb = min(lb, 0.99 / n)
    sd = np.sqrt(np.diag(cov))
    cls_idx = [np.array([i for i, c in enumerate(cls) if c == k]) for k in class_caps if any(c == k for c in cls)]
    cls_cap = [class_caps[k] for k in class_caps if any(c == k for c in cls)]
    cons = _cons(n, cls_idx, cls_cap)
    if dr_min:
        cons.append({"type": "ineq", "fun": lambda w: float(w @ sd) - dr_min * math.sqrt(max(float(w @ cov @ w), 1e-18))})
    if corr_max is not None:
        cons.append({"type": "ineq", "fun": lambda w: corr_max - wcorr(w, cov, sd)})
    x0 = np.full(n, 1 / n) if w0 is None else np.clip(w0, lb, cap)
    x0 = x0 / x0.sum()
    g = None
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
    elif kind == "maxdr":
        f = lambda w: -float(w @ sd) / math.sqrt(max(float(w @ cov @ w), 1e-18))
    elif kind == "mincorr":
        f = lambda w: wcorr(w, cov, sd)
    else:  # erc: ogni titolo contribuisce in modo uguale al rischio
        def f(w):
            rc = w * (cov @ w)
            return float(((rc - rc.mean()) ** 2).sum()) * 1e6
    r = minimize(f, x0, jac=g, bounds=[(lb, cap)] * n, constraints=cons, method="SLSQP", options={"maxiter": 400, "ftol": 1e-10})
    w = np.clip(r.x, lb, None)
    if w.sum() <= 0:
        return None
    w = w / w.sum()
    return w if _check(w, cap, lb, cls_idx, cls_cap, cov, dr_min, corr_max) else None


def capacity(idx, cls, caps, cap):
    """Quanto del portafoglio possono ospitare i titoli idx rispettando tetto per titolo e massimi per classe (>= 1: fattibile)."""
    by = {}
    for i in idx:
        by[cls[i]] = by.get(cls[i], 0) + cap
    return sum(min(v, caps.get(k, 1.0)) for k, v in by.items())


def _solve_idx(kind, ds, mu, idx, cap, caps, rf, vol_cap=None, lb=0.0, ck=None):
    return solve(kind, mu[idx], ds.cov[np.ix_(idx, idx)], cap, [ds.cls[i] for i in idx], caps, rf, vol_cap, lb=lb, **(ck or {}))


def prune(kind, ds, mu, kmin, kmax, cap, caps, rf, vol_cap=None, start=None, ck=None):
    """Parte da tutti i titoli (o da `start`) e toglie via via quello di peso minore finché ce ne sono al massimo kmax e nessuno pesa meno di MINW (mai sotto kmin).
    Alla fine ogni titolo scelto riceve almeno MINW: il numero di ETF del portafoglio è quello dichiarato, senza titoli a peso zero. Ritorna (indici, pesi) o None."""
    idx = list(range(len(mu))) if start is None else list(start)
    w = _solve_idx(kind, ds, mu, idx, cap, caps, rf, vol_cap, 0.0, ck)
    if w is None:
        return None
    while True:
        k = len(idx)
        nxt = None
        if k > 2 * kmax:  # primo passo grossolano
            c = [idx[j] for j in sorted(np.argsort(-w)[: 2 * kmax])]
            w2 = _solve_idx(kind, ds, mu, c, cap, caps, rf, vol_cap, 0.0, ck)
            if w2 is not None:
                nxt = (c, w2)
        if nxt is None and (k > kmax or (w.min() < MINW and k > kmin)):
            for d in np.argsort(w)[:4]:  # toglie il titolo più piccolo; se i vincoli non lo permettono, prova il successivo
                c = [i for j, i in enumerate(idx) if j != d]
                w2 = _solve_idx(kind, ds, mu, c, cap, caps, rf, vol_cap, 0.0, ck)
                if w2 is not None:
                    nxt = (c, w2)
                    break
        if nxt is None:
            break
        idx, w = nxt
    if len(idx) > kmax or len(idx) < min(kmin, len(mu)):
        return None
    for lb in (MINW, MINW / 2, 0.005):
        w3 = _solve_idx(kind, ds, mu, idx, cap, caps, rf, vol_cap, lb, ck)
        if w3 is not None:
            return idx, w3
    return None


def greedy_dr(ds, mu, kmin, kmax, cap, caps, rf, ck=None):
    """Sceglie i titoli che aggiungono più diversificazione (rapporto di diversificazione, Choueifaty–Coignard 2008), partendo dal miglior rendimento/rischio.
    Con diversificazione minima o correlazione massima impostate continua finché non sono raggiunte (entro kmax)."""
    ck = ck or {}
    n = len(mu)
    sd = ds.sd

    def inv(s):
        w = 1 / sd[s]
        return w / w.sum()

    def dr(s):
        w = inv(s)
        return (w @ sd[s]) / math.sqrt(w @ ds.cov[np.ix_(s, s)] @ w)

    def goal(s):
        w = inv(s)
        return (not ck.get("dr_min") or dr(s) >= ck["dr_min"]) and (ck.get("corr_max") is None or wcorr(w, ds.cov[np.ix_(s, s)], sd[s]) <= ck["corr_max"])

    sel = [int(np.argmax((mu - rf) / sd))]
    cur = 1.0
    while len(sel) < kmax:
        cand = [(dr(sel + [j]), j) for j in range(n) if j not in sel]
        if not cand:
            break
        if capacity(sel, ds.cls, caps, cap) < 1:  # servono altre classi: si sceglie solo tra quelle che aumentano la capacità
            cand = [c for c in cand if capacity(sel + [c[1]], ds.cls, caps, cap) > capacity(sel, ds.cls, caps, cap) + 1e-9] or cand
        d, j = max(cand)
        if len(sel) >= kmin and capacity(sel, ds.cls, caps, cap) >= 1 and d < cur * DR_GAIN and goal(sel):
            break
        sel.append(j)
        cur = d
    return sel


def metrics(ds, idx, w, rf):
    mu, cov, sd = ds.mu[idx], ds.cov[np.ix_(idx, idx)], ds.sd[idx]
    vol = math.sqrt(w @ cov @ w)
    ret = float(w @ mu)
    return {"ret": ret, "vol": vol, "sharpe": (ret - rf) / vol if vol else 0.0, "dr": float(w @ sd) / vol if vol else 1.0, "corr": wcorr(w, cov, sd)}


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


def limits(ds, cap, caps):
    """Il massimo di diversificazione e il minimo di correlazione media pesata raggiungibili con i fondi analizzati (per spiegare un vincolo irraggiungibile)."""
    caps = {k: v for k, v in (caps or {}).items() if v < 1.0}
    out = {}
    w = solve("maxdr", ds.mu, ds.cov, cap, ds.cls, caps)
    if w is not None:
        out["dr_max"] = float(w @ ds.sd) / math.sqrt(float(w @ ds.cov @ w))
    w = solve("mincorr", ds.mu, ds.cov, cap, ds.cls, caps)
    if w is not None:
        out["corr_min"] = wcorr(w, ds.cov, ds.sd)
    return out


def propose(ds, amount=10000.0, cap=0.35, kmin=3, kmax=8, rf=0.02, vol_aggr=0.20, caps=None, dr_min=None, corr_max=None):
    """Tre proposte sugli stessi titoli e criteri: massimo Sharpe, bilanciato (parità di rischio) e aggressivo (massimo rendimento con volatilità limitata).
    Ognuna ha tra kmin e kmax ETF, tutti con almeno MINW di peso; rispetta diversificazione minima e correlazione massima se impostate."""
    caps = {k: v for k, v in (caps or {}).items() if v < 1.0}
    ck = {k: v for k, v in (("dr_min", dr_min), ("corr_max", corr_max)) if v is not None}
    out, fail = [], []
    if len(ds.rows) < kmin:
        return out, ["Sharpe", "Bilanciato", "Aggressivo"]
    kmax = max(kmin, min(kmax, len(ds.rows)))
    mus = (1 - SHRINK) * ds.mu + SHRINK * ds.mu.mean()  # rendimenti prudenti, solo per scegliere i pesi

    r = prune("sharpe", ds, mus, kmin, kmax, cap, caps, rf, ck=ck)
    if r:
        out.append(build(ds, *r, amount, rf, "Sharpe", "Massimo rendimento per unità di rischio (rapporto di Sharpe)."))
    else:
        fail.append("Sharpe")

    sel = greedy_dr(ds, mus, kmin, kmax, cap, caps, rf, ck)
    w = None
    for lb in (MINW, MINW / 2, 0.005):
        w = solve("erc", mus[sel], ds.cov[np.ix_(sel, sel)], cap, [ds.cls[i] for i in sel], caps, rf, lb=min(lb, 0.5 / len(sel)), **ck)
        if w is not None:
            break
    if w is not None and kmin <= len(sel) <= kmax:
        out.append(build(ds, sel, w, amount, rf, "Bilanciato", "Ogni titolo contribuisce in modo uguale al rischio (parità di rischio), con i titoli più diversificanti."))
    else:
        fail.append("Bilanciato")

    allw = solve("minvar", ds.mu, ds.cov, cap, ds.cls, caps, rf, **ck)
    note = ""
    if allw is not None:
        vmin = math.sqrt(allw @ ds.cov @ allw)
        vc = max(vol_aggr, vmin * 1.05)
        if vc > vol_aggr:
            note = f"Volatilità richiesta {vol_aggr * 100:.0f}% non raggiungibile: portata a {vc * 100:.1f}%."
        r = prune("aggr", ds, mus, kmin, kmax, cap, caps, rf, vol_cap=vc, ck=ck)
        if r:
            out.append(build(ds, *r, amount, rf, "Aggressivo", f"Massimo rendimento atteso con volatilità fino al {vc * 100:.0f}%.", note))
        else:
            fail.append("Aggressivo")
    else:
        fail.append("Aggressivo")
    return out, fail


# ------------------------------------------------------------------ frontiera efficiente
def frontier(ds, idx, cap, caps, rf, kmin=3, kmax=8, dr_min=None, corr_max=None, n=28):
    """Frontiera efficiente (solo posizioni lunghe, tetto per ETF, massimi per classe, tra kmin e kmax ETF per punto) sui titoli `idx` del dataset, con
    rendimenti e rischio storici reali. Ritorna {"idx": [...], "points": [{vol, ret, sharpe, dr, corr, w, n}, ...]} dal punto di minima volatilità a quello di
    massimo rendimento; `w` è allineato a `idx`. Ogni punto può usare fondi diversi (peso zero per gli altri)."""
    caps = {k: v for k, v in (caps or {}).items() if v < 1.0}
    ck = {k: v for k, v in (("dr_min", dr_min), ("corr_max", corr_max)) if v is not None}
    idx = list(idx)
    kmax = max(kmin, min(kmax, len(idx)))
    pos = {i: k for k, i in enumerate(idx)}

    def run(kind, vc=None):
        r = prune(kind, ds, ds.mu, kmin, kmax, cap, caps, rf, vol_cap=vc, start=idx, ck=ck)
        if r is None:
            return None
        sub, w = r
        full = np.zeros(len(idx))
        for i, x in zip(sub, w):
            full[pos[i]] = x
        m = metrics(ds, sub, w, rf)
        return {"vol": m["vol"], "ret": m["ret"], "sharpe": m["sharpe"], "dr": m["dr"], "corr": m["corr"], "w": [float(x) for x in full], "n": len(sub)}

    lo, hi = run("minvar"), run("aggr", 10.0)
    if lo is None or hi is None:
        return None
    cand = [lo, hi]
    for v in np.linspace(lo["vol"], hi["vol"], n)[1:-1]:
        p = run("aggr", v * 1.0005)
        if p is not None:
            cand.append(p)
    cand.sort(key=lambda p: p["vol"])
    pts = []
    for p in cand:  # parte efficiente: il rendimento deve crescere con il rischio
        if not pts or p["ret"] > pts[-1]["ret"] + 1e-6:
            pts.append(p)
    return {"idx": idx, "points": pts}
