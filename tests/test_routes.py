import pytest
from fastapi.testclient import TestClient


class TestPublicRoutes:
    def test_health_check(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "project": "Kenhub"}

    def test_login_page(self, client: TestClient):
        response = client.get("/login")
        assert response.status_code == 200
        assert "KnowFlow" in response.text

    def test_root_redirect(self, client: TestClient):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/login"


class TestProtectedRoutes:
    def test_dashboard_requires_auth(self, client: TestClient):
        response = client.get("/dashboard", headers={"Accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/login"

    def test_documents_requires_auth(self, client: TestClient):
        response = client.get("/documents", headers={"Accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/login"

    def test_categories_requires_auth(self, client: TestClient):
        response = client.get("/categories", headers={"Accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/login"

    def test_search_requires_auth(self, client: TestClient):
        response = client.get("/search", headers={"Accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/login"

    def test_admin_requires_auth(self, client: TestClient):
        response = client.get("/admin", headers={"Accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/login"
