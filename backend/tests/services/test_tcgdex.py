"""TCGdex client + mapper tests. Fixtures are verbatim-shaped real responses.

No test here touches the network: the mappers are pure functions over
``tests/fixtures/tcgdex/*.json`` and the client is driven through
``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from merlins_collection.models.inventory import Language
from merlins_collection.services import tcgdex
from merlins_collection.services.tcgdex import (
    LANGUAGE_API_CODE,
    LANGUAGE_BY_API_CODE,
    MAX_PLAUSIBLE_PRICE,
    TcgdexClient,
    TcgdexError,
    _convert_eur_to_usd,
    _encode_card_id,
    _map_finish,
    _tcgdex_set_id,
    build_card_id,
    parse_card_id,
    to_catalog_card,
    to_catalog_card_brief,
    to_price_points,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tcgdex"
FX = Decimal("1.08")


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# identity helpers (RFC 0003 §3)
# --------------------------------------------------------------------------


def test_card_id_is_language_qualified():
    assert build_card_id(Language.EN, "base1-4") == "en:base1-4"
    assert build_card_id(Language.JP, "M5-001") == "ja:M5-001"
    # A JP card and its EN twin are DISTINCT catalog rows.
    assert build_card_id(Language.EN, "M5-001") != build_card_id(Language.JP, "M5-001")


def test_set_id_is_split_by_local_id_length_not_by_last_hyphen():
    assert _tcgdex_set_id("base1-4", "4") == "base1"
    assert _tcgdex_set_id("exu-!", "!") == "exu"
    assert _tcgdex_set_id("exu-%3F", "%3F") == "exu"
    # a local id that itself contains a hyphen: splitting on "-" would be wrong
    assert _tcgdex_set_id("swsh4-SV1-2", "SV1-2") == "swsh4"


def test_encode_card_id_percent_encodes_every_unsafe_character():
    assert _encode_card_id("base1-4") == "base1-4"
    assert _encode_card_id("exu-!") == "exu-%21"
    # OQ-2 default: the reported id is treated as literal characters.
    assert _encode_card_id("exu-%3F") == "exu-%253F"


# --------------------------------------------------------------------------
# finish mapping (RFC 0003 §6)
# --------------------------------------------------------------------------


def test_map_finish_normalizes_to_the_internal_vocabulary():
    assert _map_finish("normal") == "normal"
    assert _map_finish("holofoil") == "holofoil"
    assert _map_finish("reverse-holofoil") == "reverseHolofoil"


def test_map_finish_camelizes_unknown_keys_instead_of_dropping_them():
    assert _map_finish("first-edition-holofoil") == "firstEditionHolofoil"
    assert _map_finish("mystery") == "mystery"


def test_map_finish_rejects_a_key_that_would_corrupt_the_sort_key():
    with pytest.raises(ValueError):
        _map_finish("weird#finish")


@pytest.mark.parametrize("key", ["", "   ", "-", "__"])
def test_map_finish_rejects_a_key_that_normalizes_to_nothing(key):
    """An empty finish would produce the sort key ``PRICE#RAW##<date>``."""
    with pytest.raises(ValueError):
        _map_finish(key)


def test_convert_eur_to_usd_rounds_to_cents():
    assert _convert_eur_to_usd(Decimal("12.50"), FX) == Decimal("13.50")
    assert _convert_eur_to_usd(Decimal("0.03"), FX) == Decimal("0.03")


# --------------------------------------------------------------------------
# SEC-1 / LOG-1 — every upstream figure is bounded at the mapping boundary
# --------------------------------------------------------------------------


def _tcgplayer_market(raw_value, *, fixture="card_en_base1-4", finish="holofoil"):
    """Map a fixture with one TCGplayer ``marketPrice`` replaced."""
    raw = load(fixture)
    raw["pricing"]["tcgplayer"][finish]["marketPrice"] = raw_value
    return to_catalog_card(raw, Language.EN, fx_rate=FX).prices


