"""Apply a ``MERLIN-REVIEW-V1`` decision block to the live table.

This is the write-side companion to ``scripts/build_review.py`` (which is
strictly read-only and produces the review page). You triage in the browser,
copy the paste-back block into a file, and hand that file to this script.

    cd backend
    python scripts/apply_review_decisions.py ../data/spreadsheet/decisions/batch-01.txt
    python scripts/apply_review_decisions.py ../data/spreadsheet/decisions/batch-01.txt --apply

**DRY RUN IS THE DEFAULT.** A bare invocation reads the table, prints exactly
what it would do to every record, and writes nothing. Writing requires ``--apply``
spelled out. This touches real money data, so every rule below is fail-closed:
a row that does not validate is REFUSED, the remaining rows still run, and the
process exits non-zero.

What each verb means (confirmed with the business owner):

``CARD <item_id> ACCEPT|SET card_id=..; name=..; set=..; number=..; value=..``
    Apply the identity to the inventory item: set ``card_id`` and clear
    ``needs_review`` (a human resolved it). ``name``/``set``/``number`` are NOT
    stored — they are the human-readable confirmation of *which* catalog card
    was chosen, and they VALIDATE the id twice over: against the catalog card,
    and against the item's OWN preserved sheet text. The id is never trusted on
    its own, and a block that disagrees with the item it names is refused unless
    the operator adds ``override=stored-text-mismatch``.

    ``value`` is **reported, not written**. ``current_market_value`` belongs to
    the nightly ``refresh_inventory_market_values``; writing it from here would
    be overwritten within a day and would, on a re-run, put a stale review-page
    figure back over a fresher synced one.

    A **non-English** item is refused outright: the catalog holds English cards
    only, so no English ``card_id`` is a correct answer for one.

``CARD <item_id> REJECT`` / ``TXN <txn_id> REJECT`` / ``TXN <txn_id> NOCHANGE``
    NO WRITE AT ALL. "Leave it flagged" and "it is already fine" are both
    already true of the stored record; counted and reported, never written. The
    TXN no-ops do not even read the ledger.

``SET note=<free text>`` with no other field
    A message to a human, not a database field. Never written; surfaced in its
    own section of the report so it is not lost. (An ``ACCEPT`` carrying only a
    note is refused rather than quietly downgraded to a no-op.)

``TXN <txn_id>`` with a ``date`` field — REFUSED, not applied.
    This tool NO LONGER MOVES transactions. Correcting a transaction's date means
    a delete-and-reput of a money record across ``TXN#<YYYY-MM>`` key partitions,
    which proved too hard to make crash-safe (four Council rounds failed in that
    one path). The capability was cut. The handful of date typos are fixed by a
    separate, eyes-on manual operation described in the runbook — a ``TXN`` line
    carrying a ``date`` is refused here with a message pointing there.

The inventory shard comes from ``_bucket`` in ``services/dynamodb.py``. Text is
compared with ``services/card_text.py``, the same module the review page used to
build the block, so producer and consumer agree by construction.

This file writes exactly ONE thing: a card-identity ``update_item`` on a single
inventory item (``card_id`` / ``needs_review`` / GSI keys). The catalog
(``catalog_card`` / ``price_point``) and the transaction ledger are never written
to by any path here. Every row is individually guarded: one failing row is
reported as ``REFUSED`` and the batch continues, writes are announced as they
land, and the report prints even if the run dies.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from merlins_collection.config import settings
from merlins_collection.models.inventory import LANGUAGE_LABELS, Language
from merlins_collection.services.card_text import (
    item_language,
    normalize_name,
    normalize_number,
    parse_source_text,
)
from merlins_collection.services.dynamodb import InventoryRepository, _bucket

MARKER = "MERLIN-REVIEW-V1"

KINDS = ("CARD", "TXN")
VERBS = ("ACCEPT", "REJECT", "NOCHANGE", "SET")

# Field keys the CARD path accepts. Anything else is refused rather than guessed
# at — an unrecognized key could mean a field we would silently drop.
CARD_FIELDS = frozenset({"card_id", "name", "set", "number", "value", "override"})

# Actions reported per decision. The only one that writes is UPDATE (a single
# card-identity update_item); everything else is a skip or a refusal.
UPDATE = "UPDATE"
SKIP_NO_WRITE = "SKIP-no-write"
SKIP_NOTE_ONLY = "SKIP-note-only"
SKIP_APPLIED = "SKIP-already-applied"
REFUSED = "REFUSED-validation-failed"

# A TXN line carrying a ``date`` asks this tool to move a transaction between
# date-keyed partitions — a capability that was cut (see the module docstring).
_TXN_DATE_MOVE_REFUSAL = (
    "transaction date corrections are NO LONGER applied by this tool: it no "
    "longer MOVES transactions between date-keyed partitions (that "
    "delete-and-reput of a money record proved too hard to make crash-safe and "
    "was cut after repeated review). This row was NOT applied. Fix the date with "
    "the targeted MANUAL operation in the runbook - eyes-on each transaction - "
    "not here."
)

_LINE = re.compile(r"^(?P<kind>\w+)\s+(?P<id>\S+)\s+(?P<verb>\w+)\s*(?P<fields>.*)$")


# --- parsing -------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """One decision line, already split into its parts."""

    kind: str
    record_id: str
    verb: str
    fields: dict
    lineno: int

    @property
    def label(self) -> str:
        return f"{self.kind} {self.record_id}"


@dataclass
class ParseResult:
    decisions: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    # The table + snapshot the review page was generated against, from the block
    # header. ``table`` binds the decisions to one table so a block cannot be
    # applied to a different one (Council R8 BLOCKER-D); ``snapshot`` is
    # informational.
    table: str | None = None
    snapshot: str | None = None


def _split_fields(text: str, lineno: int) -> tuple[dict, list]:
    """``"card_id=x; name=y"`` -> ``{"card_id": "x", "name": "y"}``.

    Values may contain ``=`` and spaces (note text does), so each pair splits on
    its FIRST ``=`` only. A pair with no ``=`` is an error, not a silent drop.
    """
    fields: dict = {}
    errors: list = []
    for chunk in text.split(";"):
        pair = chunk.strip()
        if not pair:
            continue
        key, sep, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            errors.append(f"line {lineno}: '{pair}' is not a key=value pair")
        elif key in fields:
            errors.append(f"line {lineno}: field '{key}' given twice")
        elif not value:
            errors.append(f"line {lineno}: field '{key}' has no value")
        else:
            fields[key] = value
    return fields, errors


def parse_block(text) -> ParseResult:
    """Parse a paste-back block into decisions plus a list of complaints.

    Nothing is dropped quietly: a line that cannot be understood becomes an
    error, and any error makes the whole run exit non-zero. The ``MERLIN-REVIEW-V1``
    marker is mandatory — it is the only thing standing between this script and
    being pointed at the wrong file.
    """
    lines = str(text or "").splitlines()
    if not any(line.strip().lstrip("#").strip().startswith(MARKER) for line in lines):
        return ParseResult([], [f"no '{MARKER}' marker found - refusing to parse this file"])

    table = snapshot = None
    decisions: list = []
    errors: list = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # Header metadata the review page emits so a block is bound to the
            # table it was decided against (BLOCKER-D). Everything else after '#'
            # is a human comment and ignored.
            body = line.lstrip("#").strip()
            key, sep, value = body.partition(":")
            if sep and key.strip().lower() == "table":
                table = value.strip() or None
            elif sep and key.strip().lower() == "snapshot":
                snapshot = value.strip() or None
            continue
        match = _LINE.match(line)
        if not match:
            errors.append(f"line {lineno}: cannot parse '{line}'")
            continue
        kind, record_id = match["kind"].upper(), match["id"]
        verb = match["verb"].upper()
        if kind not in KINDS:
            errors.append(f"line {lineno}: unknown record type '{match['kind']}' "
                          f"(expected CARD or TXN) in '{line}'")
            continue
        if verb not in VERBS:
            errors.append(f"line {lineno}: unknown verb '{match['verb']}' for {record_id}")
            continue
        fields, field_errors = _split_fields(match["fields"], lineno)
        if field_errors:
            errors.extend(f"{message} ({kind} {record_id})" for message in field_errors)
            continue
        decisions.append(Decision(kind, record_id, verb, fields, lineno))

    seen = Counter((d.kind, d.record_id) for d in decisions)
    duplicates = {key for key, count in seen.items() if count > 1}
    for kind, record_id in sorted(duplicates):
        errors.append(f"{kind} {record_id} is decided twice - refusing both, "
                      f"resolve it in the source block")
    return ParseResult(
        [d for d in decisions if (d.kind, d.record_id) not in duplicates],
        errors, table=table, snapshot=snapshot)


# --- comparison helpers --------------------------------------------------
# ``normalize_name`` / ``normalize_number`` come from ``services.card_text``, the
# same functions the review page used to build this block. Two implementations of
# one contract is how R7 ended up with `HS—Unleashed` normalizing differently at
# the two ends of a single round trip.


def _as_decimal(value):
    """Parse a money figure, refusing anything DynamoDB (or arithmetic) cannot
    take: ``NaN`` raises on comparison and ``Infinity``/``1E+130`` are unstorable,
    so a hand-typed ``value=nan`` must not reach a live write."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    if not parsed.is_finite():
        return None
    if parsed != 0 and not (Decimal("1E-130") <= abs(parsed) <= Decimal("9.9E125")):
        return None
    return parsed


