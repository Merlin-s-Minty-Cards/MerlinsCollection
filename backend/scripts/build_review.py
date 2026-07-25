"""Offline triage tool for the records the spreadsheet import flagged.

Reads the live table **STRICTLY READ-ONLY** (``Scan`` is the only DynamoDB API
this module calls — there is no code path here that can modify production data)
and renders one self-contained HTML page you open by double-clicking. No server,
no build step, no npm.

    cd backend
    python scripts/build_review.py                     # -> data/spreadsheet/review.html
    python scripts/build_review.py --table merlins-cards --region us-east-1
    python scripts/build_review.py --out C:/tmp/review.html

The page carries cost bases and listed prices, so it defaults into the
git-ignored ``data/spreadsheet/`` folder. Keep it out of the repository.

Defaults come from the app's own settings (``MERLINS`` env / ``backend/.env``),
so the table/region match the rest of the backend: ``merlins-cards`` in
``us-east-1``.

What it produces, per flagged inventory item:

* the source text the importer preserved in ``notes`` (name / set / card #),
* a predicted catalog identity with 2-3 runners-up,
* a predicted market value from that card's price history,
* an honest HIGH/MEDIUM/LOW confidence band with the reason in plain English,
* the divergence between the predicted value and what the sheet recorded.

A non-English card gets a fourth band, ``N/A``: the catalog is English-only, so
no match is possible and none is offered — a Japanese card is a different card at
a different price, and its value comes from the sheet's own figures. Those rows
are settled, not uncertain, so they rank below every LOW row.

The page accumulates your decisions into a compact paste-back block you copy
back into the chat; nothing is applied from here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

import boto3

from merlins_collection.config import settings
from merlins_collection.models.inventory import LANGUAGE_LABELS, Language
from merlins_collection.services.card_text import (
    _QUALIFIER_TOKENS,
    SourceText,
    core_name,
    normalize_name,
    normalize_number,
    number_keys,
    parse_source_text,
    sets_agree,
    strip_float_artifact,
)

# ``core_name`` / ``number_keys`` / ``sets_agree`` moved into ``card_text`` so the
# importer's matcher and this review page normalize identically (RFC 0001 B.1).
# Keep the historical private names as thin aliases so the call sites below — and
# this page's own tests — read unchanged.
_number_keys = number_keys
_sets_agree = sets_agree

# --- tuning knobs --------------------------------------------------------

# A predicted value only counts as "diverging" from the sheet when it is both
# proportionally and absolutely different — a $1 card predicted at $3 is noise.
DIVERGENCE_RATIO = 2.0
DIVERGENCE_MIN_DELTA = Decimal("5")

# Finishes to fall back through when the item's own finish has no price.
FINISH_PREFERENCE = ("normal", "holofoil", "reverseHolofoil",
                     "1stEditionHolofoil", "1stEditionNormal", "unlimitedHolofoil")

FUZZY_CUTOFF = 0.72

# Two bands beyond HIGH/MEDIUM/LOW.
#
# ``NA`` sits below HIGH: the row has no catalog identity to find and never will
# (a non-English printing). It is a settled answer, not a weak guess, so it ranks
# last — these rows are not "most likely wrong", they are done.
#
# ``CONTRADICTION`` sits above everything: a non-English item that nevertheless
# carries a catalog ``card_id``. That state should be unreachable — the importer
# refuses it and the applier now refuses it — so an item in it was linked by
# something that predates or bypasses those gates, and it is being priced from
# the wrong card right now. It is shown even when ``needs_review`` is False,
# because "resolved" is exactly the lie that hides it.
NO_MATCH_BAND = "NA"
CONTRADICTION_BAND = "CONTRADICTION"

CONFIDENCE_RANK = {CONTRADICTION_BAND: 4, "LOW": 3, "MEDIUM": 2, "HIGH": 1,
                   NO_MATCH_BAND: 0}

# --- identifier + name normalization ------------------------------------
# ``strip_float_artifact`` / ``normalize_name`` / ``normalize_number`` /
# ``core_name`` / ``number_keys`` / ``sets_agree`` are imported from
# ``services.card_text`` so this page, the importer's matcher and the decision
# applier — every end of one paste-back round trip — compare text identically.


# --- recovering the importer's source text -------------------------------
# ``SourceText`` / ``parse_source_text`` are imported from
# ``services.card_text``: the applier validates a decision against the very
# same parse this page derived its candidates from.


# --- catalog index -------------------------------------------------------

@dataclass
class CatalogIndex:
    """Lookup structures over the seeded ``catalog_card`` records."""

    cards: list[dict] = field(default_factory=list)
    by_name_number: dict = field(default_factory=lambda: defaultdict(list))
    by_core_number: dict = field(default_factory=lambda: defaultdict(list))
    by_name: dict = field(default_factory=lambda: defaultdict(list))
    by_core: dict = field(default_factory=lambda: defaultdict(list))
    by_prefix: dict = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def build(cls, cards) -> CatalogIndex:
        index = cls()
        for card in cards:
            index.cards.append(card)
            name, core = normalize_name(card.get("name")), core_name(card.get("name"))
            number = normalize_number(card.get("number"))
            index.by_name[name].append(card)
            index.by_core[core].append(card)
            for key in _number_keys(number):
                index.by_name_number[(name, key)].append(card)
                index.by_core_number[(core, key)].append(card)
        for core in set(index.by_core) | set(index.by_name):
            if core:
                index.by_prefix[core[:3]].append(core)
        return index

    def cards_for(self, name: str) -> list[dict]:
        return self.by_name.get(name, []) or self.by_core.get(name, [])

    def fuzzy_names(self, name: str, limit: int) -> list[tuple[float, str]]:
        """Closest catalog names to ``name``, scored 0-1.

        Restricted to names sharing the first three letters, which keeps this
        cheap over a 20k-card catalog; only a name with no such neighbours pays
        for a full pass.
        """
        if not name:
            return []
        pool = self.by_prefix.get(name[:3]) or list(set(self.by_name) | set(self.by_core))
        hits = get_close_matches(name, pool, n=limit, cutoff=FUZZY_CUTOFF)
        return [(round(SequenceMatcher(None, name, hit).ratio(), 2), hit) for hit in hits]


@dataclass
class CardPrediction:
    candidates: list[dict]
    confidence: str
    reason: str
    # True when the candidates are tied on identity evidence, so their order
    # carries no meaning and something else (price fit) may reorder them.
    undetermined: bool = False

    @property
    def best(self):
        return self.candidates[0] if self.candidates else None


def _demote(band: str) -> str:
    return {"HIGH": "MEDIUM", "MEDIUM": "LOW"}.get(band, "LOW")


def _rank(hits: list[dict], number: str) -> list[dict]:
    """Stable ordering: an exact card-number hit first, then by id."""
    return sorted(hits, key=lambda c: (normalize_number(c.get("number")) != number,
                                       str(c.get("card_id"))))


def predict_card(source: SourceText, index: CatalogIndex, *, kind: str = "raw",
                 max_candidates: int = 4) -> CardPrediction:
    """Best-guess catalog identity for one flagged item, with an honest band.

    HIGH means several independent fields agreed. MEDIUM means the match is
    real but ambiguous (usually: the singles tab has no Set column, so a name +
    card # hits the same card in several sets). LOW means a fuzzy or single-field
    guess — treat it as a suggestion, not an answer.
    """
    # Language gate FIRST, above the kind check: ``language`` lives on the shared
    # item base precisely because every kind can be a non-English printing, so a
    # Japanese sealed box must not be filed under "sealed, look by hand" when the
    # sharper and more permanent answer is "non-English, no catalog exists".
    if source.language != Language.EN.value:
        label = LANGUAGE_LABELS.get(Language(source.language), source.language)
        return CardPrediction([], NO_MATCH_BAND, (
            f"{label} printing — the catalog holds English cards only, so no "
            f"catalog match is possible for this card and none is offered. This "
            f"is the correct final answer, not a failed lookup: its value comes "
            f"from your sheet (cost, sticker, market at purchase), shown on the "
            f"left"))

    if kind in {"sealed", "bulk"}:
        return CardPrediction([], "LOW", (
            "sealed/bulk product — the catalog holds single cards only, so no "
            "automatic identity match is possible; check the product type and "
            "value by hand"))

    name = normalize_name(source.name)
    core = core_name(source.name)
    number = normalize_number(source.number)
    if not name:
        return CardPrediction([], "LOW", "no name text survived the import; nothing to match on")

    stripped = core != name
    hits: list[dict] = []
    tier = ""
    for key_name, table, label in (
        (name, index.by_name_number, "name + card#"),
        (core, index.by_core_number, "name + card# (after dropping variant words)"),
    ):
        for num_key in _number_keys(number):
            hits = table.get((key_name, num_key), [])
            if hits:
                tier, number = label, num_key
                break
        if hits:
            break

    undetermined = False
    if hits:
        band, reason = _from_number_hits(hits, source, tier)
    else:
        split = _from_split_name(name, number, index)
        if split:
            band, reason, hits = split
        else:
            band, reason, hits = _from_name_only(name, core, number, index, stripped)
            undetermined = len(hits) > 1

    if not hits:
        return CardPrediction([], "LOW", reason)
    ranked = _rank(hits, number)
    if source.set_name:
        narrowed = [c for c in ranked if _sets_agree(source.set_name, c.get("set_name"))]
        if narrowed and len(narrowed) < len(ranked):
            ranked = narrowed
            if len(narrowed) == 1 and band != "LOW":
                band = "HIGH"
                reason = f"{tier or 'name'} + set '{source.set_name}' all agree on one card"
    band, reason = _apply_qualifier_caveat(band, reason, source.name, ranked[0])
    return CardPrediction(ranked[:max_candidates], band, reason, undetermined)


def _apply_qualifier_caveat(band: str, reason: str, source_name: str, card: dict):
    """Demote a match that only worked by ignoring a variant/language word.

    "Mew Gold Celebrations" matching plain "Mew" is a real lead, but a gold
    secret rare is a different card at a different price — so it is never HIGH.
    """
    ignored = sorted({t for t in normalize_name(source_name).split()
                      if t in _QUALIFIER_TOKENS}
                     - set(normalize_name(card.get("name")).split()))
    if not ignored:
        return band, reason
    words = "', '".join(ignored)
    if band == "HIGH":
        return "MEDIUM", (f"{reason} — but the sheet also says '{words}', which the catalog "
                          f"name does not; that variant is often a different card at a "
                          f"very different price")
    return band, f"{reason} (the sheet also says '{words}', ignored while matching)"


def _from_number_hits(hits, source: SourceText, tier: str) -> tuple[str, str]:
    count = len(hits)
    if count == 1:
        if source.set_name:
            return "HIGH", (f"exact {tier} match, unique in the catalog "
                            f"(set text '{source.set_name}' also present)")
        return "HIGH", (f"exact {tier} match, unique in the catalog — but the "
                        f"singles tab has no Set column, so nothing cross-checks it")
    sets = sorted({str(c.get("set_name")) for c in hits})
    if count <= 5:
        return "MEDIUM", (f"{tier} matched {count} catalog cards across {len(sets)} sets "
                          f"({', '.join(sets[:4])}) and there is no Set text to "
                          f"disambiguate — pick one below")
    return "LOW", (f"{tier} matched {count} catalog cards across {len(sets)} sets; "
                   f"too many to call without a set")


def _from_split_name(name: str, number: str, index: CatalogIndex):
    """Try reading the tail of the name as set text: "Mew Gold Celebrations".

    The singles tab has no Set column, so sellers wrote the set into the name.
    Splitting is only *trusted* when the leftover text actually matches the set
    of a card that already agrees on name + number — otherwise we have invented
    a split, and the result stays LOW no matter how tidy it looks.
    """
    tokens = name.split()
    if not number or len(tokens) < 2:
        return None
    fallback = None
    for cut in range(len(tokens) - 1, 0, -1):
        head, tail = " ".join(tokens[:cut]), " ".join(tokens[cut:])
        hits: list[dict] = []
        for key in (head, core_name(head)):
            for num_key in _number_keys(number):
                hits = (index.by_name_number.get((key, num_key))
                        or index.by_core_number.get((key, num_key)) or [])
                if hits:
                    break
            if hits:
                break
        if not hits:
            continue
        narrowed = [c for c in hits if _sets_agree(tail, c.get("set_name"))]
        if narrowed:
            if len(narrowed) == 1:
                return "HIGH", (f"read the trailing text as a set: name '{head}' + card# "
                                f"{number} + set '{narrowed[0].get('set_name')}' "
                                f"(from '{tail}') all agree"), narrowed
            return "MEDIUM", (f"read the trailing text as a set: name '{head}' + card# "
                              f"{number} + '{tail}' still matches "
                              f"{len(narrowed)} printings"), narrowed
        if fallback is None:
            fallback = ("LOW", (f"name '{head}' + card# {number} matches {len(hits)} "
                                f"catalog card(s), but the leftover text '{tail}' is not "
                                f"any of their set names — an unverified guess"), hits)
    return fallback


def _from_name_only(name, core, number, index: CatalogIndex, stripped: bool):
    """Fallback tiers once (name, card #) found nothing."""
    for key, label in ((name, "name"), (core, "name (variant words dropped)")):
        hits = index.by_name.get(key) or index.by_core.get(key) or []
        if not hits:
            continue
        sets = sorted({str(c.get("set_name")) for c in hits})
        if len(hits) == 1:
            note = (f"; card # '{number}' matches no card under that name, so the "
                    f"number is suspect" if number else "; no card # in the source")
            return "MEDIUM", f"exact {label} match, unique in the catalog{note}", hits
        return "LOW", (f"exact {label} match but {len(hits)} printings across "
                       f"{len(sets)} sets, and card # "
                       f"{'%r matched none of them' % number if number else 'is missing'}"), hits

    scored = index.fuzzy_names(core, limit=4)
    if scored:
        hits = []
        for _score, hit_name in scored:
            hits.extend(index.cards_for(hit_name))
        top = scored[0]
        return "LOW", (f"no exact catalog name; closest fuzzy match is "
                       f"'{top[1]}' (similarity {top[0]}) — genuinely uncertain, "
                       f"check the candidates"), hits
    hint = " (variant words were dropped first)" if stripped else ""
    return "LOW", f"no catalog candidate found for this name{hint}", []


# --- value prediction ----------------------------------------------------

@dataclass
class ValuePrediction:
    value: Decimal | None
    basis: str
    note: str = ""


def _as_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _latest(points) -> dict | None:
    priced = [p for p in points if _as_decimal(p.get("market")) is not None]
    return max(priced, key=lambda p: str(p.get("date") or ""), default=None)


def _catalog_price(card, finish) -> tuple[Decimal | None, str]:
    prices = card.get("prices") or {}
    order = [finish] + [f for f in FINISH_PREFERENCE if f != finish]
    for name in order + sorted(prices):
        band = prices.get(name)
        if isinstance(band, dict):
            market = _as_decimal(band.get("market")) or _as_decimal(band.get("mid"))
            if market is not None:
                return market, name
    return None, ""


def predict_value(item, card, price_points) -> ValuePrediction:
    """Predicted market value for one item from its matched card's price data."""
    if not card:
        return ValuePrediction(None, "none", "no matched catalog card, so no value to predict")

    if item.get("kind") == "graded":
        company = str(item.get("company") or "").upper()
        grade = _as_decimal(item.get("grade"))
        graded = [p for p in price_points
                  if p.get("kind") == "graded"
                  and str(p.get("company") or "").upper() == company
                  and _as_decimal(p.get("grade")) == grade]
        newest = _latest(graded)
        if newest:
            return ValuePrediction(_as_decimal(newest["market"]), "price_point_graded",
                                   f"{company} {grade} price point dated {newest.get('date')}")
        raw_value, finish = _catalog_price(card, "normal")
        raw_point = _latest([p for p in price_points if p.get("kind") == "raw"])
        if raw_point:
            raw_value, finish = _as_decimal(raw_point["market"]), raw_point.get("finish")
        if raw_value is None:
            return ValuePrediction(None, "none", "no price data at all for this card")
        return ValuePrediction(raw_value, "raw_only", (
            f"RAW ungraded {finish} price — the catalog carries no {company} {grade} "
            f"figure, so this is NOT a slab value and is usually far too low"))

    finish = str(item.get("finish") or "normal")
    same_finish = [p for p in price_points
                   if p.get("kind") == "raw" and str(p.get("finish") or "") == finish]
    newest = _latest(same_finish)
    if newest:
        return ValuePrediction(_as_decimal(newest["market"]), "price_point",
                               f"{finish} price point dated {newest.get('date')}")
    newest = _latest([p for p in price_points if p.get("kind") == "raw"])
    if newest:
        return ValuePrediction(_as_decimal(newest["market"]), "price_point", (
            f"no {finish} price; using the {newest.get('finish')} price point dated "
            f"{newest.get('date')}"))
    value, used = _catalog_price(card, finish)
    if value is None:
        return ValuePrediction(None, "none", "the matched card carries no price at all")
    note = f"catalog {used} price" + ("" if used == finish else f" (item finish is {finish})")
    return ValuePrediction(value, "catalog_price", note)


def value_divergence(predicted: Decimal | None, item) -> dict | None:
    """Compare a predicted value with what the sheet recorded for the item.

    ``None`` when there is nothing to compare. ``flagged`` marks the rows worth
    a human's attention: off by 2x or more *and* by at least a few dollars.
    """
    for label in ("listed_price", "market_value_at_purchase"):
        basis = _as_decimal(item.get(label))
        if basis is not None and basis != 0:
            break
    else:
        return None
    if predicted is None:
        return None
    ratio = float(predicted / basis)
    delta = predicted - basis
    return {
        "basis_label": label,
        "basis": basis,
        "ratio": round(ratio, 2),
        "delta": delta,
        "flagged": abs(delta) >= DIVERGENCE_MIN_DELTA
        and (ratio >= DIVERGENCE_RATIO or ratio <= 1 / DIVERGENCE_RATIO),
    }


# --- row assembly --------------------------------------------------------

def _money(value) -> str | None:
    dec = _as_decimal(value)
    return None if dec is None else f"{dec:f}"


def _card_view(card, item=None, points=None) -> dict:
    view = {
        "card_id": card.get("card_id"),
        "name": card.get("name"),
        "set_name": card.get("set_name"),
        "number": card.get("number"),
        "rarity": card.get("rarity"),
        "image": (card.get("images") or {}).get("small"),
    }
    if item is not None:
        prediction = predict_value(item, card, points or [])
        view["value"] = _money(prediction.value)
        view["value_basis"] = prediction.basis
        view["value_note"] = prediction.note
    return view


def _order_by_price_fit(prediction: CardPrediction, item, price_points_by_card,
                        *, keep: int = 6) -> CardPrediction:
    """Reorder identity-tied candidates by which one costs what the sheet says.

    Only applies when the match is ``undetermined`` — every candidate is an
    equally good guess on identity, so an arbitrary order (and three of forty
    printings) is useless to a human. This is a PRICE heuristic, not evidence of
    identity, and the reason text says so; the band stays where it was.
    """
    if not prediction.undetermined or len(prediction.candidates) < 2:
        return CardPrediction(prediction.candidates[:4], prediction.confidence,
                              prediction.reason, prediction.undetermined)
    for label in ("listed_price", "market_value_at_purchase"):
        basis = _as_decimal(item.get(label))
        if basis is not None and basis != 0:
            break
    else:
        return CardPrediction(prediction.candidates[:keep], prediction.confidence,
                              prediction.reason, prediction.undetermined)

    def distance(card):
        value = predict_value(item, card, price_points_by_card.get(card["card_id"], []))
        return (value.value is None, abs(value.value - basis) if value.value else 0)

    ordered = sorted(prediction.candidates, key=distance)
    return CardPrediction(ordered[:keep], prediction.confidence, (
        f"{prediction.reason}; candidates below are ordered by how close their "
        f"market price sits to the ${basis:f} the sheet recorded — a price hint "
        f"only, not identity evidence"), prediction.undetermined)


def _contradiction(source: SourceText, item) -> CardPrediction | None:
    """A non-English item that nevertheless carries a catalog ``card_id``.

    Nothing should be able to produce this state, which is exactly why it has to
    be shown: it means something linked the item before the gates existed, or
    around them. The item is being valued from an English card right now, and
    because whatever linked it also cleared ``needs_review``, the ordinary filter
    would hide it forever (Council R7 BLOCKER-1(d)).
    """
    card_id = item.get("card_id")
    if source.language == Language.EN.value or not card_id:
        return None
    label = LANGUAGE_LABELS.get(Language(source.language), source.language)
    return CardPrediction([], CONTRADICTION_BAND, (
        f"CONTRADICTION — this is a {label} printing but it is linked to English "
        f"catalog card '{card_id}', so any market value on it comes from the "
        f"wrong card. Nothing in the current code can create this state; unlink "
        f"it (REJECT) and take the value from your sheet"))


def build_card_rows(items, index: CatalogIndex, price_points_by_card) -> list[dict]:
    """One review row per flagged inventory item, worst-looking rows first.

    Also picks up rows that are NOT flagged but are self-contradictory — see
    ``_contradiction``. Everything else that is already resolved stays off the
    page.
    """
    rows = []
    for item in items:
        source = parse_source_text(item)
        contradiction = _contradiction(source, item)
        if not item.get("needs_review") and contradiction is None:
            continue
        kind = str(item.get("kind") or "raw")
        if contradiction is not None:
            prediction = contradiction
        else:
            prediction = predict_card(source, index, kind=kind, max_candidates=8)
            prediction = _order_by_price_fit(prediction, item, price_points_by_card)
        best = prediction.best
        points = price_points_by_card.get(best["card_id"], []) if best else []
        value = predict_value(item, best, points)
        divergence = value_divergence(value.value, item)
        rows.append({
            "item_id": item.get("item_id"),
            "kind": kind,
            "status": item.get("status"),
            "source": {"name": source.name, "number": source.number,
                       "set": source.set_name, "extra": source.extra},
            "stored": {
                "cost_basis": _money(item.get("cost_basis")),
                "listed_price": _money(item.get("listed_price")),
                "market_value_at_purchase": _money(item.get("market_value_at_purchase")),
                "acquired_at": str(item.get("acquired_at") or ""),
                "condition": _condition_text(item),
                "company": item.get("company"),
                "grade": _money(item.get("grade")),
                "cert_number": strip_float_artifact(item.get("cert_number")),
                "finish": item.get("finish"),
                "location": item.get("location"),
                "product_type": item.get("product_type"),
                "notes": item.get("notes"),
                "tcg_url": item.get("tcg_url"),
                "card_id": item.get("card_id"),
                "language": source.language,
            },
            "prediction": (_card_view(best, item, points) | {
                "value": _money(value.value), "value_basis": value.basis,
                "value_note": value.note}) if best else None,
            "runners": [_card_view(card, item, price_points_by_card.get(card["card_id"], []))
                        for card in prediction.candidates[1:]],
            "confidence": prediction.confidence,
            "reason": prediction.reason,
            "divergence": {**divergence, "basis": _money(divergence["basis"]),
                           "delta": _money(divergence["delta"])} if divergence else None,
        })
    for row in rows:
        diverged = bool(row["divergence"] and row["divergence"]["flagged"])
        magnitude = abs(float(row["divergence"]["delta"])) if diverged else 0.0
        row["priority"] = round(
            CONFIDENCE_RANK[row["confidence"]] * 100
            + (50 if diverged else 0) + min(magnitude, 49) / 50, 3)
    rows.sort(key=lambda r: (-r["priority"], r["item_id"] or ""))
    return rows


def _condition_text(item) -> str | None:
    condition = item.get("condition")
    if not condition:
        return None
    return f"{condition}{item.get('condition_modifier') or ''}"


# --- reading the live table (Scan only — nothing here can modify data) ----

_WANTED_ENTITIES = frozenset({"catalog_card", "inventory_item", "price_point"})


def scan_records(table_name: str, region_name: str, *, endpoint_url=None, progress=None):
    """Yield every record in the table. The ONLY DynamoDB call in this module."""
    table = boto3.resource("dynamodb", region_name=region_name,
                           endpoint_url=endpoint_url).Table(table_name)
    kwargs: dict = {}
    seen = 0
    while True:
        response = table.scan(**kwargs)
        batch = response.get("Items", [])
        seen += len(batch)
        yield from batch
        if progress:
            progress(seen)
        last = response.get("LastEvaluatedKey")
        if not last:
            return
        kwargs["ExclusiveStartKey"] = last


def collect(records) -> dict:
    """Bucket a raw record stream into the pieces the review needs."""
    catalog, inventory = [], []
    prices: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        entity = record.get("entity")
        if entity not in _WANTED_ENTITIES:
            continue
        if entity == "catalog_card":
            catalog.append(record)
        elif entity == "inventory_item":
            inventory.append(record)
        elif record.get("card_id"):
            prices[record["card_id"]].append(record)
    return {"catalog": catalog, "inventory": inventory, "prices": dict(prices)}


# --- HTML rendering ------------------------------------------------------

_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Merlin's needs_review triage</title>
<style>
:root{--bg:#0f1512;--panel:#16201b;--panel2:#1d2a23;--line:#2b3b31;--ink:#e8f0ea;
--dim:#93a89b;--accent:#5fbf82;--high:#3fa46a;--med:#c9a227;--low:#d4633f;--warn:#e0794f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:13px/1.45 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--panel);
border-bottom:1px solid var(--line);padding:10px 14px}
h1{margin:0;font-size:15px;letter-spacing:.02em}
.meta{color:var(--dim);font-size:11px;margin-top:2px}
.tabs{display:flex;gap:6px;margin-top:8px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
.bar label{color:var(--dim);display:flex;gap:4px;align-items:center}
select,input[type=text],input[type=search]{background:var(--bg);color:var(--ink);
border:1px solid var(--line);border-radius:5px;padding:4px 6px;font:inherit}
.prog{margin-left:auto;color:var(--dim)}
.prog b{color:var(--accent)}
main{padding:12px 14px 240px}
table{border-collapse:collapse;width:100%}
th{position:sticky;top:0;background:var(--panel2);text-align:left;font-size:11px;
color:var(--dim);text-transform:uppercase;letter-spacing:.05em;padding:6px;
border-bottom:1px solid var(--line)}
td{border-bottom:1px solid var(--line);padding:7px 6px;vertical-align:top}
tr.decided{opacity:.45}
.badge{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10px;
font-weight:700;letter-spacing:.04em}
.HIGH{background:var(--high);color:#06130b}.MEDIUM{background:var(--med);color:#1b1503}
.LOW{background:var(--low);color:#180a05}
.NA{background:var(--panel2);color:var(--dim);border:1px solid var(--line)}
.CONTRADICTION{background:var(--warn);color:#180a05}
.k{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
.name{font-weight:600}
.dim{color:var(--dim)}
.reason{color:var(--dim);font-size:11.5px;max-width:38ch}
.flag{color:var(--warn);font-weight:700}
img.thumb{width:44px;height:61px;object-fit:cover;border-radius:3px;background:var(--panel2)}
.cand{display:flex;gap:6px;align-items:center;margin-top:4px}
.cand button{background:var(--panel2);border:1px solid var(--line);color:var(--ink);
border-radius:5px;padding:3px 7px;cursor:pointer;font:inherit;font-size:11px;text-align:left}
.cand button:hover{border-color:var(--accent)}
.acts{display:flex;flex-direction:column;gap:4px;min-width:150px}
.acts .row{display:flex;gap:4px}
.acts button{border:1px solid var(--line);background:var(--panel2);color:var(--ink);
border-radius:5px;padding:4px 8px;cursor:pointer;font:inherit;font-size:11px}
.acts button.on{background:var(--accent);color:#08120c;border-color:var(--accent);font-weight:700}
.acts button.no.on{background:var(--low);color:#160804;border-color:var(--low)}
.acts input{width:100%;font-size:11px}
footer{position:fixed;bottom:0;left:0;right:0;background:var(--panel);
border-top:1px solid var(--line);padding:8px 14px;z-index:30}
footer .head{display:flex;gap:10px;align-items:center}
textarea{width:100%;height:112px;background:var(--bg);color:var(--ink);border:1px solid var(--line);
border-radius:6px;padding:6px;font:12px/1.4 ui-monospace,Consolas,monospace;resize:vertical}
.legend{color:var(--dim);font-size:11px;margin-top:4px}
.legend code{color:var(--ink)}
.more{margin:14px auto;display:block;padding:7px 16px;background:var(--panel2);
color:var(--ink);border:1px solid var(--line);border-radius:6px;cursor:pointer;font:inherit}
.conf-filter{color:var(--dim);display:flex;gap:8px;align-items:center}
.conf-filter label{gap:3px}
.hidden{display:none}
</style>
</head>
<body>
<header>
  <h1>Merlin's Minty Cards — needs_review triage <span class="dim" id="src"></span></h1>
  <div class="meta" id="meta"></div>
  <div class="tabs">
    <span class="prog" id="prog"></span>
  </div>
  <div class="bar" id="bar">
    <span class="conf-filter">confidence
      <label title="non-English item linked to an English card — fix these first"><input
        type="checkbox" class="f-conf" value="CONTRADICTION" checked> CONTRADICTION</label>
      <label><input type="checkbox" class="f-conf" value="LOW" checked> LOW</label>
      <label><input type="checkbox" class="f-conf" value="MEDIUM" checked> MEDIUM</label>
      <label><input type="checkbox" class="f-conf" value="HIGH"> HIGH</label>
      <label title="non-English printings — no catalog match is possible"><input
        type="checkbox" class="f-conf" value="NA"> N/A</label>
    </span>
    <label>kind <select id="f-kind"><option value="">all</option></select></label>
    <label><input type="checkbox" id="f-div"> only value divergence</label>
    <label><input type="checkbox" id="f-undecided"> hide decided</label>
    <label>sort <select id="f-sort">
      <option value="priority">most likely wrong first</option>
      <option value="delta">biggest value gap first</option>
      <option value="name">name A-Z</option>
    </select></label>
    <label>search <input type="search" id="f-q" placeholder="name, id, set"></label>
  </div>
  <div class="meta" id="count"></div>
</header>
<main>
  <div id="cards-pane"><table id="cards"><thead><tr>
    <th style="width:78px">Conf</th><th style="width:20%">Stored (from the sheet)</th>
    <th style="width:22%">Prediction</th><th style="width:9%">Value vs sheet</th>
    <th>Why / other candidates</th><th style="width:160px">Decision</th>
  </tr></thead><tbody></tbody></table>
  <button class="more hidden" id="more-cards">show more rows</button></div>
</main>
<footer>
  <div class="head">
    <b>Paste this back into the chat</b>
    <span class="dim" id="pb-count"></span>
    <button class="more" style="margin:0;padding:4px 12px" id="copy">Copy</button>
    <button class="more" style="margin:0;padding:4px 12px" id="reset">Clear all decisions</button>
    <button class="more" style="margin:0 0 0 auto;padding:4px 12px" id="fold">Hide</button>
  </div>
  <textarea id="pb" readonly spellcheck="false"></textarea>
  <div class="legend" id="legend">
    Format <code>MERLIN-REVIEW-V1</code>: one decision per line,
    <code>CARD|TXN &lt;id&gt; VERB [k=v; k=v]</code>. Verbs:
    <code>ACCEPT</code> take the prediction (fields spelled out, so the block stands alone),
    <code>REJECT</code> prediction is wrong, leave the record alone,
    <code>NOCHANGE</code> confirmed already correct,
    <code>SET</code> use these values instead. Only rows you actually decided appear.
  </div>
</footer>
<script type="application/json" id="review-data">__PAYLOAD__</script>
<script>
(function(){
"use strict";
var DATA = JSON.parse(document.getElementById("review-data").textContent);
var KEY = "merlins-review-v1";
var decisions = {};
try { decisions = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch(e) { decisions = {}; }
var limit = 250;

function save(){ try { localStorage.setItem(KEY, JSON.stringify(decisions)); } catch(e){} }
function el(tag, cls, txt){ var n=document.createElement(tag); if(cls)n.className=cls;
  if(txt!==undefined&&txt!==null)n.textContent=String(txt); return n; }
function clean(v){ return String(v===null||v===undefined?"":v)
  .replace(/[;\r\n]+/g," ").trim(); }
function money(v){ return v===null||v===undefined?"—":"$"+Number(v).toFixed(2); }

document.getElementById("src").textContent = "";
document.getElementById("meta").textContent =
  "table " + DATA.meta.table + " · generated " + DATA.meta.generated_at +
  " · " + DATA.cards.length + " flagged items · read-only snapshot, " +
  "nothing here changes the database";

var kinds = {};
DATA.cards.forEach(function(r){ kinds[r.kind]=1; });
var kindSel = document.getElementById("f-kind");
Object.keys(kinds).sort().forEach(function(k){
  var o=el("option",null,k); o.value=k; kindSel.appendChild(o); });

function filters(){
  var conf = Array.prototype.filter.call(
    document.querySelectorAll("input.f-conf"), function(c){ return c.checked; })
    .map(function(c){ return c.value; });
  return { conf: conf, kind: kindSel.value,
    div: document.getElementById("f-div").checked,
    undecided: document.getElementById("f-undecided").checked,
    q: document.getElementById("f-q").value.trim().toLowerCase(),
    sort: document.getElementById("f-sort").value };
}

function visibleCards(){
  var f = filters();
  var rows = DATA.cards.filter(function(r){
    if(f.conf.length && f.conf.indexOf(r.confidence)<0) return false;
    if(f.kind && r.kind!==f.kind) return false;
    if(f.div && !(r.divergence && r.divergence.flagged)) return false;
    if(f.undecided && decisions["CARD:"+r.item_id]) return false;
    if(f.q){
      var hay = [r.item_id, r.source.name, r.source.set, r.source.number,
        r.prediction?r.prediction.name:"", r.prediction?r.prediction.set_name:""]
        .join(" ").toLowerCase();
      if(hay.indexOf(f.q)<0) return false;
    }
    return true;
  });
  if(f.sort==="delta"){ rows.sort(function(a,b){
    return Math.abs(Number(b.divergence?b.divergence.delta:0)) -
           Math.abs(Number(a.divergence?a.divergence.delta:0)); }); }
  else if(f.sort==="name"){ rows.sort(function(a,b){
    return (a.source.name||"").localeCompare(b.source.name||""); }); }
  else { rows.sort(function(a,b){ return b.priority-a.priority; }); }
  return rows;
}

function decide(id, verb, fields){
  var cur = decisions[id];
  if(cur && cur.verb===verb && verb!=="SET"){ delete decisions[id]; }
  else { decisions[id] = {verb: verb, fields: fields||{}}; }
  save(); draw();
}

function actions(id, opts){
  var box = el("div","acts"), cur = decisions[id];
  var row = el("div","row");
  opts.verbs.forEach(function(v){
    var b = el("button", v.verb==="REJECT"?"no":"", v.label);
    if(cur && cur.verb===v.verb) b.className += " on";
    b.onclick = function(){ decide(id, v.verb, v.fields()); };
    row.appendChild(b);
  });
  box.appendChild(row);
  opts.inputs.forEach(function(inp){
    var i = el("input"); i.type="text"; i.placeholder = inp.placeholder;
    i.value = (cur && cur.verb==="SET" && cur.fields[inp.name]) || "";
    i.onchange = function(){
      var fields = (cur && cur.verb==="SET") ? Object.assign({}, cur.fields) : {};
      var v = clean(i.value);
      if(v) fields[inp.name]=v; else delete fields[inp.name];
      if(Object.keys(fields).length) decisions[id]={verb:"SET",fields:fields};
      else delete decisions[id];
      save(); draw();
    };
    box.appendChild(i);
  });
  return box;
}

function cardCell(c, onPick){
  var wrap = el("div");
  var head = el("div","cand");
  if(c.image){
    var img = el("img"); img.className="thumb"; img.loading="lazy"; img.src=c.image;
    img.alt=""; img.onerror=function(){ this.style.visibility="hidden"; };
    head.appendChild(img);
  }
  var txt = el("div");
  txt.appendChild(el("div","name", c.name));
  txt.appendChild(el("div","dim", (c.set_name||"?") + " #" + (c.number||"?") +
    (c.rarity?" · "+c.rarity:"")));
  txt.appendChild(el("div","dim", "predicted value " + money(c.value) +
    (c.value_basis?" ("+c.value_basis+")":"")));
  if(c.value_note) txt.appendChild(el("div","dim", c.value_note));
  txt.appendChild(el("div","dim", c.card_id));
  head.appendChild(txt);
  wrap.appendChild(head);
  if(onPick){
    var b = el("button", null, "use this one");
    b.onclick = onPick; wrap.appendChild(b);
  }
  return wrap;
}

function drawCards(){
  var body = document.querySelector("#cards tbody");
  body.textContent = "";
  var rows = visibleCards(), shown = rows.slice(0, limit);
  shown.forEach(function(r){
    var id = "CARD:"+r.item_id, tr = el("tr");
    if(decisions[id]) tr.className = "decided";

    var c1 = el("td");
    c1.appendChild(el("span","badge "+r.confidence, r.confidence));
    c1.appendChild(el("div","k", r.kind));
    tr.appendChild(c1);

    var c2 = el("td");
    c2.appendChild(el("div","name", r.source.name || "(no name text)"));
    var bits = [];
    if(r.source.number) bits.push("#"+r.source.number);
    if(r.source.set) bits.push(r.source.set);
    if(r.stored.language && r.stored.language!=="EN") bits.push(r.stored.language);
    if(r.stored.condition) bits.push(r.stored.condition);
    if(r.stored.company) bits.push(r.stored.company+" "+(r.stored.grade||""));
    if(r.stored.cert_number) bits.push("cert "+r.stored.cert_number);
    if(r.stored.product_type) bits.push(r.stored.product_type);
    c2.appendChild(el("div","dim", bits.join(" · ")));
    c2.appendChild(el("div","dim", "cost " + money(r.stored.cost_basis) +
      " · listed " + money(r.stored.listed_price) +
      " · mkt@buy " + money(r.stored.market_value_at_purchase)));
    c2.appendChild(el("div","dim", "acquired " + r.stored.acquired_at +
      " · " + r.status + " · " + r.item_id));
    if(r.source.extra) c2.appendChild(el("div","dim", r.source.extra));
    tr.appendChild(c2);

    var c3 = el("td");
    if(r.prediction) c3.appendChild(cardCell(r.prediction, null));
    else if(r.confidence==="NA")
      c3.appendChild(el("div","dim","no catalog entry exists — value from your sheet"));
    else c3.appendChild(el("div","flag","no candidate"));
    tr.appendChild(c3);

    var c4 = el("td");
    if(r.divergence){
      c4.appendChild(el("div", r.divergence.flagged?"flag":"dim",
        (r.divergence.ratio)+"x"));
      c4.appendChild(el("div","dim", money(r.divergence.delta)+" vs "+
        r.divergence.basis_label.replace(/_/g," ")));
    } else { c4.appendChild(el("div","dim","—")); }
    tr.appendChild(c4);

    var c5 = el("td");
    c5.appendChild(el("div","reason", r.reason));
    r.runners.forEach(function(cand){
      c5.appendChild(cardCell(cand, function(){
        decide("CARD:"+r.item_id, "SET", {card_id: cand.card_id,
          name: clean(cand.name), set: clean(cand.set_name),
          number: clean(cand.number)});
      }));
    });
    tr.appendChild(c5);

    var c6 = el("td");
    c6.appendChild(actions("CARD:"+r.item_id, {
      verbs: [
        {verb:"ACCEPT", label:"Accept", fields:function(){
          return r.prediction ? {card_id:r.prediction.card_id,
            name:clean(r.prediction.name), set:clean(r.prediction.set_name),
            number:clean(r.prediction.number), value:r.prediction.value||""} : {}; }},
        {verb:"REJECT", label:"Reject", fields:function(){ return {}; }}
      ],
      inputs: [{name:"card_id", placeholder:"corrected card_id"},
               {name:"value", placeholder:"corrected value"},
               {name:"note", placeholder:"note"}]
    }));
    tr.appendChild(c6);
    body.appendChild(tr);
  });
  var more = document.getElementById("more-cards");
  more.className = rows.length > shown.length ? "more" : "more hidden";
  more.textContent = "show more (" + (rows.length - shown.length) + " hidden)";
  document.getElementById("count").textContent =
    "showing " + shown.length + " of " + rows.length + " matching rows (" +
    DATA.cards.length + " flagged in total) — the confidence boxes above start on " +
    "LOW + MEDIUM, the rows most likely to be wrong";
}

function pasteBack(){
  // The table + snapshot bind the block to what it was decided against, so the
  // applier can refuse a block pointed at a different table (BLOCKER-D).
  var lines = ["# MERLIN-REVIEW-V1",
    "# table: " + DATA.meta.table,
    "# snapshot: " + DATA.meta.generated_at], cards = 0, other = 0;
  Object.keys(decisions).sort().forEach(function(key){
    var d = decisions[key], parts = key.split(":");
    var pairs = Object.keys(d.fields).filter(function(k){
      return clean(d.fields[k]) !== ""; }).map(function(k){
      return k + "=" + clean(d.fields[k]); });
    lines.push(parts[0] + " " + parts[1] + " " + d.verb +
      (pairs.length ? " " + pairs.join("; ") : ""));
    if(parts[0]==="CARD") cards++; else other++;
  });
  // `other` only ever counts a TXN decision left in localStorage by an EARLIER
  // build of this page: this is now card-triage only and creates none. It is
  // emitted, not dropped, so a stale decision is never lost silently — the
  // applier still validates or refuses any TXN line in a MERLIN-REVIEW-V1 block.
  lines.push("# end: " + cards + " cards, " + other + " transactions");
  document.getElementById("pb").value = lines.join("\n");
  document.getElementById("pb-count").textContent =
    cards + " cards" + (other ? " + " + other + " transactions" : "") + " decided";
  document.getElementById("prog").innerHTML =
    "<b>" + cards + "</b> of " + DATA.cards.length + " cards reviewed";
}

function draw(){
  drawCards();
  pasteBack();
}

["f-kind","f-div","f-undecided","f-sort"].forEach(function(id){
  document.getElementById(id).onchange = function(){ limit=250; draw(); }; });
Array.prototype.forEach.call(document.querySelectorAll("input.f-conf"), function(c){
  c.onchange = function(){ limit=250; draw(); }; });
document.getElementById("fold").onclick = function(){
  var hidden = document.getElementById("pb").className === "hidden";
  document.getElementById("pb").className = hidden ? "" : "hidden";
  document.getElementById("legend").className = hidden ? "legend" : "legend hidden";
  document.body.style.paddingBottom = hidden ? "" : "0";
  document.querySelector("main").style.paddingBottom = hidden ? "" : "60px";
  this.textContent = hidden ? "Hide" : "Show";
};
document.getElementById("f-q").oninput = function(){ limit=250; draw(); };
document.getElementById("more-cards").onclick = function(){ limit+=250; draw(); };
document.getElementById("copy").onclick = function(){
  var ta = document.getElementById("pb");
  ta.removeAttribute("readonly"); ta.select();
  try { document.execCommand("copy"); } catch(e){}
  if(navigator.clipboard) navigator.clipboard.writeText(ta.value).catch(function(){});
  ta.setAttribute("readonly","readonly");
  this.textContent = "Copied"; var b=this;
  setTimeout(function(){ b.textContent="Copy"; }, 1200);
};
document.getElementById("reset").onclick = function(){
  if(confirm("Clear every decision on this page?")){ decisions={}; save(); draw(); } };
draw();
})();
</script>
</body>
</html>
"""


def render_html(card_rows, *, table_name: str, generated_at: str) -> str:
    """Render the whole review page — one file, no external assets."""
    payload = json.dumps(
        {"meta": {"table": table_name, "generated_at": generated_at},
         "cards": card_rows},
        default=str, separators=(",", ":"),
    )
    # `<` can never appear literally inside the JSON block or a `</script>` in
    # the data would end the block early; escaping it keeps the page inert.
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028")
    return _PAGE.replace("__PAYLOAD__", payload)


# --- CLI -----------------------------------------------------------------

def _default_out() -> Path:
    """Prefer the git-ignored spreadsheet folder — the page holds cost bases and
    listed prices, which must never reach the repository."""
    private = Path(__file__).resolve().parents[2] / "data" / "spreadsheet"
    return (private if private.is_dir() else Path.cwd()) / "review.html"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table to read (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--endpoint-url", default=None,
                        help="override the DynamoDB endpoint (local testing)")
    parser.add_argument("--out", default=_default_out(), type=Path,
                        help="output HTML file (default: %(default)s)")
    args = parser.parse_args(argv)

    print(f"Reading {args.table} ({args.region}) — read-only scan...")
    data = collect(scan_records(
        args.table, args.region, endpoint_url=args.endpoint_url,
        progress=lambda seen: print(f"  {seen} records read", end="\r"),
    ))
    print()
    print(f"  catalog cards {len(data['catalog'])} · inventory {len(data['inventory'])} "
          f"· cards with price history {len(data['prices'])}")

    index = CatalogIndex.build(data["catalog"])
    card_rows = build_card_rows(data["inventory"], index, data["prices"])
    bands = Counter(row["confidence"] for row in card_rows)
    print(f"  flagged items {len(card_rows)} -> "
          f"HIGH {bands['HIGH']} / MEDIUM {bands['MEDIUM']} / LOW {bands['LOW']}"
          f" / N/A {bands[NO_MATCH_BAND]} (non-English, no catalog match possible)")
    if bands[CONTRADICTION_BAND]:
        print(f"  !! {bands[CONTRADICTION_BAND]} CONTRADICTION row(s): non-English "
              f"items linked to an English catalog card — fix these first")

    html = render_html(card_rows, table_name=args.table,
                       generated_at=datetime.now().isoformat(timespec="seconds"))
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote {args.out.resolve()} ({len(html) / 1024:.0f} KB) — open it in a browser.")


if __name__ == "__main__":
    main()
