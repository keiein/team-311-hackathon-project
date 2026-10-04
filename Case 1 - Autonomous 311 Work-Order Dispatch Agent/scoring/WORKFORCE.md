# workforce

**Supply.** One shared operational workforce for the hackathon dispatch simulation.

Database `dispatch_311`, created by `schema.sql` in this folder, `scoring/`.

Existing database still on the old `crew_pool` table? Run `migrate_to_workforce.sql`.

The demand side: [SCORED_TICKETS.md](SCORED_TICKETS.md). Its `crew_pool` column is **service-area metadata for reporting**. It does **not** control whether a ticket can be dispatched.

## Hackathon assumption

For this simulation only (not a claim about real City of Calgary staffing):

- All available workers can perform any 311 work order.
- Every dispatched job uses `people_per_crew` people (default **5**).
- Available crews = `FLOOR(available_people / people_per_crew)`.
- Priority ranking still decides *which* tickets go first; workforce only decides *how many*.

## Columns

| Column | Type | Meaning |
|---|---|---|
| `workforce_id` | TINYINT, key | Always `1` for the single shared workforce |
| `total_people` | INT | **SIMULATED PLACEHOLDER** stable headcount (default 100). Not real City staffing. |
| `busy_people` | INT, starts at 0 | People currently assigned to active 311 jobs |
| `sick_people` | INT, starts at 0 | Temporarily unavailable because of sick calls |
| `snow_redeployed` | INT, starts at 0 | Temporarily on snow response (no dedicated snow crew) |
| `people_per_crew` | INT, default 5 | People required per work order |
| `available_people` | INT, generated | `total_people − busy_people − sick_people − snow_redeployed` |
| `available_crews` | INT, generated | `FLOOR(available_people / people_per_crew)` |

## Plus and minus

```sql
-- Job dispatched / completed (use people_per_crew from the row; do not hardcode 5 in app code)
UPDATE workforce SET busy_people = busy_people + people_per_crew WHERE workforce_id = 1;
UPDATE workforce SET busy_people = busy_people - people_per_crew WHERE workforce_id = 1;

-- Sick call / return
UPDATE workforce SET sick_people = sick_people + 3 WHERE workforce_id = 1;
UPDATE workforce SET sick_people = sick_people - 3 WHERE workforce_id = 1;

-- Snow redeployment / release (still the same shared workforce)
UPDATE workforce SET snow_redeployed = snow_redeployed + 30 WHERE workforce_id = 1;
UPDATE workforce SET snow_redeployed = snow_redeployed - 10 WHERE workforce_id = 1;
```

Do **not** reduce `total_people` for sick calls or snow redeployment. MySQL refuses negative counts and refuses `busy + sick + snow > total_people` (error 3819).

## Capacity examples

| Scenario | busy | sick | snow | available_people | available_crews |
|---|---:|---:|---:|---:|---:|
| Normal | 0 | 0 | 0 | 100 | 20 |
| Sick call (7) | 0 | 7 | 0 | 93 | 18 |
| Blizzard (7 sick + 30 snow) | 0 | 7 | 30 | 63 | 12 |

## Conceptual dispatch flow

```
open scored tickets
        ↓
sort by existing priority_rank
        ↓
read available_crews from workforce
        ↓
dispatch highest-priority tickets first (one crew per ticket)
        ↓
remaining tickets stay waiting/deferred
```

No crew specialization. No matching on `scored_tickets.crew_pool`.
