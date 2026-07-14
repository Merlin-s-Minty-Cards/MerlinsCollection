"""On-demand catalog seed: pull the full pokemontcg.io catalog into DynamoDB.

Wraps ``catalog_sync.run_daily_sync`` (the same function the scheduled daily
sync will call once it's wired up) using the app's own settings, so this
writes to whatever table/region/API key ``backend/.env`` points at. Run from
``backend/`` with the project venv active:

    python scripts/seed_catalog.py
"""

from __future__ import annotations

import time
from datetime import date

import httpx

from merlins_collection.config import settings
from merlins_collection.services.catalog_sync import run_daily_sync
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.pokemontcg import PokemonTcgClient, PokemonTcgError

MAX_ATTEMPTS = 25
# Pacing didn't make the failures monotonic (page 2, 42, 2, 6, 53 across
# attempts) — this looks like genuine intermittent instability on
# pokemontcg.io's end right now rather than a pure client-side rate limit.
# The best attempt got 54/82 pages in, so patient retrying is the practical
# fix: keep the pacing (good practice regardless) and just retry generously.
PAGE_DELAY_SECONDS = 2.2


def _log_page(response: httpx.Response) -> None:
    if response.request.url.path.endswith("/cards"):
        page = response.request.url.params.get("page")
        print(f"  fetched page {page} ({response.status_code})")
        if response.status_code == 200:
            time.sleep(PAGE_DELAY_SECONDS)


def _new_client() -> PokemonTcgClient:
    http_client = httpx.Client(
        base_url=PokemonTcgClient.BASE_URL,
        headers={"X-Api-Key": settings.pokemontcg_api_key} if settings.pokemontcg_api_key else {},
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        event_hooks={"response": [_log_page]},
    )
    return PokemonTcgClient(
        api_key=settings.pokemontcg_api_key,
        client=http_client,
        page_size=250,
        max_retries=5,
        backoff_base=1.0,
    )


def main() -> None:
    if not settings.pokemontcg_api_key:
        raise SystemExit("POKEMONTCG_API_KEY is not set in backend/.env")

    repo = InventoryRepository(settings.dynamodb_table_name, region_name=settings.aws_region)

    print(
        f"Syncing pokemontcg.io catalog into DynamoDB table "
        f"'{settings.dynamodb_table_name}' ({settings.aws_region})..."
    )

    # sync_catalog upserts and is idempotent for same-day price points, so
    # re-running the whole sync after a failure just re-writes the same rows
    # and continues — safe to retry the whole run, not just one request. A
    # fresh client per attempt avoids reusing a connection pool that may be
    # pinned to a struggling upstream node.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        client = _new_client()
        try:
            summary = run_daily_sync(repo, client, date.today())
            break
        except (PokemonTcgError, httpx.HTTPError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            wait = min(15 * attempt, 90)
            print(f"Attempt {attempt} failed ({exc}); retrying in {wait}s...")
            time.sleep(wait)
    print(summary)


if __name__ == "__main__":
    main()
