-- ===========================================================================
--  WEAVING — ANALYTICAL VIEWS
--
--  The application layer holds no arithmetic. Every number the dashboard
--  shows is defined once, here, so a figure quoted on the shift screen and
--  the same figure quoted in the MD's monthly view cannot disagree.
--
--  The period views are the comparison engine. Each carries period_index,
--  an integer that increases by one per period, so "the period before this
--  one" is a self-join on period_index - 1 and needs no date arithmetic and
--  no special case at a year boundary.
-- ===========================================================================
SET search_path TO weaving, public;

-- ---------------------------------------------------------------------------
--  v_fact — the enriched production row. Everything else builds on this.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fact AS
SELECT
    p.production_id,
    p.date_key,
    d.month_key, d.week_key, d.quarter_key,
    d.month_index, d.week_index, d.quarter_index,
    d.iso_week, d.year, d.quarter, d.is_working_day,
    p.shift_code,
    s.shift_name_en, s.sort_order AS shift_sort, s.is_real_shift,
    m.machine_id, m.machine_code, m.line_group, m.model, m.peer_group,
    m.is_commissioned,
    sp.spec_id, sp.weaving_spec, sp.dyeing_spec,
    sp.per_yard_weight_g, sp.per_yard_price,
    p.lines_fitted, p.lines_running, p.single_line_share,
    p.machine_status, p.event, p.remarks,
    p.previous_reading_m, p.current_reading_m, p.rebase_override_m,
    p.difference_m, p.total_m,
    p.gross_yards, p.rejection_yards, p.net_yards, p.target_yards,
    CASE WHEN p.target_yards > 0 THEN p.net_yards / p.target_yards END AS efficiency,
    CASE WHEN p.gross_yards  > 0 THEN p.rejection_yards / p.gross_yards END AS rejection_rate,
    p.net_yards * sp.per_yard_weight_g / 1000.0 AS net_kgs,
    p.net_yards * sp.per_yard_price             AS net_value,
    -- yards per fitted line: the only efficiency-like measure that is
    -- comparable across machines when a target is missing or disputed
    CASE WHEN p.lines_running > 0 THEN p.net_yards / p.lines_running END AS yards_per_line,
    p.operator_id,   o.staff_name AS operator_name,
    p.supervisor_id, v.staff_name AS supervisor_name,
    p.confidence, p.confidence_why,
    (p.machine_status = 'RUNNING' AND COALESCE(p.gross_yards,0) > 0) AS produced,
    p.source_note
FROM fact_production p
JOIN dim_date    d  ON d.date_key    = p.date_key
JOIN dim_shift   s  ON s.shift_code  = p.shift_code
JOIN dim_machine m  ON m.machine_id  = p.machine_id
LEFT JOIN dim_spec  sp ON sp.spec_id = p.spec_id
LEFT JOIN dim_staff o  ON o.staff_id = p.operator_id
LEFT JOIN dim_staff v  ON v.staff_id = p.supervisor_id;


-- ---------------------------------------------------------------------------
--  v_machine_day — one row per machine per date, all shifts folded together.
--  This is what the machine heat-map reads, and what "was this loom running
--  yesterday" is answered from.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_machine_day AS
SELECT
    f.date_key, f.month_key, f.week_key, f.quarter_key,
    f.machine_id, f.machine_code, f.line_group, f.model, f.peer_group,
    MAX(f.lines_fitted)                      AS lines_fitted,
    MAX(f.lines_running)                     AS lines_running,
    SUM(f.gross_yards)                       AS gross_yards,
    SUM(f.rejection_yards)                   AS rejection_yards,
    SUM(f.net_yards)                         AS net_yards,
    SUM(f.target_yards)                      AS target_yards,
    CASE WHEN SUM(f.target_yards) > 0
         THEN SUM(f.net_yards) / SUM(f.target_yards) END AS efficiency,
    CASE WHEN SUM(f.gross_yards) > 0
         THEN SUM(f.rejection_yards) / SUM(f.gross_yards) END AS rejection_rate,
    BOOL_OR(f.produced)                      AS produced,
    COUNT(*) FILTER (WHERE f.machine_status = 'RUNNING')     AS shifts_running,
    COUNT(*) FILTER (WHERE f.machine_status = 'CHANGEOVER')  AS shifts_changeover,
    COUNT(*) FILTER (WHERE f.machine_status IN ('STOPPED','IDLE')) AS shifts_stopped,
    COUNT(*)                                 AS shift_rows,
    MIN(f.confidence)                        AS confidence_worst,
    STRING_AGG(DISTINCT f.weaving_spec, ', ') AS specs,
    STRING_AGG(DISTINCT f.operator_name, ', ') AS operators
