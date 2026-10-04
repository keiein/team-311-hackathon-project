# crew_pool

**Supply.** One row per crew pool: how many people it has and how many are out on jobs.

Database `dispatch_311`, created by `schema.sql` in this folder, `scoring/`.

The demand side: [SCORED_TICKETS.md](SCORED_TICKETS.md). Its `crew_pool` column points at this table.

| Column | Type | Meaning |
|---|---|---|
| `crew_pool` | VARCHAR(80), key | The ticket's `agency_responsible` under its current name |
| `total_people` | INT | Headcount |
| `busy_people` | INT, starts at 0 | People the match has drawn and not put back |
| `available_people` | INT, calculated | `total_people − busy_people` |

## Plus and minus

```sql
UPDATE crew_pool SET busy_people  = busy_people  + 3 WHERE crew_pool = 'OS - Mobility';  -- draw 3
UPDATE crew_pool SET busy_people  = busy_people  - 3 WHERE crew_pool = 'OS - Mobility';  -- put 3 back
UPDATE crew_pool SET total_people = total_people - 2 WHERE crew_pool = 'OS - Mobility';  -- 2 call in sick
```

MySQL refuses any update that leaves `busy_people` below 0 or above `total_people` (error 3819).

## The numbers

Placeholders. Each pool drew a whole number from 4 to 20 with `RAND(311)`, so every setup gets the same draw. They are not tied to workload.

| crew_pool | total_people |
|---|---|
| OS - Mobility | 20 |
| CS - Emergency Management and Community Safety | 16 |
| OS - Parks and Open Spaces | 14 |
| OS - Waste and Recycling Services | 14 |
| IS - Real Estate and Development Services | 12 |
| OS - Facility Management | 11 |
| OS - Calgary Transit | 10 |
| IS - Capital Planning and Business Services | 7 |
| OS - Water Services | 5 |
| OSC - Waste and Recycling Services | 5 |

To change the range, the seed, or draw again: see the comments in `schema.sql`.
