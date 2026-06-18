from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from maps.models import Note

TTL_DAYS = 7


class Command(BaseCommand):
    help = "Hard-delete ephemeral sandbox content older than the TTL (seed is never touched)."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=TTL_DAYS)
        # all_objects so already-soft-deleted rows are purged too; .delete() is a hard
        # SQL DELETE and cascades to child appends (Note.parent on_delete=CASCADE).
        qs = Note.all_objects.filter(is_seed=False, created_at__lt=cutoff)
        count = qs.count()
        qs.delete()
        self.stdout.write(
            self.style.SUCCESS(f"Reaped {count} ephemeral notes/appends older than {TTL_DAYS}d.")
        )
