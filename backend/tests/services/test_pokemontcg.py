from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from merlins_collection.services.pokemontcg import (
    PokemonTcgClient,
    PokemonTcgError,
    to_catalog_card,
)

SAMPLE = {
    "id": "swsh1-1",
    "name": "Celebi V",
    "number": "1",
    "rarity": "Rare Holo V",
    "types": ["Grass"],
    "set": {"id": "swsh1", "name": "Sword & Shield"},
    "images": {"small": "s.png", "large": "l.png"},
    "tcgplayer": {"prices": {
        "holofoil": {"low": 5.0, "mid": 8.0, "high": 20.0, "market": 9.25},
        "reverseHolofoil": {"market": 6.5},
    }},
}


def test_maps_core_fields_and_decimal_prices():
    card = to_catalog_card(SAMPLE, synced_at=datetime(2026, 6, 22, 12, 0, 0))
    assert card.card_id == "swsh1-1"
    assert card.set_id == "swsh1"
    assert card.types == ["Grass"]
    assert card.prices["holofoil"].market == Decimal("9.25")
    assert card.prices["reverseHolofoil"].market == Decimal("6.5")
    assert card.prices["holofoil"].low == Decimal("5.0")


def test_card_without_tcgplayer_prices_maps_to_empty():
    raw = {"id": "p-1", "name": "Promo", "number": "1",
           "set": {"id": "promo", "name": "Promo"},
           "images": {"small": "s", "large": "l"}}
    card = to_catalog_card(raw)
    assert card.prices == {}
    assert card.rarity is None


def _client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url=PokemonTcgClient.BASE_URL)
    return PokemonTcgClient(client=http, backoff_base=0, **kwargs)


def test_iter_all_cards_paginates():
    def handler(request):
        page = int(request.url.params["page"])
        bodies = {1: {"data": [{"id": "x1"}, {"id": "x2"}]}, 2: {"data": [{"id": "x3"}]}}
        return httpx.Response(200, json=bodies.get(page, {"data": []}))

    ids = [c["id"] for c in _client(handler, page_size=2).iter_all_cards()]
    assert ids == ["x1", "x2", "x3"]


def test_get_card_retries_on_5xx():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"data": {"id": "z"}})

    assert _client(handler, max_retries=3).get_card("z") == {"id": "z"}
    assert calls["n"] == 2


def test_get_card_404_returns_none():
    assert _client(lambda r: httpx.Response(404, json={})).get_card("nope") is None


def test_get_card_4xx_raises():
    with pytest.raises(PokemonTcgError):
        _client(lambda r: httpx.Response(400, json={})).get_card("bad")