def _texts_agree(given, stored) -> bool:
    """True when two card names describe the same card.

    The sheet's name and the catalog's name are rarely identical: the sheet adds
    printing qualifiers ("Snorlax Prerelease", "Tyranitar Prime") and spells
    punctuation its own way ("Stevens" for "Steven's"). So one being contained in
    the other — as a token subset or, once spaces are dropped, as a substring —
    counts as agreement. A substituted or misspelled word does not.
    """
    left, right = normalize_name(given), normalize_name(stored)
    if not left or not right:
        return True                      # nothing comparable, so no disagreement
    if left == right:
        return True
    flat_left, flat_right = left.replace(" ", ""), right.replace(" ", "")
    if flat_left in flat_right or flat_right in flat_left:
        return True
    tokens_left, tokens_right = set(left.split()), set(right.split())
    return tokens_left <= tokens_right or tokens_right <= tokens_left


def _numbers_agree(given, stored) -> bool:
    """True when two collector numbers refer to the same card.

    ``"182/167"`` and ``"182"`` are the same number written two ways, so only the
    part before the slash is compared.
    """
    left = normalize_number(given).split("/", 1)[0].lstrip("0")
    right = normalize_number(stored).split("/", 1)[0].lstrip("0")
    if not left or not right:
        return True
    return left == right


