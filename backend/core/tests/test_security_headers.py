import pytest
from django.test import Client


@pytest.mark.django_db
def test_security_headers_present():
    resp = Client().get("/api/v1/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]
