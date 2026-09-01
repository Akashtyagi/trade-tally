from django.core.management.base import BaseCommand

from integrations.checker import run_checks


class Command(BaseCommand):
    help = (
        "Sync the Google Sheet, refresh Kite holdings/LTP, and send Telegram alerts. "
        "Skips automatically outside weekday market hours unless --force is set."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-sheet",
            action="store_true",
            help="Do not pull the Google Sheet on this run.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even outside Monday–Friday 09:15–15:30 IST.",
        )

    def handle(self, *args, **options):
        result = run_checks(sync_sheet=not options["skip_sheet"], force=options["force"])
        if result.get("skipped"):
            self.stdout.write(self.style.WARNING(f"Skipped: {result['skipped']}"))
            return
        self.stdout.write(self.style.SUCCESS(f"Checks complete: {result}"))
