"""Tests for the shared card-text module.

This module exists because R7 shipped two divergent implementations of one
contract (BLOCKER-9): ``build_review.normalize_name`` dropped non-ASCII before
splitting words while ``apply_review_decisions._norm_text`` split first, so the
producer and consumer of a single paste-back round trip disagreed on
``HS—Unleashed``. There is now one implementation and both ends import it.
"""

from __future__ import annotations

import pytest

from merlins_collection.models.inventory import Language
from merlins_collection.services.card_text import (
    ITEM_TEXT_FIELD,
    format_display_name,
    item_language,
    language_from_url,
    normalize_name,
    normalize_number,
    parse_language,
    strip_float_artifact,
)


# --- one normalizer, correct ordering (BLOCKER-9) ------------------------

def test_a_dash_separates_words_whatever_kind_of_dash_it_is():
    """The em-dash case that made the two R7 normalizers disagree. batch-01
    line 8 carries `set=HS—Unleashed` with this exact character."""
    assert normalize_name("HS—Unleashed") == "hs unleashed"
    assert normalize_name("HS-Unleashed") == "hs unleashed"
    assert normalize_name("HS—Unleashed") == normalize_name("HS-Unleashed")


def test_normalize_name_still_does_what_both_callers_needed():
    assert normalize_name("Moltres & Zapdos-GX") == "moltres zapdos gx"
    assert normalize_name("  Team Rocket's  Mewtwo ") == "team rocket s mewtwo"
    assert normalize_name(None) == ""


def test_non_ascii_names_do_not_all_collapse_to_the_same_empty_string():
    """S3: two fully non-ASCII names must not normalize to '' and compare equal —
    that is exactly the field a Japanese catalog would populate."""
    assert normalize_name("ピカチュウ") == ""
    assert normalize_name("リザードン") == ""
    # ...so the callers must not treat an empty normalization as a match; the
    # helper reports it so they can refuse.
    assert normalize_name("Pikachu") != ""


def test_strip_float_artifact_and_number_normalization():
    assert strip_float_artifact("83.0") == "83"
    assert strip_float_artifact("1400665984.0") == "1400665984"
    assert strip_float_artifact("83.5") == "83.5"
    assert strip_float_artifact("sm210") == "sm210"
    assert strip_float_artifact(None) == ""
    assert normalize_number("83.0") == "83"
    assert normalize_number("SWSH068") == "swsh068"
    # a collector number's punctuation is load-bearing: callers split on it
    assert normalize_number("182/167") == "182/167"
    assert normalize_number("TG12/TG30") == "tg12/tg30"


# --- language markers glued to another token (BLOCKER-8) -----------------

@pytest.mark.parametrize("text", [
    "Pikachu Ex world championship Promo — WCS23JP #1.0",
    "Pikachu Ex — Pokemon WCS23JP #1.0",
])
def test_a_marker_glued_to_a_digit_prefix_is_still_a_marker(text):
    """Two live production records (01KY8EC1BM7RAY8C77JM8BSJAF,
    01KY8EC4H4Z4Q11E7KMDF6C9KY) read 'WCS23JP' — Worlds 2023 Japanese. R7's
    whole-word rule missed both, leaving them eligible for an English card_id."""
    assert parse_language(text)[0] is Language.JP


def test_the_glued_marker_is_removed_leaving_the_set_code():
    assert parse_language("Pikachu Ex — Pokemon WCS23JP #1.0") == (
        Language.JP, "Pikachu Ex — Pokemon WCS23 #1.0")


@pytest.mark.parametrize("text", [
    "jpeg", "Jpop", "Japanophile", "1stjp", "jpn2", "xxx_JP88yyy",
    "Charizard jpeg scan", "Mewtwo Jpop Promo", "Japanophile Deck",
])
def test_the_adversarial_set_the_council_verified_stays_english(text):
    """The Council recorded ZERO false positives across 1266 production records
    and these probes. Widening recall must not cost that."""
    assert parse_language(text) == (Language.EN, text)


def test_letter_glued_markers_are_still_refused():
    """Only a DIGIT may precede a marker. A letter still means it is part of a
    word, which is what keeps 'jpeg'/'1stjp' out."""
    assert parse_language("sm12ajp")[0] is Language.EN
    assert parse_language("WCS23JPX")[0] is Language.EN


