"""Every question the dashboard asks the database.

No SQL lives in the user interface. Two reasons that matters here: a figure is
defined once so two screens cannot disagree about it, and when the database
moves from the factory PC to a proper server, nothing above this file changes.

Every function takes a Filters object. Filters are applied identically to every
panel, so drilling on one view drills on all of them.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict

import pandas as pd
import streamlit as st

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl import db                                            # noqa: E402

CACHE_TTL = 300          # five minutes: a shift is eight hours long


class NoData(Exception):
    """The database is reachable but holds nothing to show."""


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Filters:
    d0: dt.date
    d1: dt.date
    shifts: tuple = ()
    machines: tuple = ()
    line_groups: tuple = ()
    peer_groups: tuple = ()
    specs: tuple = ()
    operators: tuple = ()
    supervisors: tuple = ()
    measured_only: bool = False
    real_shifts_only: bool = False
    commissioned_only: bool = True

    def where(self, alias: str = "f") -> tuple[str, list]:
        """Build the WHERE clause and its parameters."""
        sql = [f"{alias}.date_key BETWEEN %s AND %s"]
        args: list = [self.d0, self.d1]
        for col, val in (("shift_code", self.shifts),
                         ("machine_code", self.machines),
                         ("line_group", self.line_groups),
                         ("peer_group", self.peer_groups),
                         ("weaving_spec", self.specs),
                         ("operator_name", self.operators),
                         ("supervisor_name", self.supervisors)):
            if val:
                sql.append(f"{alias}.{col} = ANY(%s)")
                args.append(list(val))
        if self.measured_only:
            sql.append(f"{alias}.confidence = 'MEASURED'")
        if self.real_shifts_only:
            sql.append(f"{alias}.is_real_shift")
        if self.commissioned_only:
            sql.append(f"{alias}.is_commissioned")
        return " AND ".join(sql), args

    def key(self):
        return tuple(sorted(asdict(self).items()))


# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def _engine():
    """One pooled engine per session.

    pool_pre_ping matters here: the dashboard runs on a desk on the department
    LAN and the link to the factory PC does drop. Without it the first query
    after a drop fails with a dead socket; with it the pool quietly replaces
    the connection and the user never sees it.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    d = db.dsn()
    # A host that is a path is a local unix socket, which belongs in the query
    # string rather than the authority part of the URL.
    if str(d["host"]).startswith("/"):
        url = URL.create("postgresql+psycopg2", username=d["user"],
                         password=d["password"] or None, database=d["dbname"],
                         query={"host": d["host"], "port": str(d["port"])})
    else:
        url = URL.create("postgresql+psycopg2", username=d["user"],
                         password=d["password"] or None, host=d["host"],
                         port=d["port"], database=d["dbname"])
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800,
                         connect_args={"options": f"-csearch_path={db.SCHEMA},public"})


def _df(sql: str, args=None) -> pd.DataFrame:
    from sqlalchemy import text
    eng = _engine()
    if args:
        # psycopg2 %s placeholders, bound positionally
        named = {f"p{i}": v for i, v in enumerate(args)}
        i = iter(range(len(args)))
        bound = sql.replace("%s", "__P__")
        for k in named:
            bound = bound.replace("__P__", f":{k}", 1)
        with eng.connect() as c:
            return pd.read_sql_query(text(bound), c, params=named)
    with eng.connect() as c:
        return pd.read_sql_query(text(sql), c)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _cached(sql: str, args: tuple = ()) -> pd.DataFrame:
    return _df(sql, list(args) if args else None)