@pytest.mark.parametrize(
    "hostile",
    [
        0,            # observed in real Cardmarket responses; renders "$0.00"
        0.0,
        -500,         # would undercut the shop's own listed_price on the tile
        0.004,        # quantizes to $0.00
        1e12,
        float("nan"),
        float("inf"),
        float("-inf"),
        "12345678901234567890123456789012345678901234",  # >38 significant digits
        "N/A",        # decimal.InvalidOperation is an ArithmeticError, not ValueError
        True,         # bool is an int subclass; not a price
    ],
)
def test_an_out_of_band_upstream_figure_is_treated_as_absent(hostile):
    """No band, no clamp, no substitute, and nothing escapes the mapper.

    A rejected figure must fall through to the existing ``needs_review`` path
    rather than reaching ``CardTile``'s ``marketPrice ?? item.listed_price``.
    """
    prices = _tcgplayer_market(hostile)
    assert "holofoil" not in prices


def test_the_ceiling_admits_a_real_grail_and_rejects_the_absurd():
    assert _tcgplayer_market(float(MAX_PLAUSIBLE_PRICE) / 2)["holofoil"].market
    assert "holofoil" not in _tcgplayer_market(str(MAX_PLAUSIBLE_PRICE + 1))


def test_a_zero_cardmarket_trend_falls_through_to_avg7_instead_of_pricing_at_zero():
    """``trend: 0`` is absence wearing a number: it must not stop the chain."""
    raw = load("card_cardmarket_nulls")
    raw["pricing"]["cardmarket"]["trend"] = 0
    band = to_catalog_card(raw, Language.EN, fx_rate=FX).prices["normal"]
    assert band.market == Decimal("10.80")  # avg7 10.00 * 1.08, not $0.00
    assert "cardmarket avg7" in band.value_note


def test_a_sub_cent_cardmarket_figure_emits_no_band():
    raw = load("card_cardmarket_nulls")
    for field in ("trend", "avg7", "avg30", "avg"):
        raw["pricing"]["cardmarket"][field] = 0.004
    assert "normal" not in to_catalog_card(raw, Language.EN, fx_rate=FX).prices


def test_a_hostile_figure_never_reaches_a_price_point():
    raw = load("card_en_base1-4")
    raw["pricing"]["tcgplayer"]["holofoil"]["marketPrice"] = float("nan")
    card = to_catalog_card(raw, Language.EN, fx_rate=FX)
    assert to_price_points(card, date(2026, 7, 26)) == []
    assert card.name == "Charizard"  # the identity row survives


# --------------------------------------------------------------------------
# SEC-2 — the image host is validated at the mapping boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    ["https://evil.attacker.tld/x", "//evil.tld/x", "javascript:alert(1)",
     "http://assets.tcgdex.net/x", "https://assets.tcgdex.net.evil.tld/x", 42],
)
def test_an_image_url_from_an_unexpected_host_is_dropped(hostile):
    """The API hands the raw URL to the MCP server and to Bedrock tool results,
    neither of which has ``next/image``'s host allowlist behind it."""
    raw = load("card_en_base1-4")
    raw["image"] = hostile
    card = to_catalog_card(raw, Language.EN, fx_rate=FX)
    assert card.images.small == "" and card.images.large == ""


# --------------------------------------------------------------------------
# FRAIL-5 — names are NFC-normalized so the JP match key is stable
# --------------------------------------------------------------------------


def test_a_japanese_name_is_nfc_normalized_at_the_boundary():
    """NFD and NFC kana render identically and are not equal in Python; the
    match key is name + number + language, so an NFD row is unmatchable."""
    raw = load("card_ja_M5-001")
    nfd = unicodedata.normalize("NFD", raw["name"])
    assert nfd != raw["name"]  # the fixture really does have a composed form
    raw["name"] = nfd
    assert to_catalog_card(raw, Language.JP, fx_rate=FX).name == "トロピウス"


def test_surrounding_whitespace_is_stripped_from_names():
    raw = load("card_en_base1-4")
    raw["name"] = "  Charizard\n"
    raw["set"]["name"] = " Base Set "
    card = to_catalog_card(raw, Language.EN, fx_rate=FX)
    assert card.name == "Charizard"
    assert card.set_name == "Base Set"


