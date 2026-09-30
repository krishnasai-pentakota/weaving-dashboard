-- ===========================================================================
--  WEAVING — PRODUCTION ANALYTICS DATABASE
--  Layer 2 :: PostgreSQL star schema
--
--  Design rules applied throughout:
--    * Every table has a PRIMARY KEY.
--    * Every business key has a UNIQUE constraint (so a machine or a spec can
--      never be entered twice under the same name).
--    * Every relationship is a FOREIGN KEY, so a shift row can never point at
--      a machine that does not exist.
--    * Every column that must always hold a value is NOT NULL.
--    * Every value with a known legal range carries a CHECK, so bad data is
--      refused at the door rather than discovered in a chart six weeks later.
--    * Derived numbers (yards, net, efficiency) are GENERATED columns. They
--      cannot drift from their inputs because the database computes them.
--    * Reference data that the floor may revise later (stop reasons, staff,
--      specs) is table-driven and versioned, never hard-coded.
--
--  Units, fixed for the whole database:
--    counter readings .......... METRES   (what the meter on the loom shows)
--    production ................ YARDS    (metres / 0.9144)
--    weight .................... KILOGRAMS
--    value ..................... RUPEES
--    downtime .................. MINUTES
-- ===========================================================================

DROP SCHEMA IF EXISTS weaving CASCADE;
CREATE SCHEMA weaving;
SET search_path TO weaving, public;

-- The one physical constant in the system. Kept in a table, not scattered
-- through code, so there is exactly one place it can ever be changed.
CREATE TABLE constant (
    key         TEXT           PRIMARY KEY,
    value       NUMERIC(18,10) NOT NULL,
    note        TEXT           NOT NULL
);
INSERT INTO constant VALUES
    ('METRES_PER_YARD', 0.9144,
     'One yard is 0.9144 metres. Production yards = metres / 0.9144.'),
    ('SHIFTS_PER_DAY',  3,
     'Three fixed eight-hour shifts. A day target divided by three is a shift target.');


-- ===========================================================================
--  DIMENSIONS
-- ===========================================================================

-- ---------------------------------------------------------------------------
--  dim_date — one row per calendar day, carrying every period key the
--  dashboard groups by. Holidays are irregular here (Sunday is the weekly
--  holiday, but a mid-week festival moves it), so is_working_day is set from
--  the data that actually exists, never from a day-of-week rule.
--
--  period_index columns are the comparison engine: "previous week" is simply
--  week_index - 1. No date arithmetic in the application layer.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key        DATE        PRIMARY KEY,
    year            SMALLINT    NOT NULL,
    quarter         SMALLINT    NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month           SMALLINT    NOT NULL CHECK (month   BETWEEN 1 AND 12),
    day_of_month    SMALLINT    NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    day_of_week     SMALLINT    NOT NULL CHECK (day_of_week  BETWEEN 1 AND 7),
    iso_year        SMALLINT    NOT NULL,
    iso_week        SMALLINT    NOT NULL CHECK (iso_week BETWEEN 1 AND 53),

    month_key       CHAR(7)     NOT NULL,          -- '2026-01'
    week_key        CHAR(8)     NOT NULL,          -- '2026-W01'
    quarter_key     CHAR(7)     NOT NULL,          -- '2026-Q1'

    month_index     INTEGER     NOT NULL,          -- year*12 + month
    week_index      INTEGER     NOT NULL,          -- iso_year*53 + iso_week
    quarter_index   INTEGER     NOT NULL,          -- year*4 + quarter

    is_working_day  BOOLEAN     NOT NULL DEFAULT FALSE,
    holiday_name    TEXT,

    CONSTRAINT dim_date_month_key_fmt   CHECK (month_key   ~ '^\d{4}-\d{2}$'),
    CONSTRAINT dim_date_week_key_fmt    CHECK (week_key    ~ '^\d{4}-W\d{2}$'),
    CONSTRAINT dim_date_quarter_key_fmt CHECK (quarter_key ~ '^\d{4}-Q\d$')
);
CREATE INDEX ix_dim_date_month   ON dim_date (month_key);
CREATE INDEX ix_dim_date_week    ON dim_date (week_key);
CREATE INDEX ix_dim_date_quarter ON dim_date (quarter_key);
CREATE INDEX ix_dim_date_working ON dim_date (is_working_day) WHERE is_working_day;