# --------------------------------------------------------------------------- #
#  Metadata and pick lists
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def meta() -> dict:
    d = _df("""
        SELECT (SELECT count(*) FROM fact_production)                     AS rows,
               (SELECT count(*) FROM dim_machine WHERE is_commissioned)   AS machines,
               (SELECT min(date_key) FROM fact_production)                AS d0,
               (SELECT max(date_key) FROM fact_production)                AS d1,
               (SELECT count(*) FROM dim_date WHERE is_working_day)       AS working_days,
               (SELECT count(*) FROM fact_downtime)                       AS downtime_rows,
               (SELECT count(*) FROM data_issue WHERE status='OPEN')      AS open_issues,
               (SELECT max(finished_at) FROM load_batch WHERE status<>'FAILED') AS last_load
    """)
    if d.empty or d.at[0, "rows"] == 0:
        raise NoData("The database is empty. Run the loader before starting the dashboard.")
    return d.iloc[0].to_dict()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def options() -> dict:
    return {
        "machines":    _df("SELECT machine_code FROM dim_machine WHERE is_commissioned "
                           "ORDER BY 1")["machine_code"].tolist(),
        "line_groups": _df("SELECT DISTINCT line_group FROM dim_machine ORDER BY 1")
                       ["line_group"].tolist(),
        "peers":       _df("SELECT DISTINCT peer_group FROM dim_machine ORDER BY 1")
                       ["peer_group"].tolist(),
        "specs":       _df("SELECT weaving_spec FROM dim_spec WHERE in_production "
                           "ORDER BY 1")["weaving_spec"].tolist(),
        "operators":   _df("SELECT staff_name FROM dim_staff WHERE role='OPERATOR' "
                           "ORDER BY is_current DESC, staff_name")["staff_name"].tolist(),
        "supervisors": _df("SELECT staff_name FROM dim_staff WHERE role='SUPERVISOR' "
                           "ORDER BY is_current DESC, staff_name")["staff_name"].tolist(),
        "qc":          _df("SELECT staff_name FROM dim_staff WHERE role='QC' "
                           "ORDER BY is_current DESC, staff_name")["staff_name"].tolist(),
        "stop_reasons": _df("SELECT reason_code, reason_text_en FROM dim_stop_reason "
                            "WHERE is_active ORDER BY reason_code"),
    }


# --------------------------------------------------------------------------- #
#  Periods — the comparison engine
# --------------------------------------------------------------------------- #
GRAINS = ("DAY", "WEEK", "MONTH", "QUARTER")

# What the screen calls the comparison, in words a reader does not have to
# decode. This is the whole point of the grain selector.
COMPARE_WORDS = {
    "DAY":     ("today", "the day before"),
    "WEEK":    ("this week", "last week"),
    "MONTH":   ("this month", "last month"),
    "QUARTER": ("this quarter", "last quarter"),
}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def periods(grain: str) -> pd.DataFrame:
    return _df("""
        SELECT period_key, period_label, period_index, period_start, period_end,
               working_days
        FROM v_period WHERE grain = %s ORDER BY period_index
    """, [grain])


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def period_series(grain: str) -> pd.DataFrame:
    """The full trend for a grain, each period beside the one before it."""
    return _df("""
        SELECT * FROM v_period_compare WHERE grain = %s ORDER BY period_index
    """, [grain])


def period_bounds(grain: str, period_key: str) -> tuple[dt.date, dt.date, int]:
    p = periods(grain)
    row = p.loc[p.period_key == period_key]
    if row.empty:
        raise NoData(f"No {grain.lower()} called {period_key}.")
    r = row.iloc[0]
    return r.period_start, r.period_end, int(r.working_days)


def previous_period(grain: str, period_key: str):
    """The previous period that has data, not the previous calendar slot.

    The shed does not work every day: Sunday is the weekly holiday and a
    festival moves it, so the day before the 31st may well be the 29th. Taking
    period_index - 1 would leave those comparisons blank, which is exactly the
    comparison somebody standing at the screen wants most.
    """
    p = periods(grain).sort_values("period_index").reset_index(drop=True)
    hit = p.index[p.period_key == period_key]
    if len(hit) == 0 or hit[0] == 0:
        return None
    return p.at[hit[0] - 1, "period_key"]


