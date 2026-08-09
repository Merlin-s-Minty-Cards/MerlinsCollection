from decimal import Decimal


def test_settings_defaults_the_eur_usd_rate():
    from merlins_collection.config import Settings

    assert Settings().eur_usd_rate == Decimal("1.08")


def test_settings_reads_the_eur_usd_rate_from_the_environment(monkeypatch):
    """Correcting the FX rate must be a config change, never a code deploy."""
    monkeypatch.setenv("EUR_USD_RATE", "1.15")
    from merlins_collection.config import Settings

    assert Settings().eur_usd_rate == Decimal("1.15")


# --- Graded-pricing budget (RFC 0009) -------------------------------------
#
# These two are DOCUMENTATION GUARDS, not new behaviour: `pricing_daily_quota`
# shipped with T6/T7. They exist because `.env.example`, backend/README.md and
# CLAUDE.md now all print the number 100 next to the words "50 lookups", and a
# default changed in code without changing those three files would make every one
# of them quietly wrong.
#
# `_env_file=None` is deliberate. `Settings.model_config` uses `env_file=".env"`,
# resolved against the CWD, so the same assertion run from `backend/` rather than
# the repo root would read the developer's real `.env` and pass or fail for the
# wrong reason.


def test_pricing_daily_quota_defaults_to_one_hundred_credits():
    """100 CREDITS, which is 50 lookups — a graded lookup costs 2.

    If this default ever changes, update `.env.example`, `backend/README.md` and
    CLAUDE.md's "Third-Party APIs" section in the same commit; all three quote it.
    """
    from merlins_collection.config import Settings

    assert Settings(_env_file=None).pricing_daily_quota == 100


def test_pricing_daily_quota_reads_from_the_environment(monkeypatch):
    """Raising the budget after a paid upgrade must not need a deploy."""
    monkeypatch.setenv("PRICING_DAILY_QUOTA", "20000")
    from merlins_collection.config import Settings

    assert Settings(_env_file=None).pricing_daily_quota == 20000


def test_there_is_still_no_psa_setting_to_configure():
    """`PSA_API_KEY` is documented but INERT, and the docs say so.

    `Settings` has no PSA field while the cert lookup (T2) is deferred behind PSA
    account approval, and `model_config` uses `extra="ignore"` — so setting
    `PSA_API_KEY` today does nothing at all. `.env.example`, `backend/README.md`
    and `docs/aws-setup.md` all state that explicitly.

    **When T2 lands and adds the field, this test SHOULD fail.** Delete it and
    correct those three files in the same commit — that is the whole point of it.
    """
    from merlins_collection.config import Settings

    assert not any("psa" in name for name in Settings.model_fields)
