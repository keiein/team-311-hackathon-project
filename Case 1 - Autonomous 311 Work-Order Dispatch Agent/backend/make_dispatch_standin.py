"""
MAKE DISPATCH: today's plan on the team's crew_pool model, the comparison and the improvement loop
===================================================================================================

The crew side follows Alvin's design in scoring/CREW_POOL.md, scoring/schema.sql and the
data guide ("rank the open tickets within each crew pool, give the top ones to the available
crews, and compare against oldest-first"):

    SUPPLY   One row per crew pool (department): total_people, busy_people, available_people.
             The headcounts are Alvin's placeholders (schema.sql draws them with RAND(311)).
    MATCH    Rank the jobs inside each pool by the team priority score. The pool's crews take
             turns picking. Every crew sent out "draws" its people (busy_people + 2).
    SICK     "A crew calls in sick: total_people - 2" (schema.sql). At noon one crew is lost,
             and its unfinished jobs are re-planned inside the same pool.

Two numbers are NOT written in Alvin's files, so they are settings here, stated openly:
    PEOPLE_PER_CREW = 2   from schema.sql's example ("a crew calls in sick: total_people - 2")
    JOBS_PER_CREW   = 5   from the case ("C crews x K jobs") and the organizers' starter (K = 5)

What it does, in plain words:
    1. Reads today's scored jobs (frontend/public/data/requests.geojson, the team score) and the
       crew pools (frontend/public/data/crew_pools.json). Both come from export_team_scores.py.
    2. OLD WAY (baseline): each pool's crews take the OLDEST jobs of their pool.
    3. OUR WAY: each pool's crews take turns picking the best-scoring job of their pool, with a small
       "distance penalty" for jobs far from the crew's first job.
    4. THE LOOP: tries several distance-penalty settings, scores each whole plan, keeps the best.
          plan quality = total priority points planned  -  0.2 x total km driven
    5. NOON: one crew calls in sick (the crew with the most high-priority work still to do).
       Its unfinished jobs (stops 3 to 5), most important first, each take the slot of the least
       important unfinished job of another crew in the SAME pool, but only if they are more
       important. Otherwise they wait until tomorrow. Bumped jobs also wait until tomorrow.
       Assumption: every crew finished its first 2 stops before noon.

How to run it (from the project folder, after export_team_scores.py):
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/make_dispatch_standin.py"

What comes out (in frontend/public/data/):
    dispatch.json    the Dispatch page and the Crews page read this
    reports.json     the Reports page reads this
    routes.geojson   one line per crew through its 8 a.m. stops, for the Dashboard map
    crew_pools.json  updated with each pool's crews, busy and available people at 8 a.m. and after noon
"""

import json
import math
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DATA_DIR = REPO_ROOT / "frontend" / "public" / "data"
REQUESTS_FILE = DATA_DIR / "requests.geojson"
POOLS_FILE = DATA_DIR / "crew_pools.json"
DISPATCH_FILE = DATA_DIR / "dispatch.json"
REPORTS_FILE = DATA_DIR / "reports.json"
ROUTES_FILE = DATA_DIR / "routes.geojson"

# =============================================================================
# SETTINGS
# =============================================================================
AS_OF = "2026-10-02"           # the day the team's data was exported
PEOPLE_PER_CREW = 2            # schema.sql: "a crew calls in sick: total_people - 2"
JOBS_PER_CREW = 5              # the case's "K jobs"; organizers' starter JOBS_PER_CREW = 5
DONE_BY_NOON = 2               # each crew finished its first 2 stops by noon

# Short names for the crews of each pool (crew "Roads 3" belongs to pool "OS - Mobility")
POOL_SHORT = {
    "OS - Mobility": "Roads",
    "OS - Parks and Open Spaces": "Parks",
    "OS - Water Services": "Water",
    "OS - Waste and Recycling Services": "Waste",
    "OSC - Waste and Recycling Services": "Waste OSC",
    "CS - Emergency Management and Community Safety": "Community Safety",
    "OS - Calgary Transit": "Transit",
    "IS - Real Estate and Development Services": "Real Estate",
    "IS - Capital Planning and Business Services": "Capital Planning",
    "OS - Facility Management": "Facilities",
}

