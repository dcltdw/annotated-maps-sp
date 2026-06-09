import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_returns_ok_with_version():
    resp = Client().get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body and "git_sha" in body
