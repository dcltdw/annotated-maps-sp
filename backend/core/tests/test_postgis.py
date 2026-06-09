import pytest
from django.db import connection


@pytest.mark.django_db
def test_postgis_extension_is_available():
    with connection.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'postgis';")
        assert cur.fetchone() is not None, "PostGIS extension is not installed"
