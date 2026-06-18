from django.test import RequestFactory

from maps.sandbox import client_ip


def test_client_ip_uses_last_forwarded_for_hop():
    # Render appends the real client IP to the right; the leftmost hop is client-forgeable.
    req = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_ignores_a_forged_leftmost_hop():
    req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="9.9.9.9", REMOTE_ADDR="10.0.0.1")
    # single hop → that hop is the one Render appended (the real client)
    assert client_ip(req) == "9.9.9.9"


def test_client_ip_falls_back_to_remote_addr():
    req = RequestFactory().get("/", REMOTE_ADDR="198.51.100.4")
    assert client_ip(req) == "198.51.100.4"
