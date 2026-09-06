from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConditionModifier,
    ConsignmentTerms,
    GradedInventoryItem,
    GradingCompany,
    InventoryItemAdapter,
    ItemStatus,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


def _base(**over):
    kw = dict(cost_basis=Decimal("10.00"), acquired_at=date(2026, 1, 5))
    kw.update(over)
    return kw


def test_raw_item_defaults_and_new_fields():
    item = RawInventoryItem(**_base(finish="holofoil", condition="LP",
                                    condition_modifier="+", factory_sealed=True))
    assert item.kind == "raw"
    assert item.card_id is None
    assert item.status is ItemStatus.AVAILABLE
    assert item.condition_modifier is ConditionModifier.PLUS
    assert item.factory_sealed is True
    assert item.listed_price is None
    assert item.consignment is None
    assert item.needs_review is False
    assert len(item.item_id) == 26  # ULID


def test_item_ids_are_unique():
    a = RawInventoryItem(**_base(finish="normal", condition="NM"))
    b = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert a.item_id != b.item_id


def test_raw_item_parses_via_adapter():
    item = InventoryItemAdapter.validate_python(
        {
            "kind": "raw",
            "card_id": "swsh1-1",
            "listed_price": Decimal("10"),
            "cost_basis": Decimal("4"),
            "acquired_at": date(2026, 1, 1),
            "finish": "holofoil",
            "condition": "NM",
        }
    )
    assert isinstance(item, RawInventoryItem)
    assert item.condition is Condition.NM
    assert item.current_market_value is None


def test_graded_item_parses_via_adapter():
    item = InventoryItemAdapter.validate_python(
        {
            "kind": "graded",
            "card_id": "swsh1-1",
            "listed_price": Decimal("600"),
            "cost_basis": Decimal("300"),
            "acquired_at": date(2026, 1, 1),
            "company": "PSA",
            "grade": Decimal("10"),
            "cert_number": "12345678",
        }
    )
    assert isinstance(item, GradedInventoryItem)
    assert item.grade == Decimal("10")
    assert item.company is GradingCompany.PSA


def test_sealed_and_bulk_kinds_round_trip_through_adapter():
    sealed = SealedInventoryItem(**_base(product_name="Evolving Skies Booster Box",
                                         product_type="booster_box"))
    bulk = BulkInventoryItem(**_base(description="5k common/uncommon lot"))
    assert sealed.product_type is SealedProductType.BOOSTER_BOX
    for item in (sealed, bulk):
        again = InventoryItemAdapter.validate_python(item.model_dump(mode="python"))
        assert again == item


def test_consignment_terms_attach_to_any_kind():
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"),
                             minimum_price=Decimal("50.00"))
    item = GradedInventoryItem(**_base(company="PSA", grade=Decimal("10"),
                                       cert_number="123", consignment=terms))
    assert item.consignment.paid_out is False
    assert item.consignment.split_percent == Decimal("20")


def test_quantity_field_is_gone():
    item = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert not hasattr(item, "quantity")


def test_invalid_condition_modifier_rejected():
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(finish="normal", condition="NM",
                                 condition_modifier="++"))


# ---- print language (part of a card's identity, not a label) ----

def test_language_defaults_to_english():
    item = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert item.language is Language.EN


def test_language_is_shared_by_every_item_kind():
    """A Japanese slab is as real as a Japanese single, so ``language`` lives on
    the shared base rather than only on raw cards."""
    kinds = [
        RawInventoryItem(**_base(finish="normal", condition="NM", language="JP")),
        GradedInventoryItem(**_base(company="PSA", grade=Decimal("10"),
                                    cert_number="123", language="JP")),
        SealedInventoryItem(**_base(product_name="Booster Box",
                                    product_type="booster_box", language="JP")),
        BulkInventoryItem(**_base(description="5k lot", language="JP")),
    ]
    assert [item.language for item in kinds] == [Language.JP] * 4


