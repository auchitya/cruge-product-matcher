import gzip
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def amazon_html():
    def load(asin: str) -> str:
        return gzip.decompress((FIXTURES / f"amazon_{asin}.html.gz").read_bytes()).decode()
    return load


@pytest.fixture
def platform_json():
    def load(name: str) -> dict:
        return json.loads(gzip.decompress((FIXTURES / f"{name}.json.gz").read_bytes()))
    return load
