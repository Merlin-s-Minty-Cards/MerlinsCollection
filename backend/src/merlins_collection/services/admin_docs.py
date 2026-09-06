"""Search/browse layer over the admin docs knowledge base (RFC 0026).

Backs BOTH `GET /admin/docs` (`routers/admin/docs.py`) and the
`search_admin_docs` MCP tool (`mcp_admin/server.py`) — one function, two
thin callers, so the two surfaces cannot drift the way two independent
implementations of the same filter could. No repo/DynamoDB dependency at
all: this module only ever reads `admin_docs_content.ARTICLES`, which is
what makes it trivially importable from the standalone admin MCP
subprocess, same as `admin_analytics.py`'s lazy-import discipline achieves
for the DynamoDB-backed tools.
"""

from __future__ import annotations

from merlins_collection.services.admin_docs_content import (
    ADMIN_DOC_CATEGORIES,
    ARTICLES,
    AdminDocArticle,
)

_VALID_CATEGORIES = {cat_id for cat_id, _label in ADMIN_DOC_CATEGORIES}


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def list_categories() -> list[dict]:
    return [{"id": cat_id, "label": label} for cat_id, label in ADMIN_DOC_CATEGORIES]


def list_all() -> list[dict]:
    """Every article, full body included.

    The knowledge base is small (a few dozen short articles) — this is the
    same "just return the whole thing" reasoning `/admin/locations` and
    `/admin/cosigners` already use, not a decision specific to this feature.
    """
    return [a.model_dump(mode="json") for a in ARTICLES]


def _index_row(article: AdminDocArticle) -> dict:
    """id/category/title/summary only — no body, no keywords, no routes.

    This is what makes browse mode cheap: the model (or the frontend) can
    see what exists before committing to reading a full article.
    """
    return {
        "id": article.id,
        "category": article.category,
        "title": article.title,
        "summary": article.summary,
    }


def search(
    query: str | None = None,
    category: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Browse or search the admin docs knowledge base.

    Omitting ``query`` — or passing ``""``, which is what the frontend's
    cleared search box sends, not ``None`` — returns a lightweight INDEX of
    every matching article (no ``body``): a browse mode, not a search with
    an empty needle. A non-empty ``query`` returns full article dicts
    (``body`` included) for a case-insensitive substring match against
    title/summary/keywords/body, capped at ``limit``.

    ``limit`` rejects negative values outright rather than silently
    mis-slicing — Python's ``rows[:-1]`` reads as "all but the last row" for
    a negative stop, the exact bug RFC 0020 item 3 found and fixed in
    ``list_transactions``; repeating that mistake here would produce the
    same plausible-looking wrong answer for a nonsensical input.

    ``category``, when given, must be a real category id and otherwise
    RAISES — mirroring ``find_pricing_outliers``'s "unknown direction
    raises" precedent, so a typo'd category reads as a caller error rather
    than a silent empty result that looks like "nothing exists on this
    topic."
    """
    if limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")

    # Normalize "" (and whitespace-only) the same as omitted for BOTH params
    # — a caller (the frontend's cleared search box, or a model passing an
    # unset optional argument as an empty string rather than leaving it out)
    # can send "" instead of None, and the two must mean the same thing.
    query = _blank_to_none(query)
    category = _blank_to_none(category)

    if category is not None and category not in _VALID_CATEGORIES:
        raise ValueError(
            f"unknown category {category!r}; expected one of "
            f"{sorted(_VALID_CATEGORIES)}"
        )

    articles = ARTICLES
    if category is not None:
        articles = [a for a in articles if a.category == category]

    if not query:
        return [_index_row(a) for a in articles]

    needle = query.lower()

    def _matches(article: AdminDocArticle) -> bool:
        haystack = " ".join(
            [article.title, article.summary, " ".join(article.keywords), article.body]
        ).lower()
        return needle in haystack

    matched = [a for a in articles if _matches(a)]
    return [a.model_dump(mode="json") for a in matched[:limit]]