# --------------------------------------------------------------------------
# FRAIL-6 — source_updated_at is timezone-consistent or absent
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-07-20T08:02:22.370Z", datetime(2026, 7, 20, 8, 2, 22, 370000, tzinfo=timezone.utc)),
        ("2026-07-20T09:02:22+01:00", datetime(2026, 7, 20, 8, 2, 22, tzinfo=timezone.utc)),
        ("2026-07-20T08:02:22", datetime(2026, 7, 20, 8, 2, 22, tzinfo=timezone.utc)),
    ],
)
def test_updated_stamps_are_coerced_to_aware_utc(stamp, expected):
    """A naive stamp stored verbatim makes RFC §7's ``now - source_updated_at``
    raise ``TypeError`` at a random card partway through the run."""
    raw = load("card_en_base1-4")
    raw["pricing"]["tcgplayer"]["updated"] = stamp
    band = to_catalog_card(raw, Language.EN, fx_rate=FX).prices["holofoil"]
    assert band.source_updated_at == expected
    assert band.source_updated_at.tzinfo is not None


@pytest.mark.parametrize("stamp", ["2087-01-01T00:00:00Z", "1970-01-01T00:00:00Z", "later"])
def test_an_absurd_or_unparseable_updated_stamp_is_dropped(stamp):
    raw = load("card_en_base1-4")
    raw["pricing"]["tcgplayer"]["updated"] = stamp
    assert to_catalog_card(raw, Language.EN, fx_rate=FX).prices[
        "holofoil"
    ].source_updated_at is None


# --------------------------------------------------------------------------
# to_catalog_card — English (TCGplayer USD path, RFC 0003 §5.1)
# --------------------------------------------------------------------------


def test_english_card_maps_identity_set_and_images():
    card = to_catalog_card(load("card_en_base1-4"), Language.EN, fx_rate=FX,
                           synced_at=datetime(2026, 7, 26, tzinfo=timezone.utc))
    assert card.card_id == "en:base1-4"
    assert card.language is Language.EN
    assert card.name == "Charizard"
    assert card.set_id == "en:base1"
    assert card.set_name == "Base Set"
    assert card.number == "4"
    assert card.rarity == "Rare"
    assert card.types == ["Fire"]
    assert card.images.small == "https://assets.tcgdex.net/en/base/base1/4/low.webp"
    assert card.images.large == "https://assets.tcgdex.net/en/base/base1/4/high.webp"
    assert card.detail == "full"


def test_english_card_prices_come_from_tcgplayer_in_usd():
    card = to_catalog_card(load("card_en_base1-4"), Language.EN, fx_rate=FX)
    band = card.prices["holofoil"]
    assert band.market == Decimal("800.43")
    assert band.low == Decimal("510")
    assert band.mid == Decimal("918.8")
    assert band.high == Decimal("2550.35")
    assert band.currency == "USD"
    assert band.source == "tcgplayer"
    assert band.source_currency == "USD"
    assert band.value_note is None
    assert band.source_updated_at == datetime(
        2026, 7, 26, 8, 2, 22, 370000, tzinfo=timezone.utc
    )


def test_cardmarket_is_ignored_when_tcgplayer_priced_the_card():
    """base1-4 has no normal printing; the Cardmarket flat block must not
    invent a ``normal`` band alongside TCGplayer's holofoil figure."""
    card = to_catalog_card(load("card_en_base1-4"), Language.EN, fx_rate=FX)
    assert set(card.prices) == {"holofoil"}


def test_hyphenated_reverse_holofoil_key_is_normalized():
    card = to_catalog_card(load("card_en_reverse"), Language.EN, fx_rate=FX)
    assert set(card.prices) == {"normal", "reverseHolofoil"}
    assert card.prices["reverseHolofoil"].market == Decimal("0.28")


def test_unknown_finish_key_is_camelized_and_kept():
    card = to_catalog_card(load("card_unknown_finish"), Language.EN, fx_rate=FX)
    assert set(card.prices) == {"firstEditionHolofoil"}
    assert card.prices["firstEditionHolofoil"].market == Decimal("250")


# --------------------------------------------------------------------------
# to_catalog_card — Japanese (Cardmarket EUR path, RFC 0003 §5.2)
# --------------------------------------------------------------------------


def test_japanese_card_maps_identity_with_no_image_and_no_tcgplayer():
    card = to_catalog_card(load("card_ja_M5-001"), Language.JP, fx_rate=FX)
    assert card.card_id == "ja:M5-001"
    assert card.language is Language.JP
    assert card.name == "トロピウス"
    assert card.set_id == "ja:M5"
    assert card.set_name == "アビスアイ"
    assert card.number == "001"
    # the API omitted "image" entirely — empty, never a fabricated URL
    assert card.images.small == ""
    assert card.images.large == ""


