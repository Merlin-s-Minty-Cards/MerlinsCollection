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
they disagree about which cards the English catalog may be matched against.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from merlins_collection.models.inventory import ITEM_TEXT_FIELD, Language

__all__ = [
    "ITEM_TEXT_FIELD", "LANGUAGE_MARKER_RE", "SourceText", "item_language",
    "language_from_url", "normalize_name", "normalize_number", "parse_language",
    "parse_source_text", "strip_float_artifact",
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
    """The language implied by a product URL's category slug, else ``EN``.

    Only the slug counts, so a product whose *name* happens to contain "japanese"
    is not mistaken for a Japanese printing.
    """
    lowered = str(url or "").lower()
    for slug, language in _URL_LANGUAGE.items():
        if slug in lowered:
            return language
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
       all.

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
    return language_from_url(_field(record, "tcg_url"))


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
