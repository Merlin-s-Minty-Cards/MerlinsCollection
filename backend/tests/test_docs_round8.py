"""DOCUMENTATION GUARDS for RFC 0010 Round 8 (T14).

These are not tests of behaviour. They are tripwires on the two documents that
steer future work — ``CLAUDE.md``, which is loaded into every agent session, and
``backend/.env.example``, which is the operator's map of what is configurable.

The rule that makes them worth having: **a guard asserts a doc claim against the
CODE that makes it true**, never against another sentence. So the sidebar guard
reads the routes out of ``AdminShell.tsx``, the countability guard imports
``services.ledger``, and the ``.env.example`` guard reflects over ``Settings``.
A guard that only matched prose would go green on prose and prove nothing.

The three that ARE plain string checks (the stale-claim tripwires) name the
exact sentence that became false in Round 8, so they fail loudly if anyone
restores it — a stale instruction in CLAUDE.md does not merely mislead, it
directs work at scope the owner cancelled.

Precedent: ``test_config.py``'s credit-arithmetic guards, added by RFC 0009 T8
for the same reason.

RED gate, run 2026-08-12 before any doc was edited: **18 failed, 6 passed.** The
six that passed are labelled ``REGRESSION GUARD`` below — each pins something an
earlier Round 8 task already got right, so it is kept as a guard rather than
dressed up as new work. A seventh passed *for the wrong reason* and was hardened
before the doc was touched: ``test_claude_md_lists_every_route_the_sidebar_can_reach``
originally searched the whole file, and ``/admin/locations`` — genuinely missing
from the route table — matched an unrelated mention of the *API* endpoint 330
lines below it. Scoped to the table, it failed. Both rewritten guards were
re-proven RED against ``git show HEAD:CLAUDE.md`` rather than assumed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
ENV_EXAMPLE = REPO_ROOT / "backend" / ".env.example"
ADMIN_SHELL = REPO_ROOT / "frontend" / "components" / "admin" / "AdminShell.tsx"
CERT_INPUT = (
    REPO_ROOT / "frontend" / "components" / "admin" / "slabs" / "CertInput.tsx"
)


@pytest.fixture(scope="module")
def claude_md() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


# --- backend/.env.example ---------------------------------------------------


# Assigned in `.env.example` but deliberately NOT a `Settings` field. Anything
# added here needs a reader named in the comment beside it, or it is exactly the
# inert-config trap this guard exists to catch.
NOT_A_SETTINGS_FIELD = {
    # Read by uvicorn's --proxy-headers, from the Dockerfile CMD. Never by us.
    "FORWARDED_ALLOW_IPS",
}


def test_env_example_advertises_no_setting_that_nothing_reads():
    """Every assignable var in `.env.example` must actually be read.

    `Settings.model_config` uses `extra="ignore"`, so an env var with no
    matching field is silently inert: an operator wires it into ECS secrets,
    sees no error, and believes a feature is configured. `PSA_API_KEY` was
    exactly that for the whole of RFC 0009, and RFC 0010 §H made the gap
    permanent — so the placeholder had to go.
    """
    from merlins_collection.config import Settings

    fields = set(Settings.model_fields)
    assigned = set(
        re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(encoding="utf-8"), re.M)
    )
    inert = {
        name
        for name in assigned - NOT_A_SETTINGS_FIELD
        if name.lower() not in fields
    }
    assert not inert, (
        f".env.example advertises settings nothing reads: {sorted(inert)}. "
        "Either add the Settings field or remove the line — a blank placeholder "
        "reads as 'configure me' and cannot work."
    )


def test_env_example_still_explains_why_there_is_no_psa_key():
    """Removing the line must not delete the DECISION.

    The owner's own `backend/.env` still carries a real `PSA_API_KEY`, so a
    reader who finds it there and not here needs to land on a decision rather
    than a silence.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "PSA" in text, "the PSA withdrawal must stay documented in .env.example"
    assert not re.search(r"^PSA_API_KEY=", text, re.M), (
        "PSA_API_KEY must be prose, never an assignable line"
    )


# --- CLAUDE.md: the admin sidebar (T13) -------------------------------------


def _sidebar_routes() -> set[str]:
    """Every destination in the real sidebar, read out of the component."""
    return set(re.findall(r"href: '(/admin[^']*)'", ADMIN_SHELL.read_text(encoding="utf-8")))