def test_japanese_card_prices_convert_from_cardmarket_eur_and_say_so():
    card = to_catalog_card(load("card_ja_M5-001"), Language.JP, fx_rate=FX)
    band = card.prices["normal"]
    assert band.market == Decimal("0.03")  # EUR 0.03 trend * 1.08
    assert band.low == Decimal("0.02")
    assert band.mid == Decimal("0.02")
    assert band.high is None  # Cardmarket publishes no high; never synthesize one
    assert band.currency == "USD"
    assert band.source == "cardmarket"
    assert band.source_currency == "EUR"
    assert band.value_note == (
        "converted from EUR 0.03 (cardmarket trend) at EUR_USD_RATE=1.08"
    )


def test_cardmarket_falls_back_down_the_trend_chain_and_names_the_field():
    card = to_catalog_card(load("card_cardmarket_nulls"), Language.EN, fx_rate=FX)
    normal = card.prices["normal"]
    assert normal.market == Decimal("10.80")  # trend is null -> avg7 (10.00)
    assert normal.low == Decimal("7.83")
    assert normal.mid == Decimal("10.26")
    assert "cardmarket avg7" in normal.value_note


def test_cardmarket_holo_suffixed_fields_map_to_the_holofoil_finish_only():
    card = to_catalog_card(load("card_cardmarket_nulls"), Language.EN, fx_rate=FX)
    assert set(card.prices) == {"normal", "holofoil"}
    assert card.prices["holofoil"].market == Decimal("26.46")  # trend-holo 24.50
    # never guessed onto reverseHolofoil, even though the card has a reverse variant
    assert "reverseHolofoil" not in card.prices


# --------------------------------------------------------------------------
# absent pricing (RFC 0003 §5.3) — must map cleanly, never raise
# --------------------------------------------------------------------------


def test_card_with_no_pricing_block_maps_with_no_prices():
    card = to_catalog_card(load("card_en_no_pricing"), Language.EN, fx_rate=FX)
    assert card.prices == {}
    assert card.card_id == "en:ex12-100"
    assert to_price_points(card, date(2026, 7, 26)) == []


@pytest.mark.parametrize("pricing", [None, {}, {"tcgplayer": None, "cardmarket": None}])
def test_null_or_empty_pricing_blocks_never_raise(pricing):
    raw = load("card_en_base1-4")
    raw["pricing"] = pricing
    assert to_catalog_card(raw, Language.EN, fx_rate=FX).prices == {}


def test_an_unpriced_tcgplayer_block_falls_through_to_cardmarket():
    """TCGplayer listing a finish with no figures at all must not shadow the
    Cardmarket data — that would silently drop the only price we have."""
    raw = load("card_ja_M5-001")
    raw["pricing"]["tcgplayer"] = {
        "unit": "USD", "updated": "2026-07-26T08:02:22.370Z",
        "normal": {"productId": 1, "marketPrice": None, "lowPrice": None,
                   "midPrice": None, "highPrice": None},
    }
    band = to_catalog_card(raw, Language.JP, fx_rate=FX).prices["normal"]
    assert band.source == "cardmarket"


def test_a_partially_populated_tcgplayer_band_does_not_block_the_fallback():
    """LOG-3: ``lowPrice`` with a null ``marketPrice`` is routine for
    thin-liquidity singles. It must not leave the card showing no price while a
    complete Cardmarket figure sits one branch away."""
    raw = load("card_cardmarket_nulls")
    raw["pricing"]["tcgplayer"] = {
        "unit": "USD", "updated": "2026-07-26T08:02:22.370Z",
        "normal": {"marketPrice": None, "lowPrice": 0.11},
    }
    band = to_catalog_card(raw, Language.EN, fx_rate=FX).prices["normal"]
    assert band.source == "cardmarket"
    assert band.market == Decimal("10.80")


def test_a_market_less_band_is_never_stored_or_written_to_history():
    """It costs a write, renders nothing, and ``build_review._latest`` drops it."""
    raw = load("card_en_no_pricing")
    raw["pricing"] = {"tcgplayer": {
        "unit": "USD", "normal": {"marketPrice": None, "lowPrice": 0.11},
    }}
    card = to_catalog_card(raw, Language.EN, fx_rate=FX)
    assert card.prices == {}
    assert to_price_points(card, date(2026, 7, 26)) == []


