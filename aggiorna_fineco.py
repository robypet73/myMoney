#!/usr/bin/env python3
"""Aggiorna fineco_gratis.json: la lista degli ETF con commissioni di acquisto nulle su Fineco (Fineco AM, Franklin Templeton, Xtrackers, iShares, Amundi/Lyxor).

Fineco pubblica la lista come PDF e la cambia ogni mese:
    https://images.fineco.it/cms/mail/immagini/docs/2022_Promo_ETF/PromoETFZeroCommissioni_Lista.pdf
Il PDF si legge con `pdftotext` (pacchetto poppler-utils: sudo apt install poppler-utils, brew install poppler).

Uso:
    python aggiorna_fineco.py                 scarica il PDF e riscrive fineco_gratis.json
    python aggiorna_fineco.py lista.pdf       parte da un PDF già scaricato
    python aggiorna_fineco.py lista.txt       parte dal testo di `pdftotext -raw`
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request

URL = "https://images.fineco.it/cms/mail/immagini/docs/2022_Promo_ETF/PromoETFZeroCommissioni_Lista.pdf"
USCITA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fineco_gratis.json")
ISIN = re.compile(r"^([A-Z]{2}[A-Z0-9]{9}[0-9])\b\s*(.*)$")
SEZIONE = re.compile(r"Strumenti (.+?) in promozione dal (\d\d\.\d\d\.\d{4}) al (\d\d\.\d\d\.\d{4})")
CLASSI_PDF = ("Securities Lending Transactions", "ETF Active Collection", "ETF Active Portfolio", "Sector Equity Alternative Energy", "Sector Equity Healthcare",
              "Sector Equity Technology", "Japan Large-Cap Equity", "EUR Corporate Bond - Short Term", "EUR High Yield Bond", "USD High Yield Bond", "USD Corporate Bond",
              "Broad Commodities", "Fixed Income", "Other Equity", "Multi Asset", "Alternatives", "Commodities", "Equity", "Monetario", "Indici di mercato", "Economia Digitale",
              "Geopolitica", "Sicurezza e difesa", "Tecnologie del Futuro", "AI e Cybersecurity", "Salute del Futuro", "Demografia", "Benessere", "#N/A")


def tipo_di(nome, classe):
    """Azioni, Obbligazioni, Materie prime, Monetario o Altro: dal nome (la classe del PDF a volte è sbagliata, per esempio l'oro è «Fixed Income»)."""
    n = nome.lower()
    if re.search(r"\bgold\b|commodit|\boro\b|physical (silver|platinum|palladium)", n):
        return "Materie prime"
    if re.search(r"bond|govt|gov bd|government|treasur|gilt|\bbtp\b|aggregate|obbligaz|inflation|corporate|\bhy\b|credit|floating|money market|monetario|overnight|€str|ester|sonia|sofr|€ cash", n):
        return "Monetario" if re.search(r"money market|monetario|overnight|€str|ester|sonia|sofr|€ cash|cash ucits", n) else "Obbligazioni"
    if classe.startswith(("Equity", "Other Equity", "Sector Equity", "Japan", "Economia", "Geopolitica", "Sicurezza", "Tecnologie", "AI ", "Salute", "Demografia", "Benessere")) or re.search(r"msci|stoxx|s&p|nasdaq|ftse|dax|nikkei|topix|russell|equity|world|europe|cac 40|ibex|dow jones|hydrogen|energy|agribusiness|metals|entertainment|africa", n):
        return "Azioni"
    return "Altro"


def emittente_di(sezione):
    s = sezione.lower()
    return "Fineco AM" if "fineco" in s else "Franklin Templeton" if "franklin" in s else "Xtrackers" if "xtrackers" in s else "iShares" if "ishares" in s else "Amundi" if "amundi" in s else sezione


def analizza(testo):
    """Righe di `pdftotext -raw` -> (elenco ETF, validità). Un ETF comincia con l'ISIN; il nome può continuare sulle righe dopo; la classe è in fondo."""
    etf, cur, sez, val = [], None, "", ""

    def chiudi():
        nonlocal cur
        if not cur:
            return
        t = re.sub(r"\s+", " ", cur["raw"]).strip()
        classe = ""
        for c in CLASSI_PDF:
            if t.endswith(" " + c) or t == c:
                classe, t = c, t[: len(t) - len(c)].strip()
                break
        nome = t.strip(" -")
        if nome:
            etf.append({"isin": cur["isin"], "nome": nome, "emittente": cur["emit"], "tipo": tipo_di(nome, classe)})
        cur = None

    for riga in testo.splitlines():
        riga = riga.strip()
        if not riga:
            continue
        m = SEZIONE.search(riga)
        if m:
            chiudi(); sez = emittente_di(m.group(1)); val = f"{m.group(2)} – {m.group(3)}"; continue
        if re.match(r"^(ISIN\b|Pagina\b|\d+\s*/\s*\d+$)", riga):
            continue
        m = ISIN.match(riga)
        if m and sez:
            chiudi(); cur = {"isin": m.group(1), "raw": m.group(2), "emit": sez}; continue
        if cur and sez:
            cur["raw"] += " " + riga
    chiudi()
    visti, out = set(), []
    for e in etf:
        if e["isin"] not in visti:
            visti.add(e["isin"]); out.append(e)
    return out, val


def testo_da(sorgente):
    if sorgente.lower().endswith(".txt"):
        with open(sorgente, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    if not sorgente.lower().endswith(".pdf"):
        raise SystemExit("Indica un file .pdf o .txt (oppure niente, per scaricare la lista da Fineco).")
    try:
        return subprocess.run(["pdftotext", "-raw", sorgente, "-"], check=True, capture_output=True, text=True).stdout
    except FileNotFoundError:
        raise SystemExit("Serve `pdftotext` (poppler-utils): sudo apt install poppler-utils (Linux), brew install poppler (Mac), oppure su Windows 'choco install poppler'.")


def main():
    if len(sys.argv) > 1:
        sorgente = sys.argv[1]
    else:
        sorgente = os.path.join(os.path.dirname(USCITA), "lista-fineco.pdf")
        rq = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(rq, timeout=60) as r, open(sorgente, "wb") as fh:
            fh.write(r.read())
    etf, val = analizza(testo_da(sorgente))
    if len(etf) < 50:
        raise SystemExit(f"Ho letto solo {len(etf)} ETF: il formato del PDF è cambiato? Non riscrivo il file.")
    doc = {"aggiornato": datetime.date.today().isoformat(), "validita": val, "fonte": URL, "etf": etf}
    with open(USCITA, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=0, separators=(",", ":"))
        fh.write("\n")
    if len(sys.argv) == 1 and os.path.exists(sorgente):
        os.remove(sorgente)
    print(f"{len(etf)} ETF, validità {val} -> {USCITA}")


if __name__ == "__main__":
    main()
