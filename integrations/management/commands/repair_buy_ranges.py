"""Rewrite Buy Range (column T) from Comments when dips were omitted."""

from django.core.management.base import BaseCommand

from integrations.recommendations import repair_buy_ranges_from_comments
from integrations.sheets import sync_from_sheet


class Command(BaseCommand):
    help = (
        "Scan open-row Comments for 'Buy at' / 'dips upto' and patch Buy Range "
        "(column T) when it does not match."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-sync", action="store_true")

    def handle(self, *args, **options):
        result = repair_buy_ranges_from_comments(dry_run=options["dry_run"])
        self.stdout.write(
            f"patches={len(result['patches'])} cells={result['cells']} "
            f"dry_run={result['dry_run']}"
        )
        for item in result["patches"]:
            self.stdout.write(
                f"  row {item['sheet_row']} {item['ticker']}: "
                f"{item['was'] or '(empty)'} → {item['buy_range']}"
            )
        if not result["dry_run"] and result["cells"] and not options["no_sync"]:
            sync_from_sheet()
            self.stdout.write("synced sheet into the app")
