"""Per-grade graded-card pricing (RFC 0009 §5.2, T6).

The raw TCGplayer/Cardmarket feed the catalog already syncs does not price
slabs — a PSA 10 and a PSA 4 of one card are wildly different products and the
feed knows about neither. This module fills the ``GRADEDPRICE#<company>#<grade>``
rows that already existed in ``services/dynamodb.py`` (previously only ever
written by hand) from PokemonPriceTracker's eBay sold-comp data.

Every field name here was recorded from 19 real responses in T0 and is
documented in ``docs/plans/rfc-0009/spike-findings.md`` §2 and §3. Nothing is
guessed.

THE RULE THAT GOVERNS THIS MODULE
=================================

**A price attaches automatically only on a VERIFIED ``externalCatalogId``
join.** T0 measured the vendor's name search returning the wrong card on
roughly a third of the owner's own shelf (spike §3.3) — "M Latias EX" answered
with *Latios* EX, "Umbreon Star" with Umbreon *VMAX*, a bare "Pikachu" with one
arbitrary pick out of 592 hits. Every wrong answer came back looking exactly
like a right one: HTTP 200, fully populated price block, no hint of doubt.

The mitigation is a join, not a heuristic. Each vendor card carries an
``externalCatalogId`` in TCGdex's own shape, and ``en:<externalCatalogId>`` IS
our ``card_id`` (spike §3.1, verified against four live catalog rows). When that
id resolves to the catalog row the item is ALREADY linked to, our own data has
confirmed the vendor's answer. When it does not, nothing attaches.

Two consequences are by design, not bugs:

* **Japanese slabs never take the automatic path.** All three JP cards in T0's
  sample returned ``externalCatalogId: null``, so this is the norm for JP stock
  rather than an edge case.
* **An unpriced slab is NOT flagged into Triage** (owner's decision,
  2026-08-08). It renders "not priced" on ``/admin/slabs``, and that list is the
  worklist. Flagging would put every Japanese slab in Triage permanently — the
  same noise problem that got a T3 rule reversed a week earlier.

WHAT THIS MODULE MAY WRITE
==========================

**Values only.** Never ``card_id``, ``display_name``, ``display_name_override``,
``company``, ``grade`` or ``cert_number``. Identity comes from the admin (and,
once PSA approves the account, from the cert lookup); a price is a number hung
off an identity that already exists. The one field it does write back on the
item is ``price_source_id``, which is the vendor's own product handle — an
addressing detail, not an identity claim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx
from pydantic import BaseModel

from merlins_collection.config import settings
from merlins_collection.models.inventory import (
    GradedInventoryItem,
    GradingCompany,
    Language,
)
from merlins_collection.services.slab.quota import DailyQuota, MinuteWindow, QuotaExceeded

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pokemonpricetracker.com/api/v2"

# `limit` is the COST DIAL, not a breadth knob. Billing is `2 x limit` and is
# charged even when the search matches nothing — T0's first probe used `limit=2`,
# matched zero cards, and was still billed 4 credits (spike §2.1). Pinned to 1
# here and never made a parameter, because the only thing a caller could do with
# it is make every lookup more expensive.
_LIMIT = 1
# 1 credit for the card + 1 for `includeEbay`. `costPerCard: 2` confirmed against
# a live response, not inferred from the docs. The graded sales data is the whole
# reason we call this API, so the eBay credit is not optional.
_CREDITS_PER_CALL = 2 * _LIMIT

_PROVIDER_SOURCE = "provider"


class PricingProviderError(RuntimeError):
    """The vendor failed, or answered in a shape we refuse to guess at.

    Distinct from "no coverage", which is ``None``. Conflating them is how a
    nightly refresh overwrites good prices with silence: T7 must be able to tell
    "the vendor is down" from "this grade has no comps".
    """


class PricingQuotaExceeded(PricingProviderError):
    """Today's credit budget is spent. Raised before any HTTP call."""