def test_a_non_price_object_in_the_tcgplayer_block_is_not_read_as_a_finish():
    raw = load("card_en_base1-4")
    raw["pricing"]["tcgplayer"]["meta"] = {"note": "not a price band"}
    assert set(to_catalog_card(raw, Language.EN, fx_rate=FX).prices) == {"holofoil"}


def test_a_relabelled_currency_costs_that_provider_its_bands_and_nothing_else():
    """LOG-6: the guard stays hard — a non-USD ``unit`` never becomes a price —
    but it is scoped, so a broken TCGplayer block does not discard a valid EUR
    block, and never takes the card's identity with it."""
    raw = load("card_cardmarket_nulls")
    raw["pricing"]["tcgplayer"] = dict(raw["pricing"]["cardmarket"], unit="GBP")
    card = to_catalog_card(raw, Language.EN, fx_rate=FX)
    assert card.prices["normal"].source == "cardmarket"


def test_a_card_whose_price_mapping_fails_entirely_still_maps_its_identity():
    raw = load("card_cardmarket_nulls")
    raw["pricing"] = {
        "tcgplayer": dict(raw["pricing"]["cardmarket"], unit="GBP"),
        "cardmarket": dict(raw["pricing"]["cardmarket"], unit="GBP"),
    }
    card = to_catalog_card(raw, Language.EN, fx_rate=FX)
    assert card.prices == {}
    assert card.card_id == "en:sv09-045" and card.name


def test_a_bad_unit_never_silently_relabels_a_figure_as_usd():
    raw = load("card_cardmarket_nulls")
    raw["pricing"] = {"cardmarket": dict(raw["pricing"]["cardmarket"], unit="GBP")}
    assert to_catalog_card(raw, Language.EN, fx_rate=FX).prices == {}


# --------------------------------------------------------------------------
# LOG-4 — a Cardmarket band is only emitted for a printing that exists
# --------------------------------------------------------------------------


def test_cardmarket_never_invents_a_band_for_a_printing_the_card_does_not_have():
    """The whole JP path has ``tcgplayer: null``, so the unsuffixed (print-
    agnostic) Cardmarket fields would otherwise manufacture a ``normal`` band on
    a holo-only card — and ``normal`` is first in both ``_MARKET_FINISH_FALLBACK``
    and ``FINISH_PREFERENCE``, so the phantom wins every fallback and satisfies
    (silences) ``build_review._finish_caveat``."""
    raw = load("card_ja_M5-001")
    raw["variants"] = {"normal": False, "holo": True, "reverse": False}
    raw["pricing"]["cardmarket"].update({"trend-holo": 5.00, "low-holo": 4.00})
    assert raw["pricing"]["tcgplayer"] is None
    assert set(to_catalog_card(raw, Language.JP, fx_rate=FX).prices) == {"holofoil"}


def test_cardmarket_emits_no_band_when_variants_cannot_confirm_the_printing():
    raw = load("card_ja_M5-001")
    del raw["variants"]
    assert to_catalog_card(raw, Language.JP, fx_rate=FX).prices == {}


def test_tcgplayer_bands_are_not_gated_on_variants():
    """TCGplayer names the finish it is quoting, so it needs no corroboration."""
    raw = load("card_en_base1-4")
    raw["variants"] = {"normal": False, "holo": False, "reverse": False}
    assert set(to_catalog_card(raw, Language.EN, fx_rate=FX).prices) == {"holofoil"}


# --------------------------------------------------------------------------
# brief mapping (list endpoint) + the language/card_id invariant
# --------------------------------------------------------------------------


def test_brief_rows_map_without_prices_and_derive_set_id_by_length():
    briefs = load("cards_en_brief")
    cards = [to_catalog_card_brief(b, Language.EN) for b in briefs]
    by_id = {c.card_id: c for c in cards}
    assert set(by_id) == {"en:base1-4", "en:exu-!", "en:exu-%3F", "en:sv09-045"}
    assert by_id["en:exu-!"].set_id == "en:exu"
    assert by_id["en:exu-!"].number == "!"
    assert by_id["en:exu-!"].images.small == ""  # no "image" key on this row
    assert all(c.prices == {} and c.detail == "brief" for c in cards)


def test_japanese_brief_rows_map_without_images():
    cards = [to_catalog_card_brief(b, Language.JP) for b in load("cards_ja_brief")]
    assert [c.card_id for c in cards] == ["ja:M5-001", "ja:M5-002", "ja:SV11B-097"]
    assert cards[0].images.small == ""
    assert cards[2].images.large.endswith("/high.webp")


