"""Independent verification of language detection against the production snapshot.

R7 claimed completeness with "records still carrying a marker word: 0", measured
with the same regex that defines "marker" — a tautology that cannot detect a miss
(Council R7 BLOCKER-8). These tests reconcile the text parser against a signal it
does not use and did not produce: TCGplayer's own ``pokemon-japan`` category slug,
written by a different system into a different column.

The fixture is the real ``data/spreadsheet/review.html`` — 1266 production records
embedded by ``build_review.py`` from ``merlins-cards``. It is gitignored, so these
tests skip when it is absent (CI, a fresh clone) rather than failing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from merlins_collection.models.inventory import Language
from merlins_collection.services.card_text import (
    item_language,
    language_from_url,
    parse_language,
)

SNAPSHOT = (Path(__file__).resolve().parents[3]
            / "data" / "spreadsheet" / "review.html")


def _records():
    if not SNAPSHOT.exists():
        pytest.skip("production snapshot not present (gitignored)")
    html = SNAPSHOT.read_text(encoding="utf-8")
    match = re.search(r'id="review-data">(.*?)</script>', html, re.S)
    payload = json.loads(match.group(1).replace("\\u003c", "<"))
    # Rebuild records in the shape the live table holds them.
    return [{"kind": row["kind"], "notes": row["stored"].get("notes"),
             "product_name": row["stored"].get("notes"),
             "description": row["stored"].get("notes"),
             "tcg_url": row["stored"].get("tcg_url"),
             "card_id": row["stored"].get("card_id"),
             "item_id": row["item_id"]}
            for row in payload["cards"]]


@pytest.fixture(scope="module")
def records():
    return _records()


def test_the_text_parser_agrees_with_the_tcgplayer_category_slug(records):
    """The reconciliation that can actually fail — and did.

    Every row whose URL says ``pokemon-japan`` must be detected as Japanese. When
    this was first run it failed on three rows carrying no marker at all in their
    text, which is why ``item_language`` consults the URL.
    """
    by_url = [r for r in records if language_from_url(r["tcg_url"]) is Language.JP]
    assert by_url, "snapshot has no pokemon-japan URLs — fixture is wrong"
    missed = [r["item_id"] for r in by_url if item_language(r) is not Language.JP]
    assert missed == []


def test_the_slug_and_the_text_corroborate_each_other(records):
    """32 of the 35 URL-flagged rows are independently marked in their text. Two
    signals produced by different systems agreeing on the same rows is what makes
    either of them believable."""
    by_url = {r["item_id"] for r in records
              if language_from_url(r["tcg_url"]) is Language.JP}
    by_text = {r["item_id"] for r in records
               if parse_language(r["notes"])[0] is Language.JP}
    assert len(by_url & by_text) >= 30
    # ...and the text finds far more than the URL does, so neither subsumes the other
    assert len(by_text - by_url) > 60


def test_the_two_wcs23jp_rows_are_caught(records):
    """Named by the Council as live misses: 'WCS23JP' is Worlds 2023 Japanese,
    and R7's whole-word rule could not see a marker glued to a digit."""
    wanted = {"01KY8EC1BM7RAY8C77JM8BSJAF", "01KY8EC4H4Z4Q11E7KMDF6C9KY"}
    found = {r["item_id"] for r in records if item_language(r) is Language.JP}
    assert wanted <= found


def test_the_two_set_column_slabs_are_caught(records):
    """The BLOCKER-1 rows: the marker is in the SET half of the notes."""
    wanted = {"01KY8EC7JYF175WA1NKFYESKZV", "01KY8EC1PRGMR1HW32Z7QSD7J5"}
    found = {r["item_id"] for r in records if item_language(r) is Language.JP}
    assert wanted <= found


def test_the_three_url_only_rows_are_caught(records):
    """Singles.csv:551, :552 and :586 — no marker in the text at all."""
    wanted = {"01KY8E955CKP21Y2X2RXFW4DCJ", "01KY8E95FJQ8GWSTCN2AAMC1FP",
              "01KY8E9BDGA1QXMS1X6ADGGCHC"}
    found = {r["item_id"] for r in records if item_language(r) is Language.JP}
    assert wanted <= found


def test_the_population_is_109_and_none_of_them_is_linked(records):
    """The number the operator must see in the production dry run before
    ``--apply``, and the precondition that makes the backfill safe: a JP item with
    a ``card_id`` would be priced from an English card by the nightly sync."""
    japanese = [r for r in records if item_language(r) is Language.JP]
    assert len(japanese) == 109
    assert [r["item_id"] for r in japanese if r["card_id"]] == []


def test_no_english_row_is_swept_up(records):
    """The other direction: widening recall must not cost the zero-false-positive
    property the Council verified across these same 1266 records."""
    english = [r for r in records if item_language(r) is Language.EN]
    assert len(english) == len(records) - 109
    for probe in ("jpeg", "Jpop", "Japanophile", "1stjp", "jpn2", "xxx_JP88yyy"):
        assert parse_language(probe)[0] is Language.EN