# --------------------------------------------------------------------------- #
#  Headline numbers
# --------------------------------------------------------------------------- #
def kpis(f: Filters) -> dict:
    where, args = f.where()
    d = _cached(f"""
        SELECT
            COALESCE(SUM(gross_yards),0)      AS gross,
            COALESCE(SUM(rejection_yards),0)  AS rejection,
            COALESCE(SUM(net_yards),0)        AS net,
            SUM(target_yards)                 AS target,
            COALESCE(SUM(net_kgs),0)          AS kgs,
            COALESCE(SUM(net_value),0)        AS value,
            COUNT(DISTINCT date_key)          AS days,
            COUNT(DISTINCT machine_id)        AS machines,
            COUNT(DISTINCT machine_id) FILTER (WHERE produced) AS active,
            COUNT(*)                          AS rows,
            COUNT(*) FILTER (WHERE confidence='MEASURED') AS measured,
            COALESCE(SUM(lines_running),0)    AS line_shifts
        FROM v_fact f WHERE {where}
    """, tuple(args)).iloc[0].to_dict()

    d = {k: (float(v) if v is not None and k not in ("days", "machines", "active",
                                                     "rows", "measured") else v)
         for k, v in d.items()}
    tgt = d["target"]
    d["efficiency"] = (d["net"] / tgt) if tgt else None
    d["achieved"] = d["efficiency"]
    d["gap"] = (tgt - d["net"]) if tgt else None
    d["rejection_rate"] = (d["rejection"] / d["gross"]) if d["gross"] else 0.0
    d["availability"] = (d["active"] / d["machines"]) if d["machines"] else 0.0
    d["trust"] = (d["measured"] / d["rows"]) if d["rows"] else 0.0
    d["per_day"] = (d["net"] / d["days"]) if d["days"] else 0.0
    d["yards_per_line"] = (d["net"] / d["line_shifts"]) if d["line_shifts"] else None
    return d


def by_shift(f: Filters) -> pd.DataFrame:
    where, args = f.where()
    return _cached(f"""
        SELECT f.shift_code, f.shift_name_en, f.shift_sort,
               SUM(f.gross_yards) gross, SUM(f.rejection_yards) rejection,
               SUM(f.net_yards) net, SUM(f.target_yards) target,
               SUM(f.lines_running) line_shifts,
               COUNT(DISTINCT f.machine_id) machines,
               COUNT(DISTINCT f.date_key) days,
               COUNT(DISTINCT f.operator_id) operators,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency,
               CASE WHEN SUM(f.gross_yards)>0
                    THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END rejection_rate,
               CASE WHEN SUM(f.lines_running)>0
                    THEN SUM(f.net_yards)/SUM(f.lines_running) END yards_per_line
        FROM v_fact f WHERE {where}
        GROUP BY 1,2,3 ORDER BY 3
    """, tuple(args))


def by_machine(f: Filters) -> pd.DataFrame:
    where, args = f.where()
    return _cached(f"""
        SELECT f.machine_code, f.machine_id, f.line_group, f.model, f.peer_group,
               MAX(f.lines_fitted) lines_fitted,
               SUM(f.gross_yards) gross, SUM(f.rejection_yards) rejection,
               SUM(f.net_yards) net, SUM(f.target_yards) target,
               GREATEST(SUM(f.target_yards)-SUM(f.net_yards),0) gap,
               COUNT(DISTINCT f.date_key) days_seen,
               COUNT(DISTINCT f.date_key) FILTER (WHERE f.produced) days_producing,
               SUM(f.lines_running) line_shifts,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency,
               CASE WHEN SUM(f.gross_yards)>0
                    THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END rejection_rate,
               CASE WHEN SUM(f.lines_running)>0
                    THEN SUM(f.net_yards)/SUM(f.lines_running) END yards_per_line,
               STRING_AGG(DISTINCT f.operator_name, ', ') operators
        FROM v_fact f WHERE {where}
        GROUP BY 1,2,3,4,5
    """, tuple(args))


def machine_day_grid(f: Filters) -> pd.DataFrame:
    """Machine by date, for the heat-map."""
    where, args = f.where()
    return _cached(f"""
        SELECT f.machine_code, f.date_key,
               SUM(f.net_yards) net, SUM(f.target_yards) target,
               SUM(f.rejection_yards) rejection,
               MAX(f.lines_running) lines_running,
               BOOL_OR(f.produced) produced,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency,
               STRING_AGG(DISTINCT f.operator_name, ', ') operators,
               STRING_AGG(DISTINCT f.machine_status, ', ') statuses
        FROM v_fact f WHERE {where}
        GROUP BY 1,2
    """, tuple(args))


def daily_series(f: Filters) -> pd.DataFrame:
    where, args = f.where()
    return _cached(f"""
        SELECT f.date_key,
               SUM(f.net_yards) net, SUM(f.target_yards) target,
               SUM(f.gross_yards) gross, SUM(f.rejection_yards) rejection,
               COUNT(DISTINCT f.machine_id) FILTER (WHERE f.produced) active,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency
        FROM v_fact f WHERE {where}
        GROUP BY 1 ORDER BY 1
    """, tuple(args))


