"""Save an Amazon product page as a gzipped test fixture: python scripts/fetch_fixture.py ASIN [ASIN...]"""
import gzip
import pathlib
import sys

from curl_cffi import requests

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"

s = requests.Session(impersonate="chrome", headers={"Accept-Language": "en-IN,en;q=0.9"})
for asin in sys.argv[1:]:
    r = s.get(f"https://www.amazon.in/dp/{asin}", timeout=30)
    ok = r.status_code == 200 and "productTitle" in r.text
    if ok:
        (OUT / f"amazon_{asin}.html.gz").write_bytes(gzip.compress(r.text.encode()))
    print(asin, r.status_code, len(r.text), "saved" if ok else "SKIPPED")
