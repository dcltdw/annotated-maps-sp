import pytest
from django.test import Client


@pytest.mark.django_db
def test_response_carries_request_id_header():
    resp = Client().get("/api/v1/health")
    assert resp.headers.get("X-Request-ID")


@pytest.mark.django_db
def test_incoming_request_id_is_echoed():
    rid = "test-correlation-123"
    resp = Client().get("/api/v1/health", headers={"X-Request-ID": rid})
    assert resp.headers["X-Request-ID"] == rid