def test_records_written_before_the_language_field_read_as_english():
    """The 1489 live records carry no ``language`` attribute; they must validate
    as English rather than blow up (this is what makes the field migration-free)."""
    item = InventoryItemAdapter.validate_python(
        {"kind": "raw", "cost_basis": Decimal("4"), "acquired_at": date(2026, 1, 1),
         "finish": "normal", "condition": "NM"}
    )
    assert item.language is Language.EN


def test_language_round_trips_through_the_adapter():
    item = InventoryItemAdapter.validate_python(
        {"kind": "raw", "cost_basis": Decimal("4"), "acquired_at": date(2026, 1, 1),
         "finish": "normal", "condition": "NM", "language": "JP"}
    )
    assert item.language is Language.JP
    assert item.model_dump(mode="python")["language"] is Language.JP


def test_unknown_language_is_rejected():
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(finish="normal", condition="NM", language="KLINGON"))


def test_adapter_rejects_raw_missing_fields():
    with pytest.raises(ValidationError):
        InventoryItemAdapter.validate_python(
            {"kind": "raw", "card_id": "x",
             "listed_price": Decimal("1"), "cost_basis": Decimal("1"),
             "acquired_at": "2026-01-01"}
        )


# --- A: market price surfaced on the tile via CardSummary ----------------------

def _catalog_with_prices(prices):
    from datetime import datetime, timezone
    from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
    return CatalogCard(
        card_id="sv1-1", name="Sprigatito", set_id="sv1", set_name="Scarlet & Violet",
        number="1", images=CardImages(small="s", large="l"),
        prices={k: FinishPrice(market=Decimal(v)) for k, v in prices.items()},
        last_synced_at=datetime.now(timezone.utc),
    )


def test_card_summary_market_price_prefers_the_items_finish():
    from merlins_collection.models.inventory import CardSummary
    card = _catalog_with_prices({"normal": "3.50", "holofoil": "40.00"})
    assert CardSummary.from_catalog(card, finish="holofoil").market_price == Decimal("40.00")
    assert CardSummary.from_catalog(card, finish="normal").market_price == Decimal("3.50")


def test_card_summary_market_price_falls_back_when_the_finish_has_no_price():
    from merlins_collection.models.inventory import CardSummary
    # Holo-only card: the item's finish is "normal" but only a holo price exists.
    card = _catalog_with_prices({"holofoil": "40.00"})
    assert CardSummary.from_catalog(card, finish="normal").market_price == Decimal("40.00")


def test_card_summary_market_price_is_none_when_catalog_has_no_prices():
    from merlins_collection.models.inventory import CardSummary
    assert CardSummary.from_catalog(_catalog_with_prices({}), finish="normal").market_price is None


def test_card_summary_market_price_absent_without_a_finish_is_none_for_graded():
    """The catalog price is an UNGRADED figure, so a graded slab (no finish)
    gets no market price and the caller keeps the slab's own value (A)."""
    from merlins_collection.models.inventory import CardSummary
    card = _catalog_with_prices({"normal": "3.50"})
    assert CardSummary.from_catalog(card, finish=None).market_price is None


# --- 2.3: combined condition string -> (tier, modifier) -----------------------

@pytest.mark.parametrize(
    "raw,tier,mod",
    [
        ("LP+", "LP", "+"),
        ("LP-", "LP", "-"),
        ("NM", "NM", None),
        ("lp+", "LP", "+"),
        ("  MP-  ", "MP", "-"),
        ("dmg", "DMG", None),
    ],
)
def test_normalize_condition(raw, tier, mod):
    """The server-side mirror of the frontend ``parseCondition`` helper."""
    from merlins_collection.models.inventory import normalize_condition

    condition, modifier = normalize_condition(raw)
    assert condition is Condition(tier)
    if mod is None:
        assert modifier is None
    else:
        assert modifier is ConditionModifier(mod)


