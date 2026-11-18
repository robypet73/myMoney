#!/usr/bin/env python3
"""Crea un programma unico (myMoney.exe su Windows, myMoney su Mac e Linux) con PyInstaller: dist/myMoney[.exe]. Il database etf.db viene creato accanto al programma.

    pip install -r requirements.txt pyinstaller
    python build.py
"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", "myMoney", "--add-data", f"{os.path.join(here, 'web')}{os.pathsep}web",
       "--distpath", os.path.join(here, "dist"), "--workpath", os.path.join(here, "build"), "--specpath", os.path.join(here, "build"), os.path.join(here, "mymoney.py")]
sys.exit(subprocess.call(cmd, cwd=here))
