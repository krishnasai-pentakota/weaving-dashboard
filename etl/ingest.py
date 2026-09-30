"""The evening job: take today's sheet into the database.

    python -m etl.ingest path/to/entry_workbook.xlsx

Run it by hand at first, then from Windows Task Scheduler once the floor is
used to the form. It is safe to run the same file twice: a row that is already
in the database is updated, not duplicated, because a machine-shift is keyed on
the loom, the date and the shift.

What it does, in order:
    reads the sheet  ->  checks every row  ->  writes the good rows
                     ->  keeps the bad rows with the reason they were refused
                     ->  raises each problem where the dashboard can show it

A row that breaks a blocking rule is NOT loaded. That is the point: a backward
meter reading nobody explained is how eight months of production quietly went
wrong, and it should stop at the door rather than become a chart.
"""
from __future__ import annotations

import argparse
import sys

from . import db
from .load import load


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Load one day's (or one month's) entry sheet into the database.")
    ap.add_argument("workbook", help="the clerk's entry workbook")
    ap.add_argument("--allow-invalid", action="store_true",
                    help="load rows that break a blocking rule anyway. Only for "
                         "a one-off catch-up where the floor has confirmed the "
                         "figures by hand.")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if not a.quiet:
        print(f"Database  {db.describe()}")
    try:
        r = load(a.workbook, rebuild=False, hold_invalid=not a.allow_invalid,
                 quiet=a.quiet)
    except Exception as e:
        print(f"\nLOAD FAILED — nothing was written.\n{type(e).__name__}: {e}",
              file=sys.stderr)
        return 2

    print(f"\nBatch {r['batch_id']}")
    print(f"  {r['rows_loaded']:,} machine-shift rows loaded")
    print(f"  {r['rejections']:,} rejection events")
    print(f"  {r['downtime']:,} stoppages with a time against them")
    print(f"  {r['events']:,} changeovers, resets and line changes")
    if r["rows_held"]:
        print(f"\n  {r['rows_held']:,} rows were NOT loaded because they break a "
              f"blocking rule.\n  They are listed on the dashboard's Data health "
              f"page, with the reason for each.\n  Correct them in the sheet and "
              f"run this again — the corrected rows will go in\n  and nothing "
              f"will be duplicated.")
        return 1
    if r["issues"]:
        print(f"\n  {r['issues']:,} warnings raised (missing names, stoppages with "
              f"no reason,\n  and so on). The yards are fine; see the Data health "
              f"page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
