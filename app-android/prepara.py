#!/usr/bin/env python3
"""Prepara la cartella www dell'app Android (senza toccare i file del programma per PC):
- copia portafoglio.html applicando tre modifiche in memoria (dati dal motore JavaScript, niente stampa/scarico file, motore caricato prima del codice);
- copia motore.js e scrive seed.js con i portafogli, le schede note dei titoli e le tabelle di fonti.py;
- aggiunge index.html e l'icona.
Uso: python app-android/prepara.py"""
import json
import os
import shutil
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
WWW = os.path.join(QUI, "www")
sys.path.insert(0, RADICE)
sys.dont_write_bytecode = True
import fonti  # noqa: E402


def cambia(t, vecchio, nuovo):
    if t.count(vecchio) != 1:
        sys.exit(f"portafoglio.html è cambiato: non trovo una sola volta «{vecchio[:60]}…»")
    return t.replace(vecchio, nuovo)


def main():
    shutil.rmtree(WWW, ignore_errors=True)
    os.makedirs(WWW)
    t = open(os.path.join(RADICE, "portafoglio.html"), encoding="utf-8").read()
    t = cambia(t, 'const D = JSON.parse(document.getElementById("dati").textContent);', "const D = window.MOTORE.doc();")
    t = cambia(t, "<script>\nconst D = ", '<script src="seed.js"></script>\n<script src="motore.js"></script>\n<script>\nconst D = ')
    t = cambia(t, "</style>", "#report-pdf, #scarica-json { display: none !important; }  /* nell'app non ci sono stampa né scarico di file */\n.pfsel { display: flex; flex-wrap: wrap; max-width: 100%; } .pfsel select { flex: 1 1 180px; min-width: 0; max-width: 100%; text-overflow: ellipsis; }  /* il menu non allarga la pagina */\n</style>")
    t = '<!doctype html>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + t  # nell'app la pagina è sola: serve il tipo di documento, la codifica e la vista per il telefono
    open(os.path.join(WWW, "portafoglio.html"), "w", encoding="utf-8").write(t)
    shutil.copy(os.path.join(QUI, "motore.js"), os.path.join(WWW, "motore.js"))
    if os.path.exists(os.path.join(RADICE, "fineco_gratis.json")):
        shutil.copy(os.path.join(RADICE, "fineco_gratis.json"), os.path.join(WWW, "fineco_gratis.json"))  # lista Fineco per «Modifica portafoglio»
    # prima di aprire la pagina si allineano i portafogli con la cartella scelta (telefono o Google Drive), se c'è
    open(os.path.join(WWW, "index.html"), "w", encoding="utf-8").write(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>myMoney</title>'
        '<body style="background:#0d1219;color:#8e9bb0;font:15px system-ui;padding:24px">Apro i portafogli…'
        '<script src="seed.js"></script><script src="motore.js"></script>'
        '<script>const va = () => location.replace("portafoglio.html"); setTimeout(va, 8000); window.MOTORE.sincronizza().then(va, va);</script>\n')
    pf, titoli = {}, {}
    cart = os.path.join(RADICE, "portafogli")
    for n in sorted(os.listdir(cart)):
        if n.endswith(".json") and n != "schema.json":
            d = json.load(open(os.path.join(cart, n), encoding="utf-8"))
            d.pop("$schema", None)
            pf[n] = d
    sd = os.path.join(cart, "titoli")
    for n in sorted(os.listdir(sd)):
        if n.endswith(".json"):
            titoli[n[:-5]] = json.load(open(os.path.join(sd, n), encoding="utf-8"))
    tab = {"PAESI": fonti.PAESI, "EURO": sorted(fonti.EURO), "EUROPA_NO_EURO": sorted(fonti.EUROPA_NO_EURO), "EMERGENTI": sorted(fonti.EMERGENTI), "ALTRI_SVILUPPATI": sorted(fonti.ALTRI_SVILUPPATI),
           "VALUTE": fonti.VALUTE, "SETTORI": fonti.SETTORI, "ISO2": fonti.ISO2, "MESI": fonti.MESI}
    open(os.path.join(WWW, "seed.js"), "w", encoding="utf-8").write("window.SEED_APP = " + json.dumps({"portafogli": pf, "titoli": titoli, "tab": tab, "schema": open(os.path.join(cart, "schema.json"), encoding="utf-8").read()}, ensure_ascii=False, separators=(",", ":")) + ";\n")
    shutil.copy(os.path.join(RADICE, "icons", "icon-192.png"), os.path.join(WWW, "icon.png"))
    print("www pronta:", WWW, "-", len(pf), "portafogli,", len(titoli), "schede note")


if __name__ == "__main__":
    main()