class GradedPrices(BaseModel):
    """Every per-grade figure one vendor card offers.

    ``prices`` is keyed by the VENDOR's own grade key — ``"psa10"``,
    ``"bgs9_5"``, ``"ungraded"`` — rather than by a bare numeric grade. A bare
    grade would lose the company, and our storage is keyed by both
    (``GRADEDPRICE#<company>#<grade>``); a typical card returns ~23 buckets
    spanning PSA, BGS, CGC, SGC, ACE and TAG, so the company dimension is real
    data, not a hypothetical.
    """

    price_source_id: str
    prices: dict[str, Decimal]
    # `smartMarketPrice.confidence` — carried WITH the price, never separated
    # from it. The vendor's own word for how much it trusts its number, and the
    # only thing distinguishing a figure built from 334 sales from one built
    # from two.
    confidences: dict[str, str]
    currency: str
    # TRUE when the vendor stated no currency at all, which is the normal case —
    # there is no currency field anywhere in the response (spike §2.2). The
    # comps are eBay-US sold listings so USD is the reasonable reading, and this
    # flag is what keeps it from being a SILENT reading.
    currency_assumed: bool
    as_of: datetime | None


class ResolvedCard(BaseModel):
    """One vendor card, plus the prices that came back in the same response.

    The prices ride along because ``includeEbay=true`` already paid for them:
    splitting resolve and fetch into two HTTP calls here would double the cost
    of a first-time lookup for no benefit. ``prices(id)`` remains separate for
    T7, which refreshes a known id and never searches.
    """

    price_source_id: str
    external_catalog_id: str | None
    name: str
    set_name: str | None
    number: str | None
    prices: GradedPrices


class GradedPricing(Protocol):
    """What a graded pricing vendor must provide.

    Two methods on purpose. ``resolve`` is the expensive, fallible, fuzzy one
    and runs ONCE per card; ``prices`` is exact and is what the nightly job
    calls forever after. Splitting them is what keeps T7's cost at one lookup
    per slab.
    """

    def resolve(self, *, name: str, set_name: str | None, number: str | None,
                language: Language = Language.EN) -> ResolvedCard | None: ...

    def prices(self, price_source_id: str) -> GradedPrices | None: ...


def grade_key(company: GradingCompany | str, grade: Decimal) -> str:
    """Our (company, grade) pair as the vendor's own bucket key.

    ``PSA`` + ``9.5`` -> ``"psa9_5"``. Normalized through ``Decimal`` so a grade
    stored as ``10.0``, ``10`` or ``Decimal("1E+1")`` all produce ``"psa10"`` —
    the same normalization ``services.dynamodb._grade_key`` applies to the
    storage key, for the same reason.
    """
    value = getattr(company, "value", company)
    digits = f"{Decimal(str(grade)).normalize():f}".replace(".", "_")
    return f"{str(value).lower()}{digits}"


