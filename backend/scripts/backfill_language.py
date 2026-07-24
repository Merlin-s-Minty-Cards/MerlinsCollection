"""One-off backfill: record the print LANGUAGE of the inventory already stored.

The live table was imported before ``language`` existed, so every Japanese card
in it is recorded as English with its marker still sitting in the name text
("Seismitoad (jp) #38"). This walks the inventory and stamps ``language`` on each
item whose stored text — or TCGplayer link — identifies it as non-English.

    cd backend
    python scripts/backfill_language.py                       # DRY RUN (default)
    python scripts/backfill_language.py --apply --expect-count 109
    python scripts/backfill_language.py --apply --strip-markers   # LATER, see below

**A DRY RUN IS THE DEFAULT.** Nothing is written without ``--apply``; the dry run
prints the full per-record plan — including each row's ``card_id`` — so the change
can be read in full before any of it happens.

TWO SEPARATE OPERATIONS, DELIBERATELY
-------------------------------------
``--apply`` stamps ``language`` and **leaves the marker in the text**.
``--strip-markers`` is a second, later run that removes it.

They are split because the marker is the only evidence that lets this script find
a row again. Removing it while the deployed model has no ``language`` field is
irreversible in a way that is easy to miss: pydantic defaults to
``extra="ignore"``, so a stored ``language`` is dropped at validation, and
``put_inventory_item`` is a whole-record put built from ``model_dump()`` — so one
pass of the nightly sync over a linked item would erase the stamp, and the marker
that would have let us recover it is already gone. Stamping alone is reversible:
the marker still says JP, so a later run can re-plan the row. Only strip once the
model carrying ``language`` is deployed (Council R7 BLOCKER-2).

Safety properties, all test-enforced:

* **Idempotent.** A row already carrying the right language (and, when stripping,
  clean text) is never planned, so re-running is a no-op.
* **Pinnable.** ``--expect-count N`` and ``--expect-digest`` abort before any write
  if the re-scanned plan is not the one that was reviewed. ``--apply`` re-reads the
  table, so without these the dry run and the write are two unrelated reads.
* **Surgical writes.** The only DynamoDB write API used is ``update_item``, setting
  at most two attributes. A whole-record write would drop the import ``gen`` stamp.
* **Inventory only.** Records that are not ``inventory_item`` — the ~53k catalog
  cards and price points — are never considered, let alone written.
* **Money is never touched.** ``cost_basis``, ``listed_price``,
  ``market_value_at_purchase``, ``current_market_value`` and ``card_id`` are not in
  the update expression.
* **Conditional.** Each write is conditional on the text still being exactly what
  the plan was built from, so a record edited in between is skipped, not clobbered.
* **A failure cannot hide.** One row raising does not abort the batch, the summary
  always prints, and the process exits non-zero unless every planned row landed.

Defaults come from the app's own settings (``MERLINS`` env / ``backend/.env``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass

import boto3
from boto3.dynamodb.conditions import Attr

from merlins_collection.config import settings
from merlins_collection.models.inventory import ITEM_TEXT_FIELD, Language
from merlins_collection.services.card_text import item_language, parse_language


@dataclass(frozen=True)
class LanguagePlan:
    """One item's intended change, in full, before anything is written."""

    key: dict
    item_id: str
    kind: str
    field: str
    before_text: str
    after_text: str
    before_language: str
    after_language: str
    card_id: str | None = None

    @property
    def strips_text(self) -> bool:
        return self.after_text != self.before_text


def plan_updates(records, *, strip_markers: bool = False) -> list[LanguagePlan]:
    """Every inventory item that needs a language recorded, with before/after.

    Pure: it reads records and returns intent. A row is planned only when it is an
    ``inventory_item``, it resolves to a non-English language, and applying the
    change would actually alter something — which is what makes a second run a
    no-op. With ``strip_markers=False`` (the default) the text is left exactly as
    stored and only the ``language`` attribute changes.
    """
    plans = []
    for record in records:
        if record.get("entity") != "inventory_item":
            continue
        kind = str(record.get("kind") or "raw")
        field = ITEM_TEXT_FIELD.get(kind)
        if field is None:
            continue
        language = item_language(record)
        if language is Language.EN:
            continue
        before_text = str(record.get(field) or "")
        after_text = parse_language(before_text)[1] if strip_markers else before_text
        before_language = str(record.get("language") or Language.EN.value).upper()
        if before_language == language.value and after_text == before_text:
            continue  # already done
        plans.append(LanguagePlan(
            key={"PK": record["PK"], "SK": record["SK"]},
            item_id=str(record.get("item_id") or ""),
            kind=kind,
            field=field,
            before_text=before_text,
            after_text=after_text,
            before_language=before_language,
            after_language=language.value,
            card_id=record.get("card_id"),
        ))
    return plans


