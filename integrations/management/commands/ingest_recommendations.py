"""manage.py ingest_recommendations — advisor dump → sheet rows."""

from django.core.management.base import BaseCommand

from integrations.recommendations import ingest_recommendations
from integrations.sheets import sync_from_sheet


class Command(BaseCommand):
    help = (
        "Parse zerodha_files/trades.txt (advisor messages) and append missing "
        "open rows on the Google Sheet using skills/google-sheet fill rules."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="",
            help="Message dump path (default zerodha_files/trades.txt).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse only; do not write the Google Sheet.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Rewrite plan cells for tickers already on the sheet (from the dump).",
        )
        parser.add_argument(
            "--no-sync",
            action="store_true",
            help="Skip sync_from_sheet after a successful write.",
        )

    def handle(self, *args, **options):
        path = options["file"] or None
        result = ingest_recommendations(
            path=path,
            dry_run=options["dry_run"],
            update_existing=options["update"],
        )
        self.stdout.write(
            f"new_buys={len(result['new_buys'])} updates={len(result['updates'])} "
            f"skipped={result['skipped']} writes={len(result['writes'])} "
            f"cells={result['cells']} dry_run={result['dry_run']}"
        )
        if result["unknown_names"]:
            self.stdout.write("unknown tickers (not written):")
            for name in result["unknown_names"]:
                self.stdout.write(f"  - {name}")
        if result["skipped_existing"]:
            self.stdout.write(
                "already on sheet: " + ", ".join(sorted(set(result["skipped_existing"])))
            )
        for rec in result["writes"]:
            self.stdout.write(
                f"  {rec.get('action')} row {rec.get('sheet_row')} {rec['ticker']} "
                f"buy {rec['buy_low']}-{rec['buy_high']} sl={rec['stop_loss']}"
            )
        if result.get("closed_writes"):
            self.stdout.write("closed AC-AK:")
            for item in result["closed_writes"]:
                self.stdout.write(f"  {item['ticker']} row {item['sheet_row']}")
        if not result["dry_run"] and result["cells"] and not options["no_sync"]:
            sync_from_sheet()
            self.stdout.write("synced sheet into the app")
