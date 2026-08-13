"""RFC 0009 T6 — the graded pricing provider.

Every field name asserted here comes from `docs/plans/rfc-0009/spike-findings.md`
§2 and §3, which recorded 19 real responses. Nothing below is guessed, and no
test makes a network call: the client is fed the recorded fixtures through an
injected transport.

**The one rule that governs this module**: a price attaches automatically only
on a VERIFIED `externalCatalogId` join. T0 measured that the vendor's name
search returns the wrong card roughly a third of the time, and a wrong answer is
indistinguishable from a right one — same 200, same fully-populated price block
(spike §3.3). The owner confirmed this rule on 2026-08-08.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from merlins_collection.models.catalog import CatalogCard
from merlins_collection.models.inventory import (
    GradedInventoryItem,
    GradingCompany,
    Language,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pricing"

# Gengar VMAX, Fusion Strike #271. Chosen as the worked example throughout
# because spike §2.2 quotes its psa10 block verbatim, so a drift in these
# numbers is a drift from the recorded evidence.
GENGAR = "89787279"
# A Japanese slab. Its `externalCatalogId` is null — spike §3.2 measured that
# for ALL THREE Japanese cards, so this is the norm for JP, not an edge case.
JP_ARCEUS = "151294759"


def load_fixture(cert: str) -> dict:
    """The recorded body for one card, exactly as the vendor returned it."""
    return json.loads((FIXTURES / f"card_{cert}.json").read_text(encoding="utf-8"))


def mutated(cert: str, mutate) -> dict:
    """A recorded body with one edit applied.

    Synthetic cases (a `0` price, a stated currency) are built by MUTATING a
    real body here rather than by adding a file to `fixtures/pricing/`. That
    directory is T0's recorded evidence; dropping an invented shape into it
    would let a later reader mistake a guess for a measurement.
    """
    body = copy.deepcopy(load_fixture(cert))
    mutate(body)
    return body


def transport(*, body=None, status=200, spy=None):
    """An httpx transport that answers from a fixture instead of the network."""

    def handler(request: httpx.Request) -> httpx.Response:
        if spy is not None:
            spy.append(request)
        return httpx.Response(status, json=body if body is not None else {"data": []})

    return httpx.MockTransport(handler)


def make_client(*, body=None, status=200, spy=None, quota=None, **kw):
    from merlins_collection.services.slab.pricing import PokemonPriceTrackerClient

    http = httpx.Client(transport=transport(body=body, status=status, spy=spy))
    return PokemonPriceTrackerClient(api_key="test-key-xxxx", client=http,
                                     quota=quota, **kw)


def _graded(**over) -> GradedInventoryItem:
    kw = dict(
        card_id="en:swsh8-271", cost_basis=Decimal("300"),
        acquired_at=date(2026, 1, 1), company=GradingCompany.PSA,
        grade=Decimal("10"), cert_number=GENGAR,
    )
    kw.update(over)
    return GradedInventoryItem(**kw)


def _catalog_card(card_id="en:swsh8-271", name="Gengar VMAX", set_id="swsh8",
                  set_name="Fusion Strike", number="271") -> CatalogCard:
    return CatalogCard(
        card_id=card_id, name=name, set_id=set_id, set_name=set_name,
        number=number, images={"small": "s", "large": "l"}, prices={},
        last_synced_at=datetime(2026, 8, 8, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# 1-8: the pricing client
# ---------------------------------------------------------------------------

class TestPricingClient:
    def test_a_recorded_fixture_maps_to_per_grade_values(self):
        """RED 1. The figures are spike §2.2's, quoted from this exact card."""
        client = make_client(body=load_fixture(GENGAR))
        prices = client.prices("253266")

        assert prices is not None
        assert prices.price_source_id == "253266"
        # `smartMarketPrice.price` — the vendor's own outlier-filtered number,
        # NOT `averagePrice`, which is visibly skewed (spike §2.2).
        assert prices.prices["psa10"] == Decimal("2479.5")
        assert prices.prices["psa9"] == Decimal("929.67")
        # Carried WITH the price, per spike §2.2 and progress.md's T6 row.
        assert prices.confidences["psa10"] == "high"

    def test_half_grades_and_other_companies_survive_the_mapping(self):
        """A typical card returns ~23 buckets, not just PSA 8/9/10 (spike §2.2).
        `GRADEDPRICE#<company>#<grade>` is keyed by both, so nothing is lost."""
        prices = make_client(body=load_fixture(GENGAR)).prices("253266")
        assert "bgs9_5" in prices.prices
        assert "cgc10" in prices.prices
        assert "ungraded" in prices.prices

    def test_an_uncovered_grade_is_absent_not_zero(self):
        """RED 2. Gengar's recorded block has no psa3. Absent must stay absent —
        a slab silently valued at $0 drags totals and looks authoritative."""
        prices = make_client(body=load_fixture(GENGAR)).prices("253266")
        assert "psa3" not in prices.prices
        assert prices.prices.get("psa3") is None

    def test_a_zero_price_is_treated_as_no_coverage(self):
        """RED 3. No recorded fixture contains a 0 — all 19 were checked — so
        this is a MUTATED body, and the guard exists for a shape the vendor has
        not yet produced rather than one it has."""
        def zero_out(body):
            body["data"][0]["ebay"]["salesByGrade"]["psa10"]["smartMarketPrice"]["price"] = 0

        prices = make_client(body=mutated(GENGAR, zero_out)).prices("253266")
        assert "psa10" not in prices.prices

    def test_an_unknown_card_returns_none_not_an_exception(self):
        """RED 4. An empty `data` list is an ordinary answer, not a failure."""
        assert make_client(body={"data": [], "metadata": {}}).prices("999999") is None

    def test_a_provider_500_raises(self):
        """RED 5. A server error must not be laundered into "no coverage" —
        T7 would happily overwrite good prices with nothing."""
        from merlins_collection.services.slab.pricing import PricingProviderError

        with pytest.raises(PricingProviderError):
            make_client(status=500).prices("253266")

    def test_absent_currency_is_usd_and_the_assumption_is_recorded(self):
        """RED 6, first half. Spike §2.2: there is NO currency field anywhere in
        the response. USD is the reasonable reading (eBay-US comps) but it must
        never become a SILENT assumption."""
        prices = make_client(body=load_fixture(GENGAR)).prices("253266")
        assert prices.currency == "USD"
        assert prices.currency_assumed is True

    def test_a_stated_non_usd_currency_is_refused_not_converted(self):
        """RED 6, second half. If the vendor ever starts stating a currency, a
        non-USD one is REFUSED rather than silently taken as USD or converted
        behind the operator's back."""
        from merlins_collection.services.slab.pricing import PricingProviderError

        def eurify(body):
            body["data"][0]["currency"] = "EUR"

        with pytest.raises(PricingProviderError):
            make_client(body=mutated(GENGAR, eurify)).prices("253266")

    def test_a_stated_usd_currency_is_not_flagged_as_assumed(self):
        def usdify(body):
            body["data"][0]["currency"] = "USD"

        prices = make_client(body=mutated(GENGAR, usdify)).prices("253266")
        assert prices.currency == "USD"
        assert prices.currency_assumed is False

    def test_the_api_key_never_reaches_a_log_record(self, caplog):
        """RED 7. The key rides in an Authorization header on every call, and
        both keys have already been pasted into a chat transcript once."""
        caplog.set_level(logging.DEBUG)
        make_client(body=load_fixture(GENGAR)).prices("253266")
        assert "test-key-xxxx" not in "\n".join(
            r.getMessage() for r in caplog.records
        )

    def test_as_of_comes_from_the_ebay_block(self):
        prices = make_client(body=load_fixture(GENGAR)).prices("253266")
        assert prices.as_of == datetime.fromisoformat("2026-08-05T11:31:25.891+00:00")


