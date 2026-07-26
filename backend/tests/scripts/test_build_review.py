"""Tests for the offline needs_review triage tool (``scripts/build_review.py``).

Everything here runs over fixture dicts shaped like raw DynamoDB records — no
AWS, real or mocked, is touched. ``scripts/`` is not an importable package, so
the module is loaded straight off disk.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_review.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("build_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_review"] = module
    spec.loader.exec_module(module)
    return module


br = _load_script()


# --- fixture builders ----------------------------------------------------

def catalog_card(card_id, name, set_name, number, *, set_id=None, market="10.00",
                 rarity="Rare", finish="normal"):
    return {
        "entity": "catalog_card",
        "card_id": card_id,
        "name": name,
        "set_id": set_id or card_id.split("-")[0],
        "set_name": set_name,
        "number": number,
        "rarity": rarity,
        "types": ["Colorless"],
        "images": {"small": f"https://img.example/{card_id}.png",
                   "large": f"https://img.example/{card_id}_hires.png"},
        "prices": {finish: {"market": Decimal(market), "low": None,
                            "mid": None, "high": None}},
        "last_synced_at": "2026-07-01T00:00:00+00:00",
    }


def raw_item(item_id, notes, **over):
    item = {
        "entity": "inventory_item", "kind": "raw", "item_id": item_id,
        "status": "available", "card_id": None, "finish": "normal",
        "condition": "NM", "condition_modifier": None, "factory_sealed": False,
        "cost_basis": Decimal("5"), "market_value_at_purchase": None,
        "current_market_value": None, "listed_price": None,
        "acquired_at": "2026-03-14", "notes": notes, "needs_review": True,
    }
    item.update(over)
    return item


def graded_item(item_id, notes, **over):
    item = {
        "entity": "inventory_item", "kind": "graded", "item_id": item_id,
        "status": "available", "card_id": None, "company": "PSA",
        "grade": Decimal("10"), "cert_number": "1400665984.0",
        "cost_basis": Decimal("50"), "market_value_at_purchase": None,
        "current_market_value": None, "listed_price": None,
        "acquired_at": "2026-03-14", "notes": notes, "needs_review": True,
    }
    item.update(over)
    return item


# --- identifier normalization -------------------------------------------

def test_strip_float_artifact_removes_excel_trailing_zero():
    assert br.strip_float_artifact("83.0") == "83"
    assert br.strip_float_artifact("1400665984.0") == "1400665984"
    assert br.strip_float_artifact(Decimal("10.0")) == "10"


def test_strip_float_artifact_preserves_real_values():
    assert br.strip_float_artifact("83.5") == "83.5"
    assert br.strip_float_artifact("sm210") == "sm210"
    assert br.strip_float_artifact("TG12/TG30") == "TG12/TG30"
    assert br.strip_float_artifact(None) == ""


# --- recovering the source text the importer preserved -------------------

def test_parse_source_text_raw_splits_name_and_number():
    src = br.parse_source_text(raw_item("I1", "Charizard #4.0"))
    assert (src.name, src.number, src.set_name) == ("Charizard", "4", "")


def test_parse_source_text_raw_keeps_trailing_note_segments():
    src = br.parse_source_text(raw_item("I1", "Charizard #4.0 — creased — For David"))
    assert src.name == "Charizard"
    assert "creased" in src.extra and "For David" in src.extra


def test_parse_source_text_raw_without_number():
    src = br.parse_source_text(raw_item("I1", "Pikachu"))
    assert (src.name, src.number) == ("Pikachu", "")


def test_parse_source_text_graded_recovers_set_column():
    src = br.parse_source_text(
        graded_item("I2", "Dragonite-Holo — XY single pack Blister #83.0"))
    assert src.name == "Dragonite-Holo"
    assert src.set_name == "XY single pack Blister"
    assert src.number == "83"


def test_parse_source_text_sealed_uses_product_name():
    item = {"kind": "sealed", "item_id": "I3", "product_name": "Phatasmal Flames Bundle",
            "product_type": "bundle", "notes": None}
    src = br.parse_source_text(item)
    assert src.name == "Phatasmal Flames Bundle"


# --- card prediction -----------------------------------------------------

CATALOG = [
    catalog_card("xy-83", "Dragonite", "XY", "83", market="12.50"),
    catalog_card("base1-4", "Charizard", "Base", "4", market="300.00"),
    catalog_card("base2-4", "Charizard", "Base Set 2", "4", market="120.00"),
    catalog_card("bs3-4", "Charizard", "Legendary Collection", "4", market="90.00"),
    catalog_card("sm12-1", "Moltres & Zapdos & Articuno-GX", "Cosmic Eclipse",
                 "sm210", market="60.00"),
]


def test_predict_card_high_on_name_number_and_set():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Dragonite-Holo", number="83", set_name="XY", extra="")
    pred = br.predict_card(src, index)
    assert pred.best["card_id"] == "xy-83"
    assert pred.confidence == "HIGH"
    assert "set" in pred.reason.lower()


def test_predict_card_high_when_name_and_number_are_unique_without_set():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Dragonite", number="83", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.best["card_id"] == "xy-83"
    assert pred.confidence == "HIGH"


def test_predict_card_medium_when_several_sets_share_name_and_number():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Charizard", number="4", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.confidence == "MEDIUM"
    assert len(pred.candidates) == 3
    assert "3" in pred.reason


def test_predict_card_low_on_fuzzy_name_only():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Dragonight", number="", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.best["card_id"] == "xy-83"
    assert pred.confidence == "LOW"
    assert "fuzzy" in pred.reason.lower()


def test_predict_card_reports_no_candidates_honestly():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Zzzzqx Placeholder Lot", number="", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.best is None
    assert pred.confidence == "LOW"
    assert pred.candidates == []


def test_predict_card_number_matching_tolerates_float_artifact():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Dragonite", number="83.0", set_name="", extra="")
    assert br.predict_card(src, index).best["card_id"] == "xy-83"


def test_predict_card_limits_runner_ups():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Charizard", number="4", set_name="", extra="")
    pred = br.predict_card(src, index, max_candidates=2)
    assert len(pred.candidates) == 2


def test_predict_card_sealed_kind_is_not_guessed_from_the_card_catalog():
    index = br.CatalogIndex.build(CATALOG)
    src = br.SourceText(name="Phatasmal Flames Bundle", number="", set_name="", extra="")
    pred = br.predict_card(src, index, kind="sealed")
    assert pred.best is None
    assert pred.confidence == "LOW"
    assert "sealed" in pred.reason.lower()


SPLIT_CATALOG = [
    catalog_card("cel25-25", "Mew", "Celebrations", "25", market="40.00"),
    catalog_card("cel25-14", "Cosmoem", "Celebrations", "14"),
    catalog_card("swsh4-182", "Probopass", "Vivid Voltage", "182"),
    catalog_card("base1-58", "Eevee", "Jungle", "58"),
]


def test_predict_card_matches_a_full_collector_number():
    """The sheet writes "182/167"; the catalog stores "182"."""
    index = br.CatalogIndex.build(SPLIT_CATALOG)
    src = br.SourceText(name="Probopass", number="182/167", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.best["card_id"] == "swsh4-182"
    assert pred.confidence == "HIGH"  # name AND number agreed, not name alone


def test_predict_card_reads_a_trailing_set_name_out_of_the_card_name():
    """The singles tab has no Set column, so the set often rides on the name."""
    index = br.CatalogIndex.build(SPLIT_CATALOG)
    src = br.SourceText(name="Cosmoem Celebrations", number="14", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.best["card_id"] == "cel25-14"
    assert pred.confidence == "HIGH"
    assert "celebrations" in pred.reason.lower()


def test_predict_card_distrusts_a_split_whose_leftover_matches_no_set():
    index = br.CatalogIndex.build(SPLIT_CATALOG)
    src = br.SourceText(name="Eevee Nintendo", number="58", set_name="", extra="")
    pred = br.predict_card(src, index)
    assert pred.best["card_id"] == "base1-58"
    assert pred.confidence == "LOW"
    assert "nintendo" in pred.reason.lower()


def test_finish_words_are_free_but_variant_words_cost_confidence():
    """"Holo" is just a printing; "Gold" can be a different card entirely."""
    index = br.CatalogIndex.build(SPLIT_CATALOG)
    gold = br.predict_card(
        br.SourceText(name="Mew Gold Celebrations", number="25"), index)
    assert gold.best["card_id"] == "cel25-25"
    assert gold.confidence == "MEDIUM"
    assert "gold" in gold.reason.lower()


# --- print language: the English catalog is off limits for a JP card -----

JP_CATALOG = [catalog_card("swsh6-38", "Seismitoad", "Chilling Reign", "38",
                           market="400.00")]


def test_parse_source_text_lifts_the_language_marker_out_of_the_name():
    src = br.parse_source_text(raw_item("I1", "Seismitoad (jp) #38"))
    assert (src.name, src.number, src.language) == ("Seismitoad", "38", "JP")


def test_parse_source_text_trusts_the_stored_language_field_after_backfill():
    """Once the backfill has run the marker is gone from the text and the truth
    lives in the ``language`` attribute — the page must read it either way."""
    src = br.parse_source_text(raw_item("I1", "Seismitoad #38", language="JP"))
    assert (src.name, src.language) == ("Seismitoad", "JP")


def test_parse_source_text_defaults_to_english():
    assert br.parse_source_text(raw_item("I1", "Charizard #4.0")).language == "EN"


def test_predict_card_refuses_the_english_catalog_for_a_japanese_item():
    """Name and number hit an English card exactly; the match is still refused."""
    index = br.CatalogIndex.build(JP_CATALOG)
    pred = br.predict_card(
        br.SourceText(name="Seismitoad", number="38", language="JP"), index)
    assert pred.candidates == []
    assert pred.confidence == "NA"
    assert "japanese" in pred.reason.lower()
    assert "sheet" in pred.reason.lower()


def test_a_marker_left_in_the_stored_text_is_caught_by_the_real_path():
    """``parse_source_text`` is the only producer of a ``SourceText``, and it
    decides language from the whole record — so an un-backfilled row whose marker
    is still sitting in its text is gated without predict_card re-parsing it."""
    index = br.CatalogIndex.build(JP_CATALOG)
    src = br.parse_source_text(raw_item("I1", "Seismitoad (jp) #38"))
    assert src.language == "JP"
    pred = br.predict_card(src, index)
    assert pred.candidates == []
    assert pred.confidence == "NA"


def test_predict_card_still_matches_the_english_twin():
    index = br.CatalogIndex.build(JP_CATALOG)
    pred = br.predict_card(br.SourceText(name="Seismitoad", number="38"), index)
    assert pred.best["card_id"] == "swsh6-38"
    assert pred.confidence == "HIGH"


def test_build_card_rows_gives_a_japanese_row_no_english_price():
    index = br.CatalogIndex.build(JP_CATALOG)
    points = {"swsh6-38": [{"card_id": "swsh6-38", "kind": "raw", "finish": "normal",
                            "date": "2026-07-01", "market": Decimal("400.00")}]}
    item = raw_item("JP1", "Seismitoad (jp) #38", listed_price=Decimal("15"))
    row = br.build_card_rows([item], index, points)[0]
    assert row["confidence"] == "NA"
    assert row["prediction"] is None
    assert row["runners"] == []
    assert row["divergence"] is None          # nothing to diverge from
    assert row["stored"]["listed_price"] == "15"
    assert "japanese" in row["reason"].lower()


def test_japanese_rows_sort_below_every_row_that_still_needs_a_decision():
    """JP rows are a correct terminal state, not the most-likely-wrong rows."""
    index = br.CatalogIndex.build(JP_CATALOG)
    rows = br.build_card_rows(
        [raw_item("JP1", "Seismitoad (jp) #38"),
         raw_item("EN1", "Seismitoad #38"),
         raw_item("LOW1", "Totally Unknown Thing")], index, {})
    assert [r["item_id"] for r in rows][-1] == "JP1"


def test_review_page_can_filter_the_na_band():
    html = br.render_html([], table_name="t", generated_at="now")
    assert 'value="NA"' in html


# --- BLOCKER-1(a): the marker is often in the SET half of the notes ------

# The exact English cards the two live JP slabs were being matched to.
LIVE_JP_CATALOG = [
    catalog_card("sv3pt5-173", "Pikachu", "151", "173", market="93.50"),
    catalog_card("me1-184", "Lilie's Determination", "Mega Evolution", "184",
                 market="74.24"),
]


def test_the_live_psa10_pikachu_no_longer_bands_high_for_an_english_card():
    """R7's worst defect, pinned to the real record. Production item
    01KY8EC7JYF175WA1NKFYESKZV stores notes='Pikachu — jp 151 #173.0' with NO
    language attribute, and R7 banded it HIGH for English sv3pt5-173 at $93.50,
    quoting its own 'jp 151' marker as supporting evidence for the match."""
    item = graded_item("01KY8EC7JYF175WA1NKFYESKZV", "Pikachu — jp 151 #173.0")
    assert "language" not in item  # exactly as the live table holds it
    row = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})[0]
    assert row["confidence"] == "NA"
    assert row["prediction"] is None
    assert row["runners"] == []
    assert "japanese" in row["reason"].lower()


def test_the_second_live_jp_slab_also_bands_na():
    item = graded_item("01KY8EC1PRGMR1HW32Z7QSD7J5",
                       "Lilie's Determination — Mega 1 jp #184.0")
    row = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})[0]
    assert row["confidence"] == "NA"
    assert row["prediction"] is None


def test_parse_source_text_reads_the_language_out_of_the_set_half():
    src = br.parse_source_text(graded_item("I1", "Pikachu — jp 151 #173.0"))
    assert src.language == "JP"
    assert src.name == "Pikachu"
    assert src.set_name == "151"  # marker stripped from the set text too


def test_an_english_graded_slab_still_matches_on_its_set():
    """No regression: the set half is still used as matching evidence."""
    src = br.parse_source_text(graded_item("I1", "Dragonite-Holo — XY #83.0"))
    assert src.language == "EN"
    pred = br.predict_card(src, br.CatalogIndex.build(CATALOG), kind="graded")
    assert pred.best["card_id"] == "xy-83"
    assert pred.confidence == "HIGH"


def test_a_row_identified_only_by_its_tcgplayer_url_bands_na():
    """Three live rows carry no marker at all; the URL is the only evidence."""
    item = raw_item("01KY8E9BDGA1QXMS1X6ADGGCHC", "M Sceptile Ex #8.0",
                    tcg_url="https://www.tcgplayer.com/product/603972/"
                            "pokemon-japan-xy7-bandit-ring-mega-sceptile-ex-008-081")
    row = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})[0]
    assert row["confidence"] == "NA"


def test_the_wcs23jp_rows_band_na():
    item = raw_item("01KY8EC1BM7RAY8C77JM8BSJAF",
                    "Pikachu Ex world championship Promo — WCS23JP #1.0")
    row = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})[0]
    assert row["confidence"] == "NA"


# --- BLOCKER-9 (Architect M2): the language gate outranks the kind gate --

def test_a_japanese_sealed_product_bands_na_not_low():
    """§6 question 4, answered rather than deferred: language is on _ItemBase for
    every kind, so the gate must run before the sealed/bulk early return."""
    item = {"entity": "inventory_item", "kind": "sealed", "item_id": "S1",
            "product_name": "Eevee Heroes Booster Box (jp)", "notes": None,
            "needs_review": True, "cost_basis": Decimal("100")}
    row = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})[0]
    assert row["confidence"] == "NA"
    assert "japanese" in row["reason"].lower()


def test_an_english_sealed_product_still_bands_low_with_the_sealed_reason():
    item = {"entity": "inventory_item", "kind": "sealed", "item_id": "S2",
            "product_name": "Evolving Skies Booster Box", "notes": None,
            "needs_review": True, "cost_basis": Decimal("100")}
    row = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})[0]
    assert row["confidence"] == "LOW"
    assert "sealed" in row["reason"].lower()


# --- BLOCKER-1(d): a resolved JP row must not vanish from the page -------

def test_a_japanese_item_carrying_an_english_card_id_is_surfaced_even_if_resolved():
    """Self-concealment is the reason BLOCKER-1 was rated worst: clearing
    needs_review removes a row from every future page. A non-EN item holding a
    card_id is a contradiction and must stay visible however it got there."""
    item = graded_item("MISLINKED", "Pikachu — jp 151 #173.0",
                       card_id="sv3pt5-173", needs_review=False)
    rows = br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {})
    assert [r["item_id"] for r in rows] == ["MISLINKED"]
    assert rows[0]["confidence"] == "CONTRADICTION"
    assert "sv3pt5-173" in rows[0]["reason"]
    assert rows[0]["priority"] > 0  # ranks at the TOP, not the bottom


def test_an_english_item_that_is_resolved_still_stays_off_the_page():
    item = raw_item("DONE", "Charizard #4.0", card_id="base1-4", needs_review=False)
    assert br.build_card_rows([item], br.CatalogIndex.build(CATALOG), {}) == []


def test_a_japanese_item_without_a_card_id_is_not_a_contradiction():
    item = graded_item("FINE", "Pikachu — jp 151 #173.0", needs_review=False)
    assert br.build_card_rows([item], br.CatalogIndex.build(LIVE_JP_CATALOG), {}) == []


# --- finish-aware pricing: reverse/holo cards must price from their own band -

def mr_mime_two_finishes():
    """One catalog card the sheet carries in two finishes at very different
    prices — exactly the shape that makes a wrong-band price look like a flag."""
    return {
        "entity": "catalog_card", "card_id": "sm-mm", "name": "Mr. Mime",
        "set_id": "sm", "set_name": "Team Up", "number": "11", "rarity": "Rare",
        "types": ["Psychic"],
        "images": {"small": "https://img/mm.png", "large": "https://img/mm_l.png"},
        "prices": {"normal": {"market": Decimal("2.00")},
                   "reverseHolofoil": {"market": Decimal("18.00")}},
        "last_synced_at": "2026-07-01T00:00:00+00:00",
    }


def test_finish_from_source_maps_name_words_to_price_bands():
    assert br.finish_from_source("Mr Mime Reverse", "normal") == "reverseHolofoil"
    assert br.finish_from_source("Dragonite Holo", "normal") == "holofoil"
    assert br.finish_from_source("Charizard", "normal") == "normal"


def test_finish_from_source_does_not_upgrade_a_non_holo():
    """"Non-holo" is the normal print — a "holo" token inside it must not win."""
    assert br.finish_from_source("Charizard Non Holo", "normal") == "normal"


def test_finish_from_source_trusts_an_explicitly_stored_finish():
    """A real finish, once a finish column exists, outranks a guess from the name."""
    assert br.finish_from_source("Pikachu", "reverseHolofoil") == "reverseHolofoil"


def test_predict_value_prices_a_reverse_holo_from_the_reverse_band():
    card = mr_mime_two_finishes()
    item = raw_item("I1", "Mr Mime Reverse #11")   # importer stored finish="normal"
    got = br.predict_value(item, card, [],
                           finish=br.finish_from_source("Mr Mime Reverse", "normal"))
    assert got.value == Decimal("18.00")


def test_build_card_rows_prices_a_reverse_holo_from_its_own_band():
    """The whole point: 'Mr Mime Reverse' listed at the reverse price must NOT be
    flagged for a divergence that only exists because it was priced as normal."""
    index = br.CatalogIndex.build([mr_mime_two_finishes()])
    item = raw_item("I1", "Mr Mime Reverse #11", listed_price=Decimal("18"))
    row = br.build_card_rows([item], index, {})[0]
    assert row["prediction"]["card_id"] == "sm-mm"
    assert row["prediction"]["value"] == "18.00"
    assert not (row["divergence"] and row["divergence"]["flagged"])


def test_build_card_rows_still_flags_a_genuinely_wrong_normal_price():
    """No masking: a plain normal card listed at 9x its price is still flagged."""
    index = br.CatalogIndex.build([mr_mime_two_finishes()])
    item = raw_item("I1", "Mr Mime #11", listed_price=Decimal("18"))
    row = br.build_card_rows([item], index, {})[0]
    assert row["prediction"]["value"] == "2.00"
    assert row["divergence"]["flagged"] is True


# --- curated tail: granular bands, split words, real typos ---------------
# Every case here is a real name pulled from the 1266-card production corpus.

def test_finish_from_source_selects_the_1st_edition_and_unlimited_bands():
    """"1st Edition" and "Unlimited" are DISTINCT tcgplayer price bands — a plain
    holo/reverse map would flatten them onto the wrong price."""
    assert br.finish_from_source("Charizard 1st Edition Holo", "normal") == "1stEditionHolofoil"
    assert br.finish_from_source("Electabuzz 1st Ed Shadowless", "normal") == "1stEditionNormal"
    assert br.finish_from_source("Charizard Base Holo Unlimited", "normal") == "unlimitedHolofoil"


def test_finish_from_source_recovers_a_split_unlimited():
    """Real card: 'Typhlosion un limited Holo' — 'unlimited' typed as two words."""
    assert br.finish_from_source("Typhlosion un limited Holo", "normal") == "unlimitedHolofoil"


def test_finish_from_source_corrects_a_reverse_typo():
    """Real token in the corpus: 'reversese' — a misspelling of 'reverse'."""
    assert br.finish_from_source("Electrike reversese", "normal") == "reverseHolofoil"


def test_predict_value_reports_the_band_it_actually_priced_from():
    """The value carries the band it used, so a caller can tell a verified band
    apart from a fallback substitution."""
    got = br.predict_value(raw_item("I1", "Mr Mime Reverse #11"),
                           mr_mime_two_finishes(), [], finish="reverseHolofoil")
    assert got.value == Decimal("18.00")
    assert got.finish == "reverseHolofoil"


def test_predict_value_falls_back_and_reports_the_substitute_band():
    """Catalog card has only a normal price; a reverse request substitutes it and
    says so, rather than pretending the reverse band existed."""
    card = catalog_card("xy-83", "Dragonite", "XY", "83", market="12.50")  # normal only
    got = br.predict_value(raw_item("I1", "Dragonite Reverse #83"), card, [],
                           finish="reverseHolofoil")
    assert got.value == Decimal("12.50")
    assert got.finish == "normal"


def test_build_card_rows_does_not_caveat_a_verified_reverse_band():
    """When the matched card actually carries the reverse price, the band is
    verified — no caveat, and the false divergence is gone."""
    index = br.CatalogIndex.build([mr_mime_two_finishes()])
    row = br.build_card_rows(
        [raw_item("I1", "Mr Mime Reverse #11", listed_price=Decimal("18"))], index, {})[0]
    assert "finish" not in row["reason"].lower()
    assert not (row["divergence"] and row["divergence"]["flagged"])


def test_build_card_rows_does_not_infer_a_finish_for_a_graded_slab():
    """A graded 'Dragonite-Holo' is priced by grade, not finish — the name's
    'holo' must not trigger a band caveat or repricing."""
    index = br.CatalogIndex.build(CATALOG)
    points = {"xy-83": [{"card_id": "xy-83", "kind": "graded", "company": "PSA",
                         "grade": Decimal("10"), "date": "2026-07-01",
                         "market": Decimal("250.00")}]}
    item = graded_item("I2", "Dragonite-Holo — XY #83.0", listed_price=Decimal("250"))
    row = br.build_card_rows([item], index, points)[0]
    assert "finish" not in row["reason"].lower()
    assert row["prediction"]["value"] == "250.00"


def test_build_card_rows_caveats_a_finish_it_could_not_verify():
    """The card says 'Reverse' but the matched catalog card has no reverse price,
    so the band can't be confirmed — flag it for a human instead of silently
    repricing off the wrong band."""
    index = br.CatalogIndex.build([catalog_card("xy-83", "Dragonite", "XY", "83",
                                                 market="12.50")])  # normal only
    row = br.build_card_rows(
        [raw_item("I1", "Dragonite Reverse #83", listed_price=Decimal("40"))], index, {})[0]
    assert "finish" in row["reason"].lower()


# --- value prediction ----------------------------------------------------

def test_predict_value_prefers_a_dated_price_point():
    card = catalog_card("xy-83", "Dragonite", "XY", "83", market="12.50")
    points = [
        {"card_id": "xy-83", "kind": "raw", "finish": "normal",
         "date": "2026-01-01", "market": Decimal("9.00")},
        {"card_id": "xy-83", "kind": "raw", "finish": "normal",
         "date": "2026-07-01", "market": Decimal("14.25")},
    ]
    got = br.predict_value(raw_item("I1", "Dragonite #83"), card, points)
    assert got.value == Decimal("14.25")
    assert got.basis == "price_point"


def test_predict_value_falls_back_to_the_catalog_price():
    card = catalog_card("xy-83", "Dragonite", "XY", "83", market="12.50")
    got = br.predict_value(raw_item("I1", "Dragonite #83"), card, [])
    assert got.value == Decimal("12.50")
    assert got.basis == "catalog_price"


def test_predict_value_is_none_without_a_matched_card():
    got = br.predict_value(raw_item("I1", "Dragonite #83"), None, [])
    assert got.value is None
    assert got.basis == "none"


def test_predict_value_uses_a_matching_graded_price_point():
    card = catalog_card("xy-83", "Dragonite", "XY", "83", market="12.50")
    points = [{"card_id": "xy-83", "kind": "graded", "company": "PSA",
               "grade": Decimal("10"), "date": "2026-07-01",
               "market": Decimal("250.00")}]
    got = br.predict_value(graded_item("I2", "Dragonite — XY #83"), card, points)
    assert got.value == Decimal("250.00")
    assert got.basis == "price_point_graded"


def test_predict_value_flags_a_raw_only_figure_for_a_slab():
    card = catalog_card("xy-83", "Dragonite", "XY", "83", market="12.50")
    got = br.predict_value(graded_item("I2", "Dragonite — XY #83"), card, [])
    assert got.value == Decimal("12.50")
    assert got.basis == "raw_only"
    assert "raw" in got.note.lower()


# --- divergence ----------------------------------------------------------

def test_value_divergence_flags_a_large_gap_against_listed_price():
    item = raw_item("I1", "x", listed_price=Decimal("20"))
    div = br.value_divergence(Decimal("100"), item)
    assert div["flagged"] is True
    assert div["basis_label"] == "listed_price"
    assert div["delta"] == Decimal("80")


def test_value_divergence_ignores_small_absolute_gaps():
    item = raw_item("I1", "x", listed_price=Decimal("1"))
    assert br.value_divergence(Decimal("3"), item)["flagged"] is False


def test_value_divergence_falls_back_to_market_at_purchase():
    item = raw_item("I1", "x", market_value_at_purchase=Decimal("10"))
    div = br.value_divergence(Decimal("11"), item)
    assert div["basis_label"] == "market_value_at_purchase"
    assert div["flagged"] is False


def test_value_divergence_is_none_without_a_basis():
    assert br.value_divergence(Decimal("11"), raw_item("I1", "x")) is None
    assert br.value_divergence(None, raw_item("I1", "x", listed_price=Decimal("5"))) is None


# --- row assembly + rendering -------------------------------------------

def test_build_card_rows_only_covers_flagged_items():
    index = br.CatalogIndex.build(CATALOG)
    items = [raw_item("I1", "Dragonite-Holo #83.0"),
             raw_item("I2", "Charizard #4.0", needs_review=False)]
    rows = br.build_card_rows(items, index, {})
    assert [r["item_id"] for r in rows] == ["I1"]
    assert rows[0]["prediction"]["card_id"] == "xy-83"
    assert rows[0]["confidence"] in {"HIGH", "MEDIUM", "LOW"}


def test_build_card_rows_orders_undetermined_candidates_by_price_fit():
    """When only the name matched, every printing is an equally good guess by
    identity — so order them by which one costs what the sheet says it did."""
    catalog = [catalog_card("a-1", "Snorlax", "Jungle", "11", market="5.00"),
               catalog_card("b-2", "Snorlax", "Base", "27", market="20.00"),
               catalog_card("c-3", "Snorlax", "Celebrations", "99", market="300.00")]
    index = br.CatalogIndex.build(catalog)
    item = raw_item("I1", "Snorlax #173", listed_price=Decimal("18"))
    row = br.build_card_rows([item], index, {})[0]
    assert row["confidence"] == "LOW"
    assert row["prediction"]["card_id"] == "b-2"
    assert [c["card_id"] for c in row["runners"]] == ["a-1", "c-3"]
    assert "price" in row["reason"].lower()


def test_build_card_rows_keeps_a_determined_match_untouched_by_price():
    """A name + card # match is an identity match; price must not reorder it."""
    index = br.CatalogIndex.build(CATALOG)
    item = raw_item("I1", "Dragonite #83.0", listed_price=Decimal("999"))
    row = br.build_card_rows([item], index, {})[0]
    assert row["prediction"]["card_id"] == "xy-83"
    assert "price" not in row["reason"].lower()


