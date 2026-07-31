from decimal import Decimal


def test_settings_defaults_the_eur_usd_rate():
    from merlins_collection.config import Settings

    assert Settings().eur_usd_rate == Decimal("1.08")


def test_settings_reads_the_eur_usd_rate_from_the_environment(monkeypatch):
    """Correcting the FX rate must be a config change, never a code deploy."""
    monkeypatch.setenv("EUR_USD_RATE", "1.15")
    from merlins_collection.config import Settings

    assert Settings().eur_usd_rate == Decimal("1.15")
