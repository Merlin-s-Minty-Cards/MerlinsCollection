"""GET /health — unauthenticated liveness probe for containers/load balancers."""


def test_health_returns_ok_without_auth(client):
    # No Authorization header on purpose: orchestrators poll anonymously.
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
