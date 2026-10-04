# crew_pool (retired as supply)

The MySQL **`crew_pool` supply table has been replaced** by a single shared [`workforce`](WORKFORCE.md) table.

`scored_tickets.crew_pool` still exists. It is **metadata** for the responsible City service area (useful for reporting). It is **not** a foreign key and does **not** control dispatch eligibility.

See [WORKFORCE.md](WORKFORCE.md) for the current supply model, sick-call / snow redeployment rules, and capacity examples.

If your local database still has the old table or the foreign key `fk_scored_tickets_crew_pool`, run:

```
mysql -u root -p dispatch_311 < migrate_to_workforce.sql
```