@pytest.mark.parametrize("text,cleaned", [
    ("Team Rocket's Mewtwo (jp)", "Team Rocket's Mewtwo"),
    ("Articuno (Jp)", "Articuno"),
    ("Espeon V (Japanese)", "Espeon V"),
    ("Lugia jp", "Lugia"),
    ("JP exxeggutor Promo", "exxeggutor Promo"),
    ("Wooper (Delta Species) Jp 1st Edition", "Wooper (Delta Species) 1st Edition"),
    ("Venusaur (jp) 1st holo", "Venusaur 1st holo"),
    # Spellings absorbed from the importer's own duplicate copy of this table
    # (test_spreadsheet_import.py) when the three parallel parse_language test
    # sets were consolidated here, into the module the function lives in.
    ("Milotic (JP)", "Milotic"),
    ("Reshiram Ex (japanese)", "Reshiram Ex"),
    ("COLRESS'S EXPERIMENT - FULL ART (Japanese)", "COLRESS'S EXPERIMENT - FULL ART"),
    ("Espathra (JP)", "Espathra"),
    ("Slakoth JP", "Slakoth"),
    ("Dragonite JP ANA airlines", "Dragonite ANA airlines"),
])
def test_every_r7_marker_spelling_still_parses(text, cleaned):
    assert parse_language(text) == (Language.JP, cleaned)


def test_a_name_that_is_nothing_but_a_marker_keeps_its_text():
    """Stripping would leave the row with no identity at all, so the original
    text is kept — it still reports JP, it just refuses to destroy the only
    name it has."""
    assert parse_language("(jp)") == (Language.JP, "(jp)")


def test_parse_language_handles_none_and_empty_without_raising():
    assert parse_language(None) == (Language.EN, "")
    assert parse_language("") == (Language.EN, "")


def test_one_pattern_not_a_per_language_dict_decides(monkeypatch):
    """Architect M3: a single compiled pattern maps each token to its language,
    so 'insertion order decides' cannot be a weakness."""
    from merlins_collection.services import card_text

    assert isinstance(card_text.LANGUAGE_MARKER_RE.pattern, str)
    assert card_text._TOKEN_LANGUAGE["jp"] is Language.JP
    assert card_text._TOKEN_LANGUAGE["japanese"] is Language.JP


# --- the independent, non-circular signal (BLOCKER-8) --------------------

@pytest.mark.parametrize("url", [
    "https://www.tcgplayer.com/product/572756/pokemon-japan-sm12a-tag-team-gx-tag-all-stars-moltres",
    "https://www.tcgplayer.com/product/603972/pokemon-japan-xy7-bandit-ring-mega-sceptile-ex-008-081",
])
def test_a_tcgplayer_japan_url_is_a_language_signal(url):
    """Three live rows (Singles.csv:551, :552, :586) carry NO marker in their
    text and are identifiable only from TCGplayer's own category slug. This is a
    genuinely independent source — a different column, produced by a different
    system — which is what makes it usable to verify the text parser."""
    assert language_from_url(url) is Language.JP


def test_an_english_tcgplayer_url_is_not_a_language_signal():
    assert language_from_url(
        "https://www.tcgplayer.com/product/1234/pokemon-sword-shield-pikachu") is Language.EN
    assert language_from_url("") is Language.EN
    assert language_from_url(None) is Language.EN


def test_the_word_japan_in_a_product_name_does_not_trip_the_url_rule():
    """Only the category segment counts, not any occurrence of the word."""
    assert language_from_url(
        "https://www.tcgplayer.com/product/9/pokemon-sm-team-up-japanese-collector") is Language.EN


# --- one place decides an item's language (BLOCKER-1a, N4) ---------------

def test_item_text_field_is_the_single_kind_to_field_map():
    assert ITEM_TEXT_FIELD == {"raw": "notes", "graded": "notes",
                               "sealed": "product_name", "bulk": "description"}


def test_item_language_reads_the_whole_stored_text_not_just_the_name():
    """BLOCKER-1(a). The live PSA 10 01KY8EC7JYF175WA1NKFYESKZV stores
    notes='Pikachu — jp 151 #173.0': the marker is in the SET half, which R7's
    graded branch never language-checked. It banded HIGH for English sv3pt5-173
    at $93.50, citing its own 'jp 151' marker as supporting evidence."""
    record = {"kind": "graded", "notes": "Pikachu — jp 151 #173.0"}
    assert item_language(record) is Language.JP


def test_item_language_covers_the_second_live_slab():
    record = {"kind": "graded", "notes": "Lilie's Determination — Mega 1 jp #184.0"}
    assert item_language(record) is Language.JP