class TestQuota:
    def test_exhausted_quota_raises_before_any_http_call(self):
        """RED 8. Billing is 2 x limit and is charged EVEN ON ZERO HITS
        (spike §2.1) — so the guard has to come before the socket, not after
        the response."""
        from merlins_collection.services.slab.pricing import PricingQuotaExceeded
        from merlins_collection.services.slab.quota import DailyQuota

        spy: list[httpx.Request] = []
        spent = DailyQuota(limit=100, key="outbound:pricing")
        spent.record(100)

        client = make_client(body=load_fixture(GENGAR), spy=spy, quota=spent)
        with pytest.raises(PricingQuotaExceeded):
            client.prices("253266")
        assert spy == [], "a quota check that fires after the call has already spent it"

    def test_a_call_costs_two_credits_not_one(self):
        """Spike §2.1: `costPerCard` is 2 — 1 for the card, 1 for includeEbay.
        The free tier is therefore 50 lookups a day, not 100."""
        from merlins_collection.services.slab.quota import DailyQuota

        quota = DailyQuota(limit=100, key="outbound:pricing")
        make_client(body=load_fixture(GENGAR), quota=quota).prices("253266")
        assert quota.spent == 2

    def test_every_query_pins_limit_to_one(self):
        """`limit` is the cost dial, not a breadth knob: cost = 2 x limit,
        always, hits or no hits (spike §2.1)."""
        spy: list[httpx.Request] = []
        client = make_client(body=load_fixture(GENGAR), spy=spy)
        client.resolve(name="Gengar VMAX", set_name=None, number=None)
        assert spy, "no request was made"
        for request in spy:
            assert request.url.params["limit"] == "1"


