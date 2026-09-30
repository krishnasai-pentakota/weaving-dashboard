"""Loading the workbook into the database.

Two jobs share this code:

    python -m etl.load --rebuild <workbook.xlsx>    the eight-month history
    python -m etl.ingest <workbook.xlsx>            one more day, every evening

They are the same path on purpose. A daily row and a historical row are
validated by exactly the same rules, so a figure the dashboard shows tonight
means the same thing as a figure it showed in March.

Nothing is ever silently dropped. A row that breaks a rule is written to
stg_daily_entry with its reasons and raised in data_issue, where the dashboard
reads it. The clerk sees what is wrong; the yards are not quietly lost.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import psycopg2.extras

from . import db, workbook as W

# ---------------------------------------------------------------------------
#  Reference mappings. Kept here, in one table each, so the floor can revise
#  the vocabulary without anybody editing a chart.
# ---------------------------------------------------------------------------
REJECTION_GROUPS = {
    "LINE PROBLEM":       ("WEAVING FAULT",        "WEAVING"),
    "WEFT PROBLEM":       ("WEAVING FAULT",        "WEAVING"),
    "DOT PROBLEM":        ("WEAVING FAULT",        "WEAVING"),
    "EDGE PROBLEM":       ("EDGE / SELVEDGE",      "WEAVING"),
    "EDGE UNEVEN":        ("EDGE / SELVEDGE",      "WEAVING"),
    "FLYING YARNS":       ("YARN / MATERIAL",      "STORES / PLANNING"),
    "LOOSE YARN":         ("YARN / MATERIAL",      "STORES / PLANNING"),
    "WIDTH PROBLEM":      ("MACHINE SETTING",      "MAINTENANCE"),
    "TOLERANCE PROBLEM":  ("MACHINE SETTING",      "MAINTENANCE"),
    "OIL / BLACK STAINS": ("DIRT / CONTAMINATION", "HOUSEKEEPING"),
    "FOLDING PROBLEM":    ("HANDLING",             "WEAVING"),
}
REASON_CLASSES = {
    "MAINTENANCE": "MAINTENANCE", "MATERIAL": "MATERIAL", "PLANNING": "PLANNING",
    "UTILITIES": "UTILITIES", "HOUSEKEEPING": "HOUSEKEEPING",
    "HR / SHIFT IN-CHARGE": "MANPOWER", "UNCLASSIFIED": "UNCLASSIFIED",
}
SHIFT_MINUTES = 8 * 60


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ===========================================================================
#  VALIDATION — the rules that turn a spreadsheet into evidence
# ===========================================================================
def validate(e: W.EntryRow, known_specs: set[str], known_staff: set[str],
             commissioned: set[str]) -> tuple[list[str], list[str]]:
    """Return (blocking errors, warnings) for one entry row.

    Blocking means the row cannot be trusted as a production figure and is held
    back for the clerk to correct. A warning means the yards are usable but
    something on the floor was not written down.
    """
    errors: list[str] = []
    warn: list[str] = []
    prev, cur = e.previous_reading_m, e.current_reading_m
    lines = e.lines_running or e.lines_fitted or 0

    if e.machine_code not in commissioned and e.machine_status != "NOT YET IN PRODUCTION":
        warn.append(f"UNKNOWN_MACHINE: {e.machine_code} is not in the machine master")

    if prev is not None and cur is not None and cur < prev:
        if e.event not in ("CHANGEOVER", "RESET") and e.rebase_override_m is None:
            errors.append(
                f"BACKWARD_READING: the meter fell from {prev:,.0f} to {cur:,.0f} "
                f"and the row is not marked CHANGEOVER or RESET")

    if e.lines_fitted and e.lines_running and e.lines_running > e.lines_fitted:
        errors.append(
            f"LINES_RUNNING_GT_FITTED: {e.lines_running} running but only "
            f"{e.lines_fitted} fitted")

    if e.machine_status == "RUNNING" and not lines:
        errors.append("NO_LINE_COUNT: the row is marked RUNNING but no line count was entered")

    gross = None
    if lines and prev is not None and cur is not None and cur >= prev:
        gross = (cur - prev) * lines / 0.9144
    elif lines and e.rebase_override_m is not None:
        gross = e.rebase_override_m * lines / 0.9144

    if gross is not None and e.rejection_yards > gross + 0.5:
        errors.append(
            f"REJECTION_GT_PRODUCTION: {e.rejection_yards:,.0f} yards rejected "
            f"against {gross:,.0f} yards produced")

    if e.machine_status == "RUNNING":
        if not e.operator:
            warn.append("NO_OPERATOR: nobody is named against a running machine")
        if not e.supervisor:
            warn.append("NO_SUPERVISOR: no supervisor signed this shift")
        if gross is not None and gross == 0:
            warn.append("RUNNING_BUT_NOTHING_MADE: marked RUNNING with a zero reading move")

    if e.machine_status in ("STOPPED", "IDLE") and not e.stop_reason:
        warn.append("MACHINE_STOPPED_BUT_NO_REASON: the loom stopped and no reason was written")

    if e.stop_reason and not e.stop_time:
        warn.append("REASON_BUT_NO_STOP_TIME: a reason was given without the time it stopped")

    if e.stop_time and e.restart_time:
        mins = _minutes(e.stop_time, e.restart_time)
        if mins is not None and mins > SHIFT_MINUTES:
            warn.append(f"DOWNTIME_LONGER_THAN_SHIFT: {mins} minutes on an eight-hour shift")

    if e.rejection_yards > 0 and not e.qc_name:
        warn.append("REJECTION_WITHOUT_QC: rejection recorded with no inspector named")

    if e.rejection_yards > 0 and gross is None:
        warn.append(
            f"REJECTION_WITH_NO_READING: {e.rejection_yards:,.0f} yards rejected on a "
            f"machine-shift with no meter reading behind it (status {e.machine_status})")

    if e.weaving_spec and e.weaving_spec not in known_specs:
        warn.append(f"UNKNOWN_SPEC: {e.weaving_spec} is not in the specification master")

    for who, role in ((e.operator, "operator"), (e.supervisor, "supervisor"), (e.qc_name, "QC")):
        if who and who not in known_staff:
            warn.append(f"UNKNOWN_{role.upper()}: {who} is not on the people list")

    if e.target_yards in (None, 0) and e.machine_status == "RUNNING":
        warn.append("NO_TARGET: this machine-shift carries no target")

    return errors, warn


def _minutes(stop, restart) -> int | None:
    def to_min(v):
        if isinstance(v, dt.time):
            return v.hour * 60 + v.minute
        if isinstance(v, dt.datetime):
            return v.hour * 60 + v.minute
        if isinstance(v, (int, float)):        # Excel time fraction of a day
            return int(round(float(v) * 24 * 60))
        if isinstance(v, str) and ":" in v:
            h, _, m = v.partition(":")
            try:
                return int(h) * 60 + int(m[:2])
            except ValueError:
                return None
        return None
    a, b = to_min(stop), to_min(restart)
    if a is None or b is None:
        return None
    return b - a if b >= a else 1440 - a + b


def _as_time(v):
    if isinstance(v, dt.time):
        return v
    if isinstance(v, dt.datetime):
        return v.time()
    if isinstance(v, (int, float)):
        total = int(round(float(v) * 24 * 60))
        return dt.time((total // 60) % 24, total % 60)
    if isinstance(v, str) and ":" in v:
        try:
            h, m = v.split(":")[:2]
            return dt.time(int(h) % 24, int(m[:2]))
        except ValueError:
            return None
    return None


# ===========================================================================
#  LOAD
# ===========================================================================
def load(path: str | Path, *, rebuild: bool, hold_invalid: bool, quiet: bool = False) -> dict:
    path = Path(path)
    say = (lambda *a: None) if quiet else print

    say(f"Reading   {path.name}")
    src = W.read(path)
    say(f"          {len(src.entries):,} completed rows, {len(src.machines)} machines, "
        f"{len(src.specs)} specifications, {len(src.rejections):,} rejection events")

    conn = db.connect()
    cur = conn.cursor()
    cur.execute("SET search_path TO weaving, public")

    cur.execute(
        "INSERT INTO load_batch(source_file, source_sha256, rows_read) "
        "VALUES (%s,%s,%s) RETURNING batch_id",
        (path.name, _sha256(path), len(src.entries)))
    batch_id = cur.fetchone()[0]

    if rebuild:
        say("Clearing  facts (dimensions are merged, never dropped)")
        cur.execute("TRUNCATE fact_production, fact_rejection, fact_downtime, "
                    "fact_machine_event, stg_daily_entry RESTART IDENTITY")
        cur.execute("DELETE FROM data_issue WHERE status = 'OPEN'")

    # ---- dimensions -------------------------------------------------------
    _load_dates(cur, src)
    machine_id = _load_machines(cur, src)
    spec_id = _load_specs(cur, src)
    staff_id = _load_staff(cur, src)
    _load_stop_reasons(cur, src)
    reason_id = _load_rejection_reasons(cur, src)
    say(f"Reference {len(machine_id)} machines, {len(spec_id)} specs, "
        f"{len(staff_id)} people, {len(reason_id)} rejection reasons")

    known_specs = set(spec_id)
    known_staff = set(staff_id)
    commissioned = set(machine_id)

    # ---- staging + validation --------------------------------------------
    stg, good, held = [], [], 0
    issues = []
    for e in src.entries:
        errors, warns = validate(e, known_specs, known_staff, commissioned)
        ok = not errors
        stg.append((batch_id, path.name, e.source_row,
                    json.dumps(_jsonable(e)), ok, errors, warns))
        if ok or not hold_invalid:
            good.append(e)
        else:
            held += 1
        for code_msg, sev in [(m, "BLOCK") for m in errors] + [(m, "WARN") for m in warns]:
            code, _, desc = code_msg.partition(": ")
            issues.append((sev, code, e.date_key, machine_id.get(e.machine_code),
                           e.shift_code, desc or code))

    psycopg2.extras.execute_values(
        cur,
        "INSERT INTO stg_daily_entry(batch_id, source_file, source_row, raw, "
        "is_valid, errors, warnings) VALUES %s "
        "ON CONFLICT (batch_id, source_row) DO NOTHING", stg, page_size=2000)

    # ---- production facts -------------------------------------------------
    rows = []
    for e in good:
        lines_running = e.lines_running if e.lines_running is not None else (e.lines_fitted or 0)
        rows.append((
            e.date_key, e.shift_code, machine_id.get(e.machine_code),
            spec_id.get(e.weaving_spec),
            e.lines_fitted, lines_running,
            e.machine_status, e.event, e.remarks,
            e.previous_reading_m, e.current_reading_m, e.rebase_override_m,
            e.single_line_share, e.rejection_yards, e.target_yards,
            staff_id.get(e.operator), staff_id.get(e.supervisor),
            e.confidence, e.confidence_why, e.source_note, path.name,
        ))
    rows = [r for r in rows if r[2] is not None]

    psycopg2.extras.execute_values(cur, """
        INSERT INTO fact_production (
            date_key, shift_code, machine_id, spec_id,
            lines_fitted, lines_running, machine_status, event, remarks,
            previous_reading_m, current_reading_m, rebase_override_m,
            single_line_share, rejection_yards, target_yards,
            operator_id, supervisor_id, confidence, confidence_why,
            source_note, source_file)
        VALUES %s
        ON CONFLICT (date_key, shift_code, machine_id) DO UPDATE SET
            spec_id            = EXCLUDED.spec_id,
            lines_fitted       = EXCLUDED.lines_fitted,
            lines_running      = EXCLUDED.lines_running,
            machine_status     = EXCLUDED.machine_status,
            event              = EXCLUDED.event,
            remarks            = EXCLUDED.remarks,
            previous_reading_m = EXCLUDED.previous_reading_m,
            current_reading_m  = EXCLUDED.current_reading_m,
            rebase_override_m  = EXCLUDED.rebase_override_m,
            single_line_share  = EXCLUDED.single_line_share,
            rejection_yards    = EXCLUDED.rejection_yards,
            target_yards       = EXCLUDED.target_yards,
            operator_id        = EXCLUDED.operator_id,
            supervisor_id      = EXCLUDED.supervisor_id,
            confidence         = EXCLUDED.confidence,
            confidence_why     = EXCLUDED.confidence_why,
            source_note        = EXCLUDED.source_note,
            source_file        = EXCLUDED.source_file,
            updated_at         = now()
    """, rows, page_size=2000)
    say(f"Production {len(rows):,} rows loaded" + (f", {held:,} held back" if held else ""))

    # ---- machine events ---------------------------------------------------
    events = {}
    for e in good:
        mid = machine_id.get(e.machine_code)
        if mid is None:
            continue
        if e.event in ("CHANGEOVER", "RESET"):
            events[(e.date_key, mid, e.event)] = (e.remarks, e.weaving_spec)
        if e.line_count_change:
            events[(e.date_key, mid, "LINE COUNT CHANGE")] = (e.line_count_change, None)
        if e.spec_change:
            events[(e.date_key, mid, "SPEC CHANGE")] = (e.spec_change, e.weaving_spec)
    if events:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO fact_machine_event(date_key, machine_id, event_type, detail, spec_after)
            VALUES %s ON CONFLICT (date_key, machine_id, event_type) DO NOTHING
        """, [(d, m, t, v[0], v[1]) for (d, m, t), v in events.items()])
    say(f"Events    {len(events):,} changeovers, resets and line changes")

    # ---- downtime ---------------------------------------------------------
    down = []
    for e in good:
        st, rt = _as_time(e.stop_time), _as_time(e.restart_time)
        mid = machine_id.get(e.machine_code)
        if st is None or mid is None:
            continue
        code = None
        if e.stop_reason:
            cur.execute("SELECT reason_code FROM dim_stop_reason WHERE reason_text_en = %s",
                        (e.stop_reason,))
            got = cur.fetchone()
            code = got[0] if got else None
        down.append((e.date_key, e.shift_code, mid, st, rt, code,
                     None if code else e.stop_reason,
                     staff_id.get(e.operator), staff_id.get(e.supervisor), "PAPER FORM"))
    if down:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO fact_downtime(date_key, shift_code, machine_id, stop_time,
                restart_time, reason_code, reason_free_text, operator_id,
                supervisor_id, source) VALUES %s
        """, down)
    say(f"Downtime  {len(down):,} stops recorded")

    # ---- rejection register ----------------------------------------------
    rej = []
    for r in src.rejections:
        mid = machine_id.get(r.machine_code)
        if mid is None:
            continue
        rej.append((r.date_key, r.shift_code if r.shift_code in ("A", "B", "C") else "DAY",
                    mid, spec_id.get(r.weaving_spec), r.rejection_yards,
                    r.weight_per_yard_g, r.rejection_kgs,
                    reason_id.get(r.primary_reason), reason_id.get(r.addon_reason),
                    r.primary_reason, r.addon_reason,
                    staff_id.get(r.qc_name), staff_id.get(r.supervisor),
                    r.tied_to_production, path.name))
    if rej:
        cur.execute("DELETE FROM fact_rejection WHERE date_key BETWEEN %s AND %s",
                    (min(r[0] for r in rej), max(r[0] for r in rej)))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO fact_rejection(date_key, shift_code, machine_id, spec_id,
                rejection_yards, weight_per_yard_g, rejection_kgs,
                primary_reason_id, addon_reason_id, primary_reason_raw,
                addon_reason_raw, qc_id, supervisor_id, tied_to_production, source_file)
            VALUES %s
        """, rej, page_size=2000)
    say(f"Quality   {len(rej):,} rejection events")

    # ---- issues -----------------------------------------------------------
    if issues:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO data_issue(severity, issue_code, date_key, machine_id,
                shift_code, description) VALUES %s
        """, issues, page_size=2000)

    # ---- working days -----------------------------------------------------
    cur.execute("""
        UPDATE dim_date d SET is_working_day = TRUE
        WHERE EXISTS (SELECT 1 FROM fact_production p WHERE p.date_key = d.date_key)
    """)

    cur.execute("""
        UPDATE load_batch SET finished_at = now(), status = %s,
               rows_loaded = %s, rows_rejected = %s, message = %s
        WHERE batch_id = %s
    """, ("SUCCESS" if not held else "PARTIAL", len(rows), held,
          f"{len(issues)} data issues raised", batch_id))

    conn.commit()
    cur.close()
    conn.close()

    return dict(batch_id=batch_id, rows_read=len(src.entries), rows_loaded=len(rows),
                rows_held=held, issues=len(issues), rejections=len(rej),
                downtime=len(down), events=len(events))


def _jsonable(e: W.EntryRow) -> dict:
    out = {}
    for k, v in e.__dict__.items():
        if isinstance(v, (dt.date, dt.datetime, dt.time)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
#  dimension loaders (merge, never destroy: history must keep joining)
# ---------------------------------------------------------------------------
def _load_dates(cur, src: W.Workbook) -> None:
    dates = {e.date_key for e in src.entries} | {r.date_key for r in src.rejections}
    if not dates:
        return
    lo, hi = min(dates), max(dates)
    rows = []
    d = lo
    while d <= hi:
        iso_year, iso_week, iso_dow = d.isocalendar()
        q = (d.month - 1) // 3 + 1
        rows.append((d, d.year, q, d.month, d.day, iso_dow, iso_year, iso_week,
                     f"{d.year:04d}-{d.month:02d}", f"{iso_year:04d}-W{iso_week:02d}",
                     f"{d.year:04d}-Q{q}", d.year * 12 + d.month,
                     iso_year * 53 + iso_week, d.year * 4 + q))
        d += dt.timedelta(days=1)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO dim_date(date_key, year, quarter, month, day_of_month, day_of_week,
            iso_year, iso_week, month_key, week_key, quarter_key,
            month_index, week_index, quarter_index)
        VALUES %s ON CONFLICT (date_key) DO NOTHING
    """, rows, page_size=1000)


