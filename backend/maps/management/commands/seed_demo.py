from django.core.management.base import BaseCommand

from maps.seed import build_boston_demo


class Command(BaseCommand):
    help = "Seed the Boston demo (idempotent)."

    def handle(self, *args, **options):
        data = build_boston_demo()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded map {data['map'].id} with the Castle Island note.")
        )