@pytest.mark.parametrize(
    "fixture,language",
    [
        ("card_en_base1-4", Language.EN),
        ("card_en_reverse", Language.EN),
        ("card_en_no_pricing", Language.EN),
        ("card_cardmarket_nulls", Language.EN),
        ("card_unknown_finish", Language.EN),
        ("card_ja_M5-001", Language.JP),
    ],
)
def test_stored_language_always_agrees_with_the_card_id_prefix(fixture, language):
    card = to_catalog_card(load(fixture), language, fx_rate=FX)
    assert card.language is language
    assert card.card_id == build_card_id(language, load(fixture)["id"])


def test_a_zero_local_id_is_kept_rather_than_falsily_dropped():
    card = to_catalog_card_brief({"id": "sv09-0", "localId": 0, "name": "Zero"},
                                 Language.EN)
    assert card.number == "0"
    assert card.set_id == "en:sv09"


# --------------------------------------------------------------------------
# to_price_points — provenance survives onto the history row
# --------------------------------------------------------------------------


def test_price_points_carry_currency_and_provenance():
    card = to_catalog_card(load("card_ja_M5-001"), Language.JP, fx_rate=FX)
    (point,) = to_price_points(card, date(2026, 7, 26))
    assert point.card_id == "ja:M5-001"
    assert point.date == date(2026, 7, 26)
    assert point.kind == "raw"
    assert point.finish == "normal"
    assert point.source == "cardmarket"
    assert point.currency == "USD"
    assert point.source_currency == "EUR"
    assert point.market == Decimal("0.03")
    assert "EUR_USD_RATE=1.08" in point.value_note


def test_price_points_from_tcgplayer_have_no_conversion_note():
    card = to_catalog_card(load("card_en_base1-4"), Language.EN, fx_rate=FX)
    (point,) = to_price_points(card, date(2026, 7, 26))
    assert point.source == "tcgplayer"
    assert point.currency == "USD"
    assert point.source_currency == "USD"
    assert point.value_note is None


# --------------------------------------------------------------------------
# TcgdexClient — httpx.MockTransport, no network
# --------------------------------------------------------------------------


def _client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url=TcgdexClient.BASE_URL)
    kwargs.setdefault("request_delay_seconds", 0)
    return TcgdexClient(client=http, backoff_base=0, **kwargs)


def test_get_card_url_encodes_the_id_exactly_once_per_path_segment():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"id": "exu-!"})

    client = _client(handler)
    client.get_card(Language.EN, "exu-!")
    client.get_card(Language.JP, "exu-%3F")
    assert seen == ["/v2/en/cards/exu-%21", "/v2/ja/cards/exu-%253F"]


def test_get_card_returns_the_bare_object():
    body = load("card_en_base1-4")
    assert _client(lambda r: httpx.Response(200, json=body)).get_card(
        Language.EN, "base1-4"
    ) == body


def test_get_card_404_returns_none():
    client = _client(lambda r: httpx.Response(404, json={}))
    assert client.get_card(Language.EN, "nope") is None


def test_get_card_retries_on_5xx():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"id": "z"})

    assert _client(handler, max_retries=3).get_card(Language.EN, "z") == {"id": "z"}
    assert calls["n"] == 2


def test_get_card_4xx_raises():
    with pytest.raises(TcgdexError):
        _client(lambda r: httpx.Response(400, json={})).get_card(Language.EN, "bad")


def test_iter_brief_cards_yields_a_bare_array_and_stops_on_an_empty_page():
    pages = {1: [{"id": "a"}, {"id": "b"}], 2: [{"id": "c"}]}

    def handler(request):
        page = int(request.url.params["pagination:page"])
        return httpx.Response(200, json=pages.get(page, []))

    client = _client(handler, page_size=2)
    assert [c["id"] for c in client.iter_brief_cards(Language.EN)] == ["a", "b", "c"]


def test_a_server_side_page_cap_does_not_silently_truncate_the_catalog():
    """LOG-2: the RFC's own risk table rates a server-side ``itemsPerPage`` cap
    Medium. Under the old short-page sentinel this returned 2 of 5 cards and
    exited 0, and the symptom presented as 'the matcher got worse'."""
    rows = [{"id": str(n)} for n in range(5)]
    cap = 2

    def handler(request):
        page = int(request.url.params["pagination:page"])
        return httpx.Response(200, json=rows[(page - 1) * cap: page * cap])

    client = _client(handler, page_size=100_000)
    assert [c["id"] for c in client.iter_brief_cards(Language.EN)] == ["0", "1", "2", "3", "4"]


