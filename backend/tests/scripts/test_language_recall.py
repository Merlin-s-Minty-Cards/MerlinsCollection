"""Language detection: the regressions that were found in production data.

**Why this file no longer reads a snapshot.** It used to reconcile the text
parser against TCGplayer's ``pokemon-japan`` category slug across the real
1266-record ``data/spreadsheet/review.html``, on the principle (Council R7
BLOCKER-8) that measuring "records still carrying a marker word: 0" with the
same regex that defines "marker" is a tautology. That was the right instinct,
but the fixture it depended on is gone twice over:

1. ``review.html`` was regenerated as a **held-singles** review — 266 records,
   not 1266 — so every population count and every hardcoded ULID in the old
   assertions referred to rows that are no longer in it.
2. The signal itself is extinct. The sheet's "TCG Link" column was dropped and
   ``import_singles`` stores ``tcg_url=None`` by design since Phase 3.1, so
   **no regenerated snapshot can ever carry a pokemon-japan URL again**
   (measured 2026-08-06: 0 of 266 rows have a ``tcg_url``). The enrichment pass
   also writes clean structured names — "Chespin #84" — rather than the raw
   sheet text the markers lived in, so text detection now finds **0 of 266**
   there too. Language on a current row comes from the stored ``language``
   field, which ``item_language`` reads first.

So the old tests could not be "rewritten against the new snapshot": the data
they reconciled does not exist in any form. They spent a year skipping, which
is worse than useless — a skip reads as "unverified" and hides that the
underlying parser was never actually unprotected.

What IS still live is ``card_text``'s parser itself: ``spreadsheet_import``
calls ``parse_language`` in ten places (including the current enriched path, to
strip markers off a name before storing it, and both slab paths). Every
production miss the snapshot tests were built around is preserved below as a
hermetic case — the ULIDs are gone, the *inputs that made those rows fail* are
not. No gitignored artifact, no skips, and the cases now state what they are
instead of pointing at a row number.
"""

from __future__ import annotations

import pytest

from merlins_collection.models.inventory import Language
from merlins_collection.services.card_text import (
    item_language,
    language_from_set,
    language_from_url,
    parse_language,
)


class TestMarkersFoundInProduction:
    """Real rows the parser missed before, one test per failure mode."""

    def test_a_marker_glued_to_a_leading_digit_is_caught(self):
        """"WCS23JP" — Worlds 2023 Japanese, named by the Council as a live miss.

        R7's whole-word rule could not see a marker with a DIGIT on its left, so
        two real slabs read as English. The boundary deliberately rejects a
        preceding letter but allows a preceding digit.
        """
        assert parse_language("WCS23JP Pikachu") == (Language.JP, "WCS23 Pikachu")

    def test_a_marker_in_the_set_half_of_a_slab_name_is_caught(self):
        """The BLOCKER-1 rows. A graded slab's text is "<name> — <set> #<number>"
        and the marker is often in the SET half, which a name-only parser misses.
        """
        language, cleaned = parse_language("Pikachu — jp 151 #173.0")
        assert language is Language.JP
        assert "jp" not in cleaned.split()

    def test_bracketed_markers_are_caught(self):
        assert parse_language("Team Rocket's Mewtwo (jp)") == (
            Language.JP, "Team Rocket's Mewtwo",
        )
        assert parse_language("Charizard [JPN]") == (Language.JP, "Charizard")

    def test_the_word_japanese_is_a_marker_too(self):
        assert parse_language("Mew japanese promo") == (Language.JP, "Mew promo")

    @pytest.mark.parametrize("text", ["Umbreon jp", "Umbreon JP", "Umbreon Jp"])
    def test_a_trailing_marker_is_case_insensitive(self, text):
        assert parse_language(text)[0] is Language.JP