def test_build_card_rows_sorts_worst_first():
    index = br.CatalogIndex.build(CATALOG)
    items = [raw_item("HIGHCONF", "Dragonite #83.0"),
             raw_item("LOWCONF", "Totally Unknown Thing")]
    rows = br.build_card_rows(items, index, {})
    assert rows[0]["item_id"] == "LOWCONF"


def test_render_html_is_self_contained_and_carries_the_rows():
    index = br.CatalogIndex.build(CATALOG)
    rows = br.build_card_rows([raw_item("I1", "Dragonite-Holo #83.0")], index, {})
    html = br.render_html(rows, table_name="merlins-cards",
                          generated_at="2026-07-23T00:00:00")
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html
    assert "I1" in html
    assert "<script src" not in html and "<link " not in html
    assert "MERLIN-REVIEW-V1" in html  # the paste-back legend


def test_render_html_is_card_triage_only_with_no_transaction_section():
    """The sale-date-anomaly section was removed — the page is card-identity
    triage only. No transactions tab, pane, or payload key may survive."""
    html = br.render_html(
        br.build_card_rows([raw_item("I1", "Dragonite-Holo #83.0")],
                           br.CatalogIndex.build(CATALOG), {}),
        table_name="merlins-cards", generated_at="2026-07-23T00:00:00")
    assert "tab-txns" not in html
    assert "txns-pane" not in html
    assert "DATA.txns" not in html
    assert "date anomalies" not in html