@pytest.mark.parametrize("bad", ["SHINY", "", "+", "-", "NM++", "LP*", None])
def test_normalize_condition_rejects_garbage(bad):
    from merlins_collection.models.inventory import normalize_condition

    with pytest.raises(ValueError):
        normalize_condition(bad)


# --- T10: display_name_override (admin-authored customer-facing name) ---------
# docs/plans/rfc-0008/t10-jp-english-names.md. An admin-typed name that outranks
# the catalog name at render time, so a Japanese card whose catalog row is in
# Japanese script can be shown to customers in English. Distinct from
# ``display_name`` (materialized at import, never edited) — nothing in the sync
# or import path writes the override, so no sync can clobber a typed name.

def test_display_name_override_defaults_to_none_when_absent_from_stored_row():
    """Migration safety: every row written before this field existed lacks the
    key entirely. Reading one back must yield None, not blow up."""
    stored = {
        "kind": "raw",
        "item_id": "01JLEGACYROWNOOVERRIDE00001",
        "card_id": "ja:M4-084",
        "cost_basis": "10.00",
        "acquired_at": "2026-01-05",
        "finish": "holofoil",
        "condition": "NM",
    }
    assert "display_name_override" not in stored
    item = InventoryItemAdapter.validate_python(stored)
    assert item.display_name_override is None


def test_display_name_override_round_trips_on_every_kind():
    """It lives on _ItemBase, so a sealed/bulk item can carry one too — an
    admin correcting a product name is the same action as correcting a card."""
    raw = RawInventoryItem(**_base(finish="holofoil", condition="NM",
                                   display_name_override="Chespin"))
    sealed = SealedInventoryItem(**_base(product_name="日本語の箱",
                                         product_type=SealedProductType.ETB,
                                         display_name_override="Japanese ETB"))
    assert raw.display_name_override == "Chespin"
    assert sealed.display_name_override == "Japanese ETB"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_display_name_override_blank_is_stored_as_none(blank):
    """Clearing the box in the admin UI sends "" — that must CLEAR the override,
    not store an empty string that renders as a nameless tile."""
    item = RawInventoryItem(**_base(finish="holofoil", condition="NM",
                                    display_name_override=blank))
    assert item.display_name_override is None


def test_display_name_override_is_trimmed():
    item = RawInventoryItem(**_base(finish="holofoil", condition="NM",
                                    display_name_override="  Chespin  "))
    assert item.display_name_override == "Chespin"


def test_display_name_override_rejects_over_length_input():
    """It reaches customers, so it is bounded like the search name parameter."""
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(finish="holofoil", condition="NM",
                                 display_name_override="x" * 201))


# --- RFC 0009 T1: slab cert-verification fields ---------------------------
#
# All four are OPTIONAL, and that is a correctness requirement rather than a
# style choice: every graded row already in the live table predates them, and a
# required field would fail validation on all of them at deploy.


def _graded(**over):
    kw = _base(company=GradingCompany.PSA, grade=Decimal("10"),
               cert_number="12345678")
    kw.update(over)
    return kw


def test_graded_item_without_cert_fields_validates_with_all_none():
    """The live-data compatibility test: an existing slab row carries none of
    the four new fields and must keep validating."""
    item = InventoryItemAdapter.validate_python({
        "kind": "graded", "company": "PSA", "grade": Decimal("10"),
        "cert_number": "12345678", "cost_basis": Decimal("300"),
        "acquired_at": date(2026, 1, 1),
    })
    assert item.grade_label is None
    assert item.cert_verified_at is None
    assert item.cert_image_url is None
    assert item.price_source_id is None