def _sidebar_groups() -> set[str]:
    source = ADMIN_SHELL.read_text(encoding="utf-8")
    groups = source[source.index("const navGroups") : source.index("const mobileItems")]
    return set(re.findall(r"label: '([^']+)',\n\s*items:", groups))


def _admin_panel_table(claude_md: str) -> str:
    """Just the Admin Panel route table.

    Scoped deliberately: a bare `in claude_md` passes on any mention anywhere,
    and `/admin/locations` is mentioned in the Locations API section 330 lines
    below the table it is missing from. That weaker form passed against the
    unfixed doc — the exact green-on-broken-code the RED gate exists to catch.
    """
    start = claude_md.index("# Admin Panel")
    return claude_md[start : claude_md.index("**Prep Queue gotcha:**", start)]


def test_claude_md_lists_every_route_the_sidebar_can_reach(claude_md):
    """The Admin Panel table is the map. A destination missing from it is a page
    the next agent does not know exists."""
    table = _admin_panel_table(claude_md)
    missing = sorted(r for r in _sidebar_routes() if r not in table)
    assert not missing, (
        f"admin routes in the sidebar but not in CLAUDE.md's route table: {missing}"
    )


def test_claude_md_describes_the_sidebar_as_three_groups(claude_md):
    """T13 replaced sixteen flat tabs with three groups. A table that still
    presents a flat list describes navigation that no longer exists."""
    missing = sorted(g for g in _sidebar_groups() if g not in claude_md)
    assert _sidebar_groups(), "AdminShell parse failed — fix the guard, not the doc"
    assert not missing, f"sidebar groups not documented in CLAUDE.md: {missing}"


def test_claude_md_still_says_no_route_path_changed(claude_md):
    """REGRESSION GUARD — passed before T14.

    `/admin/outgoing` keeps its misleading path (T13 decision). The gotcha
    must survive the regrouping, because grouping is the change most likely to
    make a reader assume the URLs moved too."""
    assert "/admin/outgoing" in claude_md
    assert "Prep Queue" in claude_md


# --- CLAUDE.md: PSA is withdrawn, not pending (T12) -------------------------


# The exact claims that became false on 2026-08-10. Each was true when written.
STALE_PSA_CLAIMS = [
    "When approval lands",
    "The intake toolbar has four buttons",
    '"Scan cert" is **real**',
    "aria-describedby` naming PSA approval",
    "The remedy is an approval email",
    "is deferred whole rather than",
]


@pytest.mark.parametrize("claim", STALE_PSA_CLAIMS)
def test_claude_md_no_longer_makes_this_stale_psa_claim(claude_md, claim):
    assert claim not in claude_md, (
        f"CLAUDE.md still claims {claim!r}. PSA's cert API became a PAID feature "
        "and the owner declined it (RFC 0010 §H); the buttons were deleted by T12."
    )


def test_claude_md_records_the_psa_withdrawal_as_permanent(claude_md):
    assert "WITHDRAWN" in claude_md or "withdrawn" in claude_md
    assert "paid" in claude_md.lower()


def test_the_slab_page_really_has_no_scanner_or_psa_buttons():
    """REGRESSION GUARD — passed before T14, because T12 already deleted them.

    The doc claim above is only honest while the code matches it.
    """
    page = (
        REPO_ROOT / "frontend" / "app" / "(admin)" / "admin" / "slabs" / "page.tsx"
    ).read_text(encoding="utf-8")
    for gone in ("Camera scan", "Auto-fill from cert", "#psa-blocked"):
        assert gone not in page, f"{gone!r} is back on /admin/slabs — the docs say it is gone"


# --- CLAUDE.md: what makes wedge scanning work (T12) ------------------------


def test_claude_md_names_the_cert_input_handling_that_must_not_be_removed(claude_md):
    """Removing the scan button is safe ONLY while `CertInput` advances on Enter
    and strips the scanner's trailing newline. That is now the whole mechanism,
    so it has to be documented loudly rather than left in a component."""
    assert "CertInput" in claude_md, "CLAUDE.md must name the component by file"
    assert "Enter" in claude_md
    assert re.search(r"\\r\\n|\\\\r|trailing newline", claude_md), (
        "CLAUDE.md must say the trailing \\r\\n is stripped"
    )


