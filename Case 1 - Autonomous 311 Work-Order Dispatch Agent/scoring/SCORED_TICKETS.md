# scored_tickets

**Demand.** One row per ticket per scoring run. Key: (`run_id`, `service_request_id`).

Database `dispatch_311`, created by `schema.sql`. Filled by `load_scored_tickets.py`. Both are in this folder, `scoring/`.

How the scores are worked out: [PRIORITY_SCORING.md](PRIORITY_SCORING.md). The supply side: [WORKFORCE.md](WORKFORCE.md) (shared workforce; not specialized pools).

## Loading it

From this folder:

```
python load_scored_tickets.py                     # score open_tickets.csv on the machine clock
python load_scored_tickets.py --now 2026-10-02    # score as of the file's snapshot date
```

- **Every load is a new run.** It takes the next free `run_id`; earlier runs are kept.
- **A run keeps the scoring it was loaded with.** Changing a weight or a keyword in `priority_score.py` does not touch runs already in the table: they go on showing the old scores. After any change to the scorer, load again and read the latest run.
- **All or nothing.** If one row is refused, none of the run is written.
- **Connection:** `root` on `127.0.0.1:3306` with no password. Set `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD` or `MYSQL_DATABASE` to change it.
- **From code:** `load(scorer.score_frame(tickets), scored_at)` returns the `run_id`.

## Columns

| Column | Type | Meaning |
|---|---|---|
| `run_id` | INT | One scoring run: the morning plan, the replan |
| `service_request_id` | VARCHAR(20) | The ticket's key |
| `scored_at` | DATETIME | The clock the age score used |
| `service_name` | VARCHAR(100) | What the job is |
| `requested_date` | DATETIME, null | When it was opened |
| `comm_code` | VARCHAR(8), null | The City's 3-character community code |
| `comm_name` | VARCHAR(60), null | Community name |
| `longitude`, `latitude` | DECIMAL, null | The community's centre point, not the job's address |
| `crew_pool` | VARCHAR(80) | Responsible City service area (metadata for reporting). Does **not** gate dispatch; no FK to a supply table |
| `work_category` | VARCHAR(60) | The kind of work within that service area |
| `call_confidence` | VARCHAR(12) | Clear or Borderline |
| `priority` | DECIMAL(12,6) | The total score. No upper limit, because the age score has none |
| `priority_rank` | INT | 1 = first |
| `basic_knowledge_score`, `geo_score` | DECIMAL(7,6) | Two of the four terms, 0 to 1 |
| `age_score` | DECIMAL(12,6) | Time open ÷ SLA. 1 = at the SLA, no upper limit |
| `ticket_count_score` | DECIMAL(7,6), null | The fourth term, 0 to 1. Empty only on a run loaded before the term existed |
| `criticality_tier` | TINYINT | 4 = safety, 3 = disruption, 2 = nuisance, 1 = routine |
| `criticality_keywords` | VARCHAR(255) | The words that set the tier |
| `same_day_ticket_count` | INT, null | Tickets of the run for the same job, day and place, this one included. Empty on a run loaded before the column existed |
| `open_days`, `open_hours` | INT, null | Time open |
| `sla_days` | DECIMAL(8,4) | The deadline for the service type |
| `sla_ratio` | DECIMAL(10,3), null | Time open ÷ SLA, not capped |
| `overdue` | BOOLEAN, null | Past its SLA |
| `overdue_days`, `overdue_hours` | INT, null | Time past the SLA. Both 0 until the SLA passes |
| `keyword_found`, `community_found`, `sla_found` | BOOLEAN | FALSE = that term fell back to its default |

- **Added by the loader:** `run_id`, `scored_at` and `priority_rank`. The scorer doesn't return them.
- **The file needs `crew_pool`, `work_category` and `call_confidence`.** `open_tickets.csv` has them. The small sample doesn't, so the loader refuses it and writes nothing.
- **A table made from an older `schema.sql`** needs the `ALTER TABLE` lines written above the `scored_tickets` table in `schema.sql`. They add `same_day_ticket_count`, `overdue_days` and `overdue_hours`, and widen `priority` and `age_score`. A database built from the current file needs nothing.
- **Rank order:** `priority` high to low, then `open_days` high to low, then `service_request_id`.
- **Scores are rounded** to 6 decimals on the way in.

## Jobs for one service area, best first (reporting)

`crew_pool` here is metadata only. Dispatch capacity comes from `workforce.available_crews`.

```sql
SELECT service_request_id, service_name, comm_code, priority
FROM scored_tickets
WHERE run_id = (SELECT MAX(run_id) FROM scored_tickets) AND crew_pool = 'OS - Mobility'
ORDER BY priority_rank;
```
