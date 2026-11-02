"""Aggiunge il widget (receiver) all'AndroidManifest.xml generato da Capacitor."""
import sys
p, rc = sys.argv[1], open(sys.argv[2], encoding="utf-8").read()
s = open(p, encoding="utf-8").read()
assert "</application>" in s and "MyMoneyWidget" not in s
open(p, "w", encoding="utf-8").write(s.replace("</application>", rc + "    </application>", 1))
