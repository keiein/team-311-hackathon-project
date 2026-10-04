"""
MAKE DISPATCH STAND-IN: a PREVIEW of the plan, the comparison and the improvement loop
=====================================================================================

!! This is NOT the final algorithm. It is a simple stand-in so the screens can be built now.
!! When backend steps 4 (Supply), 5 (Match), 6 (Compare), 7 (crew goes missing) and 8 (the loop)
!! exist, they write the same files in the same fields and this script is retired.
!! The files say so themselves ("isStandIn": true) and the pages show a note while that is true.

What it does, in plain words:
    1. Reads today's open crew jobs from frontend/public/data/requests.geojson, the SAME file
       the Requests page reads, so every ticket id and priority matches.
    2. Builds 8 crews (5 roads, 2 water, 1 garbage) x 5 jobs = 40 jobs. These numbers come from
       the organizers' starter (CREWS = 8, JOBS_PER_CREW = 5).
    3. OLD WAY (baseline): crews take turns picking the OLDEST job of their own kind.
    4. OUR WAY: crews take turns picking the best-scoring job of their own kind, with a small
       "distance penalty" for jobs far from the crew's first job.
    5. THE LOOP: tries several distance-penalty settings, scores each whole plan, keeps the best.
          plan quality = total priority points planned  -  0.2 x total km driven
       The 8 a.m. plan is the best one the loop found.
    6. NOON: one roads crew goes missing. Its unfinished jobs (stops 3 to 5), most important first,
       each take the slot of the least important unfinished job on another crew of the same kind,
       but only if the missing crew's job is MORE important. Otherwise the job waits until tomorrow.
       The job that lost its slot also waits until tomorrow.
       Assumption: every crew finished its first 2 stops before noon.

How to run it (from the project folder):
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/make_dispatch_standin.py"

What comes out (in frontend/public/data/):
    dispatch.json   the Dispatch page and the Crews page read this
    reports.json    the Reports page reads this
"""

import json
import math
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DATA_DIR = REPO_ROOT / "frontend" / "public" / "data"
REQUESTS_FILE = DATA_DIR / "requests.geojson"
DISPATCH_FILE = DATA_DIR / "dispatch.json"
REPORTS_FILE = DATA_DIR / "reports.json"

# =============================================================================
# SETTINGS
# =============================================================================
AS_OF = "2026-10-02"                                   # the day the team's data was exported
CREWS = [("Roads", "roads", 5), ("Water", "water", 2), ("Garbage", "garbage", 1)]   # name, kind, how many
JOBS_PER_CREW = 5                                      # organizers' starter: JOBS_PER_CREW = 5
DONE_BY_NOON = 2                                       # each crew finished its first 2 stops by noon

# The loop tries these settings. 0 = look at priority only (the "first try").
# Penalty = points lost per km from the crew's first job.
# With the team scorer, one severity tier is worth 12 points (0.40 weight x 0.30 step x 100).
# So a job one tier lower only wins if it is more than 12 / penalty km closer:
#   0.2 -> 60 km (never, inside Calgary), 0.4 -> 30 km, 0.8 -> 15 km, 1.6 -> 7.5 km.
# The loop's quality score (below) counts priority points, so it notices when a setting gives up
# important jobs just to save driving.
LOOP_PENALTIES = [0.0, 0.2, 0.4, 0.8, 1.6]
KM_COST = 0.2                                          # in the plan quality score: points lost per km driven