def test_item_language_prefers_the_stored_field_once_it_exists():
    record = {"kind": "raw", "notes": "Seismitoad #38", "language": "JP"}
    assert item_language(record) is Language.JP


def test_item_language_falls_back_to_the_tcg_url():
    record = {"kind": "raw", "notes": "M Sceptile Ex #8.0",
              "tcg_url": "https://www.tcgplayer.com/product/603972/pokemon-japan-xy7-bandit-ring"}
    assert item_language(record) is Language.JP


def test_item_language_defaults_to_english():
    assert item_language({"kind": "raw", "notes": "Charizard #4.0"}) is Language.EN
    assert item_language({"kind": "sealed", "product_name": "Booster Box"}) is Language.EN
    assert item_language({}) is Language.EN


def test_item_language_falls_back_to_english_on_an_unrecognized_stored_value():
    """Rather than raising. Junk in one row's ``language`` field must not 500 the
    review page for every other row it is listed beside."""
    assert item_language(
        {"kind": "raw", "language": "KLINGON", "notes": "Pikachu"},
    ) is Language.EN


def test_item_language_accepts_a_model_instance_not_only_a_dict():
    """The applier holds a pydantic item, the scripts hold raw records."""
    from datetime import date
    from decimal import Decimal

    from merlins_collection.models.inventory import RawInventoryItem

    item = RawInventoryItem(cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
                            finish="normal", condition="NM",
                            notes="Pikachu — jp 151 #173.0")
    assert item_language(item) is Language.JP


# --- display_name is materialized from STRUCTURED identity (Council MUST-FIX A/C) --
# The name is composed at IMPORT time from the sheet's own ``Name`` and ``Card #``
# columns — the structured identity — never re-parsed from the free-text ``notes``
# blob at read time. That is what keeps the importer's Notes column
# ("cost 40, sold to David"), a storage location, or a cert number off the
# customer wire and out of the Bedrock prompt: there is no free-text path into
# this function at all, only the two structured columns.

def test_format_display_name_composes_name_and_number():
    """The legitimate path: a real name + card number yields ``<name> #<number>``,
    with the Excel float artifact undone."""
    assert format_display_name("Dragonair", "181") == "Dragonair #181"
    assert format_display_name("Dragonair", "181.0") == "Dragonair #181"


def test_format_display_name_returns_none_without_a_structured_name():
    """A blank ``Name`` column -> no fabricated identity (None), so a row that
    carries only internal Notes text can never get a name derived from it."""
    assert format_display_name("", "12") is None
    assert format_display_name(None, "181") is None
    assert format_display_name("   ", "181") is None


def test_format_display_name_keeps_the_name_when_the_number_is_absent_or_junk():
    """A present name with no usable card number still names the card (the number
    is simply dropped) — but a ``#``-prefixed prose value never appears because
    only the structured ``Card #`` column feeds this, and a non-card-number value
    is discarded rather than appended."""
    assert format_display_name("Dragonair", "") == "Dragonair"
    assert format_display_name("Dragonair", None) == "Dragonair"
    # a value with no digit is not a card number -> dropped, name only
    assert format_display_name("Dragonair", "abc") == "Dragonair"


def test_format_display_name_bounds_the_composed_length():
    """A pathological cell cannot emit a multi-line or unbounded token onto a
    tile or into the prompt: whitespace collapses and the whole result is capped
    (the number component is bounded here too, not only the name)."""
    long_name = "A" * 200
    assert len(format_display_name(long_name, "1")) <= 80
    long_number = "1" * 300
    assert len(format_display_name("Charizard", long_number)) <= 80
    assert format_display_name("Line1\nLine2", "1") == "Line1 Line2 #1"


# --- set_hint_from_url (D: disambiguate singles via the TCGplayer link) -------

from merlins_collection.services.card_text import set_hint_from_url  # noqa: E402


def test_set_hint_from_url_extracts_set_tokens_from_product_slug():
    url = ("https://www.tcgplayer.com/product/517020/"
           "pokemon-sv-scarlet-and-violet-151-dragonair-181-165?Condition=Near+Mint")
    hint = set_hint_from_url(url)
    # The catalog set name's tokens are all present -> sets_agree can token-contain it.
    assert "scarlet" in hint and "violet" in hint and "151" in hint
    assert "pokemon" not in hint  # the leading marketplace prefix is dropped