def _decimal(value) -> Decimal | None:
    """Coerce a vendor number to ``Decimal``, or ``None`` if it is not one.

    Via ``str()``, always. The vendor sends JSON NUMBERS (``2479.5``), which
    arrive as Python floats, and ``Decimal(2479.5)`` is not 2479.5 — it is the
    binary expansion. boto3 refuses a bare float outright anyway (CLAUDE.md),
    and this is the point where one would otherwise reach the writer.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_timestamp(raw) -> datetime | None:
    """Parse the vendor's ISO-8601-with-``Z`` stamps."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class PokemonPriceTrackerClient:
    """HTTP client for PokemonPriceTracker v2.

    ``client`` is injectable so tests answer from T0's recorded fixtures and
    never touch the network. ``quota`` is injectable so a caller can share one
    budget across several clients (or hand in a spent one, which is how the
    pre-call guard is tested).
    """

    def __init__(self, *, api_key: str, client: httpx.Client | None = None,
                 quota: DailyQuota | None = None, minute_limit: int = 60,
                 timeout: float = 20.0):
        if not api_key:
            raise PricingProviderError(
                "no pokemonpricetracker_api_key configured; refusing to call the "
                "vendor unauthenticated (it answers 401, and the 401 body is the "
                "only place that says why)"
            )
        self._api_key = api_key
        self._client = client or httpx.Client(
            base_url=BASE_URL,
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=timeout, pool=10.0),
            follow_redirects=False,
        )
        self._quota = quota if quota is not None else DailyQuota(
            limit=settings.pricing_daily_quota, key="outbound:pricing"
        )
        self._minute = MinuteWindow(minute_limit)

    @property
    def quota(self) -> DailyQuota:
        return self._quota

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # -- HTTP ---------------------------------------------------------------

    def _get_cards(self, params: dict) -> dict:
        """One billed call to ``/cards``.

        The quota check is the FIRST thing that happens, before the pacer and
        before the socket. Reversing those two would let a paced call sit in a
        sleep for its turn to spend money the budget had already refused.
        """
        try:
            self._quota.check(_CREDITS_PER_CALL)
        except QuotaExceeded as exc:
            raise PricingQuotaExceeded(str(exc)) from exc

        self._minute.acquire()
        query = {**params, "includeEbay": "true", "limit": str(_LIMIT)}

        try:
            response = self._client.get(
                f"{BASE_URL}/cards",
                params=query,
                # The ONLY place the key appears. Nothing in this module logs
                # headers, and no exception below is constructed from the
                # request — both keys have already been pasted into a chat
                # transcript once (progress.md), and a log line is forever.
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as exc:
            # `exc` may stringify to the request URL; the key is a header, not a
            # query param, so it is not in there. Kept to the class name anyway.
            raise PricingProviderError(
                f"pricing request failed: {type(exc).__name__}"
            ) from exc

        # Billed the moment the vendor answered, whatever it answered — including
        # a zero-hit search (spike §2.1). Debited before the status check for
        # exactly that reason.
        self._quota.record(_CREDITS_PER_CALL)
        self._quota.sync(
            _int_header(response.headers.get("x-ratelimit-daily-remaining")),
            _int_header(response.headers.get("x-ratelimit-daily-limit")),
        )

        if response.status_code == 401:
            raise PricingProviderError(
                "pricing provider rejected the API key (401). Unlike PSA, this "
                "vendor separates auth from quota cleanly — a 401 is the key, "
                "not the budget."
            )
        if response.status_code == 429:
            raise PricingProviderError(
                "pricing provider daily/minute quota exhausted (429); the local "
                "counter was behind the vendor's"
            )
        if response.status_code != 200:
            raise PricingProviderError(
                f"pricing provider returned HTTP {response.status_code}"
            )

        try:
            return response.json()
        except ValueError as exc:
            # A 200 that is not JSON is a CDN interstitial or a maintenance page
            # — the most common way a hosted API fails without failing.
            raise PricingProviderError(
                "pricing provider returned a 200 that is not JSON"
            ) from exc

    # -- mapping ------------------------------------------------------------

    def _map_prices(self, card: dict) -> GradedPrices:
        """Turn one vendor card into its per-grade figures."""
        currency, assumed = _read_currency(card)

        ebay = card.get("ebay") or {}
        by_grade = ebay.get("salesByGrade") or {}

        prices: dict[str, Decimal] = {}
        confidences: dict[str, str] = {}
        for key, block in by_grade.items():
            if not isinstance(block, dict):
                continue
            smart = block.get("smartMarketPrice") or {}
            value = _decimal(smart.get("price"))
            # `0` is NOT `null`. No recorded fixture contains one — all 19 were
            # checked, and "no coverage" is an ABSENT KEY (spike §2.2) — but a
            # zero that ever did arrive would price a slab at nothing while
            # looking authoritative, dragging totals and misreporting position.
            # Refused here rather than defended against downstream.
            if value is None or value <= 0:
                continue
            prices[key] = value
            confidence = smart.get("confidence")
            if isinstance(confidence, str) and confidence:
                confidences[key] = confidence

        return GradedPrices(
            price_source_id=str(card.get("tcgPlayerId") or ""),
            prices=prices,
            confidences=confidences,
            currency=currency,
            currency_assumed=assumed,
            as_of=_parse_timestamp(ebay.get("updatedAt")),
        )

    def _first_card(self, payload: dict) -> dict | None:
        data = payload.get("data") or []
        return data[0] if data else None

    # -- the Protocol -------------------------------------------------------

    def resolve(self, *, name: str, set_name: str | None, number: str | None,
                language: Language = Language.EN) -> ResolvedCard | None:
        """Find a vendor card by name. Returns ``None`` when nothing matched.

        The caller MUST NOT trust the identity of what comes back — see this
        module's docstring. ``resolve`` reports what the vendor said; deciding
        whether to believe it is ``attach_price``'s job.
        """
        query = " ".join(part for part in (name, set_name, number) if part).strip()
        payload = self._get_cards({
            "search": query,
            "language": "japanese" if language == Language.JP else "english",
        })
        card = self._first_card(payload)
        if card is None:
            logger.info("pricing: no vendor card for %r", query)
            return None

        return ResolvedCard(
            price_source_id=str(card.get("tcgPlayerId") or ""),
            external_catalog_id=card.get("externalCatalogId") or None,
            name=card.get("name") or "",
            set_name=card.get("setName"),
            number=card.get("cardNumber"),
            prices=self._map_prices(card),
        )

    def prices(self, price_source_id: str) -> GradedPrices | None:
        """Fetch per-grade figures for a known vendor id.

        Exact, not fuzzy — this is the call T7 makes every night, and the reason
        ``price_source_id`` is cached on the item in the first place.
        """
        payload = self._get_cards({"tcgPlayerId": str(price_source_id)})
        card = self._first_card(payload)
        if card is None:
            return None
        return self._map_prices(card)


def _int_header(raw: str | None) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _read_currency(card: dict) -> tuple[str, bool]:
    """Decide the currency, and whether we are assuming it.

    Spike §2.2: there is NO currency field anywhere in the recorded responses.
    The comps are eBay-US sold listings, so USD is the reasonable reading, and
    it matches our storage contract where every figure is USD. What is refused
    is a SILENT reading — hence the flag, and hence the hard failure if the
    vendor ever does state something else. We do not convert: the codebase's
    one precedent for conversion (``eur_usd_rate``) records the rate it used in
    the figure's ``value_note``, and inventing a second, quieter conversion path
    is how a wrong number becomes invisible.
    """
    stated = card.get("currency")
    if stated is None:
        return "USD", True
    if str(stated).upper() != "USD":
        raise PricingProviderError(
            f"pricing provider returned currency {stated!r}; refusing to store a "
            "non-USD figure as USD and refusing to convert it silently. Every "
            "stored value in this codebase is USD by contract "
            "(models/catalog.py); a converted one must record its rate."
        )
    return "USD", False


@dataclass
class AttachResult:
    """What happened when a price was offered to one slab.

    ``reason`` is populated on every refusal and is the honest answer to "why is
    this slab still unpriced?" — the question ``/admin/slabs?priced=false``
    exists to ask.
    """

    attached: bool
    value: Decimal | None = None
    confidence: str | None = None
    price_source_id: str | None = None
    reason: str | None = None


# Every way a price can decline to attach. Kept as a named set so the frontend,
# T7 and the follow-up docs are all talking about the same strings.
NOT_FOUND = "not_found"
NO_NAME = "no_name"
NO_CATALOG_LINK = "no_catalog_link"
NO_EXTERNAL_CATALOG_ID = "no_external_catalog_id"
EXTERNAL_ID_NOT_IN_CATALOG = "external_id_not_in_catalog"
EXTERNAL_ID_MISMATCH = "external_id_mismatch"
GRADE_NOT_COVERED = "grade_not_covered"


def attach_price(*, item: GradedInventoryItem, provider: GradedPricing,
                 repo) -> AttachResult:
    """Price one slab, but only if the vendor's answer can be verified.

    The verification is the whole point; see this module's docstring. Reads in
    order of cost: a cached ``price_source_id`` skips the fuzzy search entirely,
    which is both cheaper AND more correct, since the search is where the wrong
    answers come from.
    """
    if item.price_source_id:
        # Re-checked even on the cached path. An id only ever gets onto an item
        # by passing the join below — but `card_id` is separately editable, so
        # an admin who re-pointed or unlinked the card since then would
        # otherwise have the OLD vendor product's price written against the NEW
        # card. The stronger fix (clearing `price_source_id` when `card_id`
        # changes) belongs in the re-point flow and is in follow-ups.md.
        if not item.card_id:
            return AttachResult(False, reason=NO_CATALOG_LINK,
                                price_source_id=item.price_source_id)
        prices = provider.prices(item.price_source_id)
        if prices is None:
            return AttachResult(False, reason=NOT_FOUND)
        return _write(item=item, prices=prices, repo=repo,
                      price_source_id=item.price_source_id)

    search_name = _search_name(item, repo)
    if not search_name:
        # Refused BEFORE the call. An empty query is billed exactly like a real
        # one (2 credits, hits or no hits) and can only return an arbitrary
        # card — the worst possible trade.
        return AttachResult(False, reason=NO_NAME)

    resolved = provider.resolve(
        name=search_name, set_name=None, number=None, language=item.language,
    )
    if resolved is None:
        return AttachResult(False, reason=NOT_FOUND)

    refusal = _verify_join(item, resolved, repo)
    if refusal is not None:
        logger.info(
            "pricing: refusing to attach to %s (%s); vendor offered %r",
            item.item_id, refusal, resolved.name,
        )
        return AttachResult(False, reason=refusal,
                            price_source_id=resolved.price_source_id)

    return _write(item=item, prices=resolved.prices, repo=repo,
                  price_source_id=resolved.price_source_id)


def _search_name(item: GradedInventoryItem, repo) -> str:
    """The best name we hold for this item, for the vendor's search box.

    The CATALOG name is preferred over the admin's own label when the item is
    linked, and that is not a slight on the admin — it is what T0 measured. The
    vendor's search is literal, so "Mega Latias EX" finds Latios and "Umbreon
    Gold Star" finds nothing at all (spike §3.3), while the catalog name is the
    same vocabulary the vendor's own catalog was built from. An admin's label is
    the fallback for an unlinked slab, which will not pass the join anyway.

    Note what this does NOT do: it never writes a name anywhere, and it never
    lets the vendor's answer replace one.
    """
    if item.card_id:
        card = repo.get_catalog_card(item.card_id)
        if card and card.name:
            return card.name
    return item.display_name_override or item.display_name or ""


def _verify_join(item: GradedInventoryItem, resolved: ResolvedCard, repo) -> str | None:
    """Return a refusal reason, or ``None`` if the vendor's card is confirmed."""
    if not item.card_id:
        return NO_CATALOG_LINK
    if not resolved.external_catalog_id:
        # Every Japanese slab lands here. Expected, not exceptional.
        return NO_EXTERNAL_CATALOG_ID

    joined_card_id = f"en:{resolved.external_catalog_id}"
    if repo.get_catalog_card(joined_card_id) is None:
        # The Trainer Gallery case: TCGdex files those subsets under a different
        # set id, so `swsh9-TG23` is a real vendor id that our catalog has never
        # heard of. Nothing confirms the match, so nothing attaches.
        return EXTERNAL_ID_NOT_IN_CATALOG
    if joined_card_id != item.card_id:
        # The Mega Latias case. The vendor answered confidently with a different
        # card; our own link is the thing that says so.
        return EXTERNAL_ID_MISMATCH
    return None


def _write(*, item: GradedInventoryItem, prices: GradedPrices, repo,
           price_source_id: str) -> AttachResult:
    """Store the figure for this slab's own company+grade. Values only."""
    key = grade_key(item.company, item.grade)
    value = prices.prices.get(key)
    if value is None:
        # Trap 1, the important half: NO ROW beats a row saying $0. An unpriced
        # slab is visibly unpriced; a $0 one quietly drags every total.
        return AttachResult(False, reason=GRADE_NOT_COVERED,
                            price_source_id=price_source_id)

    confidence = prices.confidences.get(key)
    repo.set_graded_market_value(
        item.card_id, item.company, item.grade, value,
        source=_PROVIDER_SOURCE, confidence=confidence,
    )

    # The ONE field written back on the item, and it is an addressing handle,
    # not an identity claim. `model_copy` carries every other field through
    # untouched — `card_id`, `display_name`, `cert_number` and the rest are
    # exactly as the admin left them.
    if item.price_source_id != price_source_id and price_source_id:
        repo.put_inventory_item(
            item.model_copy(update={"price_source_id": price_source_id})
        )

    return AttachResult(True, value=value, confidence=confidence,
                        price_source_id=price_source_id)
