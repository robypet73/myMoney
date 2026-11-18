"""Classificazione dei titoli dal nome (Yahoo non fornisce categoria, area e distribuzione in modo affidabile)."""
import re

STOP = {"ucits", "ucit", "etf", "etc", "etn", "etp", "fund", "the", "of", "and", "plc", "ex", "ie", "lu", "de", "fr"}


def norm(s):
    s = (s or "").lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def group_key(name):
    """Chiave del fondo: lo stesso fondo quotato su più borse ha lo stesso nome lungo."""
    return " ".join(w for w in norm(name).split() if w not in STOP)


_R = lambda p: re.compile(p, re.I)
RX_CRYPTO = _R(r"bitcoin|ethereum|\bether\b|crypto|\bsolana\b|\bxrp\b|\bcardano\b")
RX_COMM = _R(r"\bgold\b|\bsilver\b|platinum|palladium|\boro\b|commodit|\boil\b|crude|brent|natural gas|copper|\bmetals?\b|agricultur|wheat|\bcorn\b|\bcoffee\b|\bsugar\b|physical")
RX_REIT = _R(r"real estate|\breits?\b|property|immobil")
RX_MONEY = _R(r"money market|overnight|\bestr\b|\bsonia\b|\bsofr\b|ultra.?short|cash\b|t-?bills?|1-3m|0-3m")
RX_BOND = _R(r"\bbonds?\b|treasur|govern|govt|aggregate|corporate|\bgilts?\b|obblig|high yield|\bhy\b|investment grade|inflation|\btips\b|\bbtp\b|credit|duration|\bbund|sovereign|covered|\bfrn\b|floating")
RX_EQUITY = _R(r"msci|ftse|s&p|nasdaq|stoxx|russell|\bdax\b|nikkei|topix|equity|equities|stock|dividend|small cap|mid cap|large cap|world|global|europe|emerging|usa|\bus\b|japan|china|india|asia|technology|healthcare|semiconductor|momentum|quality|value|low vol")
RX_ETC = _R(r"\betc\b|physical|\bgold\b.*\betc\b|commodity")
RX_ETN = _R(r"\betn\b|\betp\b|certificate|leverage|\b[23]x\b|short\b")

CLASSES = ["Azionario", "Obbligazionario", "Monetario", "Materie prime", "Immobiliare", "Criptovalute", "Altro"]


def type_of(name):
    n = name or ""
    if RX_ETN.search(n):
        return "ETN/ETP"
    if RX_ETC.search(n) and not re.search(r"\bucits etf\b", n, re.I):
        return "ETC"
    return "ETF"


def asset_class(name, stock=None, bond=None, cash=None, other=None):
    n = name or ""
    if RX_CRYPTO.search(n):
        return "Criptovalute"
    if RX_COMM.search(n) and not RX_EQUITY.search(re.sub(r"gold|silver|metal|mining", "", n, flags=re.I)):
        return "Materie prime"
    if RX_REIT.search(n):
        return "Immobiliare"
    if RX_MONEY.search(n):
        return "Monetario"
    if RX_BOND.search(n) and not (stock or 0) >= 0.5:
        return "Obbligazionario"
    for v, c in ((stock, "Azionario"), (bond, "Obbligazionario"), (cash, "Monetario")):
        if v is not None and v >= 0.5:
            return c
    if other is not None and other >= 0.5:
        return "Materie prime" if RX_COMM.search(n) else "Altro"
    return "Azionario" if RX_EQUITY.search(n) else "Altro"


REGIONS = [("Mercati emergenti", _R(r"emerging|\bem\b|\bbrics?\b")),
           ("Mondo", _R(r"world|global|\bacwi\b|all.?country")),
           ("USA", _R(r"\busa?\b|s&p ?500|s&p|nasdaq|russell|america|united states|dow jones")),
           ("Europa", _R(r"europe|\beuro\b|stoxx|\bdax\b|\bmib\b|\bcac\b|eurozone|\bemu\b|\buk\b|ftse 100")),
           ("Giappone", _R(r"japan|nikkei|topix")),
           ("Asia-Pacifico", _R(r"asia|pacific|china|india|korea|taiwan|hong kong|australia|vietnam")),
           ("America Latina", _R(r"latin america|brazil|mexico|latam")), ("Africa", _R(r"africa"))]


def region_of(name):
    for r, rx in REGIONS:
        if rx.search(name or ""):
            return r
    return ""


def distribution_of(name):
    n = name or ""
    if re.search(r"\bacc\b|accumulat|capitali[sz]|\(acc\)", n, re.I):
        return "Accumulazione"
    if re.search(r"\bdist\b|distribut|\binc\b|income|\(dist\)", n, re.I):
        return "Distribuzione"
    return ""


def hedged_of(name):
    return int(bool(re.search(r"hedged|\bhdg\b|\bhedge\b", name or "", re.I)))