def shift_by_day(f: Filters) -> pd.DataFrame:
    where, args = f.where()
    return _cached(f"""
        SELECT f.date_key, f.shift_code,
               SUM(f.net_yards) net, SUM(f.target_yards) target,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency
        FROM v_fact f WHERE {where} AND f.is_real_shift
        GROUP BY 1,2 ORDER BY 1,2
    """, tuple(args))


# --------------------------------------------------------------------------- #
#  Quality
# --------------------------------------------------------------------------- #
def rejection_by(f: Filters, dimension: str) -> pd.DataFrame:
    col = {"reason": "primary_reason", "group": "reason_group", "qc": "qc_name",
           "machine": "machine_code", "spec": "weaving_spec",
           "shift": "shift_code"}[dimension]
    sql = ["r.date_key BETWEEN %s AND %s"]
    args: list = [f.d0, f.d1]
    if f.machines:
        sql.append("r.machine_code = ANY(%s)"); args.append(list(f.machines))
    if f.specs:
        sql.append("r.weaving_spec = ANY(%s)"); args.append(list(f.specs))
    if f.shifts:
        sql.append("r.shift_code = ANY(%s)"); args.append(list(f.shifts))
    if f.line_groups:
        sql.append("r.line_group = ANY(%s)"); args.append(list(f.line_groups))
    return _cached(f"""
        SELECT COALESCE(r.{col}::text,'NOT STATED') AS k,
               COUNT(*) events, SUM(r.rejection_yards) yards,
               SUM(r.rejection_kgs) kgs,
               COUNT(DISTINCT r.machine_id) machines
        FROM v_rejection_detail r WHERE {' AND '.join(sql)}
        GROUP BY 1 ORDER BY yards DESC
    """, tuple(args))


def rejection_matrix(f: Filters, rows: str, cols: str) -> pd.DataFrame:
    m = {"reason": "primary_reason", "qc": "qc_name", "machine": "machine_code",
         "spec": "weaving_spec", "shift": "shift_code", "group": "reason_group"}
    return _cached(f"""
        SELECT COALESCE(r.{m[rows]}::text,'NOT STATED') AS row_k,
               COALESCE(r.{m[cols]}::text,'NOT STATED') AS col_k,
               SUM(r.rejection_yards) yards, COUNT(*) events
        FROM v_rejection_detail r WHERE r.date_key BETWEEN %s AND %s
        GROUP BY 1,2
    """, (f.d0, f.d1))


def rejection_register_total(f: Filters) -> dict:
    d = _cached("""
        SELECT SUM(rejection_yards) total,
               SUM(rejection_yards) FILTER (WHERE tied_to_production) tied,
               COUNT(*) events
        FROM v_rejection_detail WHERE date_key BETWEEN %s AND %s
    """, (f.d0, f.d1))
    return d.iloc[0].to_dict() if not d.empty else {}


# --------------------------------------------------------------------------- #
#  People, staffing and downtime
# --------------------------------------------------------------------------- #
def operator_machine_shift(f: Filters) -> pd.DataFrame:
    where, args = f.where()
    return _cached(f"""
        SELECT f.operator_name, f.shift_code, f.machine_code, f.peer_group,
               COUNT(*) rows, SUM(f.net_yards) net, SUM(f.target_yards) target,
               SUM(f.rejection_yards) rejection,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency,
               CASE WHEN SUM(f.gross_yards)>0
                    THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END rejection_rate
        FROM v_fact f
        WHERE {where} AND f.operator_name IS NOT NULL AND f.is_real_shift
        GROUP BY 1,2,3,4
    """, tuple(args))


def span_of_control(f: Filters) -> pd.DataFrame:
    """One row per operator, per shift, per day: how many looms, how they did."""
    return _cached("""
        SELECT * FROM v_span_of_control
        WHERE date_key BETWEEN %s AND %s AND efficiency IS NOT NULL
    """, (f.d0, f.d1))


def downtime(f: Filters) -> pd.DataFrame:
    return _cached("""
        SELECT * FROM v_downtime_detail
        WHERE date_key BETWEEN %s AND %s ORDER BY date_key DESC, stop_time DESC
    """, (f.d0, f.d1))