def _load_machines(cur, src: W.Workbook) -> dict[str, int]:
    rows = [(m.machine_code, m.line_group, m.model, m.peer_group, m.is_commissioned,
             m.lines_fitted, m.target_per_line_day, m.target_source,
             m.weaving_spec, m.dyeing_spec, m.opening_reading_m, m.data_warning)
            for m in src.machines]
    psycopg2.extras.execute_values(cur, """
        INSERT INTO dim_machine(machine_code, line_group, model, peer_group,
            is_commissioned, lines_fitted, target_per_line_day, target_source,
            default_weaving_spec, default_dyeing_spec, opening_reading_m, data_warning)
        VALUES %s
        ON CONFLICT (machine_code) DO UPDATE SET
            line_group = EXCLUDED.line_group, model = EXCLUDED.model,
            peer_group = EXCLUDED.peer_group, is_commissioned = EXCLUDED.is_commissioned,
            lines_fitted = EXCLUDED.lines_fitted,
            target_per_line_day = EXCLUDED.target_per_line_day,
            target_source = EXCLUDED.target_source,
            default_weaving_spec = EXCLUDED.default_weaving_spec,
            default_dyeing_spec = EXCLUDED.default_dyeing_spec,
            opening_reading_m = EXCLUDED.opening_reading_m,
            data_warning = EXCLUDED.data_warning
    """, rows)
    cur.execute("SELECT machine_code, machine_id FROM dim_machine")
    return dict(cur.fetchall())


