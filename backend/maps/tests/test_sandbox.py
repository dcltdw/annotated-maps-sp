from django.test import RequestFactory

from maps.sandbox import client_ip


def test_client_ip_prefers_first_forwarded_for_hop():
    req = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr():
    req = RequestFactory().get("/", REMOTE_ADDR="198.51.100.4")
    assert client_ip(req) == "198.51.100.4"