class TestResolve:
    def test_resolve_returns_the_tcgplayer_id_and_the_external_catalog_id(self):
        """Spike §2.3 / §3.1. `price_source_id` is the vendor's `tcgPlayerId` so
        later refreshes are exact; `external_catalog_id` is what makes the join
        verifiable."""
        client = make_client(body=load_fixture(GENGAR))
        resolved = client.resolve(name="Gengar VMAX", set_name=None, number=None)
        assert resolved.price_source_id == "253266"
        assert resolved.external_catalog_id == "swsh8-271"

    def test_a_japanese_card_resolves_with_no_external_catalog_id(self):
        """Spike §3.2: all 3 JP cards came back with `externalCatalogId: null`.
        The deterministic join is an English-only convenience."""
        client = make_client(body=load_fixture(JP_ARCEUS))
        resolved = client.resolve(name="Arceus V", set_name=None, number=None,
                                  language=Language.JP)
        assert resolved is not None
        assert resolved.external_catalog_id is None

    def test_no_hits_resolves_to_none(self):
        client = make_client(body={"data": [], "metadata": {}})
        assert client.resolve(name="Umbreon Gold Star", set_name=None,
                              number=None) is None


# ---------------------------------------------------------------------------
# 9-11 + the verified-join rule: attaching a price to a real item
# ---------------------------------------------------------------------------

