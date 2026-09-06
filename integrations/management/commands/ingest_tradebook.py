"""manage.py ingest_tradebook — see scripts/ingest-tradebook.sh."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from integrations.tradebook import ingest_tradebook


class Command(BaseCommand):
    help = (
        "Read Zerodha 'Tradebook - …' worksheets, merge them into "
        "'Tradebook - Ledger' / 'Tradebook - Matched', show fills on tracked "
        "share detail pages, and close BUY→SELL rounds with no open position."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            action="append",
            dest="csv_paths",
            default=[],
            help="Import a local Zerodha tradebook CSV instead of (or as well as) Google tabs. Repeatable.",
        )
        parser.add_argument(
            "--csv-dir",
            default="",
            help="Import every *.csv in this folder (e.g. zerodha_files).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and match, but do not write the Google Sheet or close trades.",
        )
        parser.add_argument(
            "--no-close",
            action="store_true",
            help="Import fills without changing OPEN/PARTIAL/CLOSED on tracked trades.",
        )

    def handle(self, *args, **options):
        csv_paths = list(options["csv_paths"] or [])
        csv_dir = options["csv_dir"]
        if csv_dir:
            folder = Path(csv_dir)
            if not folder.is_dir():
                raise CommandError(f"Not a directory: {folder}")
            csv_paths.extend(sorted(str(p) for p in folder.glob("*.csv")))
        try:
            result = ingest_tradebook(
                write_sheet=not options["dry_run"],
                writeback_closes=not options["dry_run"] and not options["no_close"],
                apply_closes=not options["dry_run"] and not options["no_close"],
                csv_paths=csv_paths or None,
                dry_run=options["dry_run"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Tradebook ingest complete: {result}"))
