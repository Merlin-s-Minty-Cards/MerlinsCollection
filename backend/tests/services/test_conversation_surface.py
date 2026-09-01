"""RED for RFC 0018 item 1 — the `surface` tag, its TTL branch, and scoping.

Unit-level rather than at the HTTP boundary, because none of this is reachable
over HTTP yet: `POST /admin/chat/` does not exist. What IS under test is the
storage contract every later item depends on — a thread belongs to exactly one
surface, admin threads are kept for two years rather than six months, and every
reader that touches a surface is scoped, INCLUDING the one that deletes rows.

Authority: docs/rfcs/0018-admin-analyst-chat.md, Open Question 3 and the risk
table's "`surface` filter forgotten in one reader" row.
"""

from datetime import datetime, timezone

import pytest

from merlins_collection.models.chat import ADMIN_SURFACE, CUSTOMER_SURFACE
from merlins_collection.services import conversations as convo

# ---- the surface tag itself ----

def test_a_row_written_before_this_field_existed_reads_as_customer():
    """Nothing is backfilled, so the default is a FACT, not a guess.

    Every conversation row written before RFC 0018 is a customer thread —
    `/admin/chat/` did not exist to write any other kind. Same precedent as
    `Transaction.batch_id`: optional, defaulted, no migration, one code path.
    """
    assert convo.surface_of({"conv_id": "01J", "title": "old"}) == CUSTOMER_SURFACE


def test_an_explicit_surface_is_respected():
    assert convo.surface_of({"surface": ADMIN_SURFACE}) == ADMIN_SURFACE
    assert convo.surface_of({"surface": CUSTOMER_SURFACE}) == CUSTOMER_SURFACE


def test_start_conversation_stamps_the_surface_it_was_started_on(dynamo_repo):
    row = convo.start_conversation(dynamo_repo, "sub-1", "hi", surface=ADMIN_SURFACE)
    assert row["surface"] == ADMIN_SURFACE
    assert convo.start_conversation(dynamo_repo, "sub-1", "hi")["surface"] == CUSTOMER_SURFACE


# ---- Open Question 3: two years for admin, six months for customer ----

def test_an_admin_row_and_a_customer_row_written_in_the_same_second_get_different_ttls(
    dynamo_repo,
):
    """The branch must not silently collapse to one clock.

    This is the test RFC 0018 Open Question 3 asks for by name. Both rows are
    written from the SAME timestamp, so any difference in the stored ttl can
    only come from the surface branch — not from write-time drift.
    """
    stamp = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    def write(conv_id: str, surface: str) -> int:
        dynamo_repo.put_conversation({
            "conv_id": conv_id, "sub": "sub-ttl", "title": "t",
            "created_at": stamp, "updated_at": stamp,
            "message_count": 0, "last_seq": 0, "panel_item_ids": [],
            "surface": surface,
        })
        row = next(r for r in dynamo_repo.list_conversations("sub-ttl")
                   if r["conv_id"] == conv_id)
        return int(row["ttl"])

    customer_ttl = write("conv-customer", CUSTOMER_SURFACE)
    admin_ttl = write("conv-admin", ADMIN_SURFACE)

    assert admin_ttl > customer_ttl, (
        "an admin thread must outlive a customer one written at the same instant"
    )
    # 730 days vs 183 — allow a day of slack rather than pinning exact seconds.
    assert (admin_ttl - customer_ttl) == pytest.approx((730 - 183) * 86400, abs=86400)


def test_a_message_row_inherits_its_thread_s_retention(dynamo_repo):
    """A two-year thread whose messages expire in six months is an empty thread."""
    stamp = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    dynamo_repo.put_conversation_message(
        "conv-admin", "sub-ttl",
        {"seq": 1, "role": "user", "content": "x", "artifact_item_ids": [],
         "created_at": stamp},
        surface=ADMIN_SURFACE,
    )
    dynamo_repo.put_conversation_message(
        "conv-cust", "sub-ttl",
        {"seq": 1, "role": "user", "content": "x", "artifact_item_ids": [],
         "created_at": stamp},
        surface=CUSTOMER_SURFACE,
    )
    admin_msg = dynamo_repo.get_conversation_messages("conv-admin")[0]
    cust_msg = dynamo_repo.get_conversation_messages("conv-cust")[0]
    assert int(admin_msg["ttl"]) > int(cust_msg["ttl"])


# ---- the scoping helper: list, count AND prune ----

def _seed(repo, sub, n, surface, *, prefix="c"):
    for i in range(n):
        stamp = f"2026-08-{(i % 27) + 1:02d}T00:00:00+00:00"
        repo.put_conversation({
            "conv_id": f"{prefix}-{i:03d}", "sub": sub, "title": f"t{i}",
            "created_at": stamp, "updated_at": stamp,
            "message_count": 0, "last_seq": 0, "panel_item_ids": [],
            "surface": surface,
        })


def test_the_history_list_shows_only_its_own_surface(dynamo_repo):
    _seed(dynamo_repo, "sub-2", 3, CUSTOMER_SURFACE, prefix="cust")
    _seed(dynamo_repo, "sub-2", 2, ADMIN_SURFACE, prefix="adm")

    customer = convo.list_summaries(dynamo_repo, "sub-2", CUSTOMER_SURFACE)
    admin = convo.list_summaries(dynamo_repo, "sub-2", ADMIN_SURFACE)

    assert len(customer) == 3
    assert len(admin) == 2
    assert {s.conversation_id for s in customer}.isdisjoint(
        {s.conversation_id for s in admin}
    )