def test_a_single_spurious_empty_page_is_confirmed_before_ending_the_walk():
    """LOGIC-1: one ``200 []`` is one untrusted response, not proof the catalog
    ended. A transient blank page mid-walk used to terminate iteration cleanly,
    so the seed committed a truncated generation and exited 0 — the same
    "the matcher got worse, not the seed stopped" symptom the empty-page
    sentinel was introduced to kill."""
    pages = {1: [{"id": "a"}], 2: [{"id": "b"}]}
    blanked = {"done": False}

    def handler(request):
        page = int(request.url.params["pagination:page"])
        if page == 2 and not blanked["done"]:
            blanked["done"] = True
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=pages.get(page, []))

    client = _client(handler, page_size=1)
    assert [c["id"] for c in client.iter_brief_cards(Language.EN)] == ["a", "b"]


def test_a_genuinely_empty_page_still_ends_the_walk_after_confirmation():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        page = int(request.url.params["pagination:page"])
        return httpx.Response(200, json=[{"id": "a"}] if page == 1 else [])

    client = _client(handler, page_size=1)
    assert [c["id"] for c in client.iter_brief_cards(Language.EN)] == ["a"]
    assert calls["n"] == 3  # page 1, page 2, page 2 confirmed


def test_a_server_that_ignores_the_page_parameter_aborts_instead_of_looping():
    """The inverse failure: an unbounded DynamoDB write bill on a third-party
    trigger, re-yielding the same rows forever."""
    client = _client(lambda r: httpx.Response(200, json=[{"id": "a"}, {"id": "b"}]),
                     page_size=2)
    with pytest.raises(TcgdexError, match="pagination"):
        list(client.iter_brief_cards(Language.EN))


def test_iter_brief_cards_stops_at_the_hard_page_ceiling():
    counter = {"n": 0}

    def handler(request):
        counter["n"] += 1
        return httpx.Response(200, json=[{"id": f"card-{counter['n']}"}])

    client = _client(handler, page_size=1, max_pages=3)
    with pytest.raises(TcgdexError, match="page ceiling"):
        list(client.iter_brief_cards(Language.EN))
    assert counter["n"] == 3


def test_iter_brief_cards_requests_the_language_path_and_page_size():
    seen = []

    def handler(request):
        seen.append((request.url.raw_path.decode(), dict(request.url.params)))
        return httpx.Response(200, json=[])

    list(_client(handler, page_size=100).iter_brief_cards(Language.JP))
    path, params = seen[0]
    assert path.startswith("/v2/ja/cards")
    assert params["pagination:itemsPerPage"] == "100"


def test_list_sets_returns_the_bare_array():
    body = [{"id": "base1", "name": "Base Set"}]
    client = _client(lambda r: httpx.Response(200, json=body))
    assert client.list_sets(Language.EN) == body


# --------------------------------------------------------------------------
# FRAIL-1 / FRAIL-8 — transport failures stay inside the retry contract
# --------------------------------------------------------------------------


def test_a_200_that_is_not_json_is_retried_and_then_raises_tcgdex_error():
    """A Cloudflare interstitial is the single most common way a free API fails
    without failing. ``JSONDecodeError`` subclasses ``ValueError``, not
    ``httpx.HTTPError``, so it used to escape every ``except TcgdexError``."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, text="<html>just a moment…</html>",
                              headers={"content-type": "text/html"})

    with pytest.raises(TcgdexError):
        _client(handler, max_retries=3).get_card(Language.EN, "base1-4")
    assert calls["n"] == 3  # the most retryable failure there is got retried


def test_a_truncated_200_recovers_on_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text='{"id": "base1-')
        return httpx.Response(200, json={"id": "base1-4"})

    assert _client(handler).get_card(Language.EN, "base1-4") == {"id": "base1-4"}


def test_an_oversized_response_body_is_refused_rather_than_buffered():
    handler = lambda r: httpx.Response(200, json=[{"id": "x" * 1000}])  # noqa: E731
    with pytest.raises(TcgdexError):
        _client(handler, max_response_bytes=64).list_sets(Language.EN)


def test_retry_after_is_honored_on_a_429(monkeypatch):
    slept = []
    monkeypatch.setattr(tcgdex.time, "sleep", slept.append)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"id": "z"})

    assert _client(handler).get_card(Language.EN, "z") == {"id": "z"}
    assert any(7 <= s <= 9 for s in slept), slept  # honored, with jitter on top


def test_the_default_client_disables_redirects_explicitly():
    """Verified correct today only by httpx's default, which an upgrade could flip."""
    with TcgdexClient() as client:
        assert client._client.follow_redirects is False