def test_cert_input_still_advances_on_enter_and_strips_the_scanner_newline():
    """REGRESSION GUARD — passed before T14, and the most load-bearing one here.

    The code half of the claim above, checked rather than assumed. Removing the
    scan button is safe ONLY while both of these survive.
    """
    source = CERT_INPUT.read_text(encoding="utf-8")
    assert "onEnter" in source, "Enter no longer advances — wedge scanning is broken"
    # The literal call, not a loose `\r` match: the explanatory COMMENT above it
    # also contains `\r`, so the loose form stays green after the strip is deleted.
    assert re.search(r"replace\(/\[\\r\\n\]/g", source), (
        "CertInput no longer strips the scanner's trailing \\r\\n — wedge scanning "
        "is broken while hand-typing still works, and CLAUDE.md now lies"
    )


# --- CLAUDE.md: the ledger can be corrected (T10/T11) -----------------------


def test_claude_md_documents_the_one_countability_predicate(claude_md):
    """The single most important rule Round 8 added. An aggregate that inlines
    its own voided check is a second set of books."""
    from merlins_collection.services import ledger

    assert callable(ledger.is_countable), "the predicate the doc points at must exist"
    assert "is_countable" in claude_md, (
        "CLAUDE.md must name services/ledger.is_countable as the ONE predicate"
    )
    assert "ledger" in claude_md


def test_claude_md_documents_that_the_archive_deliberately_does_not_filter(claude_md):
    """`GET /admin/transactions` is the one reader that shows voided rows. Left
    undocumented, the next reader 'fixes' it and the archive stops being one."""
    assert "/admin/transactions" in claude_md
    assert re.search(r"archive|does not filter|not filter", claude_md)


def test_claude_md_documents_that_only_a_sale_can_be_voided(claude_md):
    """Sales only; a purchase is a 400 and a trade cannot be voided at all."""
    assert "void" in claude_md.lower(), "CLAUDE.md says nothing about voiding"
    assert "SALES ONLY" in claude_md, "the scope of the void must be stated in caps"
    assert re.search(r"purchase[^.]{0,80}400", claude_md), (
        "CLAUDE.md must say a purchase void is refused with a 400"
    )
    assert re.search(r"trade cannot be voided", claude_md), (
        "a trade cannot be voided at all — its legs include a purchase"
    )


def test_the_void_route_really_refuses_a_purchase():
    """REGRESSION GUARD — passed before T14, because T11 built it.

    The code half — checked, because "sales only" is a money rule.
    """
    source = (
        REPO_ROOT
        / "backend"
        / "src"
        / "merlins_collection"
        / "routers"
        / "admin"
        / "analytics.py"
    ).read_text(encoding="utf-8")
    assert "status_code=400" in source and "cannot be voided" in source


def test_claude_md_documents_the_batch_id_grouping(claude_md):
    """T10's field, and the no-backfill decision that goes with it."""
    from merlins_collection.models.business import Transaction

    assert "batch_id" in Transaction.model_fields
    assert "batch_id" in claude_md


# --- CLAUDE.md: the "Never" lines Round 8 earned ----------------------------


def test_claude_md_bans_parsefloat_on_money(claude_md):
    """`parseFloat("1,300")` is 1, and it is not NaN, so it passes every isNaN
    guard in the codebase. A silent $1,299 loss."""
    assert (REPO_ROOT / "frontend" / "lib" / "money.ts").exists()
    assert "parseFloat" in claude_md, "the trap must be named to be avoided"
    assert "parseMoney" in claude_md, "the replacement must be named too"


def test_claude_md_bans_new_date_on_a_date_only_string(claude_md):
    """It parses as UTC midnight and renders a day early in every US timezone."""
    assert (REPO_ROOT / "frontend" / "lib" / "dates.ts").exists()
    assert "dates.ts" in claude_md
    assert re.search(r"UTC midnight", claude_md), (
        "CLAUDE.md must state WHY new Date('2026-08-10') is wrong"
    )


def test_claude_md_documents_the_consignor_sweep(claude_md):
    """REGRESSION GUARD — passed before T14; T2 documented it. Do not lose it.

    `put_consignor` sweeps superseded rows exactly like `put_show`.
    """
    assert "put_consignor" in claude_md


def test_claude_md_documents_the_single_triage_reason_param(claude_md):
    """REGRESSION GUARD — passed before T14; T3 documented it. Do not lose it.

    T3 made the server the authority and collapsed three params into one.
    """
    assert "triage_reason" in claude_md
    assert "reasons_for" in claude_md