class TestZeroFalsePositives:
    """The other direction, and the property that makes widening recall safe.

    Every one of these contains a marker as a SUBSTRING and must still read as
    English. This is the half of the contract that costs real money if it
    breaks: a mislabelled English card is priced from the wrong catalog row.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "jpeg",          # letter on the right
            "Jpop",          # letter on the right
            "Japanophile",   # letter on the right
            "1stjp",         # LETTER on the left (a digit would be allowed)
            "jpn2",          # digit on the right
            "xxx_JP88yyy",   # digit on the right
        ],
    )
    def test_a_marker_inside_a_word_is_not_a_marker(self, text):
        assert parse_language(text)[0] is Language.EN

    def test_the_text_is_returned_untouched_when_there_is_no_marker(self):
        assert parse_language("Charizard 1st Edition") == (
            Language.EN, "Charizard 1st Edition",
        )

    def test_a_url_whose_NAME_merely_says_japanese_does_not_count(self):
        """Only the category slug and the explicit filter may promote a card —
        a product whose name happens to contain "japanese" must not."""
        assert language_from_url("https://x.com/japanese-fan-site") is Language.EN


class TestMarkerStrippingPreservesIdentity:
    """The marker is the ONLY thing removed. Other qualifiers carry real meaning
    — "1st Ed" and "(Delta Species)" are what distinguish two otherwise
    identical cards — and the stripped name is what gets stored."""

    def test_other_qualifiers_survive(self):
        assert parse_language("Dragonair (Delta Species) 1st Ed (jp)") == (
            Language.JP, "Dragonair (Delta Species) 1st Ed",
        )

    def test_a_name_that_is_nothing_but_a_marker_keeps_its_text(self):
        """Stripping would leave nothing, so the original is kept: the row still
        records its language, but we never destroy the only identity it has."""
        assert parse_language("(jp)") == (Language.JP, "(jp)")

    def test_none_and_empty_are_english_and_do_not_raise(self):
        assert parse_language(None) == (Language.EN, "")
        assert parse_language("") == (Language.EN, "")


class TestUrlSignal:
    """``language_from_url`` is still called by the legacy import path.

    The production rows it was built for are gone (``tcg_url`` is None by design
    since Phase 3.1), but the function is live code and its two-signal
    precedence is worth pinning.
    """

    def test_the_category_slug_identifies_a_japanese_print(self):
        assert language_from_url(
            "https://www.tcgplayer.com/product/1/pokemon-japan/pikachu",
        ) is Language.JP

    def test_the_explicit_language_filter_is_honoured(self):
        assert language_from_url("https://x.com/p?Language=Japanese") is Language.JP

    def test_an_ambiguous_language_all_does_not_promote(self):
        assert language_from_url("https://x.com/p?Language=all") is Language.EN

    def test_a_missing_url_is_english(self):
        assert language_from_url(None) is Language.EN
        assert language_from_url("") is Language.EN


class TestSetOnlySignal:
    """Some slabs carry no marker in the name and no URL, and are Japanese only
    by which SET they are from. A deliberately small allowlist — an unknown set
    stays English rather than guessing."""

    @pytest.mark.parametrize("set_text", ["SV11B", "sv11b", "Shiny Treasure EX"])
    def test_a_jp_only_set_identifies_the_print(self, set_text):
        assert language_from_set(set_text) is Language.JP

    def test_an_ordinary_set_stays_english(self):
        assert language_from_set("Base Set") is Language.EN


class TestItemLanguagePrecedence:
    """``item_language`` is the one decision point the review page, the applier
    and the backfill all share, so they cannot disagree. Four rungs, most
    authoritative first."""

    def test_the_stored_field_wins(self):
        """Rung 1, and the one that decides every CURRENT row: measured
        2026-08-06, all 17 Japanese items in live inventory are identified this
        way — text detection finds none of them, because the enrichment pass
        stores clean structured names with no markers left in them."""
        assert item_language(
            {"kind": "raw", "language": "JP", "notes": "Pikachu #25"},
        ) is Language.JP

    def test_text_is_consulted_when_nothing_is_stored(self):
        assert item_language(
            {"kind": "raw", "notes": "Team Rocket's Mewtwo (jp)"},
        ) is Language.JP

    def test_the_url_is_consulted_when_the_text_is_silent(self):
        assert item_language({
            "kind": "raw",
            "notes": "Pikachu",
            "tcg_url": "https://tcgplayer.com/product/1/pokemon-japan/x",
        }) is Language.JP

    def test_the_set_is_the_last_resort(self):
        assert item_language(
            {"kind": "raw", "notes": "Seismitoad — SV11B #1"},
        ) is Language.JP

    def test_a_plain_english_record_stays_english(self):
        assert item_language(
            {"kind": "raw", "notes": "Charizard — Base Set #4"},
        ) is Language.EN

    def test_an_unrecognized_stored_language_falls_back_to_english(self):
        """Rather than raising. A junk value in one row must not 500 the review
        page for every other row."""
        assert item_language(
            {"kind": "raw", "language": "KLINGON", "notes": "Pikachu"},
        ) is Language.EN