class TestVerifiedJoin:
    """The owner-confirmed rule (2026-08-08): attach ONLY on a verified join."""

    def test_a_matching_external_catalog_id_attaches_the_price(self, dynamo_repo):
        """Spike §3.1: `en:<externalCatalogId>` IS our `card_id`. When it agrees
        with the item's own link, our catalog row confirms the vendor's guess."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded()
        dynamo_repo.put_inventory_item(item)

        result = attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                              repo=dynamo_repo)

        assert result.attached is True
        assert result.value == Decimal("2479.5")

    def test_no_external_catalog_id_does_not_attach(self, dynamo_repo):
        """Every Japanese slab takes this path — the norm, not the exception."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card(card_id="ja:sv1a-1",
                                                              name="Arceus V")])
        item = _graded(card_id="ja:sv1a-1", cert_number=JP_ARCEUS,
                       language=Language.JP)
        dynamo_repo.put_inventory_item(item)

        result = attach_price(item=item, provider=make_client(body=load_fixture(JP_ARCEUS)),
                              repo=dynamo_repo)

        assert result.attached is False
        assert result.reason == "no_external_catalog_id"
        assert dynamo_repo.get_graded_market_value("ja:sv1a-1", GradingCompany.PSA,
                                                   Decimal("10")) is None

    def test_an_external_catalog_id_absent_from_our_catalog_does_not_attach(
            self, dynamo_repo):
        """Two of nineteen: the Trainer Gallery subsets `swsh9-TG23` and
        `swsh12-TG29`, which TCGdex files under a different set id (spike §3.2).
        Nothing confirms the match, so nothing attaches — and this is the
        Umbreon Gold Star row, which the vendor also answered with the WRONG
        card, so the refusal is doing real work here."""
        from merlins_collection.services.slab.pricing import attach_price

        # Our own catalog row for the card the admin says this is.
        dynamo_repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:pop5-17", name="Umbreon Gold Star",
                          set_id="pop5", set_name="POP Series 5", number="17"),
        ])
        item = _graded(card_id="en:pop5-17", cert_number="67681781")
        dynamo_repo.put_inventory_item(item)

        # The vendor answers with ext id `swsh9-TG23` — a real id, unknown here.
        result = attach_price(item=item,
                              provider=make_client(body=load_fixture("67681781")),
                              repo=dynamo_repo)

        assert result.attached is False
        assert result.reason == "external_id_not_in_catalog"
        assert dynamo_repo.get_graded_market_value(
            "en:pop5-17", GradingCompany.PSA, Decimal("10")) is None

    def test_an_unlinked_slab_does_not_attach(self, dynamo_repo):
        """No `card_id` means nothing to verify AGAINST — the join has no left
        hand side, so the vendor's answer is unfalsifiable."""
        from merlins_collection.services.slab.pricing import attach_price

        item = _graded(card_id=None, display_name="Gengar VMAX")
        dynamo_repo.put_inventory_item(item)

        result = attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                              repo=dynamo_repo)

        assert result.attached is False
        assert result.reason == "no_catalog_link"

    def test_a_nameless_unlinked_slab_is_refused_before_the_call(self, dynamo_repo):
        """An empty query is billed exactly like a real one — 2 credits, hits or
        no hits — and can only return an arbitrary card."""
        from merlins_collection.services.slab.pricing import attach_price

        spy: list[httpx.Request] = []
        item = _graded(card_id=None)
        dynamo_repo.put_inventory_item(item)

        result = attach_price(
            item=item, provider=make_client(body=load_fixture(GENGAR), spy=spy),
            repo=dynamo_repo,
        )

        assert result.reason == "no_name"
        assert spy == [], "spent credits searching for nothing"

    def test_a_relinked_card_does_not_reuse_its_old_vendor_id(self, dynamo_repo):
        """`price_source_id` is cached, but `card_id` stays editable underneath
        it. An admin who UNLINKS a slab must not have the old vendor product's
        price written against it."""
        from merlins_collection.services.slab.pricing import attach_price

        spy: list[httpx.Request] = []
        item = _graded(card_id=None, price_source_id="253266")
        dynamo_repo.put_inventory_item(item)

        result = attach_price(
            item=item, provider=make_client(body=load_fixture(GENGAR), spy=spy),
            repo=dynamo_repo,
        )

        assert result.attached is False
        assert result.reason == "no_catalog_link"
        assert spy == []

    def test_a_mismatched_external_catalog_id_does_not_attach(self, dynamo_repo):
        """The Mega Latias case (spike §3.3): the vendor answered with Latios EX
        and looked exactly as confident as a right answer. The item's own link
        disagrees, so the price is refused."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([
            _catalog_card(),
            _catalog_card(card_id="en:xyp-XY72", name="Latios EX", set_id="xyp",
                          set_name="XY Black Star Promos", number="XY72"),
        ])
        item = _graded(card_id="en:xyp-XY72")  # the admin says Mega Latias
        dynamo_repo.put_inventory_item(item)

        # ...but the vendor answers with the Gengar body, ext id `swsh8-271`.
        result = attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                              repo=dynamo_repo)

        assert result.attached is False
        assert result.reason == "external_id_mismatch"
        assert dynamo_repo.get_graded_market_value("en:xyp-XY72", GradingCompany.PSA,
                                                   Decimal("10")) is None


class TestSearchDisambiguation:
    """A bare-name search is ambiguous for any card with a promo reprint, and
    the vendor's own ranking tends to prefer the promo. Measured on live
    inventory 2026-08-12: 7 of 8 catalog-linked-but-unpriced slabs were
    refused for exactly this reason (external_id_mismatch against a promo
    reprint the vendor matched instead of the owned mainline print, e.g.
    Volcanion EX: Steam Siege #115 owned, vendor matched XY Promos #173).
    The catalog card's own set_name/number narrow the query so the correct
    printing is far more likely to rank first."""

    def test_attach_price_includes_set_and_number_in_the_search_query(self, dynamo_repo):
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])  # Fusion Strike #271
        item = _graded()
        dynamo_repo.put_inventory_item(item)

        spy: list[httpx.Request] = []
        attach_price(item=item, provider=make_client(body=load_fixture(GENGAR), spy=spy),
                     repo=dynamo_repo)

        assert spy, "no request was made"
        query = spy[0].url.params["search"]
        assert "Fusion Strike" in query
        assert "271" in query


class TestStorage:
    def test_a_resolved_price_writes_a_readable_graded_price_row(self, dynamo_repo):
        """RED 9."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded()
        dynamo_repo.put_inventory_item(item)

        attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                     repo=dynamo_repo)

        stored = dynamo_repo.get_graded_market_value("en:swsh8-271",
                                                     GradingCompany.PSA, Decimal("10"))
        assert stored == Decimal("2479.5")

    def test_two_grades_of_the_same_card_write_independent_rows(self, dynamo_repo):
        """RED 10. `GRADEDPRICE#<company>#<grade>` is keyed by grade, so a PSA 9
        and a PSA 10 of one card never overwrite each other."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        for grade, cert in ((Decimal("10"), "1"), (Decimal("9"), "2")):
            item = _graded(grade=grade, cert_number=cert)
            dynamo_repo.put_inventory_item(item)
            attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                         repo=dynamo_repo)

        assert dynamo_repo.get_graded_market_value(
            "en:swsh8-271", GradingCompany.PSA, Decimal("10")) == Decimal("2479.5")
        assert dynamo_repo.get_graded_market_value(
            "en:swsh8-271", GradingCompany.PSA, Decimal("9")) == Decimal("929.67")

    def test_the_row_records_that_a_provider_wrote_it(self, dynamo_repo):
        """A hand-entered value and a scraped one must stay distinguishable —
        `GET /admin/slabs` reports which, so the UI can be honest."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded()
        dynamo_repo.put_inventory_item(item)
        attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                     repo=dynamo_repo)

        row = dynamo_repo.get_graded_price_row("en:swsh8-271", GradingCompany.PSA,
                                               Decimal("10"))
        assert row["source"] == "provider"
        assert row["confidence"] == "high"
        assert row["updated_at"]

    def test_a_manual_value_still_reports_itself_as_manual(self, dynamo_repo):
        dynamo_repo.set_graded_market_value("en:swsh8-271", GradingCompany.PSA,
                                            Decimal("10"), Decimal("2000"))
        row = dynamo_repo.get_graded_price_row("en:swsh8-271", GradingCompany.PSA,
                                               Decimal("10"))
        assert row["source"] == "manual"

    def test_writing_a_price_never_touches_identity_fields(self, dynamo_repo):
        """RED 11. The pricing provider supplies VALUES ONLY. `card_id`,
        `display_name` and `cert_number` come from PSA and from the admin —
        CLAUDE.md's binding rule, applied to the other direction."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded(display_name="Gengar VMAX (hand-typed)")
        dynamo_repo.put_inventory_item(item)

        attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                     repo=dynamo_repo)

        after = dynamo_repo.get_inventory_item(item.item_id)
        assert after.card_id == "en:swsh8-271"
        assert after.display_name == "Gengar VMAX (hand-typed)"
        assert after.cert_number == GENGAR
        assert after.display_name_override is None

    def test_a_price_is_stored_as_a_decimal_not_a_float(self, dynamo_repo):
        """The vendor sends JSON NUMBERS (`2479.5`), which arrive as Python
        floats. boto3 refuses a float outright — the production 500 CLAUDE.md
        records. Existing tests hid it by sending prices as strings."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded()
        dynamo_repo.put_inventory_item(item)
        attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                     repo=dynamo_repo)

        stored = dynamo_repo.get_graded_market_value("en:swsh8-271",
                                                     GradingCompany.PSA, Decimal("10"))
        assert isinstance(stored, Decimal)
        assert str(stored) == "2479.5"

    def test_a_grade_the_provider_does_not_cover_writes_no_row(self, dynamo_repo):
        """The whole point of trap 1: no row at all beats a row saying $0."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded(grade=Decimal("3"))  # Gengar's block has no psa3
        dynamo_repo.put_inventory_item(item)

        result = attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                              repo=dynamo_repo)

        assert result.attached is False
        assert result.reason == "grade_not_covered"
        assert dynamo_repo.get_graded_market_value(
            "en:swsh8-271", GradingCompany.PSA, Decimal("3")) is None

    def test_the_resolved_price_source_id_is_cached_on_the_item(self, dynamo_repo):
        """Spike §2.3: resolve once by search, then refresh by id forever after.
        This is what keeps T7's nightly cost at one lookup per slab."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded()
        dynamo_repo.put_inventory_item(item)
        attach_price(item=item, provider=make_client(body=load_fixture(GENGAR)),
                     repo=dynamo_repo)

        assert dynamo_repo.get_inventory_item(item.item_id).price_source_id == "253266"

    def test_a_cached_price_source_id_skips_the_name_search(self, dynamo_repo):
        """Once confirmed, `price_source_id` is stored and never resolved again
        (T6 doc, trap 3) — the fuzzy search is where the wrong answers come
        from, so not repeating it is a correctness win, not only a cost one."""
        from merlins_collection.services.slab.pricing import attach_price

        dynamo_repo.batch_upsert_catalog_cards([_catalog_card()])
        item = _graded(price_source_id="253266")
        dynamo_repo.put_inventory_item(item)

        spy: list[httpx.Request] = []
        attach_price(item=item,
                     provider=make_client(body=load_fixture(GENGAR), spy=spy),
                     repo=dynamo_repo)

        assert len(spy) == 1, "a cached id must cost ONE call, not a resolve plus a fetch"
        assert "search" not in str(spy[0].url)