def read_block(path: Path) -> str:
    """Read a decisions file, tolerating a UTF-8 BOM.

    The block is copied out of a browser and hand-saved, which on Windows means a
    BOM more often than not — and a BOM made the marker check fail with a
    misleading "no marker found".
    """
    return path.read_text(encoding="utf-8-sig")


# --- results -------------------------------------------------------------

@dataclass
class Result:
    """What happened (or would happen) to one decision."""

    decision: Decision
    action: str
    detail: str = ""
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)


@dataclass
class Report:
    results: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    dry_run: bool = True

    @property
    def counts(self) -> Counter:
        return Counter(r.action for r in self.results)

    @property
    def notes(self) -> list:
        """``(record_id, note)`` for every decision carrying operator note text."""
        return [(r.decision.record_id, r.decision.fields["note"])
                for r in self.results if r.decision.fields.get("note")]

    @property
    def refused(self) -> list:
        return [r for r in self.results if r.action == REFUSED]

    @property
    def exit_code(self) -> int:
        return 1 if self.refused or self.errors else 0


def _refuse(decision: Decision, reason: str, before=None, after=None) -> Result:
    return Result(decision, REFUSED, reason, before or {}, after or {})


# --- applying ------------------------------------------------------------

def _inventory_key(item_id: str) -> dict:
    """Mirror of ``InventoryRepository.get_inventory_item``'s key.

    ``dynamodb.py`` exposes no key builder, and this script deliberately does not
    edit that module, so the shard function is imported rather than reinvented and
    a test pins the result by reading the record back through the repository.
    """
    return {"PK": f"INV#{_bucket(item_id)}", "SK": f"ITEM#{item_id}"}