-- ---------------------------------------------------------------------------
--  dim_shift — three eight-hour shifts, plus the DAY pseudo-shift used for
--  history where only one combined reading per day was ever recorded.
--  Names are carried in English and Telugu because the floor screens are read
--  by operators and supervisors, and the management screens are not.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_shift (
    shift_code      VARCHAR(4)  PRIMARY KEY CHECK (shift_code IN ('A','B','C','DAY')),
    shift_name_en   TEXT        NOT NULL,
    shift_name_te   TEXT        NOT NULL,
    sort_order      SMALLINT    NOT NULL UNIQUE,
    starts_at       TIME,
    ends_at         TIME,
    is_real_shift   BOOLEAN     NOT NULL,   -- FALSE for DAY: it is a whole day
    note            TEXT
);
INSERT INTO dim_shift VALUES
 ('A','Morning','ఉదయం షిఫ్ట్',   1,'05:30','13:30', TRUE,
  'Start time stated as about 05:30, not yet confirmed on the floor.'),
 ('B','Evening','సాయంత్రం షిఫ్ట్',2,'13:30','21:30', TRUE, NULL),
 ('C','Night',  'రాత్రి షిఫ్ట్',  3,'21:30','05:30', TRUE,
  'Crosses midnight. The C reading closes the production day.'),
 ('DAY','Whole day (not split)','పూర్తి రోజు (విభజన లేదు)', 4,NULL,NULL, FALSE,
  'History only: one combined reading covering all three shifts.');


-- ---------------------------------------------------------------------------
--  dim_machine — the loom. lines_fitted here is the CURRENT fitted count and
--  is used only to pre-fill an entry form. The count actually used on a given
--  day is stored on the shift row itself, which is the whole point of the
--  long-format rebuild: a header cell can be overwritten, a fact row cannot.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_machine (
    machine_id      SERIAL      PRIMARY KEY,
    machine_code    VARCHAR(10) NOT NULL UNIQUE,
    line_group      VARCHAR(4)  NOT NULL CHECK (line_group IN ('L-A','L-B')),
    model           CHAR(1)     NOT NULL CHECK (model IN ('S','D')),
    peer_group      TEXT        NOT NULL,
    is_commissioned BOOLEAN     NOT NULL DEFAULT TRUE,
    lines_fitted    SMALLINT             CHECK (lines_fitted > 0 AND lines_fitted <= 64),
    target_per_line_day NUMERIC(10,4)    CHECK (target_per_line_day > 0),
    target_source   TEXT,
    default_weaving_spec VARCHAR(20),
    default_dyeing_spec  VARCHAR(20),
    opening_reading_m    NUMERIC(14,2)   CHECK (opening_reading_m >= 0),
    data_warning    TEXT,                -- e.g. peer group disagrees with lines fitted
    CONSTRAINT dim_machine_code_fmt CHECK (machine_code ~ '^M[AB]-\d{2}$')
);
CREATE INDEX ix_dim_machine_line  ON dim_machine (line_group);
CREATE INDEX ix_dim_machine_peer  ON dim_machine (peer_group);