def test_language_api_codes_are_the_two_supported_languages():
    assert LANGUAGE_API_CODE == {Language.EN: "en", Language.JP: "ja"}


# ---------------------------------------------------------------------------
# parse_card_id / LANGUAGE_BY_API_CODE
#
# The inverse of `build_card_id`, and the only place a stored `card_id` is taken
# apart to rebuild a request path. The depth pass calls it once per held card
# every morning, so its `None` contract is load-bearing, not decorative.
# ---------------------------------------------------------------------------


def test_language_by_api_code_is_the_exact_inverse_of_language_api_code():
    assert LANGUAGE_BY_API_CODE == {"en": Language.EN, "ja": Language.JP}


def test_parse_card_id_round_trips_build_card_id_for_every_supported_language():
    for language in LANGUAGE_API_CODE:
        assert parse_card_id(build_card_id(language, "swsh4-SV1-2")) == (
            language, "swsh4-SV1-2"
        )


def test_parse_card_id_splits_on_the_first_colon_only():
    """The language code is the HEAD; a TCGdex id may itself contain a colon."""
    assert parse_card_id("en:a:b") == (Language.EN, "a:b")


@pytest.mark.parametrize("card_id", [
    "xy7-54",      # a dead pokemontcg.io-era row -- the live hazard this guards
    "",            # nothing at all
    ":",           # a separator with neither code nor id
    "en:",         # a language, no id
    ":base1-4",    # an id, no language code
    "fr:xy7-54",   # a real language this build does not speak
    "EN:base1-4",  # the enum's NAME, not the API code: deliberately not accepted
])
def test_parse_card_id_returns_none_for_anything_that_is_not_a_composite_id(card_id):
    """`None`, never an exception: a pocket of malformed stored ids is a
    stored-data defect for the caller to count, not a reason to unwind a batch
    job that is otherwise running perfectly."""
    assert parse_card_id(card_id) is None


# ---------------------------------------------------------------------------
# `rarity` / `types` cross the same text boundary as `name` / `set_name`
# ---------------------------------------------------------------------------


def test_rarity_and_types_go_through_the_same_text_boundary_as_name():
    """`_text` is this module's declared normalize-here-and-nowhere-else
    boundary. `rarity` and `types` are upstream-controlled text exactly like
    `name`, and this is the first production path that populates `rarity`."""
    nfd_rarity = unicodedata.normalize("NFD", "  レアプ  ")
    nfd_type = unicodedata.normalize("NFD", " プサイキック ")

    card = to_catalog_card(
        {"id": "swsh1-1", "localId": "1", "name": "x",
         "set": {"id": "swsh1", "name": "S&S"},
         "rarity": nfd_rarity, "types": [nfd_type]},
        Language.JP, fx_rate=FX,
    )

    assert card.rarity == unicodedata.normalize("NFC", "レアプ")
    assert card.rarity != nfd_rarity  # i.e. it did not pass through untouched
    assert card.types == [unicodedata.normalize("NFC", "プサイキック")]


def test_an_absent_rarity_stays_none_rather_than_becoming_empty_text():
    card = to_catalog_card(
        {"id": "swsh1-1", "localId": "1", "name": "x",
         "set": {"id": "swsh1", "name": "S&S"}},
        Language.EN, fx_rate=FX,
    )
    assert card.rarity is None
    assert card.types == []


def test_a_non_list_types_field_is_refused_rather_than_split_into_characters():
    """Guard on the normalization itself: iterating a bare string would turn
    `"Grass"` into five single-character types and validate cleanly."""
    with pytest.raises(ValueError):
        to_catalog_card(
            {"id": "swsh1-1", "localId": "1", "name": "x",
             "set": {"id": "swsh1", "name": "S&S"}, "types": "Grass"},
            Language.EN, fx_rate=FX,
        )
