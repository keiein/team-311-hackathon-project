-- MySQL schema for the 311 dispatcher. Needs MySQL 8.0.16 or later (older versions ignore CHECK).
--
--     workforce        supply: one shared operational workforce (hackathon simulation)
--     scored_tickets   demand: one row per ticket per scoring run, as priority_score.py scores it
--
-- Run it (fresh install):  mysql -u root -p -e "source schema.sql"
--
-- Already have a database built from the old crew_pool model?
--     Run migrate_to_workforce.sql instead (or after). CREATE TABLE IF NOT EXISTS will NOT
--     remove the old crew_pool table or its foreign key from an existing database.
--
-- Safe to run again on a fresh shape: tables that exist are kept, and so is the workforce row.

CREATE DATABASE IF NOT EXISTS dispatch_311 CHARACTER SET utf8mb4;
USE dispatch_311;


-- ---- supply: one shared workforce (hackathon simulation) ----
-- Assumption for this hackathon: all workers can do any 311 work order.
-- Every dispatched job uses people_per_crew people (default 5).
-- Tickets are NOT matched by specialized crew_pool; crew_pool on scored_tickets is metadata only.
--
-- SIMULATED PLACEHOLDER: total_people = 100 is NOT a real City of Calgary staffing figure.
--
-- How the numbers move:
--     job dispatched          UPDATE workforce SET busy_people = busy_people + people_per_crew WHERE workforce_id = 1;
--     job completed/released  UPDATE workforce SET busy_people = busy_people - people_per_crew WHERE workforce_id = 1;
--     sick call               UPDATE workforce SET sick_people = sick_people + N WHERE workforce_id = 1;
--     return from sick        UPDATE workforce SET sick_people = sick_people - N WHERE workforce_id = 1;
--     snow redeployment       UPDATE workforce SET snow_redeployed = snow_redeployed + N WHERE workforce_id = 1;
--     release from snow       UPDATE workforce SET snow_redeployed = snow_redeployed - N WHERE workforce_id = 1;
--
-- Do NOT reduce total_people for sick calls or snow redeployment.
-- available_people and available_crews update automatically (generated columns).
-- Constraints refuse negative counts and refuse busy + sick + snow > total_people.
CREATE TABLE IF NOT EXISTS workforce (
    workforce_id      TINYINT UNSIGNED NOT NULL DEFAULT 1,
    total_people      INT              NOT NULL,           -- SIMULATED PLACEHOLDER headcount (stable)
    busy_people       INT              NOT NULL DEFAULT 0, -- people on active 311 jobs
    sick_people       INT              NOT NULL DEFAULT 0, -- temporarily unavailable (sick calls)
    snow_redeployed   INT              NOT NULL DEFAULT 0, -- temporarily on snow response
    people_per_crew   INT              NOT NULL DEFAULT 5, -- people required per work order
    available_people  INT GENERATED ALWAYS AS (
                          total_people - busy_people - sick_people - snow_redeployed
                      ) VIRTUAL,
    available_crews   INT GENERATED ALWAYS AS (
                          FLOOR((total_people - busy_people - sick_people - snow_redeployed) / people_per_crew)
                      ) VIRTUAL,
    PRIMARY KEY (workforce_id),
    CONSTRAINT chk_workforce_nonneg CHECK (
        total_people >= 0
        AND busy_people >= 0
        AND sick_people >= 0
        AND snow_redeployed >= 0
        AND people_per_crew > 0
    ),
    CONSTRAINT chk_workforce_capacity CHECK (
        busy_people + sick_people + snow_redeployed <= total_people
    )
);

-- Single shared workforce row. Fixed placeholder size; do not draw random headcounts.
INSERT IGNORE INTO workforce (workforce_id, total_people, busy_people, sick_people, snow_redeployed, people_per_crew)
VALUES (1, 100, 0, 0, 0, 5);