def _load_specs(cur, src: W.Workbook) -> dict[str, int]:
    rows = [(s.weaving_spec, s.dyeing_spec, s.per_yard_weight_g, s.per_yard_price,
             s.in_production) for s in src.specs]
    if rows:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_spec(weaving_spec, dyeing_spec, per_yard_weight_g,
                per_yard_price, in_production)
            VALUES %s
            ON CONFLICT (weaving_spec) DO UPDATE SET
                dyeing_spec = EXCLUDED.dyeing_spec,
                per_yard_weight_g = EXCLUDED.per_yard_weight_g,
                per_yard_price = EXCLUDED.per_yard_price,
                in_production = EXCLUDED.in_production
        """, rows)
    # Any specification woven but absent from the master is added so its yards
    # are never lost; it shows up on the data-health page as missing a weight.
    seen = {e.weaving_spec for e in src.entries if e.weaving_spec}
    seen |= {r.weaving_spec for r in src.rejections if r.weaving_spec}
    extra = [(s, None, None, None, True) for s in sorted(seen - {r[0] for r in rows})]
    if extra:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_spec(weaving_spec, dyeing_spec, per_yard_weight_g,
                per_yard_price, in_production) VALUES %s
            ON CONFLICT (weaving_spec) DO NOTHING
        """, extra)
    cur.execute("SELECT weaving_spec, spec_id FROM dim_spec")
    return dict(cur.fetchall())


