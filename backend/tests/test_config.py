def test_settings_reads_pokemontcg_api_key(monkeypatch):
    monkeypatch.setenv("POKEMONTCG_API_KEY", "abc123")
    from merlins_collection.config import Settings

    assert Settings().pokemontcg_api_key == "abc123"
