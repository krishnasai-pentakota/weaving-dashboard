-- ===========================================================================
--  ROLES AND GRANTS
--
--  Not switched on in the application yet - the dashboard opens with a single
--  account while the floor gets used to it. The roles are created now anyway,
--  because retrofitting permissions onto a database people already depend on is
--  far harder than starting with them.
--
--  Four roles, matching how the department actually works:
--
--    weaving_read     sees everything, changes nothing.       Supervisors, Planning, MD.
--    weaving_entry    reads, and writes production rows.      The data-entry clerk.
--    weaving_quality  reads, and writes the rejection rows.   The QC team.
--    weaving_admin    everything, including the reference     You.
--                  tables and the loader.
--
--  Nobody gets DELETE on a fact table. A figure that was wrong is corrected by
--  entering it again - the row is updated and the old values are kept in
--  audit_log. Nothing that was once recorded can disappear without trace.
--
--  Run as the database owner:  psql -d weaving_db -f sql/03_roles.sql
-- ===========================================================================
SET search_path TO weaving, public;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'weaving_read') THEN
        CREATE ROLE weaving_read    NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'weaving_entry') THEN
        CREATE ROLE weaving_entry   NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'weaving_quality') THEN
        CREATE ROLE weaving_quality NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'weaving_admin') THEN
        CREATE ROLE weaving_admin   NOLOGIN;
    END IF;
END $$;

-- ---- read -----------------------------------------------------------------
GRANT USAGE ON SCHEMA weaving TO weaving_read, weaving_entry, weaving_quality, weaving_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA weaving TO weaving_read;
ALTER DEFAULT PRIVILEGES IN SCHEMA weaving GRANT SELECT ON TABLES TO weaving_read;

-- ---- entry: production, and the events that explain it --------------------
GRANT weaving_read TO weaving_entry;
GRANT INSERT, UPDATE ON fact_production, fact_downtime, fact_machine_event
                     TO weaving_entry;
GRANT INSERT, UPDATE ON data_issue TO weaving_entry;
GRANT INSERT ON stg_daily_entry, load_batch, audit_log TO weaving_entry;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA weaving TO weaving_entry;

-- ---- quality: the rejection register only ---------------------------------
GRANT weaving_read TO weaving_quality;
GRANT INSERT, UPDATE ON fact_rejection TO weaving_quality;
GRANT INSERT, UPDATE ON data_issue TO weaving_quality;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA weaving TO weaving_quality;

-- ---- admin ----------------------------------------------------------------
GRANT weaving_entry, weaving_quality TO weaving_admin;
GRANT ALL ON ALL TABLES IN SCHEMA weaving TO weaving_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA weaving TO weaving_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA weaving
    GRANT ALL ON TABLES TO weaving_admin;

-- ---------------------------------------------------------------------------
--  To give a person an account, when the time comes:
--
--      CREATE USER analyst WITH PASSWORD '...';
--      GRANT weaving_read TO analyst;
--
--  and for the clerk who types the sheet:
--
--      CREATE USER weaving_clerk WITH PASSWORD '...';
--      GRANT weaving_entry TO weaving_clerk;
--
--  The dashboard then connects as that person rather than as one shared
--  account, and audit_log records who changed what. Until that day, every
--  connection is the single weaving account and audit_log records that name.
-- ---------------------------------------------------------------------------
