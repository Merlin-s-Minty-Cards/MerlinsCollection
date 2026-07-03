"""AUTH_DISABLED dev bypass: lets local dev run without a Cognito pool.

The flag must default to OFF — production never sets it — and when ON it
injects a fake non-admin user instead of requiring a bearer token.
"""

from fastapi.testclient import TestClient


def test_auth_disabled_defaults_to_false():
    from merlins_collection.config import Settings

    assert Settings(_env_file=None).auth_disabled is False


def test_search_works_without_token_when_auth_disabled(dynamo_repo, monkeypatch):
    from merlins_collection import dependencies
    from merlins_collection.main import app

    monkeypatch.setattr(dependencies.settings, "auth_disabled", True)
    app.dependency_overrides[dependencies.get_repo] = lambda: dynamo_repo
    try:
        client = TestClient(app)
        resp = client.get("/inventory/search")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_bypass_user_is_not_admin(monkeypatch):
    """The dev bypass must not silently grant admin rights."""
    from merlins_collection import dependencies

    monkeypatch.setattr(dependencies.settings, "auth_disabled", True)
    user = dependencies.get_current_user(credentials=None, verifier=None)
    assert user.is_admin is False


# The default-on behavior (401 without a token) is covered by
# tests/routers/test_inventory.py::test_search_requires_authentication.