def test_graded_cert_fields_round_trip():
    item = GradedInventoryItem(**_graded(
        grade_label="GEM MT 10",
        cert_verified_at=datetime(2026, 8, 7, 12, 30),
        cert_image_url="https://images.psacard.com/x.jpg",
        price_source_id="tcg-12345",
    ))
    assert item.grade_label == "GEM MT 10"
    assert item.cert_verified_at == datetime(2026, 8, 7, 12, 30)
    assert item.cert_image_url == "https://images.psacard.com/x.jpg"
    assert item.price_source_id == "tcg-12345"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)",
    "\tjava\nscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "//evil.example.com/x.jpg",     # protocol-relative: scheme is whatever the page is
    "https:///x.jpg",               # no host
    "vbscript:msgbox(1)",
])
def test_cert_image_url_rejects_non_http_schemes(url):
    """It is PROVIDER-SUPPLIED and rendered in the admin UI. The codebase already
    carries one finding for ``tcg_url`` accepting a ``javascript:`` URI; this is
    the field that does not repeat it."""
    with pytest.raises(ValidationError):
        GradedInventoryItem(**_graded(cert_image_url=url))


@pytest.mark.parametrize("url", [
    "https://images.psacard.com/x.jpg",
    "http://images.psacard.com/x.jpg",
    "HTTPS://images.psacard.com/x.jpg",
    "  https://images.psacard.com/x.jpg  ",
])
def test_cert_image_url_accepts_http_and_https(url):
    item = GradedInventoryItem(**_graded(cert_image_url=url))
    assert item.cert_image_url == url.strip()


@pytest.mark.parametrize("blank", ["", "   "])
def test_cert_image_url_blank_is_none(blank):
    """A provider that returns an empty string means "no image", not a URL."""
    assert GradedInventoryItem(**_graded(cert_image_url=blank)).cert_image_url is None


def test_grade_label_and_price_source_id_are_bounded():
    """Both ride into a DynamoDB item with a 400 KB ceiling, and both are
    provider-supplied rather than typed by us."""
    with pytest.raises(ValidationError):
        GradedInventoryItem(**_graded(grade_label="x" * 51))
    with pytest.raises(ValidationError):
        GradedInventoryItem(**_graded(price_source_id="x" * 101))


def test_cert_lookup_failed_is_a_machine_review_reason():
    """A slab that PSA could not verify goes to Triage by AUTOMATION, so its
    reason has to be in the machine vocabulary or the re-flag guard treats it as
    an admin's own note and stops protecting a reviewed item."""
    from merlins_collection.models.inventory import MACHINE_REVIEW_REASONS

    assert "cert_lookup_failed" in MACHINE_REVIEW_REASONS


# ===========================================================================
# RFC 0011 T5 — the `no_catalog_match` invariant
# ===========================================================================

def _raw_unmatched(**over):
    kw = _base(finish="normal", condition="NM", card_id=None)
    kw.update(over)
    return RawInventoryItem(**kw)


class TestUnmatchedInvariant:
    """``no_catalog_match=True`` implies ``card_id is None``.

    Allowing both creates a row that is simultaneously in Triage's "no catalog
    link" reason and in the queue that exists to hold cards which have no link —
    two answers to one question, which is the state this feature removes.
    """

    def test_cannot_park_an_item_that_still_has_a_card_id(self):
        with pytest.raises(ValidationError, match="unlink the card first"):
            _raw_unmatched(card_id="en:base1-4", no_catalog_match=True)

    def test_parking_an_unlinked_item_is_fine(self):
        assert _raw_unmatched(no_catalog_match=True).no_catalog_match is True

    def test_a_graded_slab_can_be_parked_too(self):
        """Graded cards carry a ``card_id`` and are the harder half of the
        unmatched problem — a JP slab has no ``externalCatalogId`` at all."""
        item = GradedInventoryItem(**_base(
            card_id=None, company=GradingCompany.PSA, grade=Decimal("9"),
            cert_number="12345678", no_catalog_match=True,
        ))
        assert item.no_catalog_match is True

    def test_the_flag_defaults_off_and_carries_no_timestamp(self):
        """Nothing is backfilled. A row written before these fields existed
        loads as un-parked, which is what makes the queue ship empty."""
        item = _raw_unmatched()
        assert item.no_catalog_match is False
        assert item.no_catalog_match_at is None

    def test_no_catalog_match_is_not_a_customer_field(self):
        """INTERNAL, same rule as ``review_reason``. A customer has no use for
        our cataloguing backlog."""
        from merlins_collection.routers.inventory import _CUSTOMER_ITEM_FIELDS

        assert "no_catalog_match" not in _CUSTOMER_ITEM_FIELDS
        assert "no_catalog_match_at" not in _CUSTOMER_ITEM_FIELDS