def test_set_hint_from_url_handles_base_set_and_returns_empty_for_non_product():
    assert set_hint_from_url(
        "https://www.tcgplayer.com/product/42382/pokemon-base-set-charizard"
    ) == "base set charizard"
    # A non-tcgplayer / non-product URL yields no hint, so callers gate nothing.
    assert set_hint_from_url("http://example.com/25") == ""
    assert set_hint_from_url(None) == ""


# =============================================================================
# PHASE 3.1 — language beyond the name
# marker — the TCG Link's `Language=` query param, and a SET-based JP fallback
# for rows that carry no marker anywhere (two real 7-25 Slabs rows: Bubble Mew
# EX / Shiny Treasure EX, Seismitoad / SV11B).
# =============================================================================

# ---- language_from_url: the `Language=` query param -----------------------

def test_language_from_url_reads_an_explicit_japanese_query_param():
    """A case the path-slug rule alone cannot cover: a bare numeric product id
    with no set/name slug at all, but an explicit Japanese query param."""
    assert language_from_url(
        "https://www.tcgplayer.com/product/999999?Language=Japanese") is Language.JP


def test_language_from_url_english_query_param_stays_english():
    assert language_from_url(
        "https://www.tcgplayer.com/product/124113/pokemon-xy-evolutions-"
        "m-venusaur-ex-full-art?Language=English&page=1") is Language.EN


def test_language_from_url_bare_all_query_param_alone_is_not_a_japanese_signal():
    """Real production counter-example (Singles.csv, "Giovanni's Exile"): a bare
    product id with ``Language=all`` and NO set/language-bearing slug is an
    ENGLISH card. "all" means "TCGplayer lists every language of this product
    under one id", not "this one is Japanese" — it must never, by itself,
    promote a card to JP the way the ``pokemon-japan`` slug legitimately does."""
    assert language_from_url(
        "https://www.tcgplayer.com/product/197730?page=1&Language=all"
        "&Condition=Near+Mint") is Language.EN


def test_language_from_url_still_reads_the_slug_when_the_query_param_is_ambiguous():
    """The real "Slowking Lv.36 (jp)" row: `Language=all` AND the `pokemon-japan`
    slug are both present. The slug signal must still carry the day."""
    assert language_from_url(
        "https://www.tcgplayer.com/product/607955/pokemon-japan-southern-island"
        "-slowking?page=1&Language=all&Condition=Near+Mint") is Language.JP


# ---- SET-based JP fallback (no marker anywhere; two real Slabs rows) ------

@pytest.mark.parametrize("set_text", ["SV11B", "sv11b"])
def test_language_from_set_recognizes_a_known_japanese_only_set_code(set_text):
    """Real Slabs.csv row 18: Name "Seismitoad", Set "SV11B" — no marker in
    either column. The sheet is hand-typed, so the code is matched
    case-insensitively."""
    from merlins_collection.services.card_text import language_from_set
    assert language_from_set(set_text) is Language.JP


def test_language_from_set_recognizes_a_known_japanese_only_set_name():
    """Real Slabs.csv row 5: Name "Bubble Mew EX", Set "Shiny Treasure EX"."""
    from merlins_collection.services.card_text import language_from_set
    assert language_from_set("Shiny Treasure EX") is Language.JP


def test_language_from_set_defaults_to_english_for_an_ordinary_set():
    from merlins_collection.services.card_text import language_from_set
    assert language_from_set("Base Set") is Language.EN
    assert language_from_set("Brilliant Stars") is Language.EN
    assert language_from_set("") is Language.EN
    assert language_from_set(None) is Language.EN


def test_item_language_falls_back_to_the_set_when_nothing_else_marks_it_japanese():
    """The importer stores a slab's set inside ``notes`` ("<name> — <set>
    #<number>"), so the set-code fallback must also work from the WHOLE stored
    text, exactly like the existing URL and marker fallbacks already do."""
    record = {"kind": "graded", "notes": "Seismitoad — SV11B #109.0"}
    assert item_language(record) is Language.JP


def test_item_language_set_fallback_does_not_trip_on_an_ordinary_english_set():
    record = {"kind": "graded", "notes": "Charizard — Brilliant Stars #4.0"}
    assert item_language(record) is Language.EN


def test_the_name_marker_still_outranks_the_set_fallback():
    """A marker in the text is the most explicit signal and must not be
    second-guessed by the set-code heuristic, even where they'd agree anyway."""
    record = {"kind": "graded",
              "notes": "Arceus V (jp) — Pokemon Legends Arceus Preorder #267.0"}
    assert item_language(record) is Language.JP