def test_pruning_never_deletes_an_admin_thread_to_make_room_for_customer_ones(
    dynamo_repo,
):
    """THE DATA-LOSS TEST. Open Question 3 promises admin threads live two years.

    `prune_to_cap` read EVERY row for the sub with no surface filter and deleted
    everything past the 50th most-recent. The owner is an admin who also uses
    the customer chat, so a quarterly margin analysis written in July —
    deliberately not touched since — is exactly the least-recently-used thread
    that the 51st customer conversation would have evicted in October.

    TTL is not the only deletion mechanism, and the RFC only addressed TTL.
    """
    _seed(dynamo_repo, "sub-3", 1, ADMIN_SURFACE, prefix="adm")
    # Every customer thread is more recent than the admin one.
    for i in range(convo.MAX_CONVERSATIONS + 5):
        dynamo_repo.put_conversation({
            "conv_id": f"cust-{i:03d}", "sub": "sub-3", "title": f"t{i}",
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
            "message_count": 0, "last_seq": 0, "panel_item_ids": [],
            "surface": CUSTOMER_SURFACE,
        })

    convo.prune_to_cap(dynamo_repo, "sub-3", CUSTOMER_SURFACE)

    survivors = convo.list_summaries(dynamo_repo, "sub-3", ADMIN_SURFACE)
    assert len(survivors) == 1, "the admin thread was evicted by customer traffic"


def test_the_cap_is_per_surface_not_shared(dynamo_repo):
    """50 customer threads must not make the next admin thread the 51st."""
    _seed(dynamo_repo, "sub-4", convo.MAX_CONVERSATIONS, CUSTOMER_SURFACE, prefix="cust")
    _seed(dynamo_repo, "sub-4", 3, ADMIN_SURFACE, prefix="adm")

    convo.prune_to_cap(dynamo_repo, "sub-4", ADMIN_SURFACE)

    assert len(convo.list_summaries(dynamo_repo, "sub-4", ADMIN_SURFACE)) == 3
    assert len(convo.list_summaries(dynamo_repo, "sub-4", CUSTOMER_SURFACE)) == (
        convo.MAX_CONVERSATIONS
    )


def test_clear_all_clears_only_the_surface_it_was_asked_for(dynamo_repo):
    """Clearing customer history must not silently destroy a year of analysis."""
    _seed(dynamo_repo, "sub-5", 3, CUSTOMER_SURFACE, prefix="cust")
    _seed(dynamo_repo, "sub-5", 2, ADMIN_SURFACE, prefix="adm")

    convo.clear_all(dynamo_repo, "sub-5", CUSTOMER_SURFACE)

    assert convo.list_summaries(dynamo_repo, "sub-5", CUSTOMER_SURFACE) == []
    assert len(convo.list_summaries(dynamo_repo, "sub-5", ADMIN_SURFACE)) == 2


def test_a_thread_cannot_be_fetched_from_the_wrong_surface(dynamo_repo):
    """An admin id handed to the customer surface is not found, and vice versa.

    Without this, `POST /admin/chat/` would accept a customer `conversation_id`
    and append cost basis and margins to a thread that
    `GET /chat/conversations/{id}` renders on the CUSTOMER surface.
    """
    _seed(dynamo_repo, "sub-6", 1, ADMIN_SURFACE, prefix="adm")

    assert convo.get_owned(dynamo_repo, "sub-6", "adm-000", ADMIN_SURFACE) is not None
    assert convo.get_owned(dynamo_repo, "sub-6", "adm-000", CUSTOMER_SURFACE) is None


# ---- the choices that are easy to make by accident ----

def test_surface_is_required_on_a_message_write_and_on_a_bulk_delete():
    """Both are silent-failure shapes if defaulted, so both are mandatory.

    A defaulted `surface` on `put_conversation_message` stamps an admin
    thread's messages with the six-month customer clock — a two-year thread
    with an empty transcript. A defaulted `surface` on
    `delete_all_conversations` is an unscoped bulk delete, which is the exact
    bug this change removes from `prune_to_cap`. Making them required turns a
    remembered rule into a mechanical one: an incomplete call cannot be
    written, the way a missing required argument cannot.
    """
    import inspect

    from merlins_collection.services.dynamodb import InventoryRepository

    msg = inspect.signature(InventoryRepository.put_conversation_message)
    assert msg.parameters["surface"].default is inspect.Parameter.empty

    bulk = inspect.signature(InventoryRepository.delete_all_conversations)
    assert bulk.parameters["surface"].default is inspect.Parameter.empty


def test_an_unrecognised_surface_belongs_to_neither_list(dynamo_repo):
    """Pinned deliberately: a bogus value is invisible rather than defaulting.

    Nothing writes one today — the value only ever comes from the two module
    constants — but the behaviour should be a choice on the record rather than
    an accident. Falling back to "customer" would surface an admin-titled
    thread in a customer's history list; being invisible to both is fail-closed
    for confidentiality, and the row still reaps itself on its own TTL rather
    than living forever.
    """
    _seed(dynamo_repo, "sub-7", 1, "not-a-real-surface", prefix="odd")

    assert convo.list_summaries(dynamo_repo, "sub-7", CUSTOMER_SURFACE) == []
    assert convo.list_summaries(dynamo_repo, "sub-7", ADMIN_SURFACE) == []
    # ...but it is still a stored row, not a phantom.
    assert len(dynamo_repo.list_conversations("sub-7")) == 1
