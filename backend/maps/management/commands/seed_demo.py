from django.core.management.base import BaseCommand

from maps.models import Note
from maps.seed import build_boston_demo


class Command(BaseCommand):
    help = (
        "Seed the Boston demo. Idempotent (get_or_create) by default; pass --refresh to "
        "rebuild the seed content from code so changed demo notes are re-applied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--refresh",
            action="store_true",
            help=(
                "Delete existing seed notes (is_seed=True) before seeding, so the demo "
                "content is rebuilt to match the current code. User-created notes "
                "(is_seed=False) and the personas / map / groups are left intact. "
                "Used by the Render preDeployCommand so each deploy re-applies the seed."
            ),
        )

    def handle(self, *args, **options):
        if options["refresh"]:
            # get_or_create only sets fields on CREATE, so a plain re-seed never updates an
            # existing note. Hard-delete the seed notes first (cascades sections + appends)
            # and let build_boston_demo recreate them from current code. all_objects so any
            # soft-deleted seed rows go too; the is_seed filter spares user-created content.
            deleted, _ = Note.all_objects.filter(is_seed=True).delete()
            self.stdout.write(self.style.WARNING(f"Refresh: removed {deleted} seed object(s)."))
        data = build_boston_demo()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded map {data['map'].id} with the demo notes.")
        )