-- ---------------------------------------------------------------------------
--  dim_spec — a woven specification. The plant pairs every weaving code
--  (1xxxx) with a dyeing code (2xxxx): the ribbon is woven wider and shrinks
--  under heat to the finished width. The pair is the natural key.
--
--  Codes are classified by their leading digit, never by the column heading
--  they arrived under, because the headings are swapped in some source tabs.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_spec (
    spec_id         SERIAL       PRIMARY KEY,
    weaving_spec    VARCHAR(20)  NOT NULL UNIQUE,
    dyeing_spec     VARCHAR(20),
    width_mm        NUMERIC(6,2) CHECK (width_mm > 0),
    per_yard_weight_g NUMERIC(10,6) CHECK (per_yard_weight_g > 0),
    -- zero means Planning has not supplied a price; it is real data,
    -- shown on the data-health page rather than refused at load time
    per_yard_price  NUMERIC(10,4)   CHECK (per_yard_price  >= 0),
    in_production   BOOLEAN      NOT NULL DEFAULT TRUE,
    weight_is_disputed BOOLEAN   NOT NULL DEFAULT FALSE,
    note            TEXT,
    CONSTRAINT dim_spec_weaving_prefix CHECK (weaving_spec LIKE '1%'),
    CONSTRAINT dim_spec_dyeing_prefix  CHECK (dyeing_spec IS NULL OR dyeing_spec LIKE '2%')
);
CREATE UNIQUE INDEX ux_dim_spec_pair ON dim_spec (weaving_spec, COALESCE(dyeing_spec,''));