FROM v_fact f
GROUP BY 1,2,3,4,5,6,7,8,9;


-- ---------------------------------------------------------------------------
--  PERIOD ROLLUPS
--
--  One view per grain, then a UNION view so the app can ask for any grain
--  with the same columns. period_index makes previous-period lookup trivial.
--
--  Working days are counted, and a per-working-day figure is carried on every
--  row, because the plant's holidays move: a month with 24 working days and a
--  month with 26 compare honestly only per day.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_period AS
SELECT
    g.grain, g.period_key, g.period_index,
    CASE g.grain
        WHEN 'DAY'     THEN TO_CHAR(MIN(f.date_key),'DD Mon YYYY')
        WHEN 'WEEK'    THEN 'Week ' || MIN(f.iso_week) || ', ' || MIN(f.year)
        WHEN 'MONTH'   THEN TO_CHAR(MIN(f.date_key),'Mon YYYY')
        ELSE                'Q' || MIN(f.quarter) || ' ' || MIN(f.year)
    END                                      AS period_label,
    MIN(f.date_key)                          AS period_start,
    MAX(f.date_key)                          AS period_end,
    COUNT(DISTINCT f.date_key)               AS working_days,
    SUM(f.gross_yards)                       AS gross_yards,
    SUM(f.rejection_yards)                   AS rejection_yards,
    SUM(f.net_yards)                         AS net_yards,
    SUM(f.target_yards)                      AS target_yards,
    SUM(f.net_kgs)                           AS net_kgs,
    SUM(f.net_value)                         AS net_value,
    COUNT(DISTINCT f.machine_id)             AS machines_seen,
    COUNT(DISTINCT f.machine_id) FILTER (WHERE f.produced) AS machines_producing,
    SUM(f.lines_running)                     AS line_shifts,
    COUNT(*)                                 AS shift_rows,
    COUNT(*) FILTER (WHERE f.confidence = 'MEASURED') AS measured_rows
FROM v_fact f
CROSS JOIN LATERAL (VALUES
        ('DAY',     f.date_key::TEXT, (f.date_key - DATE '2020-01-01')),
        ('WEEK',    f.week_key,       f.week_index),
        ('MONTH',   f.month_key,      f.month_index),
        ('QUARTER', f.quarter_key,    f.quarter_index)
    ) AS g(grain, period_key, period_index)
GROUP BY 1,2,3;


-- ---------------------------------------------------------------------------
--  v_period_compare — every period placed next to the one before it.
--
--  This single view answers the whole "today against yesterday, this week
--  against last week, this month against last month" requirement, at any
--  grain, including the honest per-working-day comparison and a direction
--  word the screen can print without doing its own arithmetic.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_period_compare AS
WITH p AS (
    SELECT *,
        CASE WHEN working_days > 0 THEN net_yards / working_days END AS net_per_day,
        CASE WHEN target_yards  > 0 THEN net_yards / target_yards END AS efficiency,
        CASE WHEN gross_yards   > 0 THEN rejection_yards / gross_yards END AS rejection_rate,
        -- The previous period that actually exists, not the previous slot on
        -- the calendar. Sunday is the weekly holiday and a festival moves it,
        -- so the day before the 31st may be the 29th; a week the shed was shut
        -- has no row here at all. LAG steps over the gaps.
        LAG(period_index) OVER (PARTITION BY grain ORDER BY period_index) AS prev_index
    FROM v_period
)
SELECT
    c.grain, c.period_key, c.period_index, c.period_label,
    c.period_start, c.period_end, c.working_days,
    c.gross_yards, c.rejection_yards, c.net_yards, c.target_yards,
    c.net_kgs, c.net_value,
    c.machines_seen, c.machines_producing, c.line_shifts,
    c.shift_rows, c.measured_rows,
    c.net_per_day, c.efficiency, c.rejection_rate,

    p.period_key    AS prev_period_key,
    p.period_label  AS prev_period_label,
    p.working_days  AS prev_working_days,
    p.net_yards     AS prev_net_yards,
    p.net_per_day   AS prev_net_per_day,
    p.efficiency    AS prev_efficiency,
    p.rejection_rate AS prev_rejection_rate,
    p.machines_producing AS prev_machines_producing,

    c.net_yards  - p.net_yards   AS d_net_yards,
    c.net_per_day - p.net_per_day AS d_net_per_day,
    c.efficiency - p.efficiency  AS d_efficiency,
    c.rejection_rate - p.rejection_rate AS d_rejection_rate,

    CASE WHEN p.net_yards   > 0 THEN (c.net_yards   - p.net_yards)   / p.net_yards   END AS pc_net_yards,
    CASE WHEN p.net_per_day > 0 THEN (c.net_per_day - p.net_per_day) / p.net_per_day END AS pc_net_per_day,

    -- The word the screen prints. Judged on yards per working day, not on the
    -- raw total, so a short month is not mistaken for a bad month.
    CASE
        WHEN p.net_per_day IS NULL THEN 'NO COMPARISON'
        WHEN (c.net_per_day - p.net_per_day) / NULLIF(p.net_per_day,0) >  0.02 THEN 'IMPROVING'
        WHEN (c.net_per_day - p.net_per_day) / NULLIF(p.net_per_day,0) < -0.02 THEN 'DEGRADING'
        ELSE 'HOLDING'
    END AS direction,
    CASE WHEN c.shift_rows > 0
         THEN c.measured_rows::NUMERIC / c.shift_rows END AS trust
