from datetime import timedelta

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.utils import timezone

from maps.models import Note


def test_reaper_deletes_old_ephemeral_keeps_seed_and_recent(world):
    old = Note.objects.create(
        tenant=world["tenant"],
        map=world["map"],
        author=world["alice"],
        title="old",
        is_seed=False,
        point=Point(0, 0),  # top-level notes need exactly one anchor
    )
    # backdate created_at past the 7-day TTL (created_at is auto_now_add, so update directly)
    Note.all_objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=8))
    recent = Note.objects.create(
        tenant=world["tenant"],
        map=world["map"],
        author=world["alice"],
        title="recent",
        is_seed=False,
        point=Point(0, 0),  # top-level notes need exactly one anchor
    )

    call_command("reap_ephemeral")

    assert not Note.all_objects.filter(id=old.id).exists()  # old ephemeral → gone
    assert Note.all_objects.filter(id=recent.id).exists()  # recent ephemeral → kept
    assert Note.all_objects.filter(id=world["seed"].id).exists()  # seed → always kept