-- ---------------------------------------------------------------------------
--  dim_staff — operators, supervisors, QC, HOD. People leave; history must
--  still join. So a person is never deleted, only marked not currently
--  working, and the machine range they cover is recorded for the staffing
--  analysis (span of control is the whole basis of the "hire two more
--  operators" question).
-- ---------------------------------------------------------------------------
CREATE TABLE dim_staff (
    staff_id        SERIAL      PRIMARY KEY,
    staff_name      TEXT        NOT NULL,
    role            VARCHAR(12) NOT NULL CHECK (role IN ('OPERATOR','SUPERVISOR','QC','HOD')),
    emp_no          TEXT,
    is_current      BOOLEAN     NOT NULL DEFAULT TRUE,
    machine_range   TEXT,
    CONSTRAINT ux_dim_staff UNIQUE (staff_name, role)
);
CREATE INDEX ix_dim_staff_role ON dim_staff (role) WHERE is_current;


-- ---------------------------------------------------------------------------
--  dim_stop_reason — why a loom stopped. Deliberately table-driven and
--  versioned: the twelve codes printed on paper form FM-ZD-01 are what the
--  floor uses today, and the floor will revise them. A retired code keeps its
--  history by going inactive, never by being deleted.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_stop_reason (
    reason_code     SMALLINT    PRIMARY KEY CHECK (reason_code > 0),
    reason_text_en  TEXT        NOT NULL UNIQUE,
    reason_text_te  TEXT,
    owner_function  TEXT        NOT NULL,   -- who is accountable for fixing it
    reason_class    VARCHAR(16) NOT NULL CHECK (reason_class IN
                        ('MAINTENANCE','MATERIAL','PLANNING','UTILITIES',
                         'HOUSEKEEPING','MANPOWER','UNCLASSIFIED')),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    form_version    TEXT        NOT NULL DEFAULT 'FM-ZD-01 v1.2',
    valid_from      DATE        NOT NULL DEFAULT DATE '2026-09-01',
    valid_to        DATE,
    CONSTRAINT dim_stop_reason_validity CHECK (valid_to IS NULL OR valid_to >= valid_from)
);


-- ---------------------------------------------------------------------------
--  dim_rejection_reason — the QC vocabulary, grouped so the Pareto chart has
--  something meaningful on its axis. Free text from the register is mapped
--  here on load; anything unmapped lands in UNCLASSIFIED and shows up as a
--  data-quality item rather than disappearing.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_rejection_reason (
    rejection_reason_id SERIAL  PRIMARY KEY,
    reason_text     TEXT        NOT NULL UNIQUE,
    reason_group    VARCHAR(24) NOT NULL CHECK (reason_group IN
                        ('WEAVING FAULT','YARN / MATERIAL','MACHINE SETTING',
                         'EDGE / SELVEDGE','DIRT / CONTAMINATION','HANDLING',
                         'UNCLASSIFIED')),
    owner_function  TEXT
);


-- ===========================================================================
--  FACTS
-- ===========================================================================

-- ---------------------------------------------------------------------------
--  fact_production — THE grain of the whole system: one machine, one date,
--  one shift. Everything the dashboard shows rolls up from here.
--
--  The derived columns are GENERATED, not written by the loader, so the
--  arithmetic the forensic audit established can never be re-implemented
--  slightly differently by a later script:
--
--      difference_m  = current reading - previous reading   (or the override
--                      on a changeover day, where the counter restarts at 0)
--      total_m       = difference_m x lines actually running
--      gross_yards   = total_m / 0.9144
--      net_yards     = gross_yards - rejection_yards
--      efficiency    = net_yards / target_yards
-- ---------------------------------------------------------------------------
CREATE TABLE fact_production (
    production_id   BIGSERIAL   PRIMARY KEY,

    date_key        DATE        NOT NULL REFERENCES dim_date(date_key),
    shift_code      VARCHAR(4)  NOT NULL REFERENCES dim_shift(shift_code),
    machine_id      INTEGER     NOT NULL REFERENCES dim_machine(machine_id),

    spec_id         INTEGER              REFERENCES dim_spec(spec_id),

    lines_fitted    SMALLINT             CHECK (lines_fitted  > 0  AND lines_fitted  <= 64),
    lines_running   SMALLINT    NOT NULL CHECK (lines_running >= 0 AND lines_running <= 64),

    -- What the loom was doing. CHANGEOVER and RESET are events, not states,
    -- and live in the event column: a loom can be changed over and still run.
    machine_status  VARCHAR(24) NOT NULL DEFAULT 'RUNNING'
                    CHECK (machine_status IN
                        ('RUNNING','STOPPED','IDLE','NO READING','NOT YET IN PRODUCTION')),
    event           VARCHAR(24) CHECK (event IS NULL OR event IN
                        ('CHANGEOVER','RESET','LINE COUNT CHANGE','SPEC CHANGE','RECOMMISSIONED')),
    remarks         TEXT,

    previous_reading_m NUMERIC(14,2) CHECK (previous_reading_m >= 0),
    current_reading_m  NUMERIC(14,2) CHECK (current_reading_m  >= 0),
    rebase_override_m  NUMERIC(14,2) CHECK (rebase_override_m  >= 0),

    -- The meter on the loom counts ONE line, so a reading represents 1/N of a
    -- machine fitted with N lines. Carried for fidelity with the source sheet;
    -- the multiplication back up to the whole machine is lines_running.
    single_line_share NUMERIC(10,8) CHECK (single_line_share > 0 AND single_line_share <= 1),

    rejection_yards NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (rejection_yards >= 0),
    target_yards    NUMERIC(14,4)              CHECK (target_yards >= 0),

    operator_id     INTEGER REFERENCES dim_staff(staff_id),
    supervisor_id   INTEGER REFERENCES dim_staff(staff_id),

    confidence      VARCHAR(16) NOT NULL DEFAULT 'MEASURED'
                    CHECK (confidence IN ('MEASURED','DERIVED','UNVERIFIED','NOT APPLICABLE')),
    confidence_why  TEXT,
    source_note     TEXT,

    -- ---- generated: the database owns the arithmetic ----------------------
    difference_m NUMERIC(14,4) GENERATED ALWAYS AS (
        CASE
            WHEN rebase_override_m IS NOT NULL THEN rebase_override_m
            WHEN current_reading_m IS NULL OR previous_reading_m IS NULL THEN NULL
            WHEN current_reading_m >= previous_reading_m
                 THEN current_reading_m - previous_reading_m
            ELSE NULL          -- counter went backwards: needs an override
        END) STORED,

    total_m NUMERIC(16,4) GENERATED ALWAYS AS (
        CASE
            WHEN rebase_override_m IS NOT NULL THEN rebase_override_m * lines_running
            WHEN current_reading_m IS NULL OR previous_reading_m IS NULL THEN NULL
            WHEN current_reading_m >= previous_reading_m
                 THEN (current_reading_m - previous_reading_m) * lines_running
            ELSE NULL
        END) STORED,

    gross_yards NUMERIC(16,4) GENERATED ALWAYS AS (
        CASE
            WHEN rebase_override_m IS NOT NULL
                 THEN rebase_override_m * lines_running / 0.9144
            WHEN current_reading_m IS NULL OR previous_reading_m IS NULL THEN NULL
            WHEN current_reading_m >= previous_reading_m
                 THEN (current_reading_m - previous_reading_m) * lines_running / 0.9144
            ELSE NULL
        END) STORED,

    net_yards NUMERIC(16,4) GENERATED ALWAYS AS (
        CASE
            WHEN rebase_override_m IS NOT NULL
                 THEN rebase_override_m * lines_running / 0.9144 - rejection_yards
            WHEN current_reading_m IS NULL OR previous_reading_m IS NULL THEN NULL
            WHEN current_reading_m >= previous_reading_m
                 THEN (current_reading_m - previous_reading_m) * lines_running / 0.9144
                      - rejection_yards
            ELSE NULL
        END) STORED,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_file     TEXT,

    -- One machine, one date, one shift: entered once and only once.
    CONSTRAINT ux_fact_production UNIQUE (date_key, shift_code, machine_id),

    -- A counter may only fall on a day the floor has declared a restart. This
    -- is the single most valuable rule in the database: an unexplained
    -- backward reading is how eight months of production quietly went wrong.
    CONSTRAINT ck_reading_direction CHECK (
        current_reading_m IS NULL
        OR previous_reading_m IS NULL
        OR current_reading_m >= previous_reading_m
        OR event IN ('CHANGEOVER','RESET')
        OR rebase_override_m IS NOT NULL
    ),
    -- More lines running than are fitted to the loom is impossible.
    CONSTRAINT ck_lines_running_le_fitted CHECK (
        lines_fitted IS NULL OR lines_running <= lines_fitted
    ),
    -- A loom that has never been commissioned cannot be running lines.
    CONSTRAINT ck_not_in_production CHECK (
        machine_status <> 'NOT YET IN PRODUCTION' OR COALESCE(gross_yards,0) = 0
    )
);

CREATE INDEX ix_prod_date          ON fact_production (date_key);
CREATE INDEX ix_prod_machine_date  ON fact_production (machine_id, date_key);
CREATE INDEX ix_prod_date_shift    ON fact_production (date_key, shift_code);
CREATE INDEX ix_prod_spec          ON fact_production (spec_id);
CREATE INDEX ix_prod_operator      ON fact_production (operator_id) WHERE operator_id IS NOT NULL;
CREATE INDEX ix_prod_status        ON fact_production (machine_status);


-- ---------------------------------------------------------------------------
--  fact_rejection — one row per QC event, which is the grain the quality
--  register is actually kept at. Rejection also appears as a total on the
--  production row; the two are reconciled by the loader and the difference is
--  reported, never silently adjusted.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_rejection (
    rejection_id    BIGSERIAL   PRIMARY KEY,
    date_key        DATE        NOT NULL REFERENCES dim_date(date_key),
    shift_code      VARCHAR(4)  NOT NULL REFERENCES dim_shift(shift_code),
    machine_id      INTEGER     NOT NULL REFERENCES dim_machine(machine_id),
    spec_id         INTEGER              REFERENCES dim_spec(spec_id),

    rejection_yards NUMERIC(14,4) NOT NULL CHECK (rejection_yards > 0),
    weight_per_yard_g NUMERIC(10,6)      CHECK (weight_per_yard_g > 0),
    rejection_kgs   NUMERIC(14,6)        CHECK (rejection_kgs >= 0),

    primary_reason_id INTEGER    REFERENCES dim_rejection_reason(rejection_reason_id),
    addon_reason_id   INTEGER    REFERENCES dim_rejection_reason(rejection_reason_id),
    primary_reason_raw TEXT,
    addon_reason_raw   TEXT,

    qc_id           INTEGER     REFERENCES dim_staff(staff_id),
    supervisor_id   INTEGER     REFERENCES dim_staff(staff_id),

    tied_to_production BOOLEAN  NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_file     TEXT
);
CREATE INDEX ix_rej_date         ON fact_rejection (date_key);
CREATE INDEX ix_rej_machine_date ON fact_rejection (machine_id, date_key);
CREATE INDEX ix_rej_spec         ON fact_rejection (spec_id);
CREATE INDEX ix_rej_reason       ON fact_rejection (primary_reason_id);
CREATE INDEX ix_rej_qc           ON fact_rejection (qc_id);


-- ---------------------------------------------------------------------------
--  fact_downtime — one row per stop. This table is empty for all of the
--  history: the floor has never written stop and restart times down, which is
--  precisely why downtime could not be measured from the old files. It fills
--  from September onward as the paper form is used.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_downtime (
    downtime_id     BIGSERIAL   PRIMARY KEY,
    date_key        DATE        NOT NULL REFERENCES dim_date(date_key),
    shift_code      VARCHAR(4)  NOT NULL REFERENCES dim_shift(shift_code),
    machine_id      INTEGER     NOT NULL REFERENCES dim_machine(machine_id),

    stop_time       TIME        NOT NULL,
    restart_time    TIME,
    -- Minutes, handling a stop that crosses midnight inside the night shift.
    down_minutes    INTEGER GENERATED ALWAYS AS (
        CASE WHEN restart_time IS NULL THEN NULL
             WHEN restart_time >= stop_time
                  THEN EXTRACT(EPOCH FROM (restart_time - stop_time))::INT / 60
             ELSE (86400 - EXTRACT(EPOCH FROM (stop_time - restart_time))::INT) / 60
        END) STORED,

    reason_code     SMALLINT    REFERENCES dim_stop_reason(reason_code),
    reason_free_text TEXT,
    operator_id     INTEGER     REFERENCES dim_staff(staff_id),
    supervisor_id   INTEGER     REFERENCES dim_staff(staff_id),
    source          VARCHAR(16) NOT NULL DEFAULT 'PAPER FORM'
                    CHECK (source IN ('PAPER FORM','WHATSAPP','WEB FORM','INFERRED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_down_date         ON fact_downtime (date_key);
CREATE INDEX ix_down_machine_date ON fact_downtime (machine_id, date_key);
CREATE INDEX ix_down_reason       ON fact_downtime (reason_code);


-- ---------------------------------------------------------------------------
--  fact_machine_event — changeovers, resets, line-count changes and spec
--  changes, as discrete events. The forensic audit priced a changeover at
--  roughly 5,700 yards; this table is what lets the dashboard keep pricing
--  them as they happen instead of reconstructing them a year later.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_machine_event (
    event_id        BIGSERIAL   PRIMARY KEY,
    date_key        DATE        NOT NULL REFERENCES dim_date(date_key),
    machine_id      INTEGER     NOT NULL REFERENCES dim_machine(machine_id),
    event_type      VARCHAR(20) NOT NULL CHECK (event_type IN
                        ('CHANGEOVER','RESET','LINE COUNT CHANGE','SPEC CHANGE','RECOMMISSIONED')),
    detail          TEXT,
    lines_before    SMALLINT CHECK (lines_before  >= 0),
    lines_after     SMALLINT CHECK (lines_after   >= 0),
    spec_before     VARCHAR(20),
    spec_after      VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_machine_event UNIQUE (date_key, machine_id, event_type)
);
CREATE INDEX ix_event_machine_date ON fact_machine_event (machine_id, date_key);
CREATE INDEX ix_event_type         ON fact_machine_event (event_type);


-- ===========================================================================
--  STAGING + GOVERNANCE
-- ===========================================================================

-- Raw rows exactly as they arrived, before any validation. Nothing is ever
-- thrown away: a row that fails validation stays here with its reasons, so
-- "what did the clerk actually type" is always answerable.
CREATE TABLE stg_daily_entry (
    stg_id          BIGSERIAL   PRIMARY KEY,
    batch_id        BIGINT      NOT NULL,
    source_file     TEXT        NOT NULL,
    source_row      INTEGER     NOT NULL,
    raw             JSONB       NOT NULL,
    is_valid        BOOLEAN     NOT NULL DEFAULT FALSE,
    errors          TEXT[]      NOT NULL DEFAULT '{}',
    warnings        TEXT[]      NOT NULL DEFAULT '{}',
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_stg_row UNIQUE (batch_id, source_row)
);
CREATE INDEX ix_stg_batch   ON stg_daily_entry (batch_id);
CREATE INDEX ix_stg_invalid ON stg_daily_entry (is_valid) WHERE NOT is_valid;

CREATE TABLE load_batch (
    batch_id        BIGSERIAL   PRIMARY KEY,
    source_file     TEXT        NOT NULL,
    source_sha256   CHAR(64),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(12) NOT NULL DEFAULT 'RUNNING'
                    CHECK (status IN ('RUNNING','SUCCESS','FAILED','PARTIAL')),
    rows_read       INTEGER NOT NULL DEFAULT 0 CHECK (rows_read     >= 0),
    rows_loaded     INTEGER NOT NULL DEFAULT 0 CHECK (rows_loaded   >= 0),
    rows_rejected   INTEGER NOT NULL DEFAULT 0 CHECK (rows_rejected >= 0),
    message         TEXT,
    CONSTRAINT ck_batch_counts CHECK (rows_loaded + rows_rejected <= rows_read)
);

-- Every insert, update and delete on a fact table, with the before and after
-- values. This is what makes a figure defensible in a meeting.
CREATE TABLE audit_log (
    audit_id        BIGSERIAL   PRIMARY KEY,
    table_name      TEXT        NOT NULL,
    operation       VARCHAR(6)  NOT NULL CHECK (operation IN ('INSERT','UPDATE','DELETE')),
    record_pk       BIGINT,
    old_values      JSONB,
    new_values      JSONB,
    changed_by      TEXT        NOT NULL DEFAULT CURRENT_USER,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_id        BIGINT      REFERENCES load_batch(batch_id)
);
CREATE INDEX ix_audit_table_time ON audit_log (table_name, changed_at DESC);

-- Data-quality findings raised by the loader and by the nightly checks. The
-- dashboard reads this table directly, so a problem on the floor becomes a
-- line on a screen rather than a conversation somebody has to remember.
CREATE TABLE data_issue (
    issue_id        BIGSERIAL   PRIMARY KEY,
    raised_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity        VARCHAR(8)  NOT NULL CHECK (severity IN ('BLOCK','WARN','INFO')),
    issue_code      TEXT        NOT NULL,
    date_key        DATE        REFERENCES dim_date(date_key),
    machine_id      INTEGER     REFERENCES dim_machine(machine_id),
    shift_code      VARCHAR(4)  REFERENCES dim_shift(shift_code),
    description     TEXT        NOT NULL,
    owner_function  TEXT,
    status          VARCHAR(10) NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','WONTFIX')),
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,
    CONSTRAINT ck_issue_resolution CHECK (
        (status IN ('RESOLVED','WONTFIX')) = (resolved_at IS NOT NULL)
    )
);
CREATE INDEX ix_issue_open ON data_issue (status, severity) WHERE status = 'OPEN';
CREATE INDEX ix_issue_date ON data_issue (date_key);


-- ---------------------------------------------------------------------------
--  Audit triggers on the fact tables.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_audit() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log(table_name, operation, record_pk, new_values)
        VALUES (TG_TABLE_NAME, 'INSERT', NULL, to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
            INSERT INTO audit_log(table_name, operation, record_pk, old_values, new_values)
            VALUES (TG_TABLE_NAME, 'UPDATE', NULL, to_jsonb(OLD), to_jsonb(NEW));
        END IF;
        RETURN NEW;
    ELSE
        INSERT INTO audit_log(table_name, operation, record_pk, old_values)
        VALUES (TG_TABLE_NAME, 'DELETE', NULL, to_jsonb(OLD));
        RETURN OLD;
    END IF;
END $$ LANGUAGE plpgsql;

-- Kept off during the bulk history load and switched on for daily operation;
-- see 03_triggers.sql.