# ===========================================================================
# RFC 0023 T1 — Language grows to 18 codes + OTHER, and `language_note`
# ===========================================================================


def test_language_gains_sixteen_new_members_plus_other():
    """The no-migration guarantee: EN/JP keep their stored values, and a
    hand-typed nonsense code still raises rather than silently coercing."""
    assert Language.EN == "EN"
    assert Language.JP == "JP"
    assert Language("KO") is Language.KO
    assert Language("ZH-TW") is Language.ZH_TW
    assert Language("OTHER") is Language.OTHER
    with pytest.raises(ValueError):
        Language("KLINGON")


def test_a_stored_en_row_from_before_this_change_still_validates():
    """No migration, no backfill — every existing row is EN or JP."""
    item = InventoryItemAdapter.validate_python({
        "kind": "raw", "card_id": "en:base1-4", "cost_basis": Decimal("4"),
        "acquired_at": date(2025, 1, 1), "finish": "holofoil", "condition": "NM",
        "language": "EN",
    })
    assert item.language is Language.EN


def test_a_stored_jp_row_from_before_this_change_still_validates():
    item = InventoryItemAdapter.validate_python({
        "kind": "raw", "card_id": "ja:sv1-1", "cost_basis": Decimal("4"),
        "acquired_at": date(2025, 1, 1), "finish": "holofoil", "condition": "NM",
        "language": "JP",
    })
    assert item.language is Language.JP


class TestOtherLanguageInvariant:
    """``language == OTHER`` implies ``card_id is None`` — the exact mirror of
    ``no_catalog_match``'s own invariant above and for the same reason: there
    is no catalog language to link an OTHER item to, so a linked OTHER row is
    a contradiction.
    """

    def test_cannot_set_other_on_an_item_that_still_has_a_card_id(self):
        with pytest.raises(ValidationError, match="unlink the card first"):
            RawInventoryItem(**_base(
                finish="normal", condition="NM", card_id="en:base1-4",
                language=Language.OTHER,
            ))

    def test_other_with_no_card_id_is_fine(self):
        item = RawInventoryItem(**_base(
            finish="normal", condition="NM", card_id=None, language=Language.OTHER,
        ))
        assert item.language is Language.OTHER

    def test_a_graded_slab_can_be_other_too(self):
        item = GradedInventoryItem(**_base(
            card_id=None, company=GradingCompany.PSA, grade=Decimal("9"),
            cert_number="12345678", language=Language.OTHER,
        ))
        assert item.language is Language.OTHER

    def test_a_sealed_item_can_be_other_with_no_special_handling(self):
        """Sealed product has no ``card_id`` field at all — OTHER is always
        fine for it, same as it always was for ``no_catalog_match``."""
        item = SealedInventoryItem(**_base(
            product_name="Korean Booster Box", product_type=SealedProductType.BOOSTER_BOX,
            language=Language.OTHER,
        ))
        assert item.language is Language.OTHER


def test_language_note_is_not_a_customer_field():
    from merlins_collection.routers.inventory import _CUSTOMER_ITEM_FIELDS

    assert "language_note" not in _CUSTOMER_ITEM_FIELDS


# --- RFC 0023 T5: finish_attributes ----------------------------------------