FROM p c
LEFT JOIN p ON p.grain = c.grain AND p.period_index = c.prev_index;


-- ---------------------------------------------------------------------------
--  v_shift_period — shift performance at every grain. "Which shift has the
--  lowest efficiency" is a single read of this view.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_shift_period AS
SELECT g.grain, g.period_key, g.period_index, f.shift_code, f.shift_name_en, f.shift_sort,
       COUNT(DISTINCT f.date_key)    AS working_days,
       SUM(f.gross_yards)            AS gross_yards,
       SUM(f.rejection_yards)        AS rejection_yards,
       SUM(f.net_yards)              AS net_yards,
       SUM(f.target_yards)           AS target_yards,
       SUM(f.lines_running)          AS line_shifts,
       COUNT(DISTINCT f.machine_id)  AS machines,
       CASE WHEN SUM(f.target_yards) > 0
            THEN SUM(f.net_yards)/SUM(f.target_yards) END AS efficiency,
       CASE WHEN SUM(f.gross_yards)  > 0
            THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END AS rejection_rate,
       CASE WHEN SUM(f.lines_running) > 0
            THEN SUM(f.net_yards)/SUM(f.lines_running) END AS yards_per_line
FROM v_fact f
CROSS JOIN LATERAL (VALUES
        ('DAY',     f.date_key::TEXT, (f.date_key - DATE '2020-01-01')),
        ('WEEK',    f.week_key,       f.week_index),
        ('MONTH',   f.month_key,      f.month_index),
        ('QUARTER', f.quarter_key,    f.quarter_index)
    ) AS g(grain, period_key, period_index)
GROUP BY 1,2,3,4,5,6;


-- ---------------------------------------------------------------------------
--  v_machine_period — machine performance at every grain, with the loss to
--  target that ranks "which machines are worst".
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_machine_period AS
SELECT g.grain, g.period_key, g.period_index,
       f.machine_id, f.machine_code, f.line_group, f.model, f.peer_group,
       COUNT(DISTINCT f.date_key)                              AS days_seen,
       COUNT(DISTINCT f.date_key) FILTER (WHERE f.produced)    AS days_producing,
       SUM(f.gross_yards)      AS gross_yards,
       SUM(f.rejection_yards)  AS rejection_yards,
       SUM(f.net_yards)        AS net_yards,
       SUM(f.target_yards)     AS target_yards,
       GREATEST(SUM(f.target_yards) - SUM(f.net_yards), 0) AS gap_yards,
       CASE WHEN SUM(f.target_yards) > 0
            THEN SUM(f.net_yards)/SUM(f.target_yards) END AS efficiency,
       CASE WHEN SUM(f.gross_yards)  > 0
            THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END AS rejection_rate,
       CASE WHEN SUM(f.lines_running) > 0
            THEN SUM(f.net_yards)/SUM(f.lines_running) END AS yards_per_line,
       MAX(f.lines_fitted)     AS lines_fitted
FROM v_fact f
CROSS JOIN LATERAL (VALUES
        ('DAY',     f.date_key::TEXT, (f.date_key - DATE '2020-01-01')),
        ('WEEK',    f.week_key,       f.week_index),
        ('MONTH',   f.month_key,      f.month_index),
        ('QUARTER', f.quarter_key,    f.quarter_index)
    ) AS g(grain, period_key, period_index)