def test_the_date_anomaly_backing_code_is_removed_not_orphaned():
    """The dead analysis helpers went out with the section (architect/YAGNI)."""
    for name in ("find_transaction_anomalies", "classify_date_anomaly",
                 "find_placeholder_dates", "DateVerdict"):
        assert not hasattr(br, name), f"{name} should have been removed"


def test_paste_back_binds_the_block_to_its_table_and_snapshot():
    """BLOCKER-D producer side: the page emits the table + snapshot so the applier
    can refuse a block pointed at a different table."""
    html = br.render_html([], table_name="merlins-cards",
                          generated_at="2026-07-23T16:22:48")
    assert '"# table: " + DATA.meta.table' in html
    assert '"# snapshot: " + DATA.meta.generated_at' in html


def test_render_html_has_bulk_approve_and_reject_controls():
    """Approve/Reject-all-shown act on every row the current filters leave
    visible — e.g. filter to HIGH, then approve them all in one click."""
    html = br.render_html([], table_name="t", generated_at="now")
    assert 'id="bulk-accept"' in html
    assert 'id="bulk-reject"' in html
    assert "bulkDecide" in html


def test_render_html_survives_data_that_could_break_out_of_the_script_tag():
    index = br.CatalogIndex.build(CATALOG)
    nasty = raw_item("I1", "</script><script>alert(1)</script> #4.0")
    html = br.render_html(br.build_card_rows([nasty], index, {}),
                          table_name="t", generated_at="now")
    assert "</script><script>alert(1)" not in html


