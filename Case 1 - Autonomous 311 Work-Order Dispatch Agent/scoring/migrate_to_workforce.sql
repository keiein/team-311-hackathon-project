-- Migrate an existing dispatch_311 database from the old per-pool crew_pool supply
-- model to the shared workforce table.
--
-- Safe for scored ticket data: does NOT drop or truncate scored_tickets.
--
-- Run it:  mysql -u root -p dispatch_311 < migrate_to_workforce.sql
--     or:  mysql -u root -p -e "source migrate_to_workforce.sql"
--
-- Order matters: drop the foreign key before dropping crew_pool.

USE dispatch_311;

-- 1) Remove FK scored_tickets.crew_pool -> crew_pool.crew_pool (if still present).
--    crew_pool remains on scored_tickets as service-area metadata for reporting.
SET @fk_exists := (
    SELECT COUNT(*)
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'scored_tickets'
      AND CONSTRAINT_NAME = 'fk_scored_tickets_crew_pool'
      AND CONSTRAINT_TYPE = 'FOREIGN KEY'
);

SET @sql := IF(
    @fk_exists > 0,
    'ALTER TABLE scored_tickets DROP FOREIGN KEY fk_scored_tickets_crew_pool',
    'SELECT ''fk_scored_tickets_crew_pool already absent'' AS migrate_note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2) Drop the old supply table (no longer used for dispatch capacity).
DROP TABLE IF EXISTS crew_pool;

-- 3) Create the shared workforce table (hackathon simulation).
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

-- 4) Seed the single simulated workforce row if missing.
--    total_people = 100 is a SIMULATED PLACEHOLDER, not real City staffing.
INSERT IGNORE INTO workforce (workforce_id, total_people, busy_people, sick_people, snow_redeployed, people_per_crew)
VALUES (1, 100, 0, 0, 0, 5);

-- 5) Quick capacity check (optional verification after migrate):
--    NORMAL:    100 people, 0 unavailable => 20 crews
--    SICK:      7 sick                     => 93 usable => 18 crews
--    BLIZZARD:  7 sick + 30 snow           => 63 usable => 12 crews
SELECT workforce_id, total_people, busy_people, sick_people, snow_redeployed,
       people_per_crew, available_people, available_crews
FROM workforce
WHERE workforce_id = 1;