# The loop tries these settings. 0 = look at priority only (the "first try").
# Penalty = points lost per km from the crew's first job.
# With the team scorer, one severity tier is worth 12 points (0.40 weight x 0.30 step x 100).
# So a job one tier lower only wins if it is more than 12 / penalty km closer:
#   0.2 -> 60 km (never, inside Calgary), 0.4 -> 30 km, 0.8 -> 15 km, 1.6 -> 7.5 km.
# The loop's quality score (below) counts priority points, so it notices when a setting gives up
# important jobs just to save driving.
LOOP_PENALTIES = [0.0, 0.2, 0.4, 0.8, 1.6]
KM_COST = 0.2                  # in the plan quality score: points lost per km driven

# Route colours: one per pool (the 8 pools with the most crews), the rest gray
POOL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#737373"


def km_between(a, b):
    """Straight-line km between two (lon, lat) points (haversine)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def importance(job):
    """Compared left to right: priority score first, then days waiting."""
    return (job["priorityScore"], job["daysWaiting"] or 0)


def load_jobs():
    """All jobs on the Requests page, as plain dicts. Each job's pool is its crewPool."""
    features = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))["features"]
    jobs = []
    for f in features:
        p = f["properties"]
        jobs.append({
            "id": p["id"], "serviceType": p["serviceType"], "community": p["community"],
            "priorityScore": p["priorityScore"], "priorityBand": p["priorityBand"],
            "daysWaiting": p["daysWaiting"], "pool": p["crewPool"], "where": tuple(f["geometry"]["coordinates"]),
        })
    return jobs


def load_pools():
    """Alvin's crew pools: {pool name: total_people}."""
    data = json.loads(POOLS_FILE.read_text(encoding="utf-8"))
    return data, {p["pool"]: p["people"] for p in data["pools"]}


