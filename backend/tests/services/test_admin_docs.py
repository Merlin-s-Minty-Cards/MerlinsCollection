"""RED for RFC 0026 — ``services/admin_docs.py``, the search/browse layer
behind both ``GET /admin/docs`` and the ``search_admin_docs`` MCP tool.

Two guardrails mirror bugs this repo has already shipped once and caught
during the pre-implementation adversarial review, so they get named tests
rather than being left to incidental coverage:

- a negative ``limit`` must be REJECTED, not silently mis-sliced — the exact
  ``list_transactions`` bug RFC 0020 item 3 fixed (Python's ``[:-1]`` reads
  as "all but the last row", a plausible-looking wrong answer);
- an unknown ``category`` must RAISE, not silently return ``[]`` — mirrors
  ``find_pricing_outliers``'s "unknown direction raises" precedent, so a
  typo'd category reads as a caller error, not "nothing exists on this
  topic."
"""

from __future__ import annotations

import pytest

from merlins_collection.services import admin_docs


def test_list_categories_returns_every_declared_category_in_order():
    from merlins_collection.services.admin_docs_content import ADMIN_DOC_CATEGORIES

    result = admin_docs.list_categories()
    assert [c["id"] for c in result] == [c[0] for c in ADMIN_DOC_CATEGORIES]
    assert all("label" in c for c in result)


def test_list_all_returns_full_articles_including_body():
    from merlins_collection.services.admin_docs_content import ARTICLES

    result = admin_docs.list_all()
    assert len(result) == len(ARTICLES)
    assert all("body" in row and row["body"] for row in result)


class TestSearchBrowseMode:
    """``query`` omitted (or empty) -> a lightweight index, no body."""

    def test_no_query_returns_an_index_with_no_body_field(self):
        result = admin_docs.search()
        assert result  # the seeded content is non-empty
        assert all("body" not in row for row in result)
        assert all({"id", "category", "title", "summary"} <= set(row) for row in result)

    def test_empty_string_query_behaves_the_same_as_omitted(self):
        """The frontend's cleared search box sends "", not null — both must
        mean "browse everything", not "search for the empty string"."""
        assert admin_docs.search(query="") == admin_docs.search(query=None)

    def test_whitespace_only_query_behaves_the_same_as_omitted(self):
        """A bare "not query" check treats "   " as a non-empty needle, and
        since nearly every article's body contains a space, that silently
        returns almost everything instead of browse mode (adversarial
        review, post-implementation)."""
        assert admin_docs.search(query="   ") == admin_docs.search(query=None)

    def test_empty_string_category_behaves_the_same_as_omitted(self):
        assert admin_docs.search(category="") == admin_docs.search(category=None)

    def test_category_narrows_the_browse_index(self):
        from merlins_collection.services.admin_docs_content import ARTICLES

        result = admin_docs.search(category="money")
        expected_ids = {a.id for a in ARTICLES if a.category == "money"}
        assert {row["id"] for row in result} == expected_ids
        assert expected_ids  # the category is populated, not accidentally empty

    def test_unknown_category_raises_rather_than_returning_empty(self):
        with pytest.raises(ValueError, match="unknown category"):
            admin_docs.search(category="not-a-real-category")


class TestSearchQueryMode:
    def test_query_matches_case_insensitively_against_title(self):
        from merlins_collection.services.admin_docs_content import ARTICLES

        target = ARTICLES[0]
        result = admin_docs.search(query=target.title.upper())
        assert any(row["id"] == target.id for row in result)

    def test_query_matches_against_body_text_not_just_title(self):
        """A real question ("what does sync prices cost") is answered by body
        prose, not necessarily by a title match."""
        from merlins_collection.services.admin_docs_content import ARTICLES

        # Find a word that appears in some article's body but not its title.
        target = next(
            a for a in ARTICLES
            if a.body.split() and a.body.split()[0].lower() not in a.title.lower()
        )
        needle = target.body.split()[0]
        result = admin_docs.search(query=needle)
        assert any(row["id"] == target.id for row in result)

    def test_nonexistent_query_returns_empty_not_an_error(self):
        assert admin_docs.search(query="xyzzy-nonexistent-plugh-query") == []

    def test_query_result_rows_include_full_body(self):
        from merlins_collection.services.admin_docs_content import ARTICLES

        target = ARTICLES[0]
        [row] = [r for r in admin_docs.search(query=target.title) if r["id"] == target.id]
        assert row["body"] == target.body

    def test_limit_caps_the_number_of_query_results(self):
        # A near-universal substring ("the") should match many articles;
        # limit must actually cap the returned count.
        result = admin_docs.search(query="the", limit=2)
        assert len(result) <= 2

    def test_negative_limit_is_rejected_rather_than_misslicing(self):
        with pytest.raises(ValueError, match="limit must be >= 0"):
            admin_docs.search(query="the", limit=-1)

    def test_category_and_query_combine_with_and(self):
        from merlins_collection.services.admin_docs_content import ARTICLES

        target = next(a for a in ARTICLES if a.category == "money")
        # Searching for this money-category article's own title, scoped to a
        # DIFFERENT category, must not find it.
        other_category = next(
            c for c in {a.category for a in ARTICLES} if c != target.category
        )
        assert admin_docs.search(query=target.title, category=other_category) == []
        assert any(
            row["id"] == target.id
            for row in admin_docs.search(query=target.title, category=target.category)
        )