def changeovers(f: Filters) -> pd.DataFrame:
    return _cached("""
        SELECT * FROM v_changeover_cost
        WHERE event_date BETWEEN %s AND %s ORDER BY cost_yards DESC NULLS LAST
    """, (f.d0, f.d1))


def consistency(f: Filters) -> pd.DataFrame:
    return _cached("""
        SELECT c.*, m.line_group, m.model
        FROM v_machine_consistency c
        JOIN dim_machine m USING (machine_id)
        WHERE c.days >= 5
    """)


# --------------------------------------------------------------------------- #
#  Losses, health and confidence
# --------------------------------------------------------------------------- #
def loss_waterfall(f: Filters) -> pd.DataFrame:
    return _cached("SELECT * FROM f_loss_waterfall(%s,%s) ORDER BY step_order",
                   (f.d0, f.d1))


def issues(f: Filters, severity: tuple = ()) -> pd.DataFrame:
    sql = ["i.status='OPEN'", "(i.date_key IS NULL OR i.date_key BETWEEN %s AND %s)"]
    args: list = [f.d0, f.d1]
    if severity:
        sql.append("i.severity = ANY(%s)"); args.append(list(severity))
    return _cached(f"""
        SELECT i.severity, i.issue_code, i.date_key, m.machine_code, i.shift_code,
               i.description
        FROM data_issue i LEFT JOIN dim_machine m USING (machine_id)
        WHERE {' AND '.join(sql)}
        ORDER BY CASE i.severity WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
                 i.date_key DESC
    """, tuple(args))


def issue_summary(f: Filters) -> pd.DataFrame:
    return _cached("""
        SELECT i.issue_code, i.severity, COUNT(*) n,
               COUNT(DISTINCT i.machine_id) machines,
               MIN(i.date_key) first_seen, MAX(i.date_key) last_seen
        FROM data_issue i
        WHERE i.status='OPEN' AND (i.date_key IS NULL OR i.date_key BETWEEN %s AND %s)
        GROUP BY 1,2
        ORDER BY CASE i.severity WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
                 n DESC
    """, (f.d0, f.d1))


def confidence_matrix(_f: Filters | None = None) -> pd.DataFrame:
    """Deliberately not filtered by the chosen period.

    This panel answers "how much of the whole rebuild can I stand behind",
    which is a question about all eight months at once. Narrowing it to the
    selected month would leave a single column and hide the answer.
    """
    return _cached("SELECT * FROM v_confidence_matrix ORDER BY machine_code, month_key")


def spec_performance(f: Filters) -> pd.DataFrame:
    where, args = f.where()
    return _cached(f"""
        SELECT f.weaving_spec, f.dyeing_spec,
               COUNT(DISTINCT f.machine_id) machines,
               COUNT(DISTINCT f.date_key) days,
               SUM(f.gross_yards) gross, SUM(f.rejection_yards) rejection,
               SUM(f.net_yards) net, SUM(f.net_kgs) kgs, SUM(f.net_value) value,
               CASE WHEN SUM(f.gross_yards)>0
                    THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END rejection_rate,
               CASE WHEN SUM(f.target_yards)>0
                    THEN SUM(f.net_yards)/SUM(f.target_yards) END efficiency
        FROM v_fact f WHERE {where} AND f.weaving_spec IS NOT NULL
        GROUP BY 1,2
    """, tuple(args))


def machine_detail(machine_code: str, d0, d1) -> pd.DataFrame:
    return _cached("""
        SELECT f.date_key, f.shift_code, f.weaving_spec, f.lines_fitted,
               f.lines_running, f.previous_reading_m, f.current_reading_m,
               f.gross_yards, f.rejection_yards, f.net_yards, f.target_yards,
               f.efficiency, f.machine_status, f.event, f.operator_name,
               f.supervisor_name, f.confidence, f.remarks
        FROM v_fact f
        WHERE f.machine_code = %s AND f.date_key BETWEEN %s AND %s
        ORDER BY f.date_key DESC, f.shift_code
    """, (machine_code, d0, d1))


def refresh() -> None:
    _cached.clear()
    meta.clear()
    options.clear()
    periods.clear()
    period_series.clear()