# =============================================================================
# SUPPLY AND THE TWO PLANS
# =============================================================================
def make_crews(people_by_pool):
    """Each pool's people, grouped into crews of PEOPLE_PER_CREW."""
    crews = []
    for pool, people in people_by_pool.items():
        short = POOL_SHORT.get(pool, pool)
        for i in range(people // PEOPLE_PER_CREW):
            crews.append({"name": f"{short} {i + 1}", "kind": short, "pool": pool, "jobs": []})
    return crews


def take_turns(crews, jobs, choose):
    """Inside each pool, crews take turns picking (like picking teams in gym class)."""
    pools = {c["pool"] for c in crews}
    left = {pool: [j for j in jobs if j["pool"] == pool] for pool in pools}
    for stop in range(1, JOBS_PER_CREW + 1):
        for crew in crews:
            candidates = left[crew["pool"]]
            if not candidates:
                continue
            pick, why = choose(crew, candidates, stop)
            candidates.remove(pick)
            crew["jobs"].append({**pick, "stop": stop, "crew": crew["name"], "kind": crew["kind"], "why": why})
    return crews


def build_our_plan(jobs, people_by_pool, km_penalty):
    ranked = sorted(jobs, key=importance, reverse=True)

    def choose(crew, candidates, stop):
        if stop == 1 or not crew["jobs"]:
            return candidates[0], f"Highest-priority {crew['kind']} job left"
        home = crew["jobs"][0]["where"]
        # best score after the distance penalty; ties go to the longer wait
        pick = max(candidates, key=lambda j: (j["priorityScore"] - km_penalty * km_between(home, j["where"]),
                                              j["daysWaiting"] or 0))
        return pick, f"Next-highest {crew['kind']} priority, {km_between(home, pick['where']):.1f} km from stop 1"

    return take_turns(make_crews(people_by_pool), ranked, choose)


def build_oldest_first_plan(jobs, people_by_pool):
    """The OLD WAY: each crew takes the oldest job of its pool. Priority and distance are ignored."""
    oldest = sorted(jobs, key=lambda j: (-(j["daysWaiting"] or 0), j["id"]))
    return take_turns(make_crews(people_by_pool), oldest, lambda crew, cands, stop: (cands[0], "Oldest job left"))


def plan_metrics(crews):
    """Plain numbers that describe one plan."""
    jobs = [j for c in crews for j in c["jobs"]]
    working = [c for c in crews if c["jobs"]]
    km_per_crew = [sum(km_between(a["where"], b["where"]) for a, b in zip(c["jobs"], c["jobs"][1:])) for c in working]
    points = sum(j["priorityScore"] for j in jobs)
    km_total = sum(km_per_crew)
    return {
        "planned": len(jobs),
        "high": sum(j["priorityBand"] == "High" for j in jobs),
        "points": points,
        "avgPriority": points / len(jobs),
        "avgDays": sum(j["daysWaiting"] or 0 for j in jobs) / len(jobs),
        "kmPerCrew": km_total / len(working),
        "quality": points - KM_COST * km_total,
    }


def run_loop(jobs, people_by_pool):
    """Try each setting, keep the best plan. Returns (best crews, best penalty, table of tries)."""
    tries, best = [], None
    for number, penalty in enumerate(LOOP_PENALTIES, start=1):
        crews = build_our_plan(jobs, people_by_pool, penalty)
        m = plan_metrics(crews)
        if best is None or m["quality"] > best["metrics"]["quality"]:
            best = {"crews": crews, "penalty": penalty, "metrics": m, "try": number}
        tries.append({"try": number, "setting": penalty, "highPlanned": m["high"],
                      "avgPriority": round(m["avgPriority"], 1), "kmPerCrew": round(m["kmPerCrew"], 1),
                      "quality": round(m["quality"], 1), "note": ""})
    for t in tries:
        notes = []
        if t["try"] == 1:
            notes.append("First try (priority only)")
        if t["try"] == best["try"]:
            notes.append("Kept (best quality)")
        t["note"] = ", ".join(notes)
    return best["crews"], best["penalty"], tries


# =============================================================================
# NOON: A CREW CALLS IN SICK
# =============================================================================
def row(job, assignment, crew=None, stop=None, moved_from=None, why=None):
    """One line of the Dispatch table, in the exact fields the page reads."""
    return {
        "crew": crew or job["crew"], "crewKind": job["kind"], "crewPool": job["pool"], "stop": stop or job["stop"],
        "id": job["id"], "serviceType": job["serviceType"], "community": job["community"],
        "priorityScore": job["priorityScore"], "priorityBand": job["priorityBand"],
        "daysWaiting": job["daysWaiting"], "assignment": assignment,
        "movedFrom": moved_from, "why": why or job["why"],
    }


def pick_sick_crew(crews):
    """The crew with the most High-priority jobs still to do at noon (the worst one to lose)."""
    def unfinished_high(crew):
        late = [j for j in crew["jobs"] if j["stop"] > DONE_BY_NOON]
        return (sum(j["priorityBand"] == "High" for j in late), sum(j["priorityScore"] for j in late))
    return max((c for c in crews if c["jobs"]), key=unfinished_high)


def replan_at_noon(crews, missing):
    """Apply the swap rule inside the sick crew's pool. Returns noon rows, moved count, pushed rows."""
    moved_job_ids, rows = set(), []
    replaced = {}                                   # (crew name, stop) -> the job that took the slot

    orphans = sorted((j for j in missing["jobs"] if j["stop"] > DONE_BY_NOON), key=importance, reverse=True)
    pushed = []
    for job in orphans:
        slots = [j for c in crews if c["pool"] == missing["pool"] and c["name"] != missing["name"]
                 for j in c["jobs"] if j["stop"] > DONE_BY_NOON and (j["crew"], j["stop"]) not in replaced]
        weakest = min(slots, key=importance) if slots else None
        if weakest and importance(job) > importance(weakest):
            replaced[(weakest["crew"], weakest["stop"])] = job
            moved_job_ids.add(job["id"])
            rows.append(row(job, "Moved", crew=weakest["crew"], stop=weakest["stop"], moved_from=missing["name"],
                            why=f"Took over from {missing['name']}: higher priority than the job it replaced"))
            pushed.append(row(weakest, "Pushed to tomorrow",
                              why=f"Gave its slot to a higher-priority job from {missing['name']}"))
        else:
            pushed.append(row(job, "Pushed to tomorrow",
                              why=f"{missing['name']} called in sick and no lower-priority slot was free"))

    pushed_ids = {r["id"] for r in pushed}
    for crew in crews:
        for job in crew["jobs"]:
            if job["id"] in moved_job_ids or job["id"] in pushed_ids:
                continue                              # shown under its new crew, or as pushed
            rows.append(row(job, "Done before noon" if job["stop"] <= DONE_BY_NOON else "Planned"))
    rows += pushed
    return rows, len(moved_job_ids), pushed


def crew_summary(crews, noon_rows, missing_name):
    """One line per crew for the Crews page."""
    out = []
    for c in crews:
        mine = [r for r in noon_rows if r["crew"] == c["name"]]
        seen = []
        for j in c["jobs"]:
            if j["community"] not in seen:
                seen.append(j["community"])
        out.append({
            "crew": c["name"], "crewKind": c["kind"], "crewPool": c["pool"], "jobsPlanned": len(c["jobs"]),
            "highPlanned": sum(j["priorityBand"] == "High" for j in c["jobs"]),
            "communities": seen,
            "noon": {
                "status": "Out from noon" if c["name"] == missing_name else "Active",
                "doneBeforeNoon": sum(r["assignment"] == "Done before noon" for r in mine),
                "stillToDo": sum(r["assignment"] in ("Planned", "Moved") for r in mine),
                "movedIn": sum(r["assignment"] == "Moved" for r in mine),
                "pushedToTomorrow": sum(r["assignment"] == "Pushed to tomorrow" for r in mine),
            },
        })
    return out


def pool_supply(pools_data, crews, missing):
    """Alvin's crew_pool columns at 8 a.m. and after the sick call (busy = people out on jobs)."""
    for p in pools_data["pools"]:
        mine = [c for c in crews if c["pool"] == p["pool"]]
        working = [c for c in mine if c["jobs"]]
        busy_8am = len(working) * PEOPLE_PER_CREW
        sick = p["pool"] == missing["pool"]
        total_noon = p["people"] - (PEOPLE_PER_CREW if sick else 0)
        busy_noon = busy_8am - (PEOPLE_PER_CREW if sick else 0)
        p.update({
            "crews": len(mine), "crewsWorking": len(working),
            "busy8am": busy_8am, "available8am": p["people"] - busy_8am,
            "peopleNoon": total_noon, "busyNoon": busy_noon, "availableNoon": total_noon - busy_noon,
            "sickAtNoon": PEOPLE_PER_CREW if sick else 0,
        })
    pools_data["peoplePerCrew"] = PEOPLE_PER_CREW
    pools_data["jobsPerCrew"] = JOBS_PER_CREW
    pools_data["rules"] = [
        f"A crew is {PEOPLE_PER_CREW} people (schema.sql: 'a crew calls in sick: total_people - 2').",
        f"Each crew does up to {JOBS_PER_CREW} jobs a day (the case's 'C crews x K jobs').",
        "Busy = people out on jobs (busy_people). Available = total - busy (available_people).",
    ]
    return pools_data


def routes_geojson(crews):
    """One line per crew, through its stops in order (straight lines between neighbourhood points)."""
    pools_by_size = sorted({c["pool"] for c in crews}, key=lambda pool: (-sum(c["pool"] == pool for c in crews), pool))
    color = {pool: (POOL_COLORS[i] if i < len(POOL_COLORS) else OTHER_COLOR) for i, pool in enumerate(pools_by_size)}
    features = []
    for crew in crews:
        points = [list(j["where"]) for j in crew["jobs"]]
        line = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]   # drop repeated points
        if len(line) < 2:
            continue
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": line},
                         "properties": {"crewId": crew["name"], "crewPool": crew["pool"],
                                        "crewColor": color[crew["pool"]], "jobs": len(crew["jobs"]), "standIn": True}})
    return {"type": "FeatureCollection", "features": features}


