"""Read-only client for the TCGdex v2 API (multilingual card metadata + prices).

TCGdex is unauthenticated and per-language: every path is prefixed with an API
language code (``en``/``ja``). ``TcgdexClient`` wraps the HTTP calls the catalog
sync needs — listing a language's cards and fetching one card in full — with the
same retry/backoff shape the previous catalog client established.

The mappers below are pure functions over raw response dicts, so the whole
catalog layer is testable offline against committed fixtures:

- ``to_catalog_card_brief`` maps a LIST row (``{id, localId, name, image?}``) —
  identity only, since the list endpoint never carries pricing.
- ``to_catalog_card`` maps a DETAIL object, including prices.

Two shapes are easy to get wrong and are therefore funnelled through one helper
each: ``_encode_card_id`` (real ids include ``exu-!`` and ``exu-%3F``, so no call
site may build a path by f-string) and ``_map_finish`` (TCGdex spells the reverse
finish ``reverse-holofoil``; the internal vocabulary is camelCase and is a
contract four other modules already depend on). See RFC 0003 §3, §5 and §6.

**This module is the trust boundary.** TCGdex is keyless and community-editable,
so every figure, URL and string it publishes is validated here and nowhere else:
``_dec`` bounds money, ``_images`` allowlists the image host, ``_text``
NFC-normalizes names, and ``_parse_updated`` forces timestamps to aware UTC.
Nothing is clamped or substituted — a value that fails validation is treated as
**absent**, which every consumer already handles (no band → no price point → the
importer falls back to the sheet value and sets ``needs_review``).
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import unicodedata
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote, urlsplit

import httpx

from merlins_collection.models.catalog import (
    CardImages,
    CatalogCard,
    FinishPrice,
    PricePoint,
)
from merlins_collection.models.inventory import Language

logger = logging.getLogger(__name__)

# The API's own language codes. `ja` (URL) vs `JP` (domain enum) is a live
# footgun, so the rule is: the enum is for the domain, the code is for the URL,
# and the code is what goes in `card_id` — because a stored `card_id` must be
# enough on its own to rebuild the card's request path.
LANGUAGE_API_CODE = {Language.EN: "en", Language.JP: "ja"}
LANGUAGE_BY_API_CODE = {code: language for language, code in LANGUAGE_API_CODE.items()}

# TCGdex returns an extensionless, quality-less image base URL; the suffix is
# ours to append. webp is the smallest and `next/image` consumes it fine.
IMAGE_EXTENSION = "webp"

# The only host a card image may come from. `next/image` enforces this too, but
# that control is in a different language, layer and owner, and the API hands
# the raw URL to consumers that do not have it — the MCP server, Bedrock chat
# tool results, and any future client.
ALLOWED_IMAGE_HOSTS = frozenset({"assets.tcgdex.net"})

# TCGdex finish name -> internal finish name. The internal vocabulary is NOT
# changed by this mapping: `models.inventory._MARKET_FINISH_FALLBACK`,
# `scripts.build_review.FINISH_PREFERENCE` / `finish_from_source`, and every
# `PRICE#RAW#<finish>#<date>` sort key already written all speak camelCase.
# Normalization happens here, at the boundary, and nowhere else.
TCGDEX_FINISH_MAP = {
    "normal": "normal",
    "holofoil": "holofoil",
    "reverse-holofoil": "reverseHolofoil",
}

# Cardmarket's estimate of a card's CURRENT value, best first. `trend` is their
# analog of TCGplayer's `marketPrice`; the averages are long-window means of
# completed sales and lag hard on a moving card, so they are only a fallback.
_CARDMARKET_MARKET_FIELDS = ("trend", "avg7", "avg30", "avg")

# Cardmarket publishes one flat block with `-holo`-suffixed duplicates: the
# suffixed fields describe the holo print, the unsuffixed ones the normal print.
# Each internal finish maps to (field suffix, the `variants` key that CONFIRMS
# that printing exists) — the unsuffixed fields are print-agnostic, so emitting
# them for a card with no normal printing invents a band, and `normal` is first
# in both `_MARKET_FINISH_FALLBACK` and `FINISH_PREFERENCE`, so an invented
# `normal` band wins every fallback AND silences `build_review._finish_caveat`
# by satisfying it. See RFC 0003 §5.2.
#
# There is deliberately NO reverseHolofoil entry: the block does not distinguish
# reverse prints, so mapping anything onto that finish would be a guess rendered
# as a price. A reverse single backed only by Cardmarket data therefore has no
# band, which is what makes build_review's existing finish caveat fire.
_CARDMARKET_FINISHES = {"normal": ("", "normal"), "holofoil": ("-holo", "holo")}

# What makes a nested object in the TCGplayer block a finish rather than, say, a
# future metadata blob: it quotes at least one price.
_PRICE_FIELDS = frozenset({"marketPrice", "lowPrice", "midPrice", "highPrice"})

_CENTS = Decimal("0.01")
_SEPARATORS = re.compile(r"[-_]+")

# Absolute plausibility ceiling for a single upstream figure, in the provider's
# own currency. The most expensive Pokemon card ever sold publicly went for
# ~$5.3M, so a $10M ceiling rejects the 1e12 / 20-digit garbage a keyless,
# community-editable upstream can emit without rejecting a real grail.
MAX_PLAUSIBLE_PRICE = Decimal("10000000")

# No provider quoted a price before this, and nothing legitimate is stamped in
# the future. Both directions produce a nonsense staleness figure in RFC §7's
# `now - source_updated_at`, on an append-only history row that is never
# re-derivable.
_MIN_UPDATED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
_MAX_UPDATED_SKEW = timedelta(days=1)


def _dec(value) -> Decimal | None:
    """Parse an upstream money figure, or ``None`` if it is not a usable price.

    The ONE numeric boundary between a keyless upstream and a figure a customer
    transacts against (``CardTile`` renders ``marketPrice ?? item.listed_price``,
    so an upstream number can override the shop's own listed price). It rejects
    rather than repairs — nothing is clamped, nothing is substituted:

    - non-numeric (``"N/A"`` raises ``InvalidOperation``, an ``ArithmeticError``
      and therefore NOT caught by a ``ValueError`` handler one layer out);
    - ``NaN``/``Infinity``, which survive JSON, survive pydantic, and then raise
      ``TypeError`` inside boto3 at flush time — outside every per-record guard,
      destroying a whole 500-card batch;
    - non-positive, and anything quantizing to ``0.00``: a ``trend`` of ``0`` is
      observed in real Cardmarket responses and would render ``$0.00`` to a
      customer and write a permanent history row RFC §8 never sweeps;
    - anything above ``MAX_PLAUSIBLE_PRICE``.

    Rejecting a zero is not lossy: absence is the signal the whole pipeline is
    built on, and a zero is absence wearing a number.
    """
    # bool is an int subclass; `True` is not a price.
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        logger.warning("tcgdex: unparseable price figure %r", value)
        return None
    if not amount.is_finite() or amount > MAX_PLAUSIBLE_PRICE:
        logger.warning("tcgdex: implausible price figure %r", value)
        return None
    # A zero or sub-cent figure is ordinary upstream absence, not an anomaly, so
    # it is dropped without a warning — the alternative is 23k lines of noise.
    if amount <= 0 or amount.quantize(_CENTS, rounding=ROUND_HALF_UP) <= 0:
        return None
    return amount


def _text(value) -> str:
    """NFC-normalize and strip a name/label at the boundary.

    Japanese kana with dakuten have two valid encodings (``プ`` as U+30D7, or
    U+30D5 + U+309A). Both round-trip HTTP → JSON → DynamoDB → pydantic
    byte-identically, both render identically, and they are **not equal in
    Python**. RFC §3/§7 make the match key name + number + language, so an NFD
    row against an NFC sheet is permanently unmatchable — and every
    fixture-based test still passes, because the fixture and the code agree with
    each other. This is the module that already declares itself the
    normalize-here-and-nowhere-else boundary.
    """
    if not isinstance(value, str):
        raise ValueError(f"expected a text field, got {value!r}")
    return unicodedata.normalize("NFC", value).strip()


def _optional_text(value) -> str | None:
    """``_text`` for a field TCGdex may omit entirely; absent stays ``None``.

    ``None`` and ``""`` are different facts about a ``rarity`` — "upstream does
    not say" versus "upstream says it is blank" — so the absent case is passed
    through rather than flattened into empty text.
    """
    return None if value is None else _text(value)


def _text_list(value) -> list[str]:
    """``_text`` over an optional list field (``types``); absent means ``[]``.

    The ``isinstance`` check is not defensive padding: a bare string here would
    iterate into single characters, so ``"Grass"`` would land as five one-letter
    types and validate cleanly. Raising keeps the pre-normalization behavior,
    where pydantic refused a non-list outright.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"expected a list field, got {value!r}")
    return [_text(entry) for entry in value]


