"""RED for RFC 0026 — the admin docs knowledge-base content module.

Structural/totality tests only. Article PROSE is never asserted here — that
would make every content edit a test change — but every article must satisfy
the invariants the search/browse machinery in ``services/admin_docs.py``
relies on: a unique id, a real category, and non-empty required fields. Same
"totality against the real shape, not a re-typed copy" discipline
``test_slabs_sort.py`` and ``test_locations_sort.py`` already use for their
own registries.
"""

from __future__ import annotations

from merlins_collection.services.admin_docs_content import (
    ADMIN_DOC_CATEGORIES,
    ARTICLES,
)


def test_every_article_id_is_unique():
    ids = [a.id for a in ARTICLES]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate article ids: {dupes}"


def test_every_article_category_is_a_real_category():
    valid = {c[0] for c in ADMIN_DOC_CATEGORIES}
    bad = [(a.id, a.category) for a in ARTICLES if a.category not in valid]
    assert not bad, f"articles with an unknown category: {bad}"


def test_every_category_has_at_least_one_article():
    """A tab that renders with zero articles under it is a broken category,
    not an empty one — the whole point of sectioning content is that every
    section has something in it."""
    used = {a.category for a in ARTICLES}
    all_ids = {c[0] for c in ADMIN_DOC_CATEGORIES}
    missing = all_ids - used
    assert not missing, f"categories with zero articles: {sorted(missing)}"


def test_every_article_has_non_empty_required_fields():
    for a in ARTICLES:
        assert a.title.strip(), f"{a.id} has a blank title"
        assert a.summary.strip(), f"{a.id} has a blank summary"
        assert a.body.strip(), f"{a.id} has a blank body"


def test_every_article_id_is_a_lowercase_kebab_slug():
    """A slug is what a URL/deep-link and a search-index key both need — a
    space or an uppercase letter here is a bug waiting for a future
    `/admin/docs/{id}` or anchor link, even though v1 doesn't build one yet."""
    import re

    pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    bad = [a.id for a in ARTICLES if not pattern.match(a.id)]
    assert not bad, f"article ids that are not lowercase-kebab slugs: {bad}"


def test_there_are_enough_articles_to_be_useful():
    # A knowledge base with one stub per category is not what was asked for
    # ("the worst thing to do is not go deep enough").
    assert len(ARTICLES) >= 20, (
        f"only {len(ARTICLES)} articles — that's a placeholder, not a "
        "knowledge base"
    )