def plan_digest(plans) -> str:
    """A stable fingerprint of exactly which rows change and how.

    ``--expect-count`` catches a plan that grew; this catches one that changed
    membership without changing size.
    """
    body = json.dumps(
        [[p.key["PK"], p.key["SK"], p.field, p.before_text, p.after_text,
          p.after_language, p.card_id]
         for p in sorted(plans, key=lambda p: (p.key["PK"], p.key["SK"]))],
        sort_keys=True, ensure_ascii=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def format_plan(plan: LanguagePlan) -> str:
    """One planned row, including the ``card_id`` that decides how dangerous it is.

    A non-English item holding a ``card_id`` is being priced from an English card
    by the nightly sync, so it is called out rather than merely listed.
    """
    linked = "  <<< LINKED — see the warning above" if plan.card_id else ""
    lines = [f"{plan.item_id} [{plan.kind}] "
             f"language {plan.before_language} -> {plan.after_language}  "
             f"card_id={plan.card_id}{linked}"]
    if plan.strips_text:
        lines.append(f"    {plan.field}: {plan.before_text!r}")
        lines.append(f"          -> {plan.after_text!r}")
    else:
        lines.append(f"    {plan.field}: {plan.before_text!r} (unchanged)")
    return "\n".join(lines)


def apply_updates(table, plans) -> tuple[int, list]:
    """Write the planned changes; return ``(written, failed_plans)``.

    Each write sets ONLY ``language`` and (when stripping) the one text field, and
    is conditional on that text still holding the value the plan was built from —
    so a record that changed in between is skipped rather than overwritten with
    stale text. A row that raises is reported and the batch continues: stopping
    part-way through 109 writes with nothing on screen is how an operator ends up
    not knowing what landed.
    """
    from botocore.exceptions import ClientError

    written, failed = 0, []
    for plan in plans:
        names = {"#lang": "language", "#field": plan.field}
        values = {":lang": plan.after_language, ":before": plan.before_text}
        assignments = ["#lang = :lang"]
        if plan.strips_text:
            assignments.append("#field = :after")
            values[":after"] = plan.after_text
        try:
            table.update_item(
                Key=plan.key,
                UpdateExpression="SET " + ", ".join(assignments),
                ConditionExpression="attribute_exists(PK) AND #field = :before",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
            written += 1
            print(f"  OK      {plan.item_id} language={plan.after_language}")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            failed.append(plan)
            if code == "ConditionalCheckFailedException":
                print(f"  SKIPPED {plan.item_id}: record changed since the plan "
                      f"was built; left untouched")
            else:
                print(f"  FAILED  {plan.item_id}: {code} — continuing")
        except Exception as exc:  # noqa: BLE001 — one bad row must not hide the rest
            failed.append(plan)
            print(f"  FAILED  {plan.item_id}: {exc.__class__.__name__} — continuing")
    return written, failed


def language_is_persisted() -> bool:
    """True when the model this checkout runs round-trips a ``language`` field.

    ``--strip-markers`` destroys the recovery marker, and if the deployed
    backend's model still lacks ``language`` its whole-record ``put_inventory_item``
    would drop the stamp — leaving the row with neither. A model without the field
    silently drops it (pydantic ``extra="ignore"``), so a probe value comes back as
    the ``EN`` default and we refuse to strip. This catches a stale checkout
    automatically; the ``--model-deployed`` flag is the operator asserting the
    separate deploy, which no code can verify remotely.
    """
    from decimal import Decimal

    from merlins_collection.models.inventory import InventoryItemAdapter

    probe = {"kind": "raw", "cost_basis": Decimal("0"), "acquired_at": "2026-01-01",
             "finish": "normal", "condition": "NM", "language": "JP"}
    try:
        item = InventoryItemAdapter.validate_python(probe)
        return str(getattr(item.language, "value", item.language)) == "JP"
    except Exception:  # noqa: BLE001 — any failure means the field is not usable
        return False


def scan_inventory(table):
    """Yield every ``inventory_item`` record (paginated, filtered server-side).

    ``ConsistentRead`` so a re-run after a crash sees this script's own writes and
    cannot report "record changed since the plan was built" for rows it changed
    itself seconds earlier.
    """
    kwargs = {"FilterExpression": Attr("entity").eq("inventory_item"),
              "ConsistentRead": True}
    while True:
        response = table.scan(**kwargs)
        yield from response.get("Items", [])
        last = response.get("LastEvaluatedKey")
        if not last:
            return
        kwargs["ExclusiveStartKey"] = last


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table to back-fill (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--endpoint-url", default=None,
                        help="override the DynamoDB endpoint (local testing)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write. WITHOUT THIS FLAG NOTHING IS WRITTEN.")
    parser.add_argument("--strip-markers", action="store_true",
                        help="ALSO remove the language marker from the stored text. "
                             "Refused unless --model-deployed is also given AND this "
                             "checkout's model round-trips `language` — see the "
                             "module docstring.")
    parser.add_argument("--model-deployed", action="store_true",
                        help="assert that the backend model carrying `language` is "
                             "live. Required by --strip-markers; the runbook issues "
                             "it only after the deploy.")
    parser.add_argument("--expect-count", type=int, default=None,
                        help="abort unless exactly N rows are planned (pins the "
                             "plan you reviewed in the dry run)")
    parser.add_argument("--expect-digest", default=None,
                        help="abort unless the plan's digest matches the one the "
                             "dry run printed")
    return parser


def main(argv=None) -> dict:
    args = _parser().parse_args(argv)
    summary = {"scanned": 0, "planned": 0, "updated": 0, "linked": 0,
               "failed": 0, "aborted": False, "digest": "",
               "applied": bool(args.apply), "error": None}
    try:
        table = boto3.resource("dynamodb", region_name=args.region,
                               endpoint_url=args.endpoint_url).Table(args.table)
        mode = "APPLY" if args.apply else "DRY RUN — nothing will be written"
        if args.apply and args.strip_markers:
            mode = "APPLY + STRIP MARKERS"
        print(f"{args.table} ({args.region}) — {mode}")

        records = list(scan_inventory(table))
        plans = plan_updates(records, strip_markers=args.strip_markers)
        summary["scanned"] = len(records)
        summary["planned"] = len(plans)
        summary["digest"] = plan_digest(plans)
        summary["linked"] = sum(1 for p in plans if p.card_id)

        if summary["linked"]:
            print(f"\n!! {summary['linked']} planned row(s) already carry a card_id. "
                  f"A non-English item linked to an English catalog card is priced "
                  f"from the wrong card by the nightly sync — unlink those first.\n")
        for plan in plans:
            print(format_plan(plan))

        # The strip interlock is checked before anything else so a bare
        # --strip-markers refuses regardless of the plan (BLOCKER-B).
        strip_reason = None
        if args.strip_markers:
            if not args.model_deployed:
                strip_reason = ("--strip-markers destroys the recovery marker and "
                                "is refused without --model-deployed, which asserts "
                                "the `language`-bearing model is live. Stamp first "
                                "(--apply, no strip); strip only after the deploy.")
            elif not language_is_persisted():
                strip_reason = ("this checkout's model does not round-trip a "
                                "`language` field, so stripping the marker would "
                                "leave the row unrecoverable. Refusing to strip.")

        if strip_reason:
            summary["aborted"] = True
            print(f"\nABORT: {strip_reason} Nothing was written.")
        elif args.expect_count is not None and args.expect_count != len(plans):
            summary["aborted"] = True
            print(f"\nABORT: --expect-count {args.expect_count} but {len(plans)} "
                  f"rows are planned. The table is not in the state you reviewed; "
                  f"nothing was written.")
        elif args.expect_digest and args.expect_digest != summary["digest"]:
            summary["aborted"] = True
            print(f"\nABORT: --expect-digest {args.expect_digest} but this plan is "
                  f"{summary['digest']}. The rows changed since the dry run; "
                  f"nothing was written.")
        elif args.apply and summary["linked"]:
            # The "zero linked" precondition is the one the whole procedure rests
            # on. Under --apply it is enforced, not merely printed (BLOCKER-C).
            summary["aborted"] = True
            print(f"\nABORT: {summary['linked']} planned row(s) carry a card_id. "
                  f"Stamping a linked non-English item leaves it priced from an "
                  f"English card by the nightly sync — unlink those rows (via the "
                  f"review page / applier) before backfilling. Nothing was written.")
        elif args.apply:
            written, failed = apply_updates(table, plans)
            summary["updated"] = written
            summary["failed"] = len(failed)
    except Exception as exc:  # noqa: BLE001 — the summary must print regardless
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
        print(f"\nERROR: {summary['error']}")
    finally:
        print(f"\n{summary['scanned']} inventory items scanned · "
              f"{summary['planned']} need a language recorded · "
              f"{summary['updated']} updated · {summary['failed']} failed"
              + ("" if args.apply else " (DRY RUN — re-run with --apply to write)"))
        if summary["digest"]:
            print(f"plan digest {summary['digest']} — pass it back as "
                  f"--expect-digest {summary['digest']} to pin this exact plan")
    return summary


def cli(argv=None) -> int:
    """Exit non-zero unless the run did everything it set out to do.

    A dry run with outstanding work is *not* success: it means the table still
    needs the backfill. This is what lets a wrapper or CI step tell the difference,
    which R7 could not — it always exited 0.
    """
    summary = main(argv)
    if summary["error"] or summary["aborted"] or summary["failed"]:
        return 1
    if summary["applied"]:
        return 0 if summary["updated"] == summary["planned"] else 1
    return 1 if summary["planned"] else 0


if __name__ == "__main__":
    raise SystemExit(cli())
