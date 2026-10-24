#!/usr/bin/env python3
"""Sonda temporanea."""
import re
import sys
import urllib.request

ISIN = sys.argv[1] if len(sys.argv) > 1 else "IE00B4L5Y983"
req = urllib.request.Request(f"https://www.justetf.com/en/etf-profile.html?isin={ISIN}", headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
ids = sorted(set(re.findall(r'data-testid="([^"]+)"', html)))
print("TESTIDS", len(ids))
print(" ".join(i for i in ids if re.search(r"holding|countr|sector|index|number|region|top|currenc|benchmark|tracking|dividend|swap|sfdr|strategy|legal", i)))
for key in ["etf-holdings_table", "etf-holdings_top", "etf-holdings_countries", "etf-holdings_sectors", "etf-basics_value_index", "tl_etf-basics_value_index", "holdings_number", "number-of-holdings", "etf-profile-header_index"]:
    for m in list(re.finditer(re.escape(key), html))[:1]:
        s = html[max(0, m.start() - 60): m.end() + 700]
        print(f"[{key}] {re.sub(r'\\s+', ' ', s)}")
