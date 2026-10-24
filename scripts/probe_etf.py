#!/usr/bin/env python3
"""Sonda temporanea: mostra se le pagine justETF sono raggiungibili e come sono fatte."""
import re
import sys
import urllib.request

ISIN = sys.argv[1] if len(sys.argv) > 1 else "IE00B4L5Y983"
for url in [f"https://www.justetf.com/en/etf-profile.html?isin={ISIN}", f"https://www.justetf.com/it/etf-profile.html?isin={ISIN}"]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
            print(url, r.status, len(html))
    except Exception as e:
        print(url, "ERRORE", e); continue
    for key in ["Total expense ratio", "Fund size", "Replication", "Inception", "domicile", "Distribution policy", "Investment focus", "Fund currency", "ld+json"]:
        for m in list(re.finditer(re.escape(key), html))[:2]:
            s = html[max(0, m.start() - 80): m.end() + 260].replace("\n", " ")
            print(f"[{key}] {re.sub(r'\\s+', ' ', s)}")
    break