def _parse_updated(value) -> datetime | None:
    """Parse a provider's ISO-8601 ``updated`` stamp as aware UTC, else ``None``.

    ``fromisoformat`` accepts ``…Z`` (aware), ``…+01:00`` (aware) and
    ``…T00:00:00`` (**naive**). Storing the mix verbatim makes RFC §7's
    ``now - source_updated_at`` raise ``TypeError`` at whichever card first
    carries a naive stamp; TCGplayer and Cardmarket are separate feeds, so a
    mixed corpus is entirely plausible.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    parsed = (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None
              else parsed.astimezone(timezone.utc))
    if not _MIN_UPDATED_AT <= parsed <= datetime.now(timezone.utc) + _MAX_UPDATED_SKEW:
        logger.warning("tcgdex: discarding implausible updated stamp %r", value)
        return None
    return parsed


# ---------------------------------------------------------------------------
# identity helpers
# ---------------------------------------------------------------------------


def build_card_id(language: Language, tcgdex_id: str) -> str:
    """The composite catalog key ``"{api_lang}:{tcgdex_id}"`` (e.g. ``en:base1-4``).

    Also builds ``set_id`` from a TCGdex set id, so ``card_id ==
    f"{set_id}-{local_id}"`` keeps holding structurally across languages.
    """
    return f"{LANGUAGE_API_CODE[language]}:{tcgdex_id}"


def parse_card_id(card_id: str) -> tuple[Language, str] | None:
    """Split a composite ``card_id`` back into ``(language, tcgdex_id)``, or ``None``.

    The inverse of ``build_card_id``, and the only place the composite is taken
    apart to rebuild a request path — for the same reason ``build_card_id`` is
    the only place it is assembled. Splits on the FIRST ``:`` (mirroring
    ``dynamodb.InventoryRepository._card_language``), since a TCGdex id may
    contain one.

    ``None`` means the id is not a TCGdex composite at all: a dead
    pokemontcg.io-era row (``"xy7-54"``), or a language code this build does not
    speak. Neither is fetchable, and both are a stored-data defect for the caller
    to count and report rather than an exception to unwind a batch job with.
    """
    language_code, separator, tcgdex_id = card_id.partition(":")
    if not separator or not tcgdex_id:
        return None
    language = LANGUAGE_BY_API_CODE.get(language_code)
    return None if language is None else (language, tcgdex_id)


def _tcgdex_set_id(tcgdex_id: str, local_id: str) -> str:
    """The set id embedded in a card id, split BY LENGTH rather than by delimiter.

    ``id == f"{set_id}-{local_id}"`` always holds, but local ids can contain a
    hyphen (``swsh4-SV1-2``), so splitting on the last ``-`` is wrong. Length is
    exact and also survives the punctuation ids (``exu-!``, ``exu-%3F``).
    """
    if not local_id or not tcgdex_id.endswith(f"-{local_id}"):
        raise ValueError(f"card id {tcgdex_id!r} does not end with local id {local_id!r}")
    return tcgdex_id[: -(len(local_id) + 1)]


def _local_id(raw: dict) -> str:
    """The card's number within its set, as text.

    Explicitly ``is None`` rather than falsy: TCGdex sends ``localId`` as a bare
    integer on some rows, and a card numbered ``0`` would otherwise stringify to
    ``""`` and fail ``_tcgdex_set_id``, silently dropping the card.
    """
    local_id = raw.get("localId")
    return "" if local_id is None else str(local_id)


def _encode_card_id(tcgdex_id: str) -> str:
    """Percent-encode a card id for use as a URL path segment.

    The ONLY place an id is interpolated into a path. Real ids contain ``!`` and
    ``%``, and the id is treated as literal characters (so a reported ``exu-%3F``
    is requested as ``exu-%253F``).
    """
    return quote(tcgdex_id, safe="")


# ---------------------------------------------------------------------------
# price helpers
# ---------------------------------------------------------------------------


def _map_finish(tcgdex_finish: str) -> str:
    """Normalize a TCGdex finish key into the internal finish vocabulary.

    Known keys are mapped explicitly; unknown ones are camelized rather than
    dropped (silent data loss) or forced into a known key (inventing a band), so
    a future ``first-edition-holofoil`` lands as ``firstEditionHolofoil``.

    Raises on a key containing ``#`` or on one that normalizes to nothing —
    either would corrupt the ``PRICE#RAW#<finish>#<date>`` sort key.
    """
    if "#" in tcgdex_finish:
        raise ValueError(f"finish key would corrupt a price sort key: {tcgdex_finish!r}")
    mapped = TCGDEX_FINISH_MAP.get(tcgdex_finish)
    if mapped is not None:
        return mapped
    head, *rest = _SEPARATORS.split(tcgdex_finish.strip())
    camelized = head + "".join(part[:1].upper() + part[1:] for part in rest)
    if not camelized:
        raise ValueError(f"finish key normalizes to nothing: {tcgdex_finish!r}")
    return camelized


def _convert_eur_to_usd(amount: Decimal, rate: Decimal) -> Decimal:
    """Convert a Cardmarket EUR figure to USD, rounded to cents."""
    return (amount * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _tcgplayer_prices(block: dict) -> dict[str, FinishPrice]:
    """Map ``pricing.tcgplayer`` (USD) into per-finish bands.

    Finish keys are ITERATED, not enumerated — the provider adds new ones and
    the known list would silently drop them — so any nested object carrying at
    least one price field is treated as a finish.

    A band is stored only when the provider published a ``market`` figure. A
    market-less band renders nothing, ``build_review._latest`` filters it out,
    and keeping it would cost a write plus a permanent history row carrying no
    price — while also making ``_prices_from_pricing`` treat the card as priced
    and skip the Cardmarket fallback. TCGplayer quoting ``lowPrice: 0.11`` with a
    null ``marketPrice`` is routine for thin-liquidity singles, so that is a live
    path, not a hypothetical one (RFC 0003 §5.1).

    TCGplayer names the finish it is quoting, so — unlike Cardmarket's flat
    block — these bands need no corroboration from ``variants``.
    """
    unit = block.get("unit")
    if unit != "USD":
        raise ValueError(f"expected TCGplayer prices in USD, got {unit!r}")
    updated = _parse_updated(block.get("updated"))
    prices: dict[str, FinishPrice] = {}
    for key, value in block.items():
        if not isinstance(value, dict) or not _PRICE_FIELDS & value.keys():
            continue
        market = _dec(value.get("marketPrice"))
        if market is None:
            continue  # no current-value estimate: not a price we can show
        prices[_map_finish(key)] = FinishPrice(
            market=market,
            low=_dec(value.get("lowPrice")),
            mid=_dec(value.get("midPrice")),
            high=_dec(value.get("highPrice")),
            source="tcgplayer",
            source_currency="USD",
            source_updated_at=updated,
        )
    return prices


def _cardmarket_prices(block: dict, fx_rate: Decimal, variants) -> dict[str, FinishPrice]:
    """Map ``pricing.cardmarket`` (EUR) into per-finish bands, converted to USD.

    Cardmarket publishes ONE flat block per card and does not name the printing
    it is quoting: the ``-holo`` fields describe the holo print and the
    unsuffixed ones are print-agnostic. Emitting an unsuffixed figure as a
    ``normal`` band therefore invents a printing on a holo-only card — and
    ``normal`` is first in both ``models.inventory._MARKET_FINISH_FALLBACK`` and
    ``scripts.build_review.FINISH_PREFERENCE``, so the invented band wins every
    fallback AND silences ``build_review._finish_caveat`` by satisfying it: the
    invented data suppresses the warning that exists to catch invented data.

    So a band is emitted only when the card's own ``variants`` block confirms
    that printing exists. ``variants`` travels in the same payload and is
    otherwise read by nothing. When it is absent the printing is unconfirmed and
    no band is emitted — absence is the signal, and a wrong price is worse than
    no price (RFC 0003 §5.2).

    Every converted figure carries a ``value_note`` naming the original amount,
    the Cardmarket field it came from, and the rate applied, so it is auditable
    and re-derivable if the rate ever changes.
    """
    unit = block.get("unit")
    if unit != "EUR":
        raise ValueError(f"expected Cardmarket prices in EUR, got {unit!r}")
    updated = _parse_updated(block.get("updated"))
    confirmed = variants if isinstance(variants, dict) else {}
    prices: dict[str, FinishPrice] = {}
    for finish, (suffix, variant_key) in _CARDMARKET_FINISHES.items():
        if confirmed.get(variant_key) is not True:
            continue  # this printing is not confirmed to exist; do not invent it
        market_eur = field_used = None
        for field in _CARDMARKET_MARKET_FIELDS:
            market_eur = _dec(block.get(f"{field}{suffix}"))
            if market_eur is not None:
                field_used = field
                break
        if market_eur is None:
            continue  # Cardmarket published no current-value estimate for this print
        low_eur = _dec(block.get(f"low{suffix}"))
        mid_eur = _dec(block.get(f"avg{suffix}"))
        prices[finish] = FinishPrice(
            market=_convert_eur_to_usd(market_eur, fx_rate),
            low=None if low_eur is None else _convert_eur_to_usd(low_eur, fx_rate),
            mid=None if mid_eur is None else _convert_eur_to_usd(mid_eur, fx_rate),
            # Cardmarket publishes no high; synthesizing one would invent data.
            high=None,
            source="cardmarket",
            source_currency="EUR",
            source_updated_at=updated,
            value_note=(
                f"converted from EUR {market_eur.quantize(_CENTS)} "
                f"(cardmarket {field_used}) at EUR_USD_RATE={fx_rate}"
            ),
        )
    return prices


def _prices_from_pricing(pricing, fx_rate: Decimal, variants=None) -> dict[str, FinishPrice]:
    """Apply the provider preference: TCGplayer USD first, else Cardmarket EUR.

    The preference is applied at CARD level, not per finish: Cardmarket's block
    is print-agnostic, so merging it into a card TCGplayer already priced would
    manufacture bands for printings that do not exist (RFC 0003 §5.2, amended to
    match its own worked example). The predicate is **"did TCGplayer produce a
    market figure"**, not "did TCGplayer publish anything" — a band with a
    ``lowPrice`` and a null ``marketPrice`` is not a price, and treating it as
    one leaves the card showing nothing while a complete Cardmarket figure sits
    one branch away.

    Each provider is parsed inside its own guard so a metadata failure costs
    **that provider** its bands and nothing else. A missing/relabelled ``unit``
    still hard-fails the block it belongs to — never silently relabelling a EUR
    figure as USD — but it no longer discards the other provider's valid prices,
    and it no longer escapes to take the card's whole identity row with it.
    """
    if not isinstance(pricing, dict):
        return {}
    for provider, parse in (
        ("tcgplayer", lambda block: _tcgplayer_prices(block)),
        ("cardmarket", lambda block: _cardmarket_prices(block, fx_rate, variants)),
    ):
        block = pricing.get(provider)
        if not isinstance(block, dict):
            continue
        try:
            prices = parse(block)
        except (ValueError, ArithmeticError):
            logger.warning("tcgdex: discarding unusable %s price block", provider)
            continue
        if prices:
            return prices
    return {}


def _images(raw: dict) -> CardImages:
    """Build the sized image URLs, or empty ones when ``image`` is absent or hostile.

    The base URL is upstream-controlled text, so it is host-checked here. The web
    UI is covered by ``next/image``'s own allowlist, but that control is in a
    different language, layer and owner, and **the API hands the raw URL to every
    consumer that is not ``next/image``** — the MCP server, Bedrock chat tool
    results, and any future client. A URL that fails the check is dropped, not
    rewritten: ``CardImages.small`` already defaults to ``""`` and an absent image
    is a fact to render around.
    """
    base = raw.get("image")
    if not isinstance(base, str) or not base:
        return CardImages()
    parts = urlsplit(base)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_IMAGE_HOSTS:
        logger.warning("tcgdex: dropping image URL from unexpected host %r", base)
        return CardImages()
    return CardImages(
        small=f"{base}/low.{IMAGE_EXTENSION}",
        large=f"{base}/high.{IMAGE_EXTENSION}",
    )


# ---------------------------------------------------------------------------
# mappers
# ---------------------------------------------------------------------------


def to_catalog_card_brief(
    raw: dict,
    language: Language,
    *,
    set_names: dict[str, str] | None = None,
    synced_at: datetime | None = None,
) -> CatalogCard:
    """Map a LIST row into an identity-only ``CatalogCard`` (``detail="brief"``).

    The list endpoint returns ``{id, localId, name, image?}`` and never carries
    pricing, so a brief row has no prices by construction. ``set_names`` (from
    ``list_sets``) supplies the display name; without it ``set_name`` is empty,
    which degrades display but not matching — the match key is name + number +
    language.
    """
    tcgdex_id = raw["id"]
    local_id = _local_id(raw)
    raw_set_id = _tcgdex_set_id(tcgdex_id, local_id)
    return CatalogCard(
        card_id=build_card_id(language, tcgdex_id),
        language=language,
        name=_text(raw["name"]),
        set_id=build_card_id(language, raw_set_id),
        set_name=_text((set_names or {}).get(raw_set_id, "")),
        number=local_id,
        images=_images(raw),
        detail="brief",
        last_synced_at=synced_at or datetime.now(timezone.utc),
    )


def to_catalog_card(
    raw: dict,
    language: Language,
    *,
    fx_rate: Decimal,
    synced_at: datetime | None = None,
) -> CatalogCard:
    """Map a DETAIL object into a fully hydrated ``CatalogCard``.

    Tolerates every optional block TCGdex omits in practice — ``pricing``,
    ``pricing.tcgplayer``, ``pricing.cardmarket`` and ``image`` can each be
    absent or null, and older EX/full-art cards carry none of them. A card with
    no price maps to no bands rather than a zero or a null-market band: absence
    in the catalog is the signal the importer falls back on.
    """
    tcgdex_id = raw["id"]
    local_id = _local_id(raw)
    card_set = raw.get("set") or {}
    raw_set_id = card_set.get("id") or _tcgdex_set_id(tcgdex_id, local_id)
    return CatalogCard(
        card_id=build_card_id(language, tcgdex_id),
        language=language,
        name=_text(raw["name"]),
        set_id=build_card_id(language, raw_set_id),
        set_name=_text(card_set.get("name", "")),
        number=local_id,
        rarity=_optional_text(raw.get("rarity")),
        types=_text_list(raw.get("types")),
        images=_images(raw),
        prices=_prices_from_pricing(raw.get("pricing"), fx_rate, raw.get("variants")),
        detail="full",
        last_synced_at=synced_at or datetime.now(timezone.utc),
    )


def to_price_points(card: CatalogCard, today: date) -> list[PricePoint]:
    """One dated raw history point per priced finish, provenance carried through."""
    return [
        PricePoint(
            card_id=card.card_id,
            date=today,
            source=band.source or "tcgdex",
            kind="raw",
            finish=finish,
            market=band.market,
            low=band.low,
            mid=band.mid,
            high=band.high,
            currency=band.currency,
            source_currency=band.source_currency,
            source_updated_at=band.source_updated_at,
            value_note=band.value_note,
        )
        for finish, band in card.prices.items()
    ]


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


# A hostile or broken `Retry-After` must not park the seed for a day.
_MAX_RETRY_AFTER_SECONDS = 60.0


def _retry_after_seconds(header) -> float | None:
    """Parse a ``Retry-After`` delay-seconds header, capped, else ``None``.

    Only the delay-seconds form is honored; the HTTP-date form is rare in
    practice and guessing at clock skew would be worse than backing off normally.
    """
    if header is None:
        return None
    try:
        seconds = float(header)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, _MAX_RETRY_AFTER_SECONDS)


class TcgdexError(RuntimeError):
    """A TCGdex request failed; ``status_code`` is the last HTTP status seen."""

    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class TcgdexClient:
    """HTTP client for TCGdex v2 (no auth, no API key).

    The ``client`` is injectable for tests; ``page_size``/``max_retries``/
    ``backoff_base`` tune paging and the retry schedule.
    ``request_delay_seconds`` paces successful requests — no rate limiting has
    been observed, so this is courtesy toward a free volunteer-run service, and
    it is set to 0 in tests.
    """

    BASE_URL = "https://api.tcgdex.net/v2"

    def __init__(self, *, client=None, page_size=100_000, max_retries=3,
                 backoff_base=0.5, request_delay_seconds=0.1, max_pages=1_000,
                 max_response_bytes=64 * 1024 * 1024, total_deadline_seconds=300.0):
        self._client = client or httpx.Client(
            base_url=self.BASE_URL,
            # `timeout=30.0` alone is httpx's per-READ timeout — the maximum gap
            # BETWEEN socket reads, not a deadline. An origin dribbling one byte
            # every 25s holds the connection open forever; `_read_bounded`
            # enforces the actual deadline.
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
            # Correct today only by httpx's default, which an upgrade could flip.
            follow_redirects=False,
        )
        self._page_size = page_size
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._request_delay_seconds = request_delay_seconds
        self._max_pages = max_pages
        self._max_response_bytes = max_response_bytes
        self._total_deadline_seconds = total_deadline_seconds

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        self._client.close()

    def _read_bounded(self, resp, path, deadline) -> bytes:
        """Stream the body, refusing one that is too large or too slow.

        Bounded as it arrives rather than after the fact: the normal payload is
        ~2.36 MB and an unbounded ``resp.json()`` would OOM the process on a
        runaway response with no diagnostic. Both limits are hard failures, not
        retryable ones — neither improves by asking again.
        """
        body = bytearray()
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) > self._max_response_bytes:
                raise TcgdexError(
                    f"response body for {path} exceeded "
                    f"{self._max_response_bytes} bytes; refusing to buffer it"
                )
            if time.monotonic() > deadline:
                raise TcgdexError(
                    f"request for {path} exceeded its "
                    f"{self._total_deadline_seconds}s total deadline"
                )
        return bytes(body)

    def _retry_delay(self, attempt, retry_after):
        """Back off, honoring ``Retry-After`` and adding jitter.

        Jitter scales with ``backoff_base`` so tests that set it to 0 stay
        instant while production never synchronizes its retries.
        """
        if retry_after is not None:
            return retry_after + random.uniform(0, 1.0)
        base = self._backoff_base * (2 ** attempt)
        return base + random.uniform(0, self._backoff_base)

    def _get(self, path, params=None):
        """GET ``path`` and decode it, retrying 429/5xx/undecodable-200.

        The JSON decode is INSIDE the retry-protected block. ``JSONDecodeError``
        subclasses ``ValueError``, not ``httpx.HTTPError``, so a ``200
        text/html`` — a Cloudflare interstitial, a maintenance page, a captcha,
        which is the single most common way a free API fails without failing —
        used to escape this loop, escape ``get_card``'s 404→``None`` contract,
        and escape ``TcgdexError`` entirely, missing every caller's
        ``except TcgdexError``. A truncated body got zero retries despite being
        the most retryable failure there is.
        """
        deadline = time.monotonic() + self._total_deadline_seconds
        last_exc = None
        for attempt in range(self._max_retries):
            retry_after = None
            try:
                with self._client.stream("GET", path, params=params) as resp:
                    if resp.status_code != 200:
                        err = TcgdexError(f"HTTP {resp.status_code} for {path}",
                                          status_code=resp.status_code)
                        if resp.status_code != 429 and resp.status_code < 500:
                            raise err
                        retry_after = _retry_after_seconds(resp.headers.get("retry-after"))
                        last_exc = err
                    else:
                        body = self._read_bounded(resp, path, deadline)
                        payload = json.loads(body)
                        if self._request_delay_seconds:
                            time.sleep(self._request_delay_seconds)
                        return payload
            except httpx.HTTPError as exc:
                last_exc = exc
            except json.JSONDecodeError as exc:
                logger.warning("tcgdex: %s returned a 200 that is not JSON", path)
                last_exc = exc
            if attempt < self._max_retries - 1:
                time.sleep(self._retry_delay(attempt, retry_after))
        raise TcgdexError(
            f"giving up on {path}", status_code=getattr(last_exc, "status_code", None)
        ) from last_exc

    def iter_brief_cards(self, language: Language) -> Iterator[dict]:
        """Yield every BRIEF card row for a language.

        End-of-list is an **empty page**, deliberately independent of the
        requested page size. Using "shorter than ``page_size``" as the sentinel
        conflates two different facts, and the day TCGdex adds a server-side
        ``itemsPerPage`` cap — rated Medium in RFC 0003's own risk table, and the
        single most likely thing a struggling free API does — the first capped
        page reads as end-of-list. The seed would then report
        ``{"cards_seeded": 250, "failures": 0}`` and exit 0 on 250 of ~23,444
        cards, and the symptom would present as "the matcher got worse", not
        "the seed stopped".

        An empty page is still only ONE untrusted response, so it is not taken
        on the first answer: the same page is re-requested once, immediately,
        and end-of-list is declared only if the confirmation is also empty. A
        transient blank page mid-catalog would otherwise end the walk *cleanly*
        — no exception, no non-zero exit — and commit a truncated generation.

        Two rails cover the inverse failure. A page whose rows have all been
        seen means the server is ignoring ``pagination:page`` — left alone that
        loops forever, re-yielding the same rows into
        ``batch_upsert_catalog_cards`` for an unbounded DynamoDB write bill on a
        third-party trigger. And ``max_pages`` bounds the walk absolutely.
        Both RAISE: a truncated catalog must never look like a successful run.
        """
        code = LANGUAGE_API_CODE[language]
        seen: set[str] = set()
        for page in range(1, self._max_pages + 1):
            params = {"pagination:page": page,
                      "pagination:itemsPerPage": self._page_size}
            rows = self._get(f"/{code}/cards", params=params)
            if not rows:
                # Confirm the sentinel once before trusting it. `_get` already
                # retries transport failures and non-200s; this covers the case
                # it cannot see — a well-formed `200 []` that is simply wrong.
                logger.warning("tcgdex: /%s/cards page %s came back empty; "
                               "confirming before ending the walk", code, page)
                rows = self._get(f"/{code}/cards", params=params)
                if not rows:
                    return
            fresh = [row for row in rows if row.get("id") not in seen]
            if not fresh:
                raise TcgdexError(
                    f"/{code}/cards page {page} repeated rows already seen; the "
                    f"server is ignoring `pagination:page` — aborting rather "
                    f"than looping forever"
                )
            seen.update(row.get("id") for row in fresh)
            yield from fresh
        raise TcgdexError(
            f"/{code}/cards hit the hard page ceiling ({self._max_pages} pages) "
            f"without returning an empty page"
        )

    def list_sets(self, language: Language) -> list[dict]:
        """All sets for a language (bare array of ``{id, name, …}``)."""
        return self._get(f"/{LANGUAGE_API_CODE[language]}/sets") or []

    def get_card(self, language: Language, tcgdex_id: str) -> dict | None:
        """Fetch one card in full; return ``None`` on 404, raise on other errors."""
        code = LANGUAGE_API_CODE[language]
        try:
            return self._get(f"/{code}/cards/{_encode_card_id(tcgdex_id)}")
        except TcgdexError as exc:
            if exc.status_code == 404:
                return None
            raise