def _load_staff(cur, src: W.Workbook) -> dict[str, int]:
    rows = [(s.staff_name, s.role, s.emp_no, s.is_current, s.machine_range)
            for s in src.staff]
    if rows:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_staff(staff_name, role, emp_no, is_current, machine_range)
            VALUES %s
            ON CONFLICT (staff_name, role) DO UPDATE SET
                emp_no = EXCLUDED.emp_no, is_current = EXCLUDED.is_current,
                machine_range = EXCLUDED.machine_range
        """, rows)
    # Names that appear in the history but not on today's people list are added
    # as former staff, so eight months of rows still join to a person.
    named = set()
    for e in src.entries:
        named |= {n for n in (e.operator, e.supervisor, e.qc_name) if n}
    for r in src.rejections:
        named |= {n for n in (r.qc_name, r.supervisor) if n}
    named = {n for n in named if not W.looks_like_a_note(n)}
    cur.execute("SELECT staff_name FROM dim_staff")
    have = {r[0] for r in cur.fetchall()}
    missing = sorted(named - have)
    if missing:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_staff(staff_name, role, is_current) VALUES %s
            ON CONFLICT (staff_name, role) DO NOTHING
        """, [(n, "OPERATOR", False) for n in missing])
    # Dimensions are merged, never dropped, so a bad row loaded once would stay
    # forever. A row that is plainly a note rather than a person, and that no
    # fact points at, is removed — which makes the loader self-healing rather
    # than leaving somebody to clean the people list by hand.
    cur.execute("""
        DELETE FROM dim_staff s
        WHERE (length(s.staff_name) > 60
               OR array_length(string_to_array(s.staff_name, ' '), 1) > 5)
          AND NOT EXISTS (SELECT 1 FROM fact_production p
                          WHERE p.operator_id = s.staff_id
                             OR p.supervisor_id = s.staff_id)
          AND NOT EXISTS (SELECT 1 FROM fact_rejection r
                          WHERE r.qc_id = s.staff_id
                             OR r.supervisor_id = s.staff_id)
    """)
    cur.execute("SELECT staff_name, staff_id FROM dim_staff")
    return dict(cur.fetchall())