# =============================================================================
# THE REPORT
# =============================================================================
def winner(ours, theirs, better_is):
    if round(ours, 1) == round(theirs, 1):
        return "Same"
    ours_better = ours > theirs if better_is == "higher" else ours < theirs
    return "Our plan" if ours_better else "Oldest first"


def build_report(ours, base, tries, noon_summary, pool_size, crew_count):
    """Side-by-side numbers. Written honestly: if oldest-first wins a measure, the file says so."""
    rows = [
        ("High-priority jobs planned", "high", "higher", 0),
        ("Average priority score of planned jobs", "avgPriority", "higher", 1),
        ("Straight-line km per crew", "kmPerCrew", "lower", 1),
        ("Average days waiting of planned jobs", "avgDays", "higher", 1),
    ]
    comparison = []
    for label, key, better_is, digits in rows:
        o, b = ours[key], base[key]
        comparison.append({"label": label, "oldestFirst": round(b, digits) if digits else int(b),
                           "ourPlan": round(o, digits) if digits else int(o),
                           "betterIs": better_is, "winner": winner(o, b, better_is)})
    headline = [
        {"label": "High-priority jobs planned", "ourPlan": int(ours["high"]), "oldestFirst": int(base["high"]),
         "note": f"of {ours['planned']} planned jobs"},
        {"label": "Straight-line km per crew", "ourPlan": round(ours["kmPerCrew"], 1),
         "oldestFirst": round(base["kmPerCrew"], 1), "note": "lower is better"},
        {"label": "Average priority score of planned jobs", "ourPlan": round(ours["avgPriority"], 1),
         "oldestFirst": round(base["avgPriority"], 1), "note": "higher is better"},
    ]
    return {
        "summary": {"asOf": AS_OF, "isStandIn": True, "crewCount": crew_count,
                    "jobsPerCrew": JOBS_PER_CREW, "plannedJobs": ours["planned"], "poolSize": pool_size},
        "headline": headline,
        "comparison": comparison,
        "loop": {
            "setting": "Distance penalty (points lost per km from the crew's first job)",
            "qualityFormula": f"Plan quality = total priority points planned - {KM_COST} x total km driven",
            "stoppedBecause": f"tried all {len(tries)} settings",
            "tries": tries,
        },
        "noon": noon_summary,
        "limits": [
            "Crew headcounts are placeholders (scoring/schema.sql draws them at random), not real staffing.",
            f"A crew is assumed to be {PEOPLE_PER_CREW} people doing up to {JOBS_PER_CREW} jobs a day.",
            "Distances are straight lines between stops, not driving routes.",
            "Every job counts as the same size, although a sign is quicker than a pothole.",
            "Oldest-first serves the longest-waiting jobs, so it can win on waiting time.",
            "Priority scores come from the team scorer (scoring/priority_score.py), measured on Oct 2, 2026.",
        ],
    }


