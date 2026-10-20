"""Snapshot a few live platform responses so tests run offline: python scripts/save_platform_fixtures.py"""
import gzip
import json
import pathlib
import re
import sys

from curl_cffi import requests

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"
s = requests.Session(impersonate="chrome", headers={"Accept-Language": "en-IN,en;q=0.9"})


def save(name: str, obj) -> None:
    (OUT / f"{name}.json.gz").write_bytes(gzip.compress(json.dumps(obj).encode()))
    print("saved", name)


def embedded(html: str, var: str):
    m = re.search(rf"window\.{re.escape(var)}\s*=\s*(\{{.*?\}})\s*;?\s*</script>", html, re.S)
    return json.loads(m.group(1))


r = s.get("https://www.flipkart.com/search", params={"q": "Apple iphone 15 128 GB"}, timeout=30)
state = embedded(r.text, "__INITIAL_STATE__")
save("flipkart_search_iphone15", {"pageDataV4": state["pageDataV4"]})
r = s.get("https://www.flipkart.com/search", params={"q": "PUMA smashic black sneakers"}, timeout=30)
save("flipkart_search_smashic", {"pageDataV4": embedded(r.text, "__INITIAL_STATE__")["pageDataV4"]})

r = s.get("https://api.croma.com/searchservices/v1/search", params={
    "currentPage": 0, "query": "samsung galaxy s24:relevance", "fields": "FULL", "channel": "WEB",
    "channelCode": "400049", "spellOpt": "DEFAULT"}, timeout=30)
save("croma_search_s24", r.json())

r = s.get("https://www.myntra.com/puma-smashic", params={"rawQuery": "PUMA smashic black sneakers"}, timeout=30)
myx = embedded(r.text, "__myx")
save("myntra_search_smashic", {"searchData": {"results": {"products": myx["searchData"]["results"]["products"]}}})
sys.exit(0)