class TestFinishAttributes:
    def test_defaults_to_an_empty_list(self):
        item = RawInventoryItem(**_base(finish="normal", condition="NM"))
        assert item.finish_attributes == []

    def test_accepts_a_list_of_descriptive_tags(self):
        item = RawInventoryItem(**_base(
            finish="holofoil", condition="NM",
            finish_attributes=["1st Edition", "Shadowless"],
        ))
        assert item.finish_attributes == ["1st Edition", "Shadowless"]

    def test_rejects_more_than_ten_entries(self):
        with pytest.raises(ValidationError):
            RawInventoryItem(**_base(
                finish="normal", condition="NM",
                finish_attributes=[f"tag{i}" for i in range(11)],
            ))

    def test_accepts_exactly_ten_entries(self):
        item = RawInventoryItem(**_base(
            finish="normal", condition="NM",
            finish_attributes=[f"tag{i}" for i in range(10)],
        ))
        assert len(item.finish_attributes) == 10

    def test_rejects_an_entry_over_forty_characters(self):
        with pytest.raises(ValidationError):
            RawInventoryItem(**_base(
                finish="normal", condition="NM",
                finish_attributes=["x" * 41],
            ))

    def test_accepts_an_entry_at_exactly_forty_characters(self):
        item = RawInventoryItem(**_base(
            finish="normal", condition="NM",
            finish_attributes=["x" * 40],
        ))
        assert item.finish_attributes == ["x" * 40]

    def test_is_a_customer_field(self):
        """The opposite call from language_note/review_reason: attributes are a
        DESCRIPTION of the card ("1st Edition", "Full Art"), not a note about
        our handling of the record, so they are customer-facing (RFC 0023 §2.2)."""
        from merlins_collection.routers.inventory import _CUSTOMER_ITEM_FIELDS

        assert "finish_attributes" in _CUSTOMER_ITEM_FIELDS

    def test_do_not_affect_market_price(self):
        """Attributes are descriptive only — `_market_price`/`market_price_and_finish`
        take a bare `finish` string and never see this field. Proven by actually
        pricing two otherwise-identical items rather than trusting that by reading."""
        from merlins_collection.models.inventory import market_price_and_finish

        card = _catalog_with_prices({"1stEditionHolofoil": "500.00"})
        plain = RawInventoryItem(**_base(finish="1stEditionHolofoil", condition="NM"))
        attributed = RawInventoryItem(**_base(
            finish="1stEditionHolofoil", condition="NM",
            finish_attributes=["1st Edition", "Shadowless"],
        ))
        assert (market_price_and_finish(card, plain.finish)
                == market_price_and_finish(card, attributed.finish))


def test_priced_finishes_is_the_measured_union():
    """RFC 0023 T4's live-catalog measurement (2026-09-02, 29,123 cards
    scanned — see docs/plans/rfc-0023/progress.md) union with
    `_MARKET_FINISH_FALLBACK`'s six. Order-independent: this is a UI
    vocabulary, not a priority list (that is what the fallback tuple is for)."""
    from merlins_collection.models.inventory import _MARKET_FINISH_FALLBACK, PRICED_FINISHES

    assert set(PRICED_FINISHES) == set(_MARKET_FINISH_FALLBACK) | {
        "normal", "holofoil", "reverseHolofoil",
        "1stEdition", "unlimited", "unlimitedHolofoil", "1stEditionHolofoil",
    }
    # No duplicates — a UI dropdown built from this must not repeat an entry.
    assert len(PRICED_FINISHES) == len(set(PRICED_FINISHES))


def test_a_blank_language_note_normalizes_to_none():
    item = RawInventoryItem(**_base(
        finish="normal", condition="NM", card_id=None, language_note="   ",
    ))
    assert item.language_note is None


def test_a_language_note_is_bounded_at_100_chars():
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(
            finish="normal", condition="NM", card_id=None, language_note="x" * 101,
        ))