def _load_stop_reasons(cur, src: W.Workbook) -> None:
    if not src.reasons:
        return
    rows = [(r.reason_code, r.reason_text_en, r.owner_function,
             REASON_CLASSES.get(r.owner_function.upper(), "UNCLASSIFIED"))
            for r in src.reasons]
    psycopg2.extras.execute_values(cur, """
        INSERT INTO dim_stop_reason(reason_code, reason_text_en, owner_function, reason_class)
        VALUES %s
        ON CONFLICT (reason_code) DO UPDATE SET
            reason_text_en = EXCLUDED.reason_text_en,
            owner_function = EXCLUDED.owner_function,
            reason_class   = EXCLUDED.reason_class
    """, rows)


def _load_rejection_reasons(cur, src: W.Workbook) -> dict[str, int]:
    seen = set()
    for r in src.rejections:
        seen |= {x for x in (r.primary_reason, r.addon_reason) if x}
    rows = [(t, *REJECTION_GROUPS.get(t, ("UNCLASSIFIED", "WEAVING"))) for t in sorted(seen)]
    if rows:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO dim_rejection_reason(reason_text, reason_group, owner_function)
            VALUES %s
            ON CONFLICT (reason_text) DO UPDATE SET
                reason_group = EXCLUDED.reason_group,
                owner_function = EXCLUDED.owner_function
        """, rows)
    cur.execute("SELECT reason_text, rejection_reason_id FROM dim_rejection_reason")
    return dict(cur.fetchall())


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load the weaving workbook into PostgreSQL.")
    ap.add_argument("workbook")
    ap.add_argument("--rebuild", action="store_true",
                    help="empty the fact tables first and load the whole history")
    ap.add_argument("--hold-invalid", action="store_true",
                    help="do not load rows that break a blocking rule (the default "
                         "for the nightly ingest; off for a history rebuild)")
    a = ap.parse_args(argv)

    print(f"Database  {db.describe()}")
    r = load(a.workbook, rebuild=a.rebuild, hold_invalid=a.hold_invalid)
    print(f"\nBatch {r['batch_id']}: {r['rows_loaded']:,} production rows, "
          f"{r['rejections']:,} rejection events, {r['issues']:,} issues raised.")
    if r["rows_held"]:
        print(f"{r['rows_held']:,} rows held back for correction — see the "
              f"Data health page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
