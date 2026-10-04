# crew_pool (retired as supply)

The MySQL **`crew_pool` supply table has been replaced** by a single shared [`workforce`](WORKFORCE.md) table.

`scored_tickets.crew_pool` / GeoJSON `crewPool` still exist. They are **metadata** for the responsible City service area (useful for reporting and filters). They are **not** a foreign key and do **not** control dispatch eligibility or capacity.

## Frontend supply

The Crews page reads `frontend/public/data/workforce.json`, produced by:

1. `backend/export_team_scores.py` (MySQL `workforce` when reachable, else schema placeholder 100 / 5)
2. `backend/make_dispatch_standin.py` (updates busy/sick after the stand-in plan)

There is **no** per-department headcount table feeding the UI anymore.

If your local database still has the old table or the foreign key `fk_scored_tickets_crew_pool`, run:

```
mysql -u root -p dispatch_311 < migrate_to_workforce.sql
```
