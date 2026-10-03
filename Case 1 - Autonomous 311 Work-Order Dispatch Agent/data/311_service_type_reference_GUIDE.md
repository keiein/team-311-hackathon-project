# 311 Service Type Reference: Guide

**File:** `data/311_service_type_reference.xlsx`
**Built from:** `data/311_Service_Requests_20261002.zip`, the full City of Calgary 311 export. It has 1,936,033 tickets, requested Jan 2, 2023 to Oct 1, 2026.

> Do not use the 245 MB CSV in the repo root. It stops at 1,048,575 rows (Excel's row limit), so about 46% of the tickets are missing.

## What this file is

It's a fact sheet with **one row per 311 service type**, such as "Roads - Pothole Maintenance". For each type it shows how many tickets came in, how many are still open, and how fast the City usually closes them.

It has **no severity scores**. Severity tiers come from our own research and get added on top. This file tells you which types to research, where the backlog is, and what the City's normal turnaround is.

Each type is also marked **Crew** or **Non-crew**. The case is about *dispatching crews*, so only crew types belong in the dispatcher's queue.

## Tabs

| Tab | What it shows | Rows |
|---|---|---|
| **Service Types** | Every service type that has ever existed, sorted by agency, then by total tickets. The original columns are unchanged (A to P); the crew call is added on the right (Q to T, green headers) | 740 |
| **2026 Remaining Services** | All service types with at least 1 ticket in 2026, sorted by 2026 tickets. A `work_type` column (Crew / Non-crew) is added at the end | 456 |
| **Crew - 2026** | Crew types only, with at least 1 ticket in 2026, sorted by 2026 tickets, largest first. **Start here for the dispatcher.** | 82 |
| **Crew - All Years** | Crew types only, all years 2023 to 2026 (including retired types), sorted by total tickets, largest first | 107 |
| **Crew by Community** | One row per community: crew tickets in 2026 and in all years, open tickets, 2021 population, area, density, density rank and the geography score (0.3 to 1.0) | 317 |
| **Crew 2026 Pivot** | Grid of communities (rows) × the 82 crew service types (columns), filled with 2026 tickets, with totals | 317 × 82 |
| **Pivot Data (Crew)** | One row per community + crew service type. Feeds the two tabs above; use it with Insert > PivotTable for your own views | 20,659 |
| **Multi-Agency Flags** | Types whose tickets carry more than one agency name, and why | 382 types |

The 284 types that aren't on the 2026 tabs have no tickets this year. They've been retired or renamed. For example, the Parks "- WAM" types were replaced by "- GIS" versions, and the "Finance - …" tax types were replaced by "AT - …".

## Crew vs non-crew

**A crew job** needs a City (or City-contracted) work crew to physically go to a location and do hands-on work on public property: repair, maintain, clean, remove, collect, clear snow or ice, or respond to a utility failure. It can go on a crew's daily work list.

Examples: potholes, missed garbage pickups, graffiti removal, broken streetlights, water main breaks, City tree concerns.

**Not a crew job:**

- **Desk work:** questions, billing and tax, bookings, applications, permits, feedback, programs.
- **Officers:** bylaw, animal services, licensing and transit peace officers do go out, but they issue notices or fines. They aren't work crews. For example, long grass on private property is an officer's notice to the owner, while City mowing is "Parks - Mowing Request" (crew).
- **Inspectors:** building and fire inspectors assess or approve. No repair work.
- **Planners and engineers:** requests for *new* infrastructure (new signals, new sidewalks) or project questions take weeks to months, not a dispatch.
- **Private operators:** shared e-scooters and e-bikes are handled by the vendor.

**Borderline calls.** `call_confidence` = Borderline means either the type is a mix of crew and non-crew work, or the field visit isn't really a repair:

- A mix: "CT - Bus Stops" covers stop repairs but also requests for new stops.
- Not a repair: booked water meter installs, or bylaw snow-on-sidewalk notices.

Each borderline type has its own reason in the `why` column. 56 types are borderline (32 marked crew, 24 marked non-crew).

**To flip a call,** change `work_type` on the Service Types tab. The two Crew tabs are fixed lists, so a flipped type won't move onto or off them until they're rebuilt.

### How much smaller the dispatch scope gets

| | All types | Crew only | Crew share |
|---|---|---|---|
| Service types, all years | 740 | 107 | 14% |
| Service types with 2026 tickets | 456 | 82 | 18% |
| Tickets, all years | 1,936,033 | 926,871 | 48% |
| Tickets in 2026 | 387,422 | 204,705 | 53% |
| Open now (2026 types) | 44,158 | 26,474 | 60% |
| Open > 60 days (2026 types) | 30,447 | 20,262 | 67% |

Only 18% of active types are crew work, but they carry about half the tickets and two-thirds of the stuck backlog.

**Where the crew work sits in 2026:**

| Crew pool | Types | 2026 tickets | Open now | Open > 60 days |
|---|---|---|---|---|
| OS - Mobility (Roads) | 22 | 63,237 | 21,657 | 18,569 |
| OS - Waste and Recycling Services | 11 | 62,590 | 408 | 0 |
| OS - Parks and Open Spaces | 15 | 28,456 | 1,646 | 696 |
| OS - Water Services | 22 | 25,243 | 1,116 | 402 |
| CS - Emergency Mgmt & Community Safety (graffiti, encampments) | 2 | 16,475 | 1,005 | 458 |
| OS - Calgary Transit (stops, stations, snow) | 3 | 4,008 | 567 | 110 |
| Others (GFL contract collection, City land, structures, facilities) | 7 | 4,696 | 75 | 27 |

Roads holds 82% of the open crew backlog. Waste collection is high volume but closes within days, so Roads is where prioritizing pays off most.

## How the numbers were calculated

- **Dates.** A ticket starts on `requested_date` and ends on `closed_date`. Every timestamp is a date with no time attached, so durations are whole days. Closed the same day = 0 days.
- **Days-to-close.** Only tickets with status "Closed" count. Tickets closed as duplicates are left out, since they were never actually fixed.
- **Excluded from days-to-close:** 64 Closed tickets that took more than 3 years (1,095 days). No ticket had a negative duration, and every Closed ticket has a close date.
- **Open.** Status = "Open". Ticket age is counted up to **Oct 2, 2026**, the export date.
- **Agency.** The agency that appears most often on that type's tickets.

## Columns: what they mean and how to use them

The example numbers are from **Roads - Pothole Maintenance**.

### Use these

| Column | What it means | Example | How to use it |
|---|---|---|---|
| `service_name` | The 311 service type | Roads - Pothole Maintenance | This is what we assign a severity tier to |
| `agency_responsible` | The agency that handles it | OS - Mobility | Which crew pool the ticket goes to. A Roads crew can't fix a water main |
| `tickets_2026` | Tickets requested in 2026 (Jan 1 to Oct 1) | 7,889 | How common the problem is now. Research the big ones first |
| `total_tickets` | Tickets over all years (2023 to 2026) | 34,790 | Long-run volume |
| `open_now` | Tickets still open today | 990 | How big the queue is that the dispatcher has to rank |
| `open_now_gt60d` | Open tickets older than 60 days | 924 | Stuck tickets. If this is close to `open_now`, the type has a backlog |
| `closed_tickets_used` | How many closed tickets the day counts are based on | 30,396 | If this is under about 30, don't trust the median |
| `median_days_to_close` | The middle closing time: half close faster, half slower | 1 day | The City's normal turnaround, i.e. what it already treats as urgent |
| `mean_days_to_close` | The average closing time | 5.9 days | Compare it to the median. A big gap means some tickets sit for months |
| `p90_days_to_close` | 90% of tickets close within this many days | 6 days | A per-type deadline for the age part of the score |

### Crew columns (added on the right, green headers)

| Column | What it means | Example | How to use it |
|---|---|---|---|
| `work_type` | Crew or Non-crew | Crew | Only crew types go into the dispatcher's queue |
| `work_category` | The kind of crew work, or why it isn't crew work | Road & structure repair | Group similar types when assigning tiers |
| `call_confidence` | Clear or Borderline | Clear | Review the borderline ones as a team |
| `why` | One-line reason for the call | A crew physically repairs a road… | Use it when judges ask why something was left out |

### You can ignore these

| Column | What it means |
|---|---|
| `agency_count` | How many different agency names appear on this type's tickets. It's almost always 2 because the City renamed its departments in May 2023 (TRAN - Roads became OS - Mobility). Same team, new name. |
| `p90_own`, `p90_flag` | A check that this file's p90 matches the earlier `service_catalog.csv`. Every row reads OK (the largest gap is 4 days), apart from 2 types that have no closed tickets yet. |
| `pct_of_agency_volume` | This type's share of all tickets in its agency. All OS - Mobility types add up to 341,145 tickets, and potholes are 34,790 of those, so 10.2%. |
| `cumulative_pct` | A running total of that share, going down the list from the biggest type. Potholes 10.2%, plus Snow & Ice 18.4%, plus Debris 25.7%, plus Signs 32.3%. In other words, the top 4 types are a third of all Roads tickets. |
| `in_core_set` | TRUE if the type is inside the top 95% of its agency's tickets. It's only a shortcut for building a shorter research list, and it says nothing about severity. |

## Communities and population density

The **Crew by Community** tab has one row per community. A community is the `comm_code` / `comm_name` on each ticket, the same unit the City publishes population for.

| Column | What it means |
|---|---|
| `crew_tickets_2026` | Crew tickets requested in 2026 in this community |
| `crew_tickets_all_years` | Crew tickets 2023 to 2026 |
| `crew_open_now`, `crew_open_gt60d` | Crew tickets still open, and those open more than 60 days |
| `area_note` | Why a community has no population: residual sub-area, industrial/business area, park, built after 2021, or not in the census |
| `population_2021` | People in private households, 2021 Federal Census by Community (City of Calgary open data) |
| `area_km2` | Area of the community's 2021 census boundary, calculated from its shape |
| `population_density` | People per km² (population ÷ area) |
| `density_rank` | 1 = densest of the 206 communities with a population count |
| `density_percentile` | Share of populated communities that are less dense (0% to 100%) |
| `geo_score` | **The geography score for the dispatcher:** floor + (1 − floor) × density_percentile. Densest = 1.00, least dense = 0.30 |
| `crew_2026_per_1000_people` | Crew tickets per 1,000 residents |
| `traffic_flow_notes` (yellow) | Free text; traffic volume is published per road segment, not per community |
| `source` | Where the population and area came from |

**How the geography score works**

- It uses the density **rank**, not raw density. A handful of inner-city communities are 5 to 10 times denser than the suburbs, so raw density would push almost everyone near the floor. With the rank, scores spread evenly from 0.3 to 1.0.
- **The floor is 0.3** and sits in a yellow cell on the Crew by Community tab (U12). Change it and every score updates.
- These get the floor:
  - the least dense populated community
  - the 107 areas with no 2021 count
  - 3 communities not in the 2021 census (Ambleton, 01I, 12I)
  - the "no community recorded" row
- **Examples:**
  - Lower Mount Royal is the densest (about 10,500 people/km²), score 1.00.
  - Beltline: rank 3, score 0.99.
  - Bowness: rank 158, score 0.46.
  - Cranston: rank 115, score 0.61.

**Known limits**

- **2021 is the newest population count by community.** The City's own civic census stops at 2019.
- **Communities built after 2021 get the floor even though people live there now.** Rangeview, Glacier Ridge, Haskayne and Hotchkiss each had 470 to 740 crew tickets in 2026. To override, type a newer population into `population_2021` for that row.
- **The census counts private households only.** Care homes and student residences aren't included, so the University of Calgary shows no population.
- **Industrial areas sit at the floor by design.** Manchester Industrial, for example, had 1,002 crew tickets in 2026. That's the trade-off of scoring by residents rather than traffic.

- **Data fixes applied:**
  - 4 residual-area tickets had a community name but no code; they were given their code.
  - "SCARBORO/ SUNALTA WEST" was merged into "SCARBORO/SUNALTA WEST".
- **Tickets with no community:** 1,445 crew tickets (258 in 2026). They're grouped in the last row.

The **Crew 2026 Pivot** tab is a ready-made grid: communities down the side, the 82 crew service types across the top, 2026 tickets in each cell (darker green = more). Row and column totals tie back to the Crew - 2026 tab (204,705 tickets).

For your own pivot, click inside **Pivot Data (Crew)** and choose Insert > PivotTable. A useful setup is Rows = comm_name, Columns = service_name, Values = Sum of tickets_2026.

## How the score fits together

For each **open crew ticket**:

`priority = severity weight (by service type) × geography weight (by community) × age weight (by days open)`

1. **Severity:** your tier research for each crew service type (Crew - 2026 tab).
2. **Geography:** `geo_score` on Crew by Community (0.3 to 1.0, by density rank, floor 0.3).
3. **Age:** ticket age ÷ the type's `p90_days_to_close`, capped so it never outweighs severity.

Then rank the open tickets within each crew pool (`agency_responsible`), give the top ones to the available crews, and compare against oldest-first.

## How to use it for the dispatcher

**1. Pick what to research.**
- Open the **Crew - 2026** tab: 82 types, already without inquiries, bookings, officers and planning requests. Filter `agency_responsible` to your crew pool(s), such as OS - Mobility.
- Start with the `Clear` rows, then decide the 24 `Borderline` crew rows as a team.
- "Roads - NEW Signal…" requests are already left out. They're requests to *build* new signals, which is planning work, not repair. All 2,071 open ones are older than 60 days, and the median close is 325 days.

**2. Sanity-check your severity tiers against the City's turnaround.**
- If the City closes a type in 0 to 1 days, it already treats it as urgent. Examples: potholes (1 day), sewage back-ups (0 days).
- Careful: a 0-day median can mean the ticket was *passed on*, not fixed. Streetlights (0 days) are probably handed to the power utility.

**3. Find the pitch: high severity, slow to close.**
- Look for types you rate as severe that the City is slow on. These are where our score beats oldest-first.
- **Roads - Signs - Missing - Damaged:** median 145 days, 3,812 open, 3,328 of them older than 60 days. A missing stop sign is a safety risk.
- **Roads - Sidewalk - Curb and Gutter Repair:** median 4 days but mean 47, with 4,690 open (4,680 older than 60 days). Most get fixed fast, but a long tail gets stuck.

**4. Use p90 as a per-type deadline in the age part of the score.**
- `age_ratio = ticket age in days ÷ p90_days_to_close`. A value above 1 means the ticket is overdue for its type.
- Example: a 10-day-old pothole has an age ratio of 10 ÷ 6 = 1.7, so it's overdue.
- Cap the age boost so it can never outweigh severity. Otherwise the score turns back into oldest-first, because thousands of open tickets are more than a year old.
- When p90 is huge (signs: 393 days), it reflects the City's backlog, not a sensible deadline. Set your own target for those types.

**5. Size the day's queue.**
`open_now` and `open_now_gt60d` show where the open work actually sits. Very old open tickets should go to a "needs review" list instead of the day's queue.

## Data caveats

- **2026 is a partial year.** The data runs to Oct 1, 2026, so `tickets_2026` covers 9 months. Snow and ice volume will grow over the winter.
- **Near-duplicate names.** These pairs are the same service under two spellings. Treat each pair as one type when tiering:
  - "Roads - NEW Signal, Left Turn or Pedestrian Light Request" / "Roads - New Signal, …" (case only)
  - "Roads - Traffic Signal Operation Report - Intersection Pla" / "…Plan" (cut-off name)
  - "Recreation - Arena Tournament and Special Event Applicatio" / "…Application" (cut-off name)
  - "Comm Strategies - Disability/Accessibility - Meeting & Eve" / "…Event" (cut-off name)
- **Old agency names.** Agency names are shown as they appear in the data, not mapped to today's names. Two active types show an old name as their most common agency:
  - Green Line Inquiry is now handled by IS - Green Line LRT - SE Project.
  - CHO - Affordable Housing is now handled by CS - Chief Housing Office.
- **Dead backlog.** 12,766 open tickets belong to types with no 2026 tickets. For example, "311 Contact Us" has 12,549 open and none new this year. They inflate the open count, and the dispatcher shouldn't treat them as live work.
- **Open tickets with a close date.** 4,192 tickets are marked Open but have a close date. They're counted as open, going by status.
- **Missing agency.** 299 tickets have no agency. 7 "CPI -" types have none at all and are listed under "(blank)".

## Editing and refreshing

- The yellow cells on the **Service Types** tab (W2 to W4) set the 95% cutoff and the p90-flag thresholds. Changing them updates the formulas.
- The two Crew tabs and **2026 Remaining Services** pull their numbers by formula from **Service Types**, so they always agree.
- Changing a `work_type` on Service Types doesn't add or remove rows on the Crew tabs. Ask for a rebuild if you flip several.
- The counts and day figures are fixed values calculated in Python from the zip. If a newer 311 export comes in, the workbook has to be rebuilt from that export.
