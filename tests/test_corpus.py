"""Replay the crawled corpus (eval/corpus.jsonl.gz, ~590 Amazon products, ~1,180 platform lookups)
through the current rules. Ground truth = style codes / model numbers (see scripts/evaluate.py).

This is the guard against rules that fit the handful of products someone looked at and break the
rest: any change that produces a verifiably wrong match, or loses verified matches, fails here.
Thresholds sit just under the measured numbers; tighten them when the rules improve.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "eval" / "corpus.jsonl.gz"

pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="eval corpus not present")


@pytest.fixture(scope="module")
def report():
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run(CORPUS)


def test_corpus_is_big_enough(report):
    assert report.products >= 580 and report.lookups >= 1150


def test_no_verifiably_wrong_matches(report):
    assert report.total("matched_WRONG") == 0, report.examples


def test_finds_what_is_there(report):
    assert report.total("matched_right") >= 150
    assert report.total("not_listed_but_truth_exists") <= 3, report.examples


HELDOUT = ROOT / "eval" / "heldout.jsonl.gz"


@pytest.mark.skipif(not HELDOUT.exists(), reason="held-out corpus not present")
def test_heldout_set_has_no_verifiably_wrong_matches():
    """170 products from 84 searches the rules were never tuned on (new brands, phrasings)."""
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rep = mod.run(HELDOUT)
    assert rep.products >= 160
    assert rep.total("matched_WRONG") == 0, rep.examples
    assert rep.total("matched_right") >= 30