class DecisionApplier:
    """Validates and (only with ``apply=True``) applies parsed decisions."""

    def __init__(self, repo: InventoryRepository, *, apply: bool = False):
        self._repo = repo
        self._table = repo._table
        self._apply = apply

    # -- entry point --
    def run(self, parsed: ParseResult) -> Report:
        """Apply every decision, one at a time, surviving any single failure.

        Each row is individually guarded: a raising row becomes a ``REFUSED``
        result and the batch continues. R7 ran this as a bare comprehension, so a
        throttle on write 4 of 7 aborted the process with three writes already on
        live money data and nothing printed — the operator could not tell what had
        landed without reconstructing it from a traceback. Writes are also
        announced as they happen, so the record of what landed exists before the
        final report does.
        """
        # BLOCKER-D: a block carries the table it was decided against. Applying it
        # to a different table is refused wholesale — a decision made against one
        # table's items must never be written to another's.
        applied_to = getattr(self._repo, "_table_name", None)
        if parsed.table and applied_to and parsed.table != applied_to:
            return Report(results=[], dry_run=not self._apply, errors=[
                f"this block was generated against table '{parsed.table}' but is "
                f"being applied to '{applied_to}' - refusing the whole batch. "
                f"Re-generate the decisions against the table you mean to write."])

        results = []
        for decision in parsed.decisions:
            try:
                result = (self._card(decision) if decision.kind == "CARD"
                          else self._txn(decision))
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                result = _refuse(decision, f"AWS refused this row ({code}) - it was "
                                           f"NOT applied; the batch continued")
            except Exception as exc:  # noqa: BLE001 - one row must not hide the rest
                result = _refuse(decision, f"{exc.__class__.__name__}: {exc} - this "
                                           f"row was NOT applied; the batch continued")
            results.append(result)
            if self._apply and result.action == UPDATE:
                print(f"  WROTE  {result.decision.label}  {result.action}",
                      flush=True)
        return Report(results=results, errors=list(parsed.errors),
                      dry_run=not self._apply)

    # -- inventory items --
    def _card(self, decision: Decision) -> Result:
        # Existence is checked for EVERY verb, including the ones that write
        # nothing: a typo'd item_id must be reported, not counted as "left
        # flagged" for a record that does not exist.
        item = self._repo.get_inventory_item(decision.record_id)
        if item is None:
            return _refuse(decision, "no inventory item with this item_id exists")
        if decision.verb == "REJECT":
            return Result(decision, SKIP_NO_WRITE,
                          "rejected - left flagged (needs_review stays True, "
                          "card_id unchanged)")
        if decision.verb == "NOCHANGE":
            return Result(decision, SKIP_NO_WRITE, "confirmed correct as stored")

        values = {k: v for k, v in decision.fields.items() if k != "note"}
        if not values:
            if decision.verb == "SET" and decision.fields.get("note"):
                return Result(decision, SKIP_NOTE_ONLY, decision.fields["note"])
            return _refuse(decision, f"{decision.verb} carries no field values, "
                                     f"nothing to apply")
        unknown = sorted(set(values) - CARD_FIELDS)
        if unknown:
            return _refuse(decision, f"unrecognized field(s) {unknown}")
        card_id = values.get("card_id")
        if not card_id:
            return _refuse(decision, "no card_id given, so there is nothing to link")

        if not hasattr(item, "card_id"):
            return _refuse(decision, f"a '{item.kind}' item has no card_id field - "
                                     f"the catalog holds single cards only")

        # LANGUAGE GATE. The catalog is English-only, so no English card_id is
        # ever the right answer for a non-English item. This is the last gate
        # before a live write and it deliberately does NOT trust the stored
        # `language` attribute alone: production items predate that field, so the
        # item's own text and TCGplayer link are read too, exactly as the review
        # page reads them.
        language = item_language(item)
        if language is not Language.EN:
            label = LANGUAGE_LABELS.get(language, language.value)
            return _refuse(decision, (
                f"this item is a {label} printing, so no English catalog card is "
                f"a correct match for it - card_id '{card_id}' would price it "
                f"from the wrong card. Its value comes from the sheet's own "
                f"figures; leave card_id unset (REJECT)"))

        card = self._repo.get_catalog_card(card_id)
        if card is None:
            return _refuse(decision, f"card_id '{card_id}' does not resolve to a "
                                     f"catalog card")
        mismatch = self._identity_mismatch(values, card)
        if mismatch:
            return _refuse(decision, f"card_id '{card_id}' does not match the block: "
                                     f"{mismatch}")

        override = values.get("override") == "stored-text-mismatch"
        stored_mismatch = self._stored_text_mismatch(values, item)
        if stored_mismatch and not override:
            return _refuse(decision, (
                f"the block disagrees with the item's OWN stored text: "
                f"{stored_mismatch}. That is either a legitimate correction of a "
                f"mistyped sheet row or a pasted wrong item_id, and nothing here "
                f"can tell them apart - re-send with "
                f"'override=stored-text-mismatch' if the correction is intended"))

        if "value" in values and _as_decimal(values["value"]) is None:
            return _refuse(decision, f"value '{values['value']}' is not a usable "
                                     f"number")

        # ``current_market_value`` is NOT written here: the nightly
        # ``refresh_inventory_market_values`` owns it. Writing it from the block
        # would be overwritten within a day, and on a re-run the stale block
        # figure would be written back over the fresher synced one - money
        # oscillating between two owners. It is reported instead, so the operator
        # still sees the figure they reviewed.
        before = {"card_id": item.card_id, "needs_review": item.needs_review}
        after = {"card_id": card_id, "needs_review": False}
        catalog_text = f"{card.name} | {card.set_name} #{card.number}"
        checked = sorted({"name", "set", "number"} & set(values))
        if not checked:
            # A card_id typed by hand on the review page arrives with no
            # confirming text, so existence in the catalog is the ONLY check it
            # gets. Say so instead of letting it read like a verified match.
            catalog_text += ("  [UNCONFIRMED: no name/set/number in the block to "
                             "cross-check the id against]")
        elif "name" not in checked:
            catalog_text += (f"  [PARTIALLY CONFIRMED: only {', '.join(checked)} "
                             f"cross-checked, not the name]")
        if override:
            catalog_text += "  [override=stored-text-mismatch accepted]"
        if "value" in values:
            catalog_text += (f"  [reviewed value {values['value']} NOT written - "
                             f"the daily sync owns current_market_value]")
        if before == after:
            return Result(decision, SKIP_APPLIED,
                          f"already resolved to {catalog_text}", before, after)
        if self._apply:
            self._write_card(decision.record_id, card_id)
        return Result(decision, UPDATE, f"link to {catalog_text}", before, after)

    @staticmethod
    def _identity_mismatch(values: dict, card) -> str:
        """Human-readable disagreement between the block's text and the catalog.

        A field that normalizes to nothing at all (a fully non-ASCII name) is a
        mismatch, not a match: two such names would otherwise both reduce to ""
        and compare equal.
        """
        checks = (("name", normalize_name, values.get("name"), card.name),
                  ("set", normalize_name, values.get("set"), card.set_name),
                  ("number", normalize_number, values.get("number"), card.number))
        problems = []
        for label, norm, given, actual in checks:
            if given is None:
                continue
            if str(given).strip() and not norm(given):
                problems.append(f"{label}: block says '{given}', which carries no "
                                f"comparable characters, so the id cannot be verified")
            elif norm(given) != norm(actual):
                problems.append(f"{label}: block says '{given}' but the catalog "
                                f"card is '{actual}'")
        return "; ".join(problems)

    @staticmethod
    def _stored_text_mismatch(values: dict, item) -> str:
        """Disagreement between the block and the item's OWN preserved sheet text.

        R7 checked the block only against the catalog card, so a block naming a
        real catalog card and a real-but-wrong item_id validated perfectly. The
        item's ``notes`` are the only record of what the sheet actually said about
        THIS physical card, so they are the thing worth disagreeing with.

        Tuned to catch substantive disagreement and nothing else. The sheet
        routinely carries qualifiers the catalog name does not ("Snorlax
        Prerelease" for catalog "Snorlax", "Tyranitar Prime" for "Tyranitar") and
        punctuation the catalog spells differently ("Stevens" vs "Steven's"), and
        refusing those would make the check noise the operator learns to override
        blindly. A genuinely different word — "Dark Chairzard" against "Dark
        Charizard", card 35 against card 21 — still fails.
        """
        source = parse_source_text(item)
        problems = []
        given_name = values.get("name")
        if given_name and source.name and not _texts_agree(given_name, source.name):
            problems.append(f"name: block says '{given_name}' but the item's own "
                            f"text says '{source.name}'")
        given_number = values.get("number")
        if given_number and source.number and \
                not _numbers_agree(given_number, source.number):
            problems.append(f"number: block says '{given_number}' but the item's "
                            f"own text says '{source.number}'")
        return "; ".join(problems)

    def _write_card(self, item_id: str, card_id: str) -> None:
        """Set the identity fields only — every other attribute is left alone.

        GSI1 keys are maintained alongside ``card_id`` so the item stays
        reachable by ``list_inventory_for_card``, exactly as a repository write
        would leave it. ``current_market_value`` is deliberately absent: the daily
        sync owns it.
        """
        self._table.update_item(
            Key=_inventory_key(item_id),
            UpdateExpression=("SET #card_id = :card_id, #needs_review = :needs_review,"
                              " #gsi1pk = :gsi1pk, #gsi1sk = :gsi1sk"),
            ConditionExpression=Attr("PK").exists(),
            ExpressionAttributeNames={"#card_id": "card_id",
                                      "#needs_review": "needs_review",
                                      "#gsi1pk": "GSI1PK", "#gsi1sk": "GSI1SK"},
            ExpressionAttributeValues={":card_id": card_id, ":needs_review": False,
                                       ":gsi1pk": f"CARD#{card_id}",
                                       ":gsi1sk": f"ITEM#{item_id}"},
        )

    # -- transactions (no-ops only; date moves are cut) --
    def _txn(self, decision: Decision) -> Result:
        """Classify a TXN decision. This tool no longer writes to the ledger.

        ``NOCHANGE`` / ``REJECT`` are no-ops (they never wrote, and now do not even
        read). Any TXN decision carrying a ``date`` — the review page emits date
        fixes as ``ACCEPT date=..; from=..`` and batch-01 wrote them as ``SET
        date=..`` — is a date-move request and is REFUSED with a pointer to the
        manual process. A note-only line surfaces the note. Anything else is
        refused as unsupported.
        """
        if decision.verb == "REJECT":
            return Result(decision, SKIP_NO_WRITE, "rejected - left exactly as stored")
        if decision.verb == "NOCHANGE":
            return Result(decision, SKIP_NO_WRITE, "confirmed correct as stored")
        if "date" in decision.fields:
            return _refuse(decision, _TXN_DATE_MOVE_REFUSAL)
        other = {k: v for k, v in decision.fields.items() if k != "note"}
        if not other and decision.fields.get("note"):
            return Result(decision, SKIP_NOTE_ONLY, decision.fields["note"])
        return _refuse(decision, (
            f"a TXN {decision.verb} is not supported by this tool - it applies "
            f"card-identity updates and TXN NOCHANGE/REJECT only. Transaction "
            f"edits are handled by the manual process in the runbook."))


