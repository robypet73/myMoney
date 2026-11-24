"""Punto d'ingresso di myMoney-widget.exe (widget sempre in primo piano) per l'installer di Windows.
Senza finestra nera: l'eseguibile è «windowed», quindi stdout/stderr non esistono e si mandano nel vuoto."""
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import widget

if __name__ == "__main__":
    widget.avvia()
