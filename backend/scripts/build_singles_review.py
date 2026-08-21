"""Review page for CURRENTLY-HELD singles, read fresh from the updated workbook.

The owner decided to stop reviewing every card ever held and only settle what is
still in hand. This reads the Singles tab of the new inventory ``.xlsx`` directly
(not the old review.html, and not the database), keeps only cards still held
(not sold, not lost), matches each to the catalog — using the row's TCGplayer
link to break set ties, exactly like the importer now does — and renders the
SAME self-contained review page ``build_review.py`` produces: one suggested
identity + market price per card, which you approve or override.

Read-only against DynamoDB (a catalog scan is the only call). Writes
``data/spreadsheet/review.html``.

    cd backend
    python scripts/build_singles_review.py --xlsx "../data/spreadsheet/7-25-2026 Inventory.xlsx"
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
from pathlib import Path

import openpyxl

import build_review as br
from merlins_collection.config import settings
from merlins_collection.models.inventory import Language
from merlins_collection.services.card_text import (
    SourceText,
    language_from_url,
    normalize_number,
    parse_language,
    set_hint_from_url,
)
from merlins_collection.services.spreadsheet_import import map_location, parse_condition, parse_money


def _row_reader(header):
    """A ``_find``-style getter tolerant of the sheet's dated header drift
    ("Sticker" -> "Sticker updated 7/24")."""
    idx = {str(h).strip(): i for i, h in enumerate(header) if h is not None}

    def get(row, *names):
        for n in names:
            i = idx.get(n)
            if i is not None and i < len(row) and row[i] is not None:
                return str(row[i]).strip()
        core = min(names, key=len)
        if len(core) >= 6:
            for h, i in idx.items():
                if h.lower().startswith(core.lower()) and i < len(row) and row[i] is not None:
                    return str(row[i]).strip()
        return ""

    return get


def read_held_singles(xlsx_path):
    """Yield the held singles (not sold, not lost) as (fields, get) records."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Singles"]
    it = ws.iter_rows(values_only=True)
    get = _row_reader(next(it))
    held = []
    for row in it:
        if not any(c is not None for c in row):
            continue
        name = get(row, "Name")
        if not name:
            continue
        sold = get(row, "Sold") or get(row, "Date Sold")
        loc = map_location(get(row, "Location"))
        if sold or loc["status"] == "lost":
            continue
        held.append((row, get, loc))
    return held


def _stable_id(name, number, tcg_url):
    key = f"{name}|{number}|{tcg_url}".lower()
    return "s" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def build_rows(held, index, prices):
    rows = []
    for row, get, loc in held:
        tcg_url = get(row, "TCG Link") or None
        language, name = parse_language(get(row, "Name"))
        if language is Language.EN:
            language = language_from_url(tcg_url)
        number = normalize_number(get(row, "Card #"))
        # The row's TCGplayer link names the set — feed it as the source set so
        # predict_card can narrow a name+number tie the same way the importer does.
        set_hint = set_hint_from_url(tcg_url)
        source = SourceText(name=name, number=number, set_name=set_hint,
                            language=language.value)

        try:
            condition, modifier = parse_condition(get(row, "Condition") or "NM")
        except ValueError:
            condition, modifier = None, None
        item = {
            "kind": "raw", "finish": "normal",
            "listed_price": parse_money(get(row, "Sticker")),
            "market_value_at_purchase": parse_money(get(row, "Market @ purchase")),
        }

        if language is not Language.EN:
            prediction = br.CardPrediction([], br.NO_MATCH_BAND,
                                           f"{br.LANGUAGE_LABELS.get(language, language.value)} "
                                           f"print — the catalog is English-only, so its value "
                                           f"comes from your sheet, not a match")
        else:
            prediction = br.predict_card(source, index, kind="raw", max_candidates=8)
            prediction = br._order_by_price_fit(prediction, item, prices)

        best = prediction.best
        points = prices.get(best["card_id"], []) if best else []
        value = br.predict_value(item, best, points)
        divergence = br.value_divergence(value.value, item)
        rows.append({
            "item_id": _stable_id(name, number, tcg_url or ""),
            "kind": "raw", "status": loc["status"],
            "source": {"name": name, "number": number, "set": set_hint, "extra": ""},
            "stored": {
                "cost_basis": br._money(parse_money(get(row, "Amount Paid"))),
                "listed_price": br._money(item["listed_price"]),
                "market_value_at_purchase": br._money(item["market_value_at_purchase"]),
                "acquired_at": get(row, "Date"),
                "condition": f"{condition.value}{modifier.value if modifier else ''}"
                if condition else None,
                "company": None, "grade": None, "cert_number": None,
                "finish": "normal", "location": loc["location"],
                "product_type": None,
                "notes": get(row, "Notes") or None,
                "tcg_url": tcg_url, "card_id": None, "language": language.value,
            },
            "prediction": (br._card_view(best, item, points) | {
                "value": br._money(value.value), "value_basis": value.basis,
                "value_note": value.note}) if best else None,
            "runners": [br._card_view(c, item, prices.get(c["card_id"], []))
                        for c in prediction.candidates[1:]],
            "confidence": prediction.confidence, "reason": prediction.reason,
            "divergence": {**divergence, "basis": br._money(divergence["basis"]),
                           "delta": br._money(divergence["delta"])} if divergence else None,
        })
    for r in rows:
        diverged = bool(r["divergence"] and r["divergence"]["flagged"])
        mag = abs(float(r["divergence"]["delta"])) if diverged else 0.0
        r["priority"] = round(br.CONFIDENCE_RANK[r["confidence"]] * 100
                              + (50 if diverged else 0) + min(mag, 49) / 50, 3)
    rows.sort(key=lambda r: (-r["priority"], r["item_id"]))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--xlsx", required=True, help="the updated inventory workbook")
    parser.add_argument("--table", default=settings.dynamodb_table_name)
    parser.add_argument("--region", default=settings.aws_region)
    parser.add_argument("--out", default=None, type=Path)
    args = parser.parse_args(argv)

    print(f"Reading {args.table} ({args.region}) — read-only catalog scan...")
    data = br.collect(br.scan_records(
        args.table, args.region,
        progress=lambda seen: print(f"  {seen} records read", end="\r")))
    print(f"\n  catalog cards {len(data['catalog'])} · cards with prices {len(data['prices'])}")

    index = br.CatalogIndex.build(data["catalog"])
    held = read_held_singles(args.xlsx)
    rows = build_rows(held, index, data["prices"])

    from collections import Counter
    bands = Counter(r["confidence"] for r in rows)
    print(f"  held singles {len(rows)} -> HIGH {bands['HIGH']} / MEDIUM {bands['MEDIUM']} "
          f"/ LOW {bands['LOW']} / N/A {bands[br.NO_MATCH_BAND]}")

    out = args.out or (Path(__file__).resolve().parents[2] / "data" / "spreadsheet" / "review.html")
    html = br.render_html(rows, table_name=f"{args.table} · held singles",
                          generated_at=datetime.now().isoformat(timespec="seconds"))
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out.resolve()} ({len(html) / 1024:.0f} KB) — open it in a browser.")


if __name__ == "__main__":
    main()