# --- reporting -----------------------------------------------------------

def _format_value(value) -> str:
    return "(none)" if value is None else str(value)


def format_report(report: Report, *, table: str = "") -> str:
    """The whole per-record plan plus the summary, as one printable block."""
    mode = "DRY RUN - nothing was written" if report.dry_run else "APPLY - writing"
    where = f" to {table}" if table else ""
    lines = [f"MERLIN-REVIEW-V1 decisions - {mode}{where}",
             "=" * 72]

    if report.errors:
        lines.append(f"PARSE PROBLEMS ({len(report.errors)}) - these lines were NOT applied:")
        lines.extend(f"  ! {message}" for message in report.errors)
        lines.append("")

    for result in report.results:
        lines.append(f"line {result.decision.lineno:>3}  {result.decision.label}  "
                     f"{result.action}")
        if result.detail:
            lines.append(f"    {result.detail}")
        if result.before or result.after:
            keys = list(dict.fromkeys(list(result.before) + list(result.after)))
            lines.append("    before  " + "  ".join(
                f"{k}={_format_value(result.before.get(k))}" for k in keys))
            lines.append("    after   " + "  ".join(
                f"{k}={_format_value(result.after.get(k))}" for k in keys))

    notes = report.notes
    if notes:
        lines += ["", "NOTES FOR YOU - messages from the review, never written to the "
                      "database:"]
        lines += [f"  {record_id}: {note}" for record_id, note in notes]

    counts = report.counts
    by_kind = Counter((r.decision.kind, r.action) for r in report.results)
    lines += ["", "-" * 72, f"{len(report.results)} decisions"]
    for action in (UPDATE, SKIP_APPLIED, SKIP_NO_WRITE, SKIP_NOTE_ONLY, REFUSED):
        if counts.get(action):
            breakdown = ", ".join(f"{kind} {by_kind[(kind, action)]}" for kind in KINDS
                                  if by_kind[(kind, action)])
            lines.append(f"  {action:26} {counts[action]:>3}  ({breakdown})")
    if report.refused or report.errors:
        lines.append(f"  exit code {report.exit_code}: "
                     f"{len(report.refused)} refused row(s), "
                     f"{len(report.errors)} parse problem(s)")

    if report.dry_run:
        lines.append("  re-run with --apply to write these changes.")
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("decisions", type=Path,
                        help="file holding the MERLIN-REVIEW-V1 paste-back block")
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--endpoint-url", default=None,
                        help="override the DynamoDB endpoint (local testing)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write. WITHOUT THIS FLAG NOTHING IS WRITTEN.")
    args = parser.parse_args(argv)

    parsed = parse_block(read_block(args.decisions))
    report = Report(errors=list(parsed.errors), dry_run=not args.apply)
    try:
        repo = InventoryRepository(args.table, endpoint_url=args.endpoint_url,
                                   region_name=args.region)
        report = DecisionApplier(repo, apply=args.apply).run(parsed)
    except Exception as exc:  # noqa: BLE001 - the report must print regardless
        # Reached only if something outside a single row fails (the transaction
        # scan, credentials, the table itself). Whatever landed before it must
        # still be printed, so the operator is never left with a traceback as the
        # only account of a partially applied money batch.
        report.errors.append(f"RUN FAILED: {exc.__class__.__name__}: {exc}")
    finally:
        print(format_report(report, table=args.table))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
