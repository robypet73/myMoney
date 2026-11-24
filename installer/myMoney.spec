# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: due programmi senza finestra nera (myMoney.exe con pagina nel browser e icona nell'area di notifica, myMoney-widget.exe) in una sola cartella.
# Si lancia dalla cartella principale del progetto:  pyinstaller installer/myMoney.spec
import os

radice = os.path.abspath(os.getcwd())
dati = [
    (os.path.join(radice, "portafoglio.html"), "."),
    (os.path.join(radice, "fineco_gratis.json"), "."),
    (os.path.join(radice, "portafogli", "schema.json"), "portafogli"),
    (os.path.join(radice, "drive", "mymoney_drive.gs"), "drive"),
    (os.path.join(radice, "icons", "myMoney.ico"), "icons"),
    (os.path.join(radice, "icons", "myMoney-256.png"), "icons"),
]
nascosti = ["tkinter", "tkinter.filedialog", "zoneinfo", "tzdata", "pystray", "pystray._win32", "PIL.Image"]
icona = os.path.join(radice, "icons", "myMoney.ico")

a = Analysis(
    [os.path.join(radice, "installer", "app_server.py"), os.path.join(radice, "installer", "app_widget.py")],
    pathex=[radice],
    datas=dati,
    hiddenimports=nascosti,
    excludes=["unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)

exe_app = EXE(
    pyz, [s for s in a.scripts if s[0] == "app_server"], [],
    exclude_binaries=True, name="myMoney", console=False, icon=icona,
)
exe_widget = EXE(
    pyz, [s for s in a.scripts if s[0] == "app_widget"], [],
    exclude_binaries=True, name="myMoney-widget", console=False, icon=icona,
)
coll = COLLECT(exe_app, exe_widget, a.binaries, a.datas, name="myMoney")
