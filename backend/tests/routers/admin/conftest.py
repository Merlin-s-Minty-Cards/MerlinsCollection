"""Shared fixtures for the admin router tests.

Every module in this package used to carry its own byte-identical copy of
``admin_client`` — 16 copies of the same ~20 lines, differing only in the shape
of the tuple they yielded. Changing how admin auth is wired for tests meant
editing sixteen files, which is how they drifted in the first place.

The canonical fixture yields ``(client, repo, admin_token)``. Two modules
(``test_inventory``, ``test_triage``) additionally need a NON-admin token to
prove the 403 path, so they override ``admin_client`` locally to yield a
4-tuple — but they build it with ``build_admin_client`` below rather than
restating the body.
"""

import pytest
from fastapi.testclient import TestClient


def build_admin_client(cognito_config, jwks, dynamo_repo):
    """Wire the app's auth + repo dependencies to the test doubles.

    Returns the ``TestClient``. The caller is responsible for clearing
    ``app.dependency_overrides`` on teardown — see ``admin_client``.
    """
    from merlins_collection.dependencies import get_repo, get_verifier
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    verifier = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_repo] = lambda: dynamo_repo
    return TestClient(app)


def clear_overrides():
    from merlins_collection.main import app

    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
    """TestClient + repo + an admin bearer token, as ``(client, repo, token)``."""
    client = build_admin_client(cognito_config, jwks, dynamo_repo)
    yield client, dynamo_repo, mint_token(claims={"cognito:groups": ["admin"]})
    clear_overrides()