def main():
    jobs = load_jobs()
    pools_data, people_by_pool = load_pools()

    crews, penalty, tries = run_loop(jobs, people_by_pool)        # the loop picks our 8 a.m. plan
    base_crews = build_oldest_first_plan(jobs, people_by_pool)
    ours_m, base_m = plan_metrics(crews), plan_metrics(base_crews)

    morning = [row(j, "Planned") for c in crews for j in c["jobs"]]
    missing = pick_sick_crew(crews)
    noon, moved, pushed = replan_at_noon(crews, missing)

    high_planned = sum(r["priorityBand"] == "High" for r in morning)
    high_pushed = sum(r["priorityBand"] == "High" for r in pushed)
    noon_summary = {"missingCrew": missing["name"], "missingPool": missing["pool"], "moved": moved,
                    "pushed": len(pushed), "urgentStillCovered": high_planned - high_pushed}

    dispatch = {
        "summary": {
            "asOf": AS_OF, "crewCount": len(crews), "jobsPerCrew": JOBS_PER_CREW,
            "peoplePerCrew": PEOPLE_PER_CREW, "plannedJobs": len(morning), "poolSize": len(jobs),
            "morning": {"highPriorityPlanned": high_planned},
            "noon": noon_summary, "isStandIn": True,
        },
        "crews": [c["name"] for c in crews],
        "crewSummary": crew_summary(crews, noon, missing["name"]),
        "morning": morning,
        "noon": noon,
    }
    report = build_report(ours_m, base_m, tries, noon_summary, len(jobs), len(crews))
    pools_out = pool_supply(pools_data, crews, missing)

    for path, content in ((DISPATCH_FILE, dispatch), (REPORTS_FILE, report),
                          (ROUTES_FILE, routes_geojson(crews)), (POOLS_FILE, pools_out)):
        path.write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"Supply: {len(crews)} crews of {PEOPLE_PER_CREW} people in {len(people_by_pool)} pools; "
          f"{len(morning)} jobs planned ({high_planned} High) out of {len(jobs):,}")
    print(f"Loop kept distance penalty {penalty} (try {next(t['try'] for t in tries if 'Kept' in t['note'])} of {len(tries)})")
    for c in report["comparison"]:
        print(f"  {c['label']:42s} oldest-first {c['oldestFirst']:>6}   ours {c['ourPlan']:>6}   -> {c['winner']}")
    print(f"Noon: {missing['name']} ({missing['pool']}) calls in sick -> {moved} moved, {len(pushed)} pushed, "
          f"{high_planned - high_pushed} High still covered")


if __name__ == "__main__":
    main()
