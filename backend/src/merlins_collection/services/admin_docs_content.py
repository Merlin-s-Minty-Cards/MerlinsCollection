"""The admin operations knowledge base — RFC 0026.

This is DATA, not logic: a fixed Python list of articles, imported directly
by both `services/admin_docs.py` (which backs `GET /admin/docs` and the
`search_admin_docs` MCP tool) and nothing else. Deliberately NOT a JSON file
read off disk at runtime — a plain Python import ships with the package
automatically under every install mode (editable, wheel, container image),
sidestepping the exact "runtime file read that doesn't survive packaging"
bug class CLAUDE.md documents for the admin tool contract. See RFC 0026's
Detailed Design section for the full reasoning.

**Scope of an article**: what an admin DOES, WHY, and what it COSTS — never
backend implementation internals (DynamoDB keys, generation-sweep mechanics,
Lambda packaging) that no admin action depends on knowing. CLAUDE.md stays
the engineering reference; this is the operational one, translated from it
for a non-technical admin standing at `/admin`, not a developer.

Adding a new article: append an `AdminDocArticle` to `ARTICLES` below. `id`
must be a unique lowercase-kebab slug (enforced both here, via the field
validator, and by `test_admin_docs_content.py`'s totality tests) and
`category` must be one of `ADMIN_DOC_CATEGORIES`'s ids.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class AdminDocArticle(BaseModel):
    id: str
    category: str
    title: str
    summary: str
    body: str
    keywords: list[str] = []
    related_routes: list[str] = []

    @field_validator("id")
    @classmethod
    def _id_is_a_slug(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError(f"{value!r} is not a lowercase-kebab slug")
        return value


#: Ordered so the frontend's category rail and the browse index both list
#: categories the same way — mirrors AdminShell's own three sidebar-group
#: labels (`at-the-show`/`back-office`/`data`) so an admin's existing mental
#: model of the sidebar carries straight over, plus the cross-cutting
#: sections the owner explicitly asked for (money, costs) and two reference
#: sections (chat, glossary).
ADMIN_DOC_CATEGORIES: list[tuple[str, str]] = [
    ("overview", "Overview"),
    ("at-the-show", "At the Show"),
    ("back-office", "Back Office"),
    ("data", "Data & Reporting"),
    ("money", "Money & Calculations"),
    ("costs", "Costs, Quotas & Schedules"),
    ("chat", "Asking the Analyst Chat"),
    ("glossary", "Glossary"),
]


ARTICLES: list[AdminDocArticle] = [
    # ---- Overview ----
    AdminDocArticle(
        id="sidebar-groups",
        category="overview",
        title="How the sidebar is organized",
        summary="The sidebar is grouped by WHEN you use a tab, not alphabetically.",
        keywords=["sidebar", "navigation", "groups", "layout"],
        body=(
            "The admin sidebar has three groups, plus Dashboard on its own:\n\n"
            "- **At the Show** — the tabs you use while a customer or a deal "
            "is in front of you: Inventory, Buy / Sell / Trade, Slabs.\n"
            "- **Back Office** — the paperwork you do between shows: Prep "
            "Queue, Show Prep, Shows, Triage, Unmatched, Market, Vault.\n"
            "- **Data & Reporting** — the numbers: Show Analytics, History, "
            "Cosigners, Locations.\n\n"
            "The groups are collapsible, but whichever group holds the page "
            "you're currently on stays open automatically. Every route/URL "
            "under a tab has stayed the same even when the tab moved between "
            "groups or got renamed — so an old bookmark still works."
        ),
        related_routes=["/admin"],
    ),
    AdminDocArticle(
        id="dashboard-overview",
        category="overview",
        title="What the Dashboard shows",
        summary="Quick actions, what needs attention today, and where things stand.",
        keywords=["dashboard", "home", "quick actions"],
        body=(
            "The Dashboard is the front page: quick actions for the most "
            "common tasks, a \"needs attention\" queue (Triage items, "
            "unstickered inventory, and similar things worth a look), your "
            "position at the current show if one is running, and a coverage "
            "summary. It's a starting point, not a replacement for any of "
            "the other tabs."
        ),
        related_routes=["/admin"],
    ),
    AdminDocArticle(
        id="docs-and-chat-overview",
        category="overview",
        title="This Docs tab and the Analyst Chat",
        summary="Two ways to get help: read a page here, or ask the chat directly.",
        keywords=["docs", "help", "chat", "analyst"],
        body=(
            "This Docs tab is for browsing or searching how something works. "
            "The Analyst Chat (the chat icon in the header, on every tab) is "
            "for asking a direct question instead — it can read this exact "
            "same material, plus the business's own numbers (profit, aging "
            "stock, consignor positions). See **Asking the Analyst Chat** for "
            "what it can and can't do."
        ),
        related_routes=["/admin/docs"],
    ),
    # ---- At the Show ----
    AdminDocArticle(
        id="inventory-search-and-edit",
        category="at-the-show",
        title="Inventory: searching, sorting, and editing in place",
        summary="Every column is sortable and filterable, and most cells edit in place.",
        keywords=["inventory", "search", "filter", "sort", "inline edit"],
        body=(
            "The Inventory tab is the full item list. Every column can be "
            "sorted (click the header) and filtered — click \"Show all "
            "filters\" if the one you want isn't already showing next to its "
            "column.\n\n"
            "Most cells are click-to-edit: hover a value and a pencil icon "
            "appears, or tab to it and press Enter. A few fields (Price, "
            "Cost, Sticker Price, Location, Status) show a short \"undo\" "
            "toast for a few seconds after you change them — click it if you "
            "made a mistake, instead of re-typing the old value by hand.\n\n"
            "Missing values (no price, no set, etc.) always sort to the *last* "
            "position no matter which direction you sort — so they never get "
            "hidden in the middle of a sorted column."
        ),
        related_routes=["/admin/inventory"],
    ),
    AdminDocArticle(
        id="buy-sell-trade-modes",
        category="at-the-show",
        title="Buy / Sell / Trade: one page, three modes",
        summary="One page handles buying, selling, and trading — switch modes at the top.",
        keywords=["buy", "sell", "trade", "deal", "mode"],
        body=(
            "Buy, Sell and Trade all live on one page now — switch between "
            "them with the mode toggle at the top. If you have cards already "
            "staged and switch modes, you'll be asked to confirm first, "
            "because a staged deal belongs to one mode and can't carry over "
            "to another.\n\n"
            "**Customer View** hides your cost and the acquisition-ratio "
            "percentage from what's shown on screen — turn it on before you "
            "turn a screen toward a customer at the table. The card's market "
            "price still shows either way."
        ),
        related_routes=["/admin/trade"],
    ),
    AdminDocArticle(
        id="card-identification-rule",
        category="at-the-show",
        title="Why every card picker shows image AND price",
        summary=(
            "Names alone aren't enough — every card list shows image, name, "
            "and price together."
        ),
        keywords=["card picker", "image", "price", "identify"],
        body=(
            "Whenever you're picking a card out of a list — in a search "
            "result, a staged trade leg, a repair tool — you'll always see "
            "its image and its price next to its name. This isn't a "
            "convenience, it's a hard rule: Pokémon names collide constantly "
            "across sets, printings, finishes and languages, and you're "
            "standing there holding the physical card. A name-only list is "
            "one you can't actually use to tell cards apart.\n\n"
            "If a card has no catalog match, you'll see a placeholder image "
            "instead of a blank space — a missing image is never hidden, "
            "just shown as \"no image available.\""
        ),
    ),
    AdminDocArticle(
        id="manual-entry-always-available",
        category="at-the-show",
        title="Manual entry is always available, not just when search fails",
        summary=(
            "The manual-entry button is always there, even when the catalog "
            "search finds results."
        ),
        keywords=["manual entry", "search", "wrong printing"],
        body=(
            "On Buy/Trade and Slabs intake, \"Manual entry\" is always a "
            "visible option — it's never hidden behind a failed search. "
            "That matters because the common problem isn't \"the card "
            "doesn't exist in the catalog\" — it's \"the card exists, but "
            "every result is the wrong printing.\" If the search technically "
            "\"worked\" but none of the results are right, use manual entry "
            "rather than picking the closest wrong match."
        ),
    ),
    AdminDocArticle(
        id="slabs-intake",
        category="at-the-show",
        title="Slabs: how graded-card intake works",
        summary="Scan or type the cert, pick the card, stage it, then commit the whole batch.",
        keywords=["slabs", "graded", "cert", "psa", "cgc", "bgs", "sgc", "intake"],
        body=(
            "Slab intake is one flow for every grading company (PSA, CGC, "
            "BGS, SGC) — there's no separate path per company. Type or scan "
            "the cert number (a wedge barcode scanner just types fast, so "
            "the same field works for both), identify the card via the "
            "catalog search or \"Manual entry\", enter company/grade/cost, "
            "and add it to the staging batch. When the batch is ready, "
            "**Commit** turns it into a real purchase, exactly like any "
            "other buy.\n\n"
            "If a cert number is already in the system, you'll get a "
            "**warning**, not a block — a card can legitimately be sold and "
            "bought back later, so re-entering a cert is allowed, just "
            "flagged so you notice.\n\n"
            "**Pricing happens AFTER commit, as a separate step** — the "
            "commit itself never waits on a price lookup. If a slab's card "
            "isn't in the catalog (a manually-entered/unmatched card), it "
            "simply won't have a price yet; that's expected, not an error."
        ),
        related_routes=["/admin/slabs"],
    ),
    # ---- Back Office ----
    AdminDocArticle(
        id="prep-queue-purpose",
        category="back-office",
        title="Prep Queue: unstickered inventory, not a shipment tracker",
        summary="Prep Queue finds available inventory that still needs a sticker price.",
        keywords=["prep queue", "outgoing", "sticker", "unstickered"],
        body=(
            "Prep Queue's job today is finding available inventory that "
            "doesn't have a sticker price yet, so you can price it before it "
            "goes out to a show. (Its URL is still `/admin/outgoing` from "
            "when it used to track outgoing shipments — the page changed, "
            "the address didn't.)\n\n"
            "Setting a price on a card here removes it from the list right "
            "away, without reloading the whole page — that's why the list "
            "doesn't jump around while you're pricing several cards in a "
            "row. Clearing a price (instead of setting one) leaves the row "
            "in place, since a cleared card still needs a sticker."
        ),
        related_routes=["/admin/outgoing"],
    ),
    AdminDocArticle(
        id="show-prep-workflow",
        category="back-office",
        title="Show Prep: getting inventory ready for a show",
        summary=(
            "Bulk-move cards into show boxes and fix sticker/TCGplayer-link "
            "details before you go."
        ),
        keywords=["show prep", "bulk move", "location", "sticker"],
        body=(
            "Show Prep is where you move a batch of cards into show-box "
            "locations before an event, and touch up sticker prices or "
            "TCGplayer links on the way. Filter by location and sort by "
            "whichever column matters (price, name, whatever) to work "
            "through a box efficiently."
        ),
        related_routes=["/admin/show-prep"],
    ),
    AdminDocArticle(
        id="shows-crud-and-archiving",
        category="back-office",
        title="Shows: adding, editing, and \"deleting\" a show",
        summary="\"Delete\" on a show archives it — nothing about a past show is ever destroyed.",
        keywords=["shows", "archive", "delete", "crud"],
        body=(
            "The Shows tab is where show/event days are created and edited. "
            "\"Delete\" here **archives** the show rather than destroying "
            "it — a show that already has sales or purchases behind it "
            "still archives normally, because nothing is removed, just "
            "hidden from the default list. Turn on \"Show archived\" to see "
            "it again, and un-archive it if you need to.\n\n"
            "Archiving a show also generates its analytics snapshot "
            "automatically (net sales, items sold/bought), so the Shows tab "
            "on Show Analytics fills in a real number instead of staying at "
            "zero for a show nobody ever pressed \"Generate\" on."
        ),
        related_routes=["/admin/shows"],
    ),
    AdminDocArticle(
        id="triage-queue",
        category="back-office",
        title="Triage: fixing what the automation got wrong",
        summary=(
            "The one place to correct data problems — a missing name, a bad "
            "card link, or a manual flag."
        ),
        keywords=["triage", "needs review", "missing card", "missing name"],
        body=(
            "Triage is the queue of items that need a human look. A card "
            "ends up here for one of a few reasons, shown as chips on the "
            "row — a missing catalog link, a Japanese item with no English "
            "name assigned yet, or someone explicitly flagging it. An item "
            "can carry more than one reason at once.\n\n"
            "**\"Bulk clear\"** only clears the automatic, machine-detected "
            "reasons — never a human's own written flag, and never a blank "
            "condition. Blank conditions were imported as Near Mint by "
            "default, the most expensive tier, so bulk-clearing those would "
            "quietly ratify an inflated price on a card nobody has actually "
            "graded — clear those one at a time, on purpose."
        ),
        related_routes=["/admin/triage"],
    ),
    AdminDocArticle(
        id="unmatched-queue",
        category="back-office",
        title="Unmatched: cards the catalog simply doesn't have",
        summary="For cards TCGdex doesn't carry at all — parked here, not stuck in Triage forever.",
        keywords=["unmatched", "no catalog match", "parked"],
        body=(
            "Unmatched is for a card that genuinely isn't in the catalog — "
            "not a search mistake, an actual gap. Parking a card here clears "
            "its market-value figure (a leftover figure from a "
            "close-but-wrong catalog match would otherwise be misleading, "
            "and no future price sync will ever correct it once the link is "
            "gone), and it's hand-valued from then on.\n\n"
            "Nothing here happens automatically — a card only lands in "
            "Unmatched because an admin put it there. If the catalog "
            "catches up later, pair it back to a real card and it moves on."
        ),
        related_routes=["/admin/unmatched"],
    ),
    AdminDocArticle(
        id="market-sync-buttons",
        category="back-office",
        title="Market tab: search, watchlist, and the sync buttons",
        summary=(
            "Coverage/confidence numbers, catalog search, and the two sync "
            "actions — see Costs for how often to press them."
        ),
        keywords=["market", "sync prices", "check for new sets", "coverage", "watchlist"],
        body=(
            "The Market tab is where catalog search, price coverage/"
            "confidence, and the watchlist live, plus two buttons: **Sync "
            "Prices** and **Check for new sets**. Both are also already "
            "running automatically on a schedule (overnight for prices, "
            "monthly for new sets) — pressing the button by hand is for "
            "catching up sooner, not the only time they ever run. See "
            "\"Sync Prices: what it costs and how often to press it\" in "
            "Costs, Quotas & Schedules before pressing either one repeatedly "
            "in one day."
        ),
        related_routes=["/admin/market"],
    ),
    AdminDocArticle(
        id="vault-tab",
        category="back-office",
        title="Vault: the sortable full inventory view",
        summary="A sortable table of everything in stock, including ownership.",
        keywords=["vault", "inventory table", "ownership"],
        body=(
            "Vault is a straightforward sortable table of the full "
            "inventory, including who owns each item (the business, or a "
            "consignor). \"Send to Vault\" from a card's detail panel is how "
            "an item gets held here without a sale — it writes immediately, "
            "with no note to type, and offers to undo for a few seconds "
            "right after."
        ),
        related_routes=["/admin/vault"],
    ),
    # ---- Data & Reporting ----
    AdminDocArticle(
        id="show-analytics-tabs",
        category="data",
        title="Show Analytics: Daily vs. Shows tabs",
        summary="Daily is one day's dashboard; Shows is every show's own numbers.",
        keywords=["analytics", "daily", "shows tab", "reporting"],
        body=(
            "The Daily tab shows one day at a time — sales, purchases, and a "
            "click-through to every individual sale in a bundled group "
            "(click the \"N cards\" cell on a sale to see each card's image, "
            "name and price, rather than a bare row of IDs).\n\n"
            "The Shows tab lists every show with its own generated "
            "analytics — net sales, items sold/bought — sortable by date or "
            "name. A show with no snapshot yet (never archived, never "
            "manually generated) shows as having no data, which is not the "
            "same thing as \"sold nothing.\""
        ),
        related_routes=["/admin/analytics"],
    ),
    AdminDocArticle(
        id="void-vs-edit-transactions",
        category="data",
        title="History: voiding vs. editing a transaction",
        summary=(
            "Void means \"this never happened\"; Edit means \"it happened, "
            "but a detail was typed wrong.\""
        ),
        keywords=["history", "void", "edit", "transaction", "correction"],
        body=(
            "Two different tools for two different mistakes:\n\n"
            "- **Void** says the sale didn't happen at all. It's for a "
            "genuine mistake — the wrong item was rung up, or a sale needs "
            "to be undone entirely. Only **sales** can be voided — a "
            "purchase can't (undoing a purchase could mean removing an item "
            "that's since been resold, traded, or re-priced), and neither "
            "can a trade leg.\n"
            "- **Edit** says the sale happened, but you typed something "
            "wrong — the amount, the date, the payment method. Editing "
            "keeps the original transaction's date and grouping intact "
            "instead of voiding-and-redoing it.\n\n"
            "A voided row still shows in the archive (struck through, with "
            "its reason) — the archive shows what was actually written, not "
            "a cleaned-up version of it."
        ),
        related_routes=["/admin/history"],
    ),
    AdminDocArticle(
        id="cosigners-tab",
        category="data",
        title="Cosigners: consignor records and payouts",
        summary="Consignor CRUD, split percentages, and the payout-link tool.",
        keywords=["cosigners", "consignors", "payout", "split"],
        body=(
            "The Cosigners tab manages consignor records: contact info, "
            "their split percentage, and a payout-link tool. \"Delete\" "
            "here archives the consignor the same way Shows does — nothing "
            "is destroyed, and an archived consignor's name still shows "
            "correctly everywhere rather than being mislabeled as if the "
            "item itself sold.\n\n"
            "See \"Consignor split: whose percentage is whose\" in Money & "
            "Calculations before assuming a percentage means what it sounds "
            "like."
        ),
        related_routes=["/admin/cosigners"],
    ),
    AdminDocArticle(
        id="locations-tab",
        category="data",
        title="Locations: the one list that's actually deleted, not archived",
        summary=(
            "Locations hard-delete (blocked if still in use) instead of "
            "archiving — unlike everything else."
        ),
        keywords=["locations", "delete", "archive"],
        body=(
            "Every other archivable thing in the admin panel (Shows, "
            "Cosigners) uses \"archive, never really delete.\" Locations "
            "are the one exception: a location is just a label with no "
            "history of its own, so deleting one really deletes it — but "
            "you'll get an error if any item still uses that location, so "
            "you can't accidentally orphan inventory. Move everything out "
            "of a location first, then delete it."
        ),
        related_routes=["/admin/locations"],
    ),
    # ---- Money & Calculations ----
    AdminDocArticle(
        id="acquisition-ratio",
        category="money",
        title="The acquisition-ratio percentage: how it's calculated",
        summary="Market value at purchase divided by what you paid — shown on every deal row.",
        keywords=["acquisition ratio", "percentage", "trade", "margin"],
        body=(
            "The percentage shown on a deal row (e.g. \"Market $100.00 · "
            "Paid $32.00 · 312%\") is **market value at the time of "
            "purchase, divided by what was actually paid**. 312% means the "
            "card was bought for well under what the market said it was "
            "worth at the time.\n\n"
            "**≥200% is shown as good, 100–200% as neutral, under 100% as "
            "bad** (you paid over market). If either figure is missing, or "
            "the cost was $0 (a free card — a throw-in or a bulk-lot item is "
            "routine at a buy table), the ratio shows as an em dash, never a "
            "guessed number.\n\n"
            "In **Customer View**, this percentage and the price paid are "
            "both hidden — showing a customer what you paid, or the margin "
            "on it, is worse than just showing them the market price, which "
            "stays visible either way."
        ),
        related_routes=["/admin/trade"],
    ),
    AdminDocArticle(
        id="trade-balance-calculation",
        category="money",
        title="How a trade's balance is calculated",
        summary="The balance NETS cash against the card totals — it doesn't add them.",
        keywords=["trade", "balance", "cash", "net"],
        body=(
            "A trade's displayed balance is: what you're giving out in "
            "cards, minus what you're getting in cards, minus any cash "
            "changing hands (netted, not added). A trade where the cards "
            "and cash genuinely balance to zero shows $0 — if the number "
            "looks off after adding a cash amount, double check which "
            "direction the cash is flowing (are they paying you, or are you "
            "paying them) before assuming the trade itself is unbalanced."
        ),
        related_routes=["/admin/trade"],
    ),
    AdminDocArticle(
        id="trade-cost-basis-is-automatic",
        category="money",
        title="A trade's incoming cost basis is fully automatic",
        summary=(
            "There's no mode to pick and nothing to type — it's computed "
            "from the outgoing cards plus any cash."
        ),
        keywords=["trade", "cost basis", "automatic"],
        body=(
            "When cards come IN through a trade, their cost basis (what "
            "they count as \"costing\" the business, for profit tracking "
            "later) is worked out automatically: the cost of what went out, "
            "plus any cash you paid, minus any cash you received — split "
            "proportionally across however many cards came in. There is no "
            "manual entry for this and no mode to choose; the preview "
            "balance you see before confirming a trade uses the exact same "
            "calculation, so it will always match what actually gets "
            "recorded."
        ),
        related_routes=["/admin/trade"],
    ),
    AdminDocArticle(
        id="sticker-price-is-the-customer-price",
        category="money",
        title="Sticker price vs. market price — which one customers see",
        summary=(
            "The sticker price IS what a customer pays; the market price is "
            "just a reference figure."
        ),
        keywords=["sticker price", "market price", "customer price"],
        body=(
            "The **sticker price** is what the business actually sells a "
            "card for — you typed it by hand, holding the card and judging "
            "its condition. A card with no sticker price simply doesn't "
            "show to customers at all (that's exactly what Prep Queue is "
            "for: finding those cards and pricing them).\n\n"
            "The **market price** is a live catalog reference figure — "
            "useful for judging whether a sticker price is fair, but it is "
            "NOT what gets charged, and it is not condition-adjusted for "
            "the specific card in hand — a human already priced the actual "
            "card they were holding when they set the sticker."
        ),
    ),
    AdminDocArticle(
        id="consignor-split-direction",
        category="money",
        title="Consignor split: whose percentage is whose",
        summary=(
            "Two places show a split percentage, and they mean OPPOSITE "
            "things — read carefully."
        ),
        keywords=["consignor", "split", "payout", "percent"],
        body=(
            "This one is worth double-checking every time: on an individual "
            "**item**, the split percentage stored is the **business's own "
            "cut** (a 0–1 fraction, e.g. 0.5 means the business keeps 50%). "
            "On the **Cosigners tab's** default payout percentage, the "
            "number is the **consignor's** share instead (shown as a "
            "percent, e.g. 50 means the consignor gets 50%).\n\n"
            "Same idea, opposite direction, on two different screens. If a "
            "payout number looks backwards, check which of the two you're "
            "actually looking at before assuming it's wrong."
        ),
        related_routes=["/admin/cosigners", "/admin/trade"],
    ),
    AdminDocArticle(
        id="money-input-rules",
        category="money",
        title="Typing money amounts: commas are fine, don't fight the field",
        summary="Every money field accepts \"1,300\" — you never need to strip the comma yourself.",
        keywords=["money input", "comma", "typing"],
        body=(
            "Every price/cost field in the admin panel accepts a comma the "
            "way you'd naturally type a large number — `1,300` becomes "
            "`$1,300.00` automatically. You don't need to remove the comma "
            "yourself, and a genuinely free item (cost `0`) is accepted as "
            "an actual zero, not rejected as if nothing was typed."
        ),
    ),
    # ---- Costs, Quotas & Schedules ----
    AdminDocArticle(
        id="sync-prices-cost-and-cadence",
        category="costs",
        title="Sync Prices: what it costs and how often to press it",
        summary=(
            "Graded pricing runs on a metered daily quota — roughly 50 "
            "lookups a day, and it already runs overnight automatically."
        ),
        keywords=["sync prices", "cost", "quota", "cadence", "pokemonpricetracker"],
        body=(
            "The graded-card price provider gives a limited number of free "
            "lookups per day, and each graded price lookup uses a couple of "
            "those — in practice, that's roughly **50 graded-card price "
            "lookups per day**, total, shared across the whole business.\n\n"
            "This already runs **automatically overnight**, every day, as "
            "part of the scheduled sync — so pressing \"Sync Prices\" by "
            "hand during the day is for catching up sooner (e.g. right "
            "after a big buying day), not the only time it happens. Pressing "
            "it repeatedly in the same day doesn't get you more lookups — "
            "it just uses up the same shared daily allowance faster, "
            "potentially leaving nothing left for the automatic overnight "
            "run or for other slabs that still need a price.\n\n"
            "**Rule of thumb:** press it once after a show if you want fresh "
            "numbers sooner, and otherwise let the overnight job handle it."
        ),
        related_routes=["/admin/market", "/admin/slabs"],
    ),
    AdminDocArticle(
        id="check-for-new-sets-cadence",
        category="costs",
        title="\"Check for new sets\": a monthly action, not a daily one",
        summary=(
            "This walks the whole catalog for new releases — new sets come "
            "out at most monthly."
        ),
        keywords=["check for new sets", "catalog", "cadence"],
        body=(
            "\"Check for new sets\" looks for entirely new Pokémon set "
            "releases across the catalog. New sets are released at most "
            "once a month, so there's rarely a reason to press this more "
            "than monthly — it already runs automatically on that same "
            "schedule. Pressing it doesn't cost anything toward the pricing "
            "quota above (it's a different kind of catalog check), but it "
            "does take real time to walk the catalog, so there's no benefit "
            "to pressing it more than once a day even out of curiosity."
        ),
        related_routes=["/admin/market"],
    ),
    AdminDocArticle(
        id="psa-cert-lookup-not-available",
        category="costs",
        title="PSA cert lookup: not available, and not coming",
        summary=(
            "PSA's cert-lookup API is a paid feature the business declined "
            "— slab intake stays manual, on purpose."
        ),
        keywords=["psa", "cert lookup", "camera scan"],
        body=(
            "There is no automatic PSA cert lookup and no camera-scan "
            "feature for slabs — this was tried, PSA made the cert API a "
            "paid add-on, and the business chose not to subscribe. Slab "
            "intake is manual by design (type or scan the cert, identify "
            "the card yourself) — this isn't a missing feature waiting to "
            "be finished, it's the shipped design."
        ),
        related_routes=["/admin/slabs"],
    ),
    AdminDocArticle(
        id="catalog-seeding-is-rare",
        category="costs",
        title="Seeding the catalog for a new language: a rare, deliberate action",
        summary=(
            "Adding catalog coverage for a new card language is a one-off, "
            "per-language action — never \"seed everything.\""
        ),
        keywords=["catalog", "seed", "language", "korean", "chinese"],
        body=(
            "The catalog only carries full card data for English and "
            "Japanese by default. If the business starts holding real stock "
            "in another language (Korean, Chinese, etc.), that language's "
            "catalog gets seeded **on purpose, one language at a time, when "
            "there's actual stock in it** — it's a multi-hour, resource-"
            "heavy action, not something to run \"just in case\" or all at "
            "once for every language. Until a language is seeded, an item "
            "in it is entered manually and lives in the Unmatched queue — "
            "which is exactly what that queue is for."
        ),
    ),
    AdminDocArticle(
        id="scheduled-sync-already-runs",
        category="costs",
        title="The nightly and monthly sync jobs already run on their own",
        summary=(
            "Prices sync overnight; new-set checks run monthly — both "
            "automatically, with no button press needed."
        ),
        keywords=["scheduled sync", "automatic", "nightly", "cron"],
        body=(
            "Two jobs already run on a schedule, with nobody pressing a "
            "button: prices sync every night, and a new-set check runs "
            "once a month. The Sync Prices / Check for new sets buttons "
            "described elsewhere in this section exist for catching up "
            "sooner than the schedule would, not because nothing would "
            "happen otherwise."
        ),
    ),
    # ---- Asking the Analyst Chat ----
    AdminDocArticle(
        id="what-the-analyst-chat-can-do",
        category="chat",
        title="What the Analyst Chat can (and can't) do",
        summary=(
            "It can read business numbers and this documentation. It cannot "
            "click buttons or change anything."
        ),
        keywords=["analyst chat", "read only", "capabilities"],
        body=(
            "The Analyst Chat (open it from the chat icon in the header, on "
            "any admin tab) is read-only: it can answer questions about "
            "profit, aging stock, consignor positions, pricing, and it can "
            "read this exact documentation to answer \"how does X work\" or "
            "\"what does X cost\" questions. It **cannot** press a button, "
            "change a price, void a sale, or do anything else on your "
            "behalf — if you ask it to change something, it will tell you "
            "which tab does that instead of pretending to have done it.\n\n"
            "It also does **not** have access to the website's source code "
            "or any files — only the business's own data and this "
            "knowledge base. That's a deliberate safety boundary, not a "
            "current limitation waiting to be lifted."
        ),
    ),
    AdminDocArticle(
        id="good-questions-to-ask-the-chat",
        category="chat",
        title="Example questions worth asking the Analyst Chat",
        summary="Try questions the fixed reports don't already answer directly.",
        keywords=["analyst chat", "examples", "questions"],
        body=(
            "A few kinds of questions the chat is genuinely good at:\n\n"
            "- \"What's our most profitable show this year?\"\n"
            "- \"Which consignor has the most items sitting over 90 days?\"\n"
            "- \"How often should I run Sync Prices?\"\n"
            "- \"How is the trade balance calculated?\"\n"
            "- \"What's our profit margin for the last 30 days?\"\n\n"
            "It can make several lookups in a row on its own to answer a "
            "question that no single report covers directly — you don't "
            "need to phrase the question to match one specific button or "
            "tab."
        ),
    ),
    # ---- Glossary ----
    AdminDocArticle(
        id="condition-tiers-glossary",
        category="glossary",
        title="Condition tiers: NM, LP+, LP, LP-, MP, HP, DMG",
        summary=(
            "Condition ranks from best (NM) to worst (DMG), with LP split "
            "into three finer tiers."
        ),
        keywords=["condition", "nm", "lp", "mp", "hp", "dmg", "grading"],
        body=(
            "Condition ranks, best to worst: **NM** (Near Mint) > **LP+** > "
            "**LP** > **LP-** (Lightly Played, split into three finer "
            "steps) > **MP** (Moderately Played) > **HP** (Heavily Played) "
            "> **DMG** (Damaged). Sorting by condition uses this rank order, "
            "not alphabetical order — alphabetically, \"LP+\" and \"LP-\" "
            "would look identical, which defeats the entire point of having "
            "both."
        ),
    ),
    AdminDocArticle(
        id="finish-vs-finish-attributes-glossary",
        category="glossary",
        title="Finish vs. finish attributes",
        summary=(
            "Finish decides the price lookup; finish attributes describe "
            "extra things about the printing."
        ),
        keywords=["finish", "finish attributes", "holofoil", "1st edition"],
        body=(
            "**Finish** (e.g. Holofoil, Reverse Holofoil, Normal) is what "
            "the price lookup actually joins on — it decides which market "
            "price applies. **Finish attributes** (1st Edition, Shadowless, "
            "Full Art, Signed, and similar) describe something extra about "
            "the specific printing that finish alone doesn't capture, and "
            "they carry **no automatic price multiplier** — a 1st Edition "
            "Shadowless card is often worth far more than the finish price "
            "alone suggests, and that's exactly the kind of card that gets "
            "hand-priced rather than trusted to a formula."
        ),
    ),
    AdminDocArticle(
        id="archiving-pattern-glossary",
        category="glossary",
        title="\"Archive\" vs. \"delete\": what each one really does",
        summary=(
            "Most \"delete\" buttons in the admin panel actually archive — "
            "hidden, not destroyed, and always reversible."
        ),
        keywords=["archive", "delete", "reversible"],
        body=(
            "For Shows and Cosigners, \"Delete\" archives rather than "
            "destroys — the record is hidden from the normal list but "
            "nothing is removed, and there's always a \"Show archived\" "
            "toggle plus an unarchive option. Locations are the one "
            "exception: they hard-delete for real (and refuse to if still "
            "in use), because a location is just a label with no history "
            "attached to it. If you're ever unsure whether a \"Delete\" "
            "button really deletes, check this article's exception list "
            "first — it's short."
        ),
    ),
]
