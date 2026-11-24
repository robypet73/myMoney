"""Punto d'ingresso di myMoney.exe per l'installer di Windows: nessuna finestra nera.
Il programma lavora in secondo piano e sta nell'area di notifica (accanto all'orologio): clic destro sull'icona → «Apri myMoney» / «Esci».
Messaggi e errori vanno nel file myMoney.log nella cartella dei dati (%LOCALAPPDATA%\\myMoney)."""
import os
import sys
import threading
import urllib.request
import webbrowser

import build

PORTA = 8800


def _log():
    try:
        d = build.cartella_dati()
        return open(os.path.join(d, "myMoney.log"), "w", encoding="utf-8", buffering=1)
    except OSError:
        return open(os.devnull, "w")


def _gia_attivo():
    """Porta di un myMoney già aperto (un solo programma alla volta), oppure None."""
    for p in range(PORTA, PORTA + 20):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/cartella", timeout=1.5) as r:
                if b"predefinita" in r.read():
                    return p
        except Exception:
            continue
    return None


def main():
    # senza finestra stdout/stderr non esistono: si scrivono nel file di registro
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        log = _log()
        sys.stdout = sys.stderr = log
    p = _gia_attivo()
    if p:  # già in esecuzione: si riapre solo la pagina
        webbrowser.open(f"http://127.0.0.1:{p}/")
        return
    threading.Thread(target=build.avvia_app, daemon=True).start()
    try:
        import pystray
        from PIL import Image
        icona = Image.open(os.path.join(build.cartella_programma(), "icons", "myMoney-256.png"))

        def apri(*_):
            webbrowser.open(f"http://127.0.0.1:{build.PORTA_ATTIVA or PORTA}/")

        def esci(ic, *_):
            ic.stop()

        menu = pystray.Menu(pystray.MenuItem("Apri myMoney", apri, default=True), pystray.MenuItem("Esci", esci))
        pystray.Icon("myMoney", icona, "myMoney", menu).run()
    except Exception as e:  # senza icona non ci sarebbe modo di chiudere: meglio dirlo nel registro e restare attivi
        print("icona nell'area di notifica non disponibile:", e, flush=True)
        threading.Event().wait()
    os._exit(0)


if __name__ == "__main__":
    main()