def km_between(a, b):
    """Straight-line km between two (lon, lat) points (haversine)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def importance(job):
    """Compared left to right: priority score first, then days waiting."""
    return (job["priorityScore"], job["daysWaiting"])


def load_pool():
    """All jobs on the Requests page, as plain dicts."""
    features = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))["features"]
    pool = []
    for f in features:
        p = f["properties"]
        pool.append({
            "id": p["id"], "serviceType": p["serviceType"], "community": p["community"],
            "priorityScore": p["priorityScore"], "priorityBand": p["priorityBand"],
            "daysWaiting": p["daysWaiting"], "kind": p["crew"], "where": tuple(f["geometry"]["coordinates"]),
        })
    return pool


# =============================================================================
# THE TWO PLANS
# =============================================================================
def make_crews():
    return [{"name": f"{label} {i + 1}", "kind": kind, "jobs": []} for label, kind, count in CREWS for i in range(count)]


def build_our_plan(pool, km_penalty):
    """Crews take turns picking, like picking teams in gym class."""
    crews = make_crews()
    left = {kind: sorted([j for j in pool if j["kind"] == kind], key=importance, reverse=True)
            for _, kind, _ in CREWS}

    for stop in range(1, JOBS_PER_CREW + 1):
        for crew in crews:
            candidates = left[crew["kind"]]
            if not candidates:
                continue
            if stop == 1:
                pick = candidates[0]
                why = f"Highest-priority {crew['kind']} job left"
            else:
                home = crew["jobs"][0]["where"]
                # best score after the distance penalty; ties go to the longer wait
                pick = max(candidates, key=lambda j: (j["priorityScore"] - km_penalty * km_between(home, j["where"]),
                                                      j["daysWaiting"]))
                why = f"Next-highest {crew['kind']} priority, {km_between(home, pick['where']):.1f} km from stop 1"
            candidates.remove(pick)
            crew["jobs"].append({**pick, "stop": stop, "crew": crew["name"], "why": why})
    return crews


def build_oldest_first_plan(pool):
    """The OLD WAY: each crew always takes the oldest job of its own kind. Priority and distance are ignored."""
    crews = make_crews()
    left = {kind: sorted([j for j in pool if j["kind"] == kind], key=lambda j: (-j["daysWaiting"], j["id"]))
            for _, kind, _ in CREWS}
    for stop in range(1, JOBS_PER_CREW + 1):
        for crew in crews:
            if left[crew["kind"]]:
                pick = left[crew["kind"]].pop(0)
                crew["jobs"].append({**pick, "stop": stop, "crew": crew["name"], "why": "Oldest job left"})
    return crews


def plan_metrics(crews):
    """Plain numbers that describe one plan."""
    jobs = [j for c in crews for j in c["jobs"]]
    km_per_crew = [sum(km_between(a["where"], b["where"]) for a, b in zip(c["jobs"], c["jobs"][1:])) for c in crews]
    points = sum(j["priorityScore"] for j in jobs)
    km_total = sum(km_per_crew)
    return {
        "planned": len(jobs),
        "high": sum(j["priorityBand"] == "High" for j in jobs),
        "points": points,
        "avgPriority": points / len(jobs),
        "avgDays": sum(j["daysWaiting"] for j in jobs) / len(jobs),
        "kmPerCrew": km_total / len(crews),
        "quality": points - KM_COST * km_total,
    }


def run_loop(pool):
    """Try each setting, keep the best plan. Returns (best crews, best penalty, table of tries)."""
    tries, best = [], None
    for number, penalty in enumerate(LOOP_PENALTIES, start=1):
        crews = build_our_plan(pool, penalty)
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
# NOON: A CREW GOES MISSING
# =============================================================================
def row(job, assignment, crew=None, stop=None, moved_from=None, why=None):
    """One line of the Dispatch table, in the exact fields the page reads."""
    return {
        "crew": crew or job["crew"], "crewKind": job["kind"], "stop": stop or job["stop"],
        "id": job["id"], "serviceType": job["serviceType"], "community": job["community"],
        "priorityScore": job["priorityScore"], "priorityBand": job["priorityBand"],
        "daysWaiting": job["daysWaiting"], "assignment": assignment,
        "movedFrom": moved_from, "why": why or job["why"],
    }


def pick_missing_crew(crews):
    """The roads crew with the most High-priority jobs still to do at noon (the worst one to lose)."""
    def unfinished_high(crew):
        late = [j for j in crew["jobs"] if j["stop"] > DONE_BY_NOON]
        return (sum(j["priorityBand"] == "High" for j in late), sum(j["priorityScore"] for j in late))
    return max((c for c in crews if c["kind"] == "roads"), key=unfinished_high)


def replan_at_noon(crews, missing):
    """Apply the swap rule. Returns the noon rows, how many jobs moved, and the pushed rows."""
    moved_job_ids, rows = set(), []
    replaced = {}                                   # (crew name, stop) -> the job that took the slot

    orphans = sorted((j for j in missing["jobs"] if j["stop"] > DONE_BY_NOON), key=importance, reverse=True)
    pushed = []
    for job in orphans:
        slots = [j for c in crews if c["kind"] == missing["kind"] and c["name"] != missing["name"]
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
                              why=f"{missing['name']} is out and no lower-priority slot was free"))

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
            "crew": c["name"], "crewKind": c["kind"], "jobsPlanned": len(c["jobs"]),
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


# =============================================================================
# THE REPORT
# =============================================================================
def winner(ours, theirs, better_is):
    if round(ours, 1) == round(theirs, 1):
        return "Same"
    ours_better = ours > theirs if better_is == "higher" else ours < theirs
    return "Our plan" if ours_better else "Oldest first"


def build_report(ours, base, tries, noon_summary, pool_size):
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
        "summary": {"asOf": AS_OF, "isStandIn": True, "crewCount": len(CREWS) and sum(c[2] for c in CREWS),
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
            "Distances are straight lines between stops, not driving routes.",
            "Every job counts as the same size, although a sign is quicker than a pothole.",
            "Oldest-first serves the longest-waiting jobs, so it can win on waiting time.",
            "Priority scores come from the team scorer (scoring/priority_score.py), measured on Oct 2, 2026.",
        ],
    }


def main():
    pool = load_pool()
    crews, penalty, tries = run_loop(pool)            # the loop picks our 8 a.m. plan
    base_crews = build_oldest_first_plan(pool)
    ours_m, base_m = plan_metrics(crews), plan_metrics(base_crews)

    morning = [row(j, "Planned") for c in crews for j in c["jobs"]]
    missing = pick_missing_crew(crews)
    noon, moved, pushed = replan_at_noon(crews, missing)

    high_planned = sum(r["priorityBand"] == "High" for r in morning)
    high_pushed = sum(r["priorityBand"] == "High" for r in pushed)
    noon_summary = {"missingCrew": missing["name"], "moved": moved, "pushed": len(pushed),
                    "urgentStillCovered": high_planned - high_pushed}

    dispatch = {
        "summary": {
            "asOf": AS_OF, "crewCount": len(crews), "jobsPerCrew": JOBS_PER_CREW,
            "plannedJobs": len(morning), "poolSize": len(pool),
            "morning": {"highPriorityPlanned": high_planned},
            "noon": noon_summary, "isStandIn": True,
        },
        "crews": [c["name"] for c in crews],
        "crewSummary": crew_summary(crews, noon, missing["name"]),
        "morning": morning,
        "noon": noon,
    }
    report = build_report(ours_m, base_m, tries, noon_summary, len(pool))

    DISPATCH_FILE.write_text(json.dumps(dispatch, separators=(",", ":")), encoding="utf-8")
    REPORTS_FILE.write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DISPATCH_FILE.relative_to(REPO_ROOT)} and {REPORTS_FILE.relative_to(REPO_ROOT)}")
    print(f"Loop kept distance penalty {penalty} (try {next(t['try'] for t in tries if 'Kept' in t['note'])} of {len(tries)})")
    for c in report["comparison"]:
        print(f"  {c['label']:42s} oldest-first {c['oldestFirst']:>6}   ours {c['ourPlan']:>6}   -> {c['winner']}")
    print(f"Noon: {missing['name']} goes missing -> {moved} moved, {len(pushed)} pushed, {high_planned - high_pushed} High still covered")


if __name__ == "__main__":
    main()