# --- the read path, end to end, against an in-memory table ---------------

def test_scan_and_collect_round_trip(dynamo_repo):
    """The scan path buckets real records the repository wrote (moto, no AWS)."""
    from datetime import datetime, timezone

    from merlins_collection.models.catalog import CatalogCard, PricePoint
    from merlins_collection.models.inventory import RawInventoryItem

    dynamo_repo.batch_upsert_catalog_cards([CatalogCard(
        card_id="xy-83", name="Dragonite", set_id="xy", set_name="XY", number="83",
        images={"small": "https://img/s.png", "large": "https://img/l.png"},
        prices={"normal": {"market": Decimal("12.50")}},
        last_synced_at=datetime.now(tz=timezone.utc))])
    dynamo_repo.append_price_points([PricePoint(
        card_id="xy-83", date=date(2026, 7, 1), source="pokemontcg.io", kind="raw",
        finish="normal", market=Decimal("14.25"))])
    dynamo_repo.put_inventory_item(RawInventoryItem(
        item_id="ITEM1", finish="normal", condition="NM", cost_basis=Decimal("4"),
        listed_price=Decimal("2"), acquired_at=date(2026, 3, 14),
        notes="Dragonite-Holo #83.0", needs_review=True))

    data = br.collect(br.scan_records("merlins-cards-test", "us-east-1"))
    assert len(data["catalog"]) == 1
    assert len(data["inventory"]) == 1
    assert data["prices"]["xy-83"][0]["market"] == Decimal("14.25")

    rows = br.build_card_rows(data["inventory"],
                              br.CatalogIndex.build(data["catalog"]), data["prices"])
    assert rows[0]["prediction"]["card_id"] == "xy-83"
    assert rows[0]["prediction"]["value"] == "14.25"
    assert rows[0]["divergence"]["flagged"] is True


# --- the whole point: this tool must never write to production -----------

FORBIDDEN_APIS = [
    "put_item", "update_item", "delete_item", "batch_writer", "batch_write_item",
    "transact_write_items", "create_table", "update_table", "delete_table",
]


def test_script_contains_no_dynamodb_write_calls():
    source = SCRIPT.read_text(encoding="utf-8")
    offenders = [api for api in FORBIDDEN_APIS if api in source]
    assert offenders == [], f"read-only tool must not reference {offenders}"