GROUP BY 1,2,3,4,5,6,7,8;


-- ---------------------------------------------------------------------------
--  v_machine_consistency — a machine that averages 70% by running at 95% and
--  then 45% is a different problem from one that sits at 70% every day. The
--  first is a breakdown problem, the second a setting or target problem.
--  Coefficient of variation separates them.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_machine_consistency AS
SELECT machine_id, machine_code, peer_group,
       COUNT(*)                          AS days,
       AVG(efficiency)                   AS mean_efficiency,
       STDDEV_SAMP(efficiency)           AS sd_efficiency,
       CASE WHEN AVG(efficiency) > 0
            THEN STDDEV_SAMP(efficiency)/AVG(efficiency) END AS cv,
       MIN(efficiency) AS worst_day, MAX(efficiency) AS best_day,
       COUNT(*) FILTER (WHERE efficiency < 0.60) AS days_below_60,
       -- the direction of the trend across the window, in efficiency points
       -- per day: positive is a loom getting better, negative one sliding
       REGR_SLOPE(efficiency, EXTRACT(EPOCH FROM date_key)/86400) AS slope_per_day
FROM v_machine_day
WHERE efficiency IS NOT NULL
GROUP BY 1,2,3;


-- ---------------------------------------------------------------------------
--  v_operator_machine_shift — who ran what, where, and how it went. This is
--  the view that makes a training gap visible: the same operator, strong on
--  one loom and weak on another, is a skill problem; weak everywhere on one
--  shift is a staffing or supervision problem.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_operator_machine_shift AS
SELECT f.operator_id, f.operator_name, f.shift_code, f.shift_name_en,
       f.machine_id, f.machine_code, f.peer_group,
       f.month_key,
       COUNT(*)                 AS shift_rows,
       SUM(f.net_yards)         AS net_yards,
       SUM(f.target_yards)      AS target_yards,
       SUM(f.rejection_yards)   AS rejection_yards,
       CASE WHEN SUM(f.target_yards) > 0
            THEN SUM(f.net_yards)/SUM(f.target_yards) END AS efficiency,
       CASE WHEN SUM(f.gross_yards) > 0
            THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END AS rejection_rate
FROM v_fact f
WHERE f.operator_id IS NOT NULL
GROUP BY 1,2,3,4,5,6,7,8;


-- ---------------------------------------------------------------------------
--  v_span_of_control — the evidence behind the staffing question.
--
--  One operator covers a range of looms on a shift. This view measures, for
--  every operator-shift-day actually worked, how many looms that person was
--  carrying and what those looms achieved. If efficiency falls as the number
--  of looms per operator rises, the relationship is real and the cost of
--  being short-handed can be quoted in yards instead of argued about.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_span_of_control AS
SELECT f.date_key, f.month_key, f.shift_code, f.operator_id, f.operator_name,
       COUNT(DISTINCT f.machine_id)                            AS machines_covered,
       COUNT(DISTINCT f.machine_id) FILTER (WHERE f.produced)  AS machines_producing,
       SUM(f.lines_running)     AS lines_covered,
       SUM(f.net_yards)         AS net_yards,
       SUM(f.target_yards)      AS target_yards,
       CASE WHEN SUM(f.target_yards) > 0
            THEN SUM(f.net_yards)/SUM(f.target_yards) END AS efficiency,
       CASE WHEN SUM(f.gross_yards) > 0
            THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END AS rejection_rate
FROM v_fact f
WHERE f.operator_id IS NOT NULL AND f.is_real_shift
GROUP BY 1,2,3,4,5;


