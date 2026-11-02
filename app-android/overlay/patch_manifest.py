"""Aggiunge widget, ricevitore di avvio e permessi all'AndroidManifest.xml generato da Capacitor.
Uso: patch_manifest.py AndroidManifest.xml receiver.xml permissions.xml"""
import sys
p = sys.argv[1]
rc, perms = open(sys.argv[2], encoding="utf-8").read(), open(sys.argv[3], encoding="utf-8").read()
s = open(p, encoding="utf-8").read()
assert "</application>" in s and "<application" in s and "MyMoneyWidget" not in s
s = s.replace("</application>", rc + "    </application>", 1)
i = s.index("<application")
s = s[:i] + perms.lstrip() + "\n    " + s[i:]
open(p, "w", encoding="utf-8").write(s)