-- ---- demand: the scored queue ----
-- One row per ticket per scoring run. The names are the ones PriorityScorer.score_frame() returns.
-- run_id, scored_at and priority_rank are not in that output: load_scored_tickets.py stamps them on.
-- A column that can be NULL is one the scorer leaves empty when the ticket's own field is blank or unreadable.
-- A table made from an older copy of this file keeps its old shape (IF NOT EXISTS). Bring it up to date once,
-- skipping a step it already has:
--     ALTER TABLE scored_tickets ADD COLUMN same_day_ticket_count INT UNSIGNED NULL AFTER criticality_keywords;
--     ALTER TABLE scored_tickets
--         MODIFY priority  DECIMAL(12,6) NOT NULL,
--         MODIFY age_score DECIMAL(12,6) NOT NULL,
--         ADD COLUMN overdue_days  INT UNSIGNED     NULL AFTER overdue,
--         ADD COLUMN overdue_hours TINYINT UNSIGNED NULL AFTER overdue_days;
-- If this table still has fk_scored_tickets_crew_pool, run migrate_to_workforce.sql.
CREATE TABLE IF NOT EXISTS scored_tickets (
    -- identity
    run_id                INT UNSIGNED     NOT NULL,  -- one scoring run: the morning plan, the replan, ...
    service_request_id    VARCHAR(20)      NOT NULL,  -- the ticket's key
    scored_at             DATETIME         NOT NULL,  -- the clock the age score was measured against
    -- the job
    service_name          VARCHAR(100)     NOT NULL,
    requested_date        DATETIME         NULL,      -- the export has dates only; a live feed has the time too
    comm_code             VARCHAR(8)       NULL,      -- the City's 3-character community code
    comm_name             VARCHAR(60)      NULL,
    longitude             DECIMAL(9,6)     NULL,      -- the community's centre point, not the job's own address
    latitude              DECIMAL(8,6)     NULL,
    -- service-area metadata (NOT a dispatch supply constraint)
    crew_pool             VARCHAR(80)      NOT NULL,  -- responsible City service area; reporting only
    work_category         VARCHAR(60)      NOT NULL,  -- the kind of work within that service area
    call_confidence       VARCHAR(12)      NOT NULL,  -- Clear or Borderline: how sure it is a crew job
    -- the score
    priority              DECIMAL(12,6)    NOT NULL,  -- 0 to 1.2
    priority_rank         INT UNSIGNED     NOT NULL,  -- 1 = first; ties on priority go to the longest open
    basic_knowledge_score DECIMAL(7,6)     NOT NULL,
    geo_score             DECIMAL(7,6)     NOT NULL,
    age_score             DECIMAL(12,6)    NOT NULL,  -- time open / SLA, held at 3; 1 = at the SLA
    ticket_count_score    DECIMAL(7,6)     NULL,      -- empty only on runs scored before the fourth term existed
    criticality_tier      TINYINT UNSIGNED NOT NULL,  -- 4 = safety, 3 = disruption, 2 = nuisance, 1 = routine
    criticality_keywords  VARCHAR(255)     NOT NULL DEFAULT '',
    same_day_ticket_count INT UNSIGNED     NULL,      -- tickets of the run for the same job, day and place, itself included
    open_days             INT UNSIGNED     NULL,
    open_hours            TINYINT UNSIGNED NULL,      -- hours on top of the whole days, 0..23; 0 when the date has no time of day
    sla_days              DECIMAL(8,4)     NOT NULL,
    sla_ratio             DECIMAL(10,3)    NULL,      -- time open / SLA, not capped
    overdue               BOOLEAN          NULL,
    overdue_days          INT UNSIGNED     NULL,      -- whole days past the SLA; 0 until the SLA passes
    overdue_hours         TINYINT UNSIGNED NULL,      -- hours past the SLA on top of the whole days, 0..23
    keyword_found         BOOLEAN          NOT NULL,  -- FALSE = the term fell back to its default
    community_found       BOOLEAN          NOT NULL,
    sla_found             BOOLEAN          NOT NULL,
    PRIMARY KEY (run_id, service_request_id),
    KEY idx_scored_tickets_match (crew_pool, run_id, priority_rank),  -- jobs by service area for a run (reporting)
    KEY idx_scored_tickets_rank (run_id, priority_rank)
    -- No FK on crew_pool: dispatch capacity comes from workforce, not specialized pools.
);
