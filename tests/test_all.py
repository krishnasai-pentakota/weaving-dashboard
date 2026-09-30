"""Checks that must pass before anyone trusts a number on the screen.

Run:  python -m tests.test_all

Three kinds of check:
  1. The database reproduces the audited workbook exactly.
  2. Every constraint actually refuses the thing it was written to refuse.
  3. Every query the dashboard makes returns rows and returns them quickly.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import db                                             # noqa: E402

# The figures the forensic rebuild ended on. If any of these move, something
# changed that nobody agreed to.
TRUTH = {
    "rows": 29531,
    "gross": 43_645_372.91,
    "net": 43_166_579.91,
    "target": 69_637_909.50,
    "machines": 70,
    "working_days": 215,
    "first_day": dt.date(2026, 1, 1),
    "last_day": dt.date(2026, 8, 31),
    "machine_days": 12_655,
    "rejection_events": 9_624,
}
TOL = 1.0          # yards

PASS, FAIL = [], []


def check(name, got, want, tol=0.0):
    ok = (abs(float(got) - float(want)) <= tol) if isinstance(want, (int, float)) \
        else (got == want)
    (PASS if ok else FAIL).append((name, got, want))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {got!s:>18}"
          + ("" if ok else f"   expected {want}"))


def check_true(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, ok, True))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {detail}")


# --------------------------------------------------------------------------- #
def totals(cur):
    print("\n1 · THE DATABASE REPRODUCES THE AUDITED WORKBOOK")
    cur.execute("""SELECT count(*), sum(gross_yards), sum(net_yards),
                          sum(target_yards), sum(rejection_yards)
                   FROM fact_production""")
    n, gross, net, target, rej = cur.fetchone()
    check("production rows", n, TRUTH["rows"])
    check("gross yards", gross, TRUTH["gross"], TOL)
    check("net yards", net, TRUTH["net"], TOL)
    check("target yards", target, TRUTH["target"], TOL)
    cur.execute("""SELECT sum(gross_yards) - sum(rejection_yards) - sum(net_yards)
                   FROM fact_production WHERE net_yards IS NOT NULL""")
    check("net = gross - rejection, on every row with a reading",
          cur.fetchone()[0], 0, 0.01)
    # Rejection booked against a loom the production sheet says was not yet in
    # production. Real, small, and a question for the two departments - so it is
    # asserted as a known quantity rather than allowed to drift unnoticed.
    cur.execute("""SELECT count(*), COALESCE(sum(rejection_yards),0)
                   FROM fact_production WHERE net_yards IS NULL AND rejection_yards > 0""")
    orphan_rows, orphan_yards = cur.fetchone()
    check("rejection with no meter reading behind it (yards)",
          orphan_yards, 847.0, 0.01)
    check("rejection with no meter reading behind it (rows)", orphan_rows, 13)

    cur.execute("SELECT count(*) FROM dim_machine WHERE is_commissioned")
    check("commissioned looms", cur.fetchone()[0], TRUTH["machines"])
    cur.execute("SELECT count(*) FROM dim_date WHERE is_working_day")
    check("working days", cur.fetchone()[0], TRUTH["working_days"])
    cur.execute("SELECT min(date_key), max(date_key) FROM fact_production")
    a, b = cur.fetchone()
    check("first day", a, TRUTH["first_day"])
    check("last day", b, TRUTH["last_day"])
    cur.execute("SELECT count(*) FROM (SELECT DISTINCT date_key, machine_id "
                "FROM fact_production) t")
    check("machine-days", cur.fetchone()[0], TRUTH["machine_days"])
    cur.execute("SELECT count(*) FROM fact_rejection")
    check("rejection events", cur.fetchone()[0], TRUTH["rejection_events"])

    # Reference tables. These are small and easy to lose silently: the twelve
    # stop codes were skipped for a whole build because the sheet stored them
    # as text, and nothing complained. They are asserted now.
    cur.execute("SELECT count(*) FROM dim_stop_reason WHERE is_active")
    check("stop reason codes on form FM-ZD-01", cur.fetchone()[0], 12)
    cur.execute("SELECT count(*) FROM dim_rejection_reason")
    check("rejection reasons in the QC vocabulary", cur.fetchone()[0], 12)
    cur.execute("SELECT count(*) FROM dim_rejection_reason WHERE reason_group='UNCLASSIFIED'")
    check("rejection reasons left unclassified", cur.fetchone()[0], 1)  # 'OTHER'
    cur.execute("SELECT count(*) FROM dim_shift")
    check("shifts", cur.fetchone()[0], 4)
    cur.execute("SELECT count(*) FROM dim_staff WHERE role='OPERATOR' AND is_current")
    check("operators currently working", cur.fetchone()[0], 12)
    cur.execute("SELECT count(*) FROM dim_spec WHERE per_yard_weight_g IS NULL")
    n_noweight = cur.fetchone()[0]
    check_true("every specification that was woven has a weight",
               n_noweight == 0,
               f"{n_noweight} without one" if n_noweight else "all priced and weighed")

    # The generated columns must agree with the workbook's own arithmetic.
    cur.execute("""
        SELECT count(*) FROM fact_production
        WHERE gross_yards IS NOT NULL
          AND abs(gross_yards - (COALESCE(rebase_override_m,
                  current_reading_m - previous_reading_m) * lines_running / 0.9144)) > 0.01
    """)
    check("generated yards match the readings", cur.fetchone()[0], 0)

    # Every shift row rolls up into exactly one machine-day.
    cur.execute("""
        SELECT count(*) FROM (
            SELECT date_key, shift_code, machine_id, count(*) c
            FROM fact_production GROUP BY 1,2,3 HAVING count(*) > 1) t""")
    check("no duplicate machine-shift rows", cur.fetchone()[0], 0)

    # Period rollups must equal the fact table, at every grain.
    for grain in ("DAY", "WEEK", "MONTH", "QUARTER"):
        cur.execute("SELECT sum(net_yards) FROM v_period WHERE grain=%s", (grain,))
        check(f"{grain.lower()} rollup ties to the facts",
              cur.fetchone()[0], TRUTH["net"], TOL)


def constraints(cur, conn):
    print("\n2 · THE CONSTRAINTS REFUSE WHAT THEY WERE WRITTEN TO REFUSE")
    cur.execute("SELECT machine_id FROM dim_machine LIMIT 1")
    mid = cur.fetchone()[0]

    cases = [
        ("a backward meter reading with no reset declared",
         "INSERT INTO fact_production(date_key, shift_code, machine_id, lines_running,"
         " previous_reading_m, current_reading_m)"
         " VALUES ('2026-03-02','A',%s,4,9000,8000)", (mid,)),
        ("more lines running than are fitted",
         "INSERT INTO fact_production(date_key, shift_code, machine_id,"
         " lines_fitted, lines_running, previous_reading_m, current_reading_m)"
         " VALUES ('2026-03-03','A',%s,4,9,100,200)", (mid,)),
        ("the same loom, date and shift entered twice",
         "INSERT INTO fact_production(date_key, shift_code, machine_id, lines_running,"
         " previous_reading_m, current_reading_m)"
         " SELECT date_key, shift_code, machine_id, lines_running,"
         " previous_reading_m, current_reading_m FROM fact_production LIMIT 1", ()),
        ("a shift row pointing at a loom that does not exist",
         "INSERT INTO fact_production(date_key, shift_code, machine_id, lines_running,"
         " previous_reading_m, current_reading_m)"
         " VALUES ('2026-03-04','A',999999,4,100,200)", ()),
        ("a negative rejection",
         "INSERT INTO fact_production(date_key, shift_code, machine_id, lines_running,"
         " previous_reading_m, current_reading_m, rejection_yards)"
         " VALUES ('2026-03-05','A',%s,4,100,200,-5)", (mid,)),
        ("a shift code that is not one of the three",
         "INSERT INTO fact_production(date_key, shift_code, machine_id, lines_running,"
         " previous_reading_m, current_reading_m)"
         " VALUES ('2026-03-06','Z',%s,4,100,200)", (mid,)),
        ("a machine code in the wrong shape",
         "INSERT INTO dim_machine(machine_code, line_group, model, peer_group)"
         " VALUES ('WIDGET','L-A','S','x')", ()),
        ("a dyeing code filed as a weaving specification",
         "INSERT INTO dim_spec(weaving_spec) VALUES ('29999-001')", ()),
        ("a stop that restarts before it stopped is allowed only as a midnight cross",
         "INSERT INTO fact_downtime(date_key, shift_code, machine_id, stop_time,"
         " restart_time) VALUES ('2026-03-07','A',%s,'10:00','09:00')", (mid,)),
    ]
    # The last case is legal (night shift crosses midnight); everything else
    # must be refused.
    for i, (name, sql, args) in enumerate(cases):
        must_fail = i < len(cases) - 1
        try:
            cur.execute(sql, args)
            conn.rollback()
            refused = False
        except psycopg2.Error:
            conn.rollback()
            refused = True
        if must_fail:
            check_true(f"refuses {name}", refused,
                       "refused" if refused else "*** ACCEPTED ***")
        else:
            check_true("allows a stop that crosses midnight", not refused,
                       "allowed" if not refused else "*** REFUSED ***")


def queries():
    print("\n3 · EVERY QUERY THE DASHBOARD MAKES")
    import importlib
    # queries.py decorates with streamlit caches; they are transparent off-app.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    Q = importlib.import_module("queries")

    f = Q.Filters(d0=dt.date(2026, 8, 1), d1=dt.date(2026, 8, 31))
    calls = [
        ("meta", lambda: Q.meta()),
        ("options", lambda: Q.options()),
        ("kpis", lambda: Q.kpis(f)),
        ("by_shift", lambda: Q.by_shift(f)),
        ("by_machine", lambda: Q.by_machine(f)),
        ("machine_day_grid", lambda: Q.machine_day_grid(f)),
        ("daily_series", lambda: Q.daily_series(f)),
        ("shift_by_day", lambda: Q.shift_by_day(f)),
        ("period_series MONTH", lambda: Q.period_series("MONTH")),
        ("period_series WEEK", lambda: Q.period_series("WEEK")),
        ("period_series DAY", lambda: Q.period_series("DAY")),
        ("period_series QUARTER", lambda: Q.period_series("QUARTER")),
        ("rejection_by reason", lambda: Q.rejection_by(f, "reason")),
        ("rejection_by qc", lambda: Q.rejection_by(f, "qc")),
        ("rejection_by spec", lambda: Q.rejection_by(f, "spec")),
        ("rejection_matrix", lambda: Q.rejection_matrix(f, "reason", "machine")),
        ("rejection_register_total", lambda: Q.rejection_register_total(f)),
        ("operator_machine_shift", lambda: Q.operator_machine_shift(f)),
        ("span_of_control", lambda: Q.span_of_control(f)),
        ("downtime", lambda: Q.downtime(f)),
        ("changeovers", lambda: Q.changeovers(f)),
        ("consistency", lambda: Q.consistency(f)),
        ("loss_waterfall", lambda: Q.loss_waterfall(f)),
        ("issues", lambda: Q.issues(f)),
        ("issue_summary", lambda: Q.issue_summary(f)),
        ("confidence_matrix", lambda: Q.confidence_matrix(f)),
        ("spec_performance", lambda: Q.spec_performance(f)),
        ("machine_detail", lambda: Q.machine_detail("MA-01", f.d0, f.d1)),
    ]
    slow = []
    for name, fn in calls:
        t0 = time.time()
        try:
            r = fn()
            took = time.time() - t0
            n = len(r) if hasattr(r, "__len__") else 1
            ok = took < 2.0
            if not ok:
                slow.append(name)
            print(f"  {'PASS' if ok else 'SLOW'}  {name:<46} "
                  f"{n:>8,} rows  {took:5.2f}s")
            (PASS if ok else FAIL).append((name, took, "<2s"))
        except Exception as e:
            print(f"  FAIL  {name:<46} {type(e).__name__}: {e}")
            FAIL.append((name, str(e), "no error"))

    # Filters must actually narrow the result.
    f2 = Q.Filters(d0=f.d0, d1=f.d1, machines=("MA-01",))
    a, b = Q.kpis(f), Q.kpis(f2)
    check_true("a machine filter narrows every panel",
               b["net"] < a["net"] and b["machines"] == 1,
               f"{a['machines']} looms -> {b['machines']}")
    f3 = Q.Filters(d0=f.d0, d1=f.d1, shifts=("A",))
    c = Q.kpis(f3)
    check_true("a shift filter narrows every panel", c["net"] < a["net"],
               f"{a['net']:,.0f} -> {c['net']:,.0f} yd")

    # The comparison engine must line each period up with the one before it.
    s = Q.period_series("MONTH")
    ok = (s.prev_net_yards.iloc[1:].notna().all()
          and s.prev_period_key.iloc[0] != s.prev_period_key.iloc[0])  # first is NaN
    check_true("every month is placed beside the one before it",
               s.prev_net_yards.iloc[1:].notna().all(),
               f"{len(s)} months, {int(s.prev_net_yards.notna().sum())} with a comparison")
    check_true("the direction word is set on every comparable period",
               (s.direction.iloc[1:] != "NO COMPARISON").all(),
               ", ".join(s.direction.iloc[1:].unique()))


def main() -> int:
    print(f"Database  {db.describe()}")
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("SET search_path TO weaving, public")
    totals(cur)
    constraints(cur, conn)
    cur.close()
    conn.close()
    queries()

    print(f"\n{'='*74}\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\nFailures:")
        for n, got, want in FAIL:
            print(f"  · {n}: got {got}, expected {want}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
