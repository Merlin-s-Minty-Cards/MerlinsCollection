"""RED for RFC 0026 — ``GET /admin/docs``, the REST surface the frontend
Docs tab fetches. Same content, same auth, as the ``search_admin_docs`` MCP
tool reads via ``services/admin_docs.py`` — this endpoint just calls
``list_categories``/``list_all`` directly rather than reimplementing them.
"""

from __future__ import annotations


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestGetAdminDocs:
    def test_returns_categories_and_articles(self, admin_client):
        client, _repo, token = admin_client
        resp = client.get("/admin/docs", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert "articles" in data
        assert len(data["categories"]) > 0
        assert len(data["articles"]) > 0

    def test_articles_include_full_body(self, admin_client):
        client, _repo, token = admin_client
        resp = client.get("/admin/docs", headers=_auth(token))
        assert all(a.get("body") for a in resp.json()["articles"])

    def test_requires_admin_auth(self, admin_client):
        client, _repo, _token = admin_client
        resp = client.get("/admin/docs")
        assert resp.status_code in (401, 403)
