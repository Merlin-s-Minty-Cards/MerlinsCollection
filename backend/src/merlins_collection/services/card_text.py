"""Text-level facts about a card: normalization and print language.

One contract, one implementation. Both the review page (which *produces* a
paste-back block) and the decision applier (which *consumes* one) compare card
names and numbers, and in R7 they did it with two functions that disagreed:
``HS—Unleashed`` normalized to ``hsunleashed`` at one end and ``hs unleashed`` at
the other, because one dropped non-ASCII before splitting words and the other
split first. Splitting first is the correct order — an em dash separates two
words, it is not a character to delete — so that is what lives here, and both
ends import it (Council R7 BLOCKER-9).

The language half is here for the same reason: an item's language must be decided
identically by the importer, the review page, the applier and the backfill, or
they disagree about which catalog cards an item may be matched against. Since the
catalog moved to TCGdex it holds Japanese printings alongside English ones, so
language is no longer a gate that rules the catalog out entirely — it is part of
a card's identity, and a match is valid only when item and catalog card agree on
it (a JP item belongs to a JP card, never its English twin).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from merlins_collection.models.inventory import ITEM_TEXT_FIELD, Language

__all__ = [
    "ITEM_TEXT_FIELD", "LANGUAGE_MARKER_RE", "CatalogIndex", "SourceText",
    "build_catalog_index", "coerce_language", "core_name", "format_display_name",
    "item_language", "language_from_set", "language_from_url", "normalize_name",
    "normalize_number", "number_keys", "parse_language", "parse_source_text",
    "set_hint_from_url",
    "sets_agree", "strip_float_artifact",
]


# --- identifier + name normalization -------------------------------------

def strip_float_artifact(text) -> str:
    """Undo Excel's float export: ``"83.0"`` -> ``"83"``, ``"83.5"`` unchanged.

    Card numbers and PSA cert numbers came through the CSV export as floats, so
    they are stored as ``"1400665984.0"``. Matching on the raw string fails
    against a catalog that stores ``"83"``.
    """
    raw = "" if text is None else str(text).strip()
    if re.fullmatch(r"-?\d+\.0+", raw):
        return raw.split(".")[0]
    return raw


def normalize_name(text) -> str:
    """Casefold to bare alphanumeric words: ``"Moltres & Zapdos-GX"`` ->
    ``"moltres zapdos gx"``.

    Every non-alphanumeric character becomes a separator **before** non-ASCII is
    dropped, so ``HS—Unleashed`` (em dash) and ``HS-Unleashed`` (hyphen) both give
    ``"hs unleashed"`` instead of the dash silently vanishing and welding the two
    words together. Callers comparing two normalized names must treat an empty
    result as "no evidence" rather than a match — a fully non-ASCII name (a
    Japanese catalog would be full of them) normalizes to ``""``.
    """
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    spaced = "".join(ch if ch.isalnum() else " " for ch in decomposed)
    ascii_text = spaced.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def normalize_number(text) -> str:
    """A card number ready to compare: float artifact undone, casefolded.

    Deliberately does NOT go through ``normalize_name``: a collector number's
    punctuation is load-bearing. The sheet writes ``"182/167"`` and the catalog
    stores ``"182"``, so callers reduce the slash form themselves — turning the
    slash into a space here would leave them nothing to split on.
    """
    return strip_float_artifact(text).strip().lower()


# Words that describe the *finish* of a printing, not the card. The sheet writes
# "Dragonite-Holo"; the catalog calls that card "Dragonite". Dropping these to
# find a match costs no confidence.
_FINISH_TOKENS = frozenset({
    "holo", "holofoil", "foil", "reverse", "rev", "nonholo", "non", "unlimited",
    "cosmos", "sealed", "graded",
})

# Words that can mean a materially DIFFERENT card (a gold secret rare, a
# 1st-edition). They are dropped for lookup, because the catalog name never
# carries them — but a match that needed one dropped is a different print at a
# different price. Language words are deliberately NOT here: language gates the
# lookup entirely (see the importer / review page) rather than being dropped.
_QUALIFIER_TOKENS = frozenset({
    "1st", "first", "ed", "edition", "shadowless", "promo", "staff",
    "full", "art", "fullart", "alt", "alternate", "rainbow", "gold", "secret",
    "eng", "english",
})

_VARIANT_TOKENS = _FINISH_TOKENS | _QUALIFIER_TOKENS


def core_name(text) -> str:
    """``normalize_name`` with printing/finish words removed (``dragonite holo``
    -> ``dragonite``). Falls back to the full name if everything got stripped."""
    tokens = [t for t in normalize_name(text).split() if t not in _VARIANT_TOKENS]
    return " ".join(tokens) or normalize_name(text)


def number_keys(number: str) -> list[str]:
    """Every form of a card number worth matching on, most literal first.

    The sheet writes collector numbers as ``"182/167"`` and pads with zeros; no
    catalog number contains a slash, so the part before it is the real number.
    """
    if not number:
        return []
    keys: list[str] = []
    for form in (number, number.split("/", 1)[0].strip()):
        for key in (form, form.lstrip("0")):
            if key and key not in keys:
                keys.append(key)
    return keys


def _set_tokens(text) -> frozenset[str]:
    return frozenset(normalize_name(text).split())


def sets_agree(source_set: str, catalog_set: str) -> bool:
    """True when one set label is contained in the other, token-wise.

    The sheet writes things like "XY single pack Blister" for a card the catalog
    files under "XY", so equality is too strict; substring is too loose ("XY"
    would swallow "XY Evolutions"). Token containment threads the needle.
    """
    src, cat = _set_tokens(source_set), _set_tokens(catalog_set)
    if not src or not cat:
        return False
    return src <= cat or cat <= src


# A tcgplayer product URL: ``/product/<id>/<slug>`` where the slug leads with the
# set. We keep only the slug (dropping the ``pokemon`` prefix) so ``sets_agree``
# can token-contain a catalog set name inside it. The slug also carries the card
# name and number, but those are harmless extra tokens for containment.
_TCG_PRODUCT_RE = re.compile(r"/product/\d+/([a-z0-9-]+)", re.IGNORECASE)


def set_hint_from_url(url) -> str:
    """A set-ish hint pulled from a tcgplayer product URL, for tie-breaking.

    The Singles tab has no Set column, so a name+number that several sets share
    can't be resolved — but the row's TCGplayer link does carry the set in its
    path slug: ``/product/517020/pokemon-sv-scarlet-and-violet-151-dragonair-181-165``
    -> ``"sv scarlet and violet 151 dragonair 181 165"``, inside which the catalog
    set name "Scarlet & Violet 151" is token-contained. Returns ``""`` for a URL
    that isn't a recognizable tcgplayer product link, so callers treat it as "no
    set text" (no gating) exactly as before.
    """
    match = _TCG_PRODUCT_RE.search(str(url or ""))
    if not match:
        return ""
    slug = re.sub(r"^pokemon-", "", match.group(1).lower())
    return " ".join(slug.replace("-", " ").split())


# --- catalog index (shared producer for the importer's matcher) ----------

@dataclass(frozen=True)
class CatalogIndex:
    """Normalized lookup structures over catalog cards, keyed identically to the
    review page's index so the importer and the review page normalize the same.

    ``by_name_number[(normalize_name, num_key, language)] -> [card]`` and
    ``by_core_number[(core_name, num_key, language)] -> [card]`` for each
    ``number_keys`` form. Both maps are plain dicts, so ``.get(key, [])`` is a
    safe miss.

    ``by_card_id[card_id] -> card`` is the direct identity lookup (one card, not
    a list — ``card_id`` is the catalog's primary key). It exists so a caller
    holding an ALREADY-RESOLVED id (the enriched importer path) can prove that id
    actually exists in the catalog before storing a reference to it.

    Language is part of the KEY, not a post-hoc filter over the hits. Since the
    catalog became multilingual a JP printing and its EN twin share a name and a
    number, so filtering afterwards would turn a previously unique EN hit into an
    ambiguous pair the moment the JP twin was seeded — and a JP row would silently
    borrow the EN card's identity (and its price). Keying on language keeps the
    two lookups completely independent.
    """

    by_name_number: dict = field(default_factory=dict)
    by_core_number: dict = field(default_factory=dict)
    by_card_id: dict = field(default_factory=dict)


def coerce_language(value) -> Language:
    """Read a language off a catalog card / sheet value, defaulting to ``EN``.

    Records written before the field existed, and raw DynamoDB dicts holding the
    plain string ``"JP"``, both have to land on the same ``Language`` member as a
    pydantic model's enum — otherwise a stored card and a lookup key stringify
    differently and the index misses.
    """
    if isinstance(value, Language):
        return value
    try:
        return Language(str(value or Language.EN.value).upper())
    except ValueError:
        return Language.EN


def build_catalog_index(cards) -> CatalogIndex:
    """Build the normalized catalog index the importer's ``_match_card`` reads.

    Single source of truth: keying every catalog card through ``normalize_name``,
    ``core_name``, ``number_keys`` and its print ``language`` here is what lets an
    Excel float artifact (``"181.0"``), a slash form (``"182/167"``) or
    name-punctuation drift resolve to the catalog's stored ``"181"`` /
    ``"Dragonair"`` at lookup time — in the right language.
    """
    by_name_number: dict = defaultdict(list)
    by_core_number: dict = defaultdict(list)
    by_card_id: dict = {}
    for card in cards:
        name = normalize_name(_field(card, "name"))
        core = core_name(_field(card, "name"))
        number = normalize_number(_field(card, "number"))
        language = coerce_language(_field(card, "language"))
        by_card_id[_field(card, "card_id")] = card
        for key in number_keys(number):
            by_name_number[(name, key, language)].append(card)
            by_core_number[(core, key, language)].append(card)
    return CatalogIndex(dict(by_name_number), dict(by_core_number), by_card_id)


# --- print language ------------------------------------------------------

# Every spelling of a language marker the sheet uses, mapped to its language.
# Adding a language is one row here plus one ``Language`` member; a single
# compiled pattern then covers them all, so no dict-ordering rule decides which
# language wins (Council R7, Architect M3).
_TOKEN_LANGUAGE = {
    "jp": Language.JP,
    "jpn": Language.JP,
    "japan": Language.JP,
    "japanese": Language.JP,
}

# TCGplayer files non-English product under its own category slug. This is an
# INDEPENDENT signal — a different column, written by a different system — which
# is what makes it usable to check the text parser rather than merely restate it
# (Council R7 BLOCKER-8).
_URL_LANGUAGE = {"pokemon-japan": Language.JP}

# The same links also carry an explicit ``?Language=`` filter. It resolves the one
# case the path slug cannot: a bare ``/product/<id>`` with no set/name slug at all.
# Its values in the real sheet are only "English", "Japanese" and "all" — and
# "all" is NOT a language, it is TCGplayer saying "every language of this product
# is listed under one id". The real row "Giovanni's Exile" is an ENGLISH card
# filed under ``Language=all``, so anything not naming a language reads as EN and
# only the slug may promote a card to JP.
_QUERY_LANGUAGE_RE = re.compile(r"[?&]language=([a-z]+)", re.IGNORECASE)

# Sets that exist ONLY as a Japanese printing. Some slab rows carry no marker in
# either the name or the set cell and are identifiable as Japanese by their SET
# alone (real 7-25 rows: "Seismitoad"/SV11B, "Bubble Mew EX"/"Shiny Treasure EX").
# This is a deliberately small, data-driven allowlist over sets the sheet actually
# uses — not a general JP-set database. Extend it when a new JP-only set appears;
# an unknown set stays EN rather than guessing.
_JP_SET_CODES = frozenset({"sv11b"})
_JP_SET_NAMES = ("shiny treasure ex",)

_TOKENS = "|".join(sorted(_TOKEN_LANGUAGE, key=len, reverse=True))

# A marker counts when it is bracketed — "(jp)", "[JP]" — or delimited: not
# preceded by a LETTER and not followed by a letter or digit.
#
# The left boundary rejects letters but allows digits, so the live production
# rows reading "WCS23JP" (Worlds 2023 Japanese) are caught while "1stjp", "jpeg"
# and "Jpop" are not. The right boundary still rejects digits, which is what
# keeps "jpn2" and "xxx_JP88yyy" out. Verified against all 1266 production
# records: catches 106, zero false positives.
LANGUAGE_MARKER_RE = re.compile(
    rf"(?:[(\[]\s*(?P<bracketed>{_TOKENS})\s*[)\]])"
    rf"|(?<![A-Za-z])(?P<bare>{_TOKENS})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def parse_language(text) -> tuple[Language, str]:
    """Split a card-name cell into ``(language, text with the marker removed)``.

    ``"Team Rocket's Mewtwo (jp)"`` -> ``(JP, "Team Rocket's Mewtwo")``. Text with
    no recognised marker comes back untouched as ``EN`` — the marker is the only
    thing ever removed, so other qualifiers ("1st", "holo", "(Delta Species)")
    survive.

    Two deliberate conservatisms: a marker must be bracketed or delimited (see
    ``LANGUAGE_MARKER_RE``), and if stripping would leave nothing at all the
    original text is kept — a row whose entire name is "(jp)" still records its
    language, but we never destroy the only identity it has.

    Note it normalizes whitespace across the whole string and trims leading and
    trailing dashes, not only around the marker.
    """
    raw = "" if text is None else str(text)
    match = LANGUAGE_MARKER_RE.search(raw)
    if match is None:
        return Language.EN, raw
    token = (match.group("bracketed") or match.group("bare")).lower()
    language = _TOKEN_LANGUAGE[token]
    cleaned = " ".join(LANGUAGE_MARKER_RE.sub(" ", raw).split()).strip(" -—–")
    return language, cleaned or raw


def language_from_url(url) -> Language:
    """The language implied by a product URL, else ``EN``.

    Two signals, slug first: the category slug (``pokemon-japan``), then the
    explicit ``?Language=`` filter. Only these two count, so a product whose
    *name* happens to contain "japanese" is not mistaken for a Japanese printing,
    and a slug-identified JP card is not demoted by an ambiguous
    ``Language=all`` sitting in the same query string.
    """
    lowered = str(url or "").lower()
    for slug, language in _URL_LANGUAGE.items():
        if slug in lowered:
            return language
    match = _QUERY_LANGUAGE_RE.search(lowered)
    if match:
        return _TOKEN_LANGUAGE.get(match.group(1), Language.EN)
    return Language.EN


def language_from_set(set_text) -> Language:
    """The language implied by a set name/code alone, else ``EN``.

    The last resort, for rows carrying no marker and no URL: two real slab rows
    are Japanese only by set. Matching is token-wise over ``normalize_name``, so
    it works equally on a bare set cell ("SV11B") and on the whole stored text a
    slab's ``notes`` becomes ("Seismitoad — SV11B #109.0"). An unrecognized set
    is ``EN`` — the allowlist never guesses.
    """
    normalized = normalize_name(set_text)
    if not normalized:
        return Language.EN
    if _JP_SET_CODES & set(normalized.split()):
        return Language.JP
    padded = f" {normalized} "
    if any(f" {name} " in padded for name in _JP_SET_NAMES):
        return Language.JP
    return Language.EN


def _field(record, name):
    """Read an attribute from either a raw DynamoDB dict or a pydantic item."""
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def item_language(record) -> Language:
    """The print language of one stored inventory record.

    Three sources, most authoritative first:

    1. the stored ``language`` attribute, once the backfill has written it;
    2. **the whole** of the record's card-name text — for a graded slab that is
       ``"<name> — <set> #<number>"``, and the marker is often in the *set* half
       (``"Pikachu — jp 151 #173.0"``), which is precisely the case R7 missed;
    3. the TCGplayer URL, which identifies three live rows carrying no marker at
       all;
    4. the SET named inside that same text, for the slab rows that carry no
       marker and no URL and are Japanese only by which set they are from.

    Deciding it here, from the record, means the review page, the applier and the
    backfill cannot disagree — and it works on records written before the
    ``language`` field existed, which is all 1489 of them.
    """
    stored = str(_field(record, "language") or Language.EN.value).upper()
    if stored != Language.EN.value:
        try:
            return Language(stored)
        except ValueError:
            return Language.EN
    kind = str(_field(record, "kind") or "raw")
    text = _field(record, ITEM_TEXT_FIELD.get(kind, "notes"))
    language, _ = parse_language(text)
    if language is not Language.EN:
        return language
    url_language = language_from_url(_field(record, "tcg_url"))
    if url_language is not Language.EN:
        return url_language
    return language_from_set(text)


# --- recovering the sheet's own text from a stored record ----------------

_NOTE_SEPARATORS = (" \u2014 ", " - ", " \u2013 ")


@dataclass(frozen=True)
class SourceText:
    """The name / card # / set text the importer preserved from the sheet."""

    name: str
    number: str = ""
    set_name: str = ""
    extra: str = ""
    language: str = Language.EN.value


def _note_segments(notes) -> list[str]:
    text = str(notes or "").strip()
    if not text:
        return []
    for sep in _NOTE_SEPARATORS:
        if sep in text:
            return [s.strip() for s in text.split(sep) if s.strip()]
    return [text]


def _split_name_number(text: str) -> tuple[str, str]:
    name, sep, number = text.rpartition(" #")
    if not sep:
        return text.strip(), ""
    return name.strip(), normalize_number(number)


def parse_source_text(item) -> SourceText:
    """Recover the sheet's original name/number/set for one inventory item.

    The importer stored it in ``notes``: ``"<name> #<card#>"`` for a single and
    ``"<name> - <set> #<card#>"`` for a slab (the slab tab has a Set column, the
    singles tab does not - which is exactly why singles are hard to match).

    Language comes from ``item_language`` over the WHOLE record - every text
    field, the TCGplayer URL and the stored attribute - not from re-reading one
    segment. R7 language-checked only the name half of a slab's notes, so
    ``"Pikachu - jp 151 #173.0"`` read as English and the review page recommended
    an English card while quoting that very ``jp`` as supporting evidence. Each
    segment is then cleaned of its marker for display.

    This lives beside the normalizers because both ends of a review round trip
    need it: the page derives its candidates from it, and the applier checks a
    decision against it before writing.
    """
    language = item_language(item)
    kind = str(_field(item, "kind") or "")
    if kind in ("sealed", "bulk"):
        field = ITEM_TEXT_FIELD.get(kind, "notes")
        name = parse_language(str(_field(item, field) or "").strip())[1]
        return SourceText(name=name, language=language.value)

    segments = [parse_language(s)[1] for s in _note_segments(_field(item, "notes"))]
    if not segments:
        return SourceText(name="", language=language.value)
    if kind == "graded" and len(segments) >= 2:
        set_name, number = _split_name_number(segments[1])
        return SourceText(name=segments[0], number=number, set_name=set_name,
                          extra=" | ".join(segments[2:]), language=language.value)
    name, number = _split_name_number(segments[0])
    return SourceText(name=name, number=number, extra=" | ".join(segments[1:]),
                      language=language.value)


# A card number as it survives ``normalize_number``: alphanumerics, optionally a
# single slash form ("182/167"), and it MUST contain a digit. A ``Card #`` cell
# that does not look like a card number is dropped from the composed name rather
# than appended verbatim.
_CARD_NUMBER_RE = re.compile(r"[a-z0-9]+(?:/[a-z0-9]+)?")

# Bound the composed name before it reaches a customer tile or the Bedrock prompt:
# collapse internal whitespace and cap the whole "<name> #<number>" length so a
# pathological ``Name`` / ``Card #`` cell cannot emit a multi-line or unbounded
# token (the number component is bounded here too, not only the name).
_DISPLAY_NAME_MAX = 80


def format_display_name(name, number) -> str | None:
    """A sanitized customer-facing name from a card's STRUCTURED identity fields.

    Composes ``"<name> #<number>"`` from the sheet's own ``Name`` and ``Card #``
    columns (or a review decision's confirmed name/number) — the structured
    identity the importer already holds — and NEVER from the free-text ``Notes``
    column. It is materialized once, at import time, and stored on the item;
    both customer surfaces (backend ``_enrich``, MCP ``toCard``) then read that
    one stored field rather than re-parsing ``notes`` at read time (where a
    dropped-empty identity segment could otherwise promote cost/consignor/location
    free-text onto the wire — Council MUST-FIX A/C).

    Returns ``None`` when there is no real name, so an item with no structured
    identity gets no fabricated one (→ the caller falls back to card_id / ULID).
    The number is appended only when it is a well-formed card number; the result
    is whitespace-collapsed and length-bounded.
    """
    clean_name = " ".join(str(name or "").split())
    if not clean_name:
        return None
    num = normalize_number(number)
    if num and _CARD_NUMBER_RE.fullmatch(num) and any(c.isdigit() for c in num):
        composed = f"{clean_name} #{num}"
    else:
        composed = clean_name
    return composed[:_DISPLAY_NAME_MAX].strip()