-- ---------------------------------------------------------------------------
--  v_changeover_cost — what a spec change actually costs.
--
--  The forensic audit measured it as the shortfall on the event day plus the
--  two days of wind-down before it, against the machine's own normal output.
--  Normal is that machine's median daily net yards over the surrounding
--  month, which is robust to the very days being measured.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_changeover_cost AS
WITH norm AS (
    SELECT machine_id, month_key,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY net_yards) AS typical_day
    FROM v_machine_day
    WHERE produced AND net_yards > 0
    GROUP BY 1,2
),
ev AS (
    SELECT e.event_id, e.date_key, e.machine_id, e.event_type,
           e.spec_before, e.spec_after, e.lines_before, e.lines_after,
           m.machine_code, m.peer_group
    FROM fact_machine_event e
    JOIN dim_machine m ON m.machine_id = e.machine_id
    WHERE e.event_type IN ('CHANGEOVER','RESET')
),
win AS (
    SELECT ev.event_id, ev.date_key AS event_date, ev.machine_id, ev.machine_code,
           ev.event_type, ev.spec_before, ev.spec_after, ev.peer_group,
           d.date_key AS affected_date,
           COALESCE(md.net_yards, 0) AS actual_yards
    FROM ev
    JOIN dim_date d
      ON d.is_working_day
     AND d.date_key BETWEEN ev.date_key - 2 AND ev.date_key
    LEFT JOIN v_machine_day md
      ON md.machine_id = ev.machine_id AND md.date_key = d.date_key
)
SELECT w.event_id, w.event_date, w.machine_id, w.machine_code, w.event_type,
       w.spec_before, w.spec_after, w.peer_group,
       COUNT(*)                                   AS days_affected,
       SUM(w.actual_yards)                        AS actual_yards,
       MAX(n.typical_day) * COUNT(*)              AS expected_yards,
       GREATEST(MAX(n.typical_day) * COUNT(*) - SUM(w.actual_yards), 0) AS cost_yards
FROM win w
LEFT JOIN norm n ON n.machine_id = w.machine_id
                AND n.month_key  = TO_CHAR(w.event_date,'YYYY-MM')
GROUP BY 1,2,3,4,5,6,7,8;


-- ---------------------------------------------------------------------------
--  v_rejection_detail / v_rejection_pareto — quality, from the QC register.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_rejection_detail AS
SELECT r.rejection_id, r.date_key,
       d.month_key, d.week_key, d.quarter_key,
       r.shift_code, m.machine_id, m.machine_code, m.line_group, m.peer_group,
       sp.spec_id, sp.weaving_spec, sp.dyeing_spec,
       r.rejection_yards, r.rejection_kgs,
       COALESCE(pr.reason_text, r.primary_reason_raw, 'NOT STATED') AS primary_reason,
       COALESCE(pr.reason_group, 'UNCLASSIFIED')                    AS reason_group,
       pr.owner_function,
       ar.reason_text AS addon_reason,
       q.staff_name   AS qc_name,
       sv.staff_name  AS supervisor_name,
       r.tied_to_production
FROM fact_rejection r
JOIN dim_date    d  ON d.date_key   = r.date_key
JOIN dim_machine m  ON m.machine_id = r.machine_id
LEFT JOIN dim_spec sp ON sp.spec_id = r.spec_id
LEFT JOIN dim_rejection_reason pr ON pr.rejection_reason_id = r.primary_reason_id
LEFT JOIN dim_rejection_reason ar ON ar.rejection_reason_id = r.addon_reason_id
LEFT JOIN dim_staff q  ON q.staff_id  = r.qc_id
LEFT JOIN dim_staff sv ON sv.staff_id = r.supervisor_id;

CREATE OR REPLACE VIEW v_rejection_pareto AS
SELECT month_key, reason_group, primary_reason,
       COUNT(*)                AS events,
       SUM(rejection_yards)    AS rejection_yards,
       SUM(rejection_kgs)      AS rejection_kgs,
       COUNT(DISTINCT machine_id) AS machines_affected
FROM v_rejection_detail
GROUP BY 1,2,3;


-- ---------------------------------------------------------------------------
--  v_spec_period — production and quality by specification, with value.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_spec_period AS
SELECT f.month_key, f.spec_id, f.weaving_spec, f.dyeing_spec,
       COUNT(DISTINCT f.machine_id)  AS machines,
       COUNT(DISTINCT f.date_key)    AS days,
       SUM(f.gross_yards)            AS gross_yards,
       SUM(f.rejection_yards)        AS rejection_yards,
       SUM(f.net_yards)              AS net_yards,
       SUM(f.net_kgs)                AS net_kgs,
       SUM(f.net_value)              AS net_value,
       CASE WHEN SUM(f.gross_yards) > 0
            THEN SUM(f.rejection_yards)/SUM(f.gross_yards) END AS rejection_rate
FROM v_fact f
WHERE f.spec_id IS NOT NULL
GROUP BY 1,2,3,4;


-- ---------------------------------------------------------------------------
--  v_downtime_detail — empty until the paper form is in use; the shape is
--  fixed now so nothing needs rebuilding when the first week arrives.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_downtime_detail AS
SELECT t.downtime_id, t.date_key, d.month_key, d.week_key,
       t.shift_code, m.machine_code, m.machine_id, m.peer_group,
       t.stop_time, t.restart_time, t.down_minutes,
       t.reason_code, sr.reason_text_en, sr.reason_class, sr.owner_function,
       t.reason_free_text,
       o.staff_name AS operator_name, s.staff_name AS supervisor_name,
       t.source
