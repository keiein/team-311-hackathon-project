-- MySQL schema for the 311 dispatcher. Needs MySQL 8.0.16 or later (older versions ignore CHECK).
--
--     crew_pool        supply: one row per crew pool, with how many people it has and how many are out on jobs
--     scored_tickets   demand: one row per ticket per scoring run, as priority_score.py scores it
--
-- Run it:  mysql -u root -p -e "source schema.sql"
-- Safe to run again: tables that exist are kept, and so are the crew numbers already drawn.

CREATE DATABASE IF NOT EXISTS dispatch_311 CHARACTER SET utf8mb4;
USE dispatch_311;


-- ---- supply: the crew pools ----
-- A pool is the ticket's agency_responsible under its current name (the crew_pool column of open_tickets.csv).
-- The MATCH moves the numbers:
--     draw 3 people        UPDATE crew_pool SET busy_people = busy_people + 3 WHERE crew_pool = 'OS - Mobility';
--     put 3 back           UPDATE crew_pool SET busy_people = busy_people - 3 WHERE crew_pool = 'OS - Mobility';
--     a crew calls in sick UPDATE crew_pool SET total_people = total_people - 2 WHERE crew_pool = 'OS - Mobility';
-- available_people follows on its own. A draw of more people than are available is refused (chk_crew_pool_people).
CREATE TABLE IF NOT EXISTS crew_pool (
    crew_pool        VARCHAR(80) NOT NULL,           -- the pool's name; scored_tickets.crew_pool points here
    total_people     INT         NOT NULL,           -- headcount of the pool
    busy_people      INT         NOT NULL DEFAULT 0, -- people the MATCH has drawn and not yet put back
    available_people INT GENERATED ALWAYS AS (total_people - busy_people) VIRTUAL,
    PRIMARY KEY (crew_pool),
    CONSTRAINT chk_crew_pool_people CHECK (total_people >= 0 AND busy_people BETWEEN 0 AND total_people)
);

-- ---- crew numbers (placeholder: random until the real headcounts are known) ----
-- Each pool gets a whole number from @min_people to @max_people, whatever its workload.
-- RAND(311) is seeded, so every setup draws the same numbers. Change the seed for a different draw.
-- To draw again on a table that is already filled:
--     UPDATE crew_pool SET busy_people = 0, total_people = FLOOR(@min_people + RAND() * (@max_people - @min_people + 1));
SET @min_people = 4, @max_people = 20;

-- The 10 pools are every crew_pool on the crew jobs of open_tickets.csv.
INSERT IGNORE INTO crew_pool (crew_pool, total_people)
SELECT pool, FLOOR(@min_people + RAND(311) * (@max_people - @min_people + 1))
FROM (
    SELECT 'OS - Mobility' AS pool
    UNION ALL SELECT 'OS - Parks and Open Spaces'
    UNION ALL SELECT 'OS - Water Services'
    UNION ALL SELECT 'CS - Emergency Management and Community Safety'
    UNION ALL SELECT 'OS - Calgary Transit'
    UNION ALL SELECT 'OS - Waste and Recycling Services'
    UNION ALL SELECT 'OSC - Waste and Recycling Services'
    UNION ALL SELECT 'IS - Real Estate and Development Services'
    UNION ALL SELECT 'IS - Capital Planning and Business Services'
    UNION ALL SELECT 'OS - Facility Management'
) AS pools;


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
    -- matching to supply
    crew_pool             VARCHAR(80)      NOT NULL,  -- which pool can take the job
    work_category         VARCHAR(60)      NOT NULL,  -- the kind of work within the pool
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
    KEY idx_scored_tickets_match (crew_pool, run_id, priority_rank),  -- a pool's jobs for a run, best first
    KEY idx_scored_tickets_rank (run_id, priority_rank),
    CONSTRAINT fk_scored_tickets_crew_pool FOREIGN KEY (crew_pool) REFERENCES crew_pool (crew_pool)
);