FROM fact_downtime t
JOIN dim_date    d ON d.date_key   = t.date_key
JOIN dim_machine m ON m.machine_id = t.machine_id
LEFT JOIN dim_stop_reason sr ON sr.reason_code = t.reason_code
LEFT JOIN dim_staff o ON o.staff_id = t.operator_id
LEFT JOIN dim_staff s ON s.staff_id = t.supervisor_id;


-- ---------------------------------------------------------------------------
--  v_confidence_matrix — how much of each month, for each machine, is a real
--  meter reading rather than something reconstructed. Printed as a grid so
--  nobody has to take the totals on faith.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_confidence_matrix AS
SELECT f.machine_id, f.machine_code, f.month_key,
       COUNT(*)                                                  AS rows_total,
       COUNT(*) FILTER (WHERE f.confidence = 'MEASURED')          AS rows_measured,
       COUNT(*) FILTER (WHERE f.confidence = 'DERIVED')           AS rows_derived,
       COUNT(*) FILTER (WHERE f.confidence = 'UNVERIFIED')        AS rows_unverified,
       SUM(f.net_yards)                                           AS net_yards,
       SUM(f.net_yards) FILTER (WHERE f.confidence = 'MEASURED')  AS measured_yards,
       CASE WHEN COUNT(*) > 0
            THEN COUNT(*) FILTER (WHERE f.confidence='MEASURED')::NUMERIC/COUNT(*)
       END AS trust
FROM v_fact f
GROUP BY 1,2,3;


-- ---------------------------------------------------------------------------
--  v_loss_waterfall — where the yards went, for a date range supplied by the
--  caller. Written as a function because a waterfall is always about one
--  window, and the window is the only thing that changes.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_loss_waterfall(p_from DATE, p_to DATE)
RETURNS TABLE (step TEXT, step_order INT, yards NUMERIC, note TEXT) AS $$
WITH f AS (
    SELECT * FROM v_fact WHERE date_key BETWEEN p_from AND p_to
),
t AS (
    SELECT
        COALESCE(SUM(target_yards),0)                                   AS target,
        COALESCE(SUM(gross_yards),0)                                    AS gross,
        COALESCE(SUM(rejection_yards),0)                                AS rejection,
        COALESCE(SUM(net_yards),0)                                      AS net,
        COALESCE(SUM(target_yards) FILTER (WHERE NOT produced),0)       AS idle_target,
        -- A changeover is an EVENT, not a status: the loom is still marked
        -- RUNNING on the day its specification is swapped.
        COALESCE(SUM(target_yards) FILTER (WHERE event IN ('CHANGEOVER','RESET')),0) AS chg_target,
        COALESCE(SUM(gross_yards)  FILTER (WHERE event IN ('CHANGEOVER','RESET')),0) AS chg_gross
    FROM f
)
SELECT 'Target'            , 1, t.target                       , 'What the plan asked for' FROM t
UNION ALL
SELECT 'Machines not run'  , 2, -t.idle_target                 , 'Target booked on looms that produced nothing' FROM t
UNION ALL
SELECT 'Changeover'        , 3, -(t.chg_target - t.chg_gross)  , 'Lost while a loom was being changed over' FROM t
UNION ALL
SELECT 'Running shortfall' , 4, -GREATEST(t.target - t.idle_target - (t.chg_target - t.chg_gross) - t.gross, 0),
                                'Looms that ran but under their target' FROM t
UNION ALL
SELECT 'Rejection'         , 5, -t.rejection                   , 'Woven, then failed inspection' FROM t
UNION ALL
SELECT 'Actual net'        , 6, t.net                          , 'What the plant delivered' FROM t;
$$ LANGUAGE SQL STABLE;


-- ---------------------------------------------------------------------------
--  v_data_health — the standing list of what is wrong with the data itself.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_data_health AS
SELECT i.issue_code, i.severity, i.owner_function,
       COUNT(*)                                   AS open_items,
       MIN(i.date_key)                            AS earliest,
       MAX(i.date_key)                            AS latest,
       COUNT(DISTINCT i.machine_id)               AS machines
FROM data_issue i
WHERE i.status = 'OPEN'
GROUP BY 1,2,3;
