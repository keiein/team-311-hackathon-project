"""
MAKE DISPATCH: today's plan on the shared workforce model
=========================================================

Supply is ONE shared operational workforce (scoring/WORKFORCE.md / scoring/schema.sql):

    SUPPLY   workforce.json from export_team_scores.py (MySQL when available, else
             SIMULATED PLACEHOLDER total_people=100, people_per_crew=5).
    MATCH    Rank all open jobs by the team priority score (global — not by crew_pool).
             Deployable crews = available_crews. Highest-priority jobs get crews first.
             Each dispatched job consumes people_per_crew people (busy_people += people_per_crew).
             crew_pool on a ticket is service-area metadata only; it does NOT gate assignment.
    SICK     sick_people += people_per_crew at noon (do NOT reduce total_people). One crew
             goes out; unfinished jobs may take a lower-priority slot on another crew.

JOBS_PER_CREW = 5 is the case's "K jobs" per crew per day (route length), separate from
people_per_crew (people required to form one deployable crew).

How to run it (from the project folder, after export_team_scores.py):
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/make_dispatch_standin.py"

What comes out (in frontend/public/data/):
    dispatch.json     Dispatch page + Crews "Today's crews"
    reports.json      Reports page
    routes.geojson    Dashboard map lines
    workforce.json    updated with busy / sick after the morning plan and noon sick call
"""

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DATA_DIR = REPO_ROOT / "frontend" / "public" / "data"
REQUESTS_FILE = DATA_DIR / "requests.geojson"
WORKFORCE_FILE = DATA_DIR / "workforce.json"
DISPATCH_FILE = DATA_DIR / "dispatch.json"
REPORTS_FILE = DATA_DIR / "reports.json"
ROUTES_FILE = DATA_DIR / "routes.geojson"

sys.path.insert(0, str(HERE))
from workforce_standin import (  # noqa: E402
    load_workforce,
    scenarios_from,
    with_counts,
    workforce_file_payload,
)

# =============================================================================
# SETTINGS
# =============================================================================
AS_OF = "2026-10-02"
JOBS_PER_CREW = 5              # case "K jobs" per crew per day (route stops)
DONE_BY_NOON = 2               # each crew finished its first 2 stops by noon

LOOP_PENALTIES = [0.0, 0.2, 0.4, 0.8, 1.6]
KM_COST = 0.2

CREW_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#737373"


def km_between(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def importance(job):
    return (job["priorityScore"], job["daysWaiting"] or 0)


def load_jobs():
    features = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))["features"]
    jobs = []
    for f in features:
        p = f["properties"]
        jobs.append({
            "id": p["id"], "serviceType": p["serviceType"], "community": p["community"],
            "priorityScore": p["priorityScore"], "priorityBand": p["priorityBand"],
            "daysWaiting": p["daysWaiting"],
            # Metadata only — not used for dispatch eligibility.
            "serviceArea": p["crewPool"],
            "where": tuple(f["geometry"]["coordinates"]),
        })
    return jobs


def load_base_workforce():
    """Unloaded morning capacity for planning (not the post-dispatch busy snapshot)."""
    if WORKFORCE_FILE.exists():
        data = json.loads(WORKFORCE_FILE.read_text(encoding="utf-8"))
        scenarios = data.get("scenarios") or {}
        if isinstance(scenarios.get("normal"), dict):
            return scenarios["normal"]
        if isinstance(data.get("workforce"), dict):
            # Ignore busy from a previous stand-in run; keep stable headcount + people_per_crew.
            return with_counts(data["workforce"], busy=0, sick=0, snow=0)
    return load_workforce()


def make_crews(available_crews):
    """One deployable crew per available_crews slot. No specialized pools."""
    return [
        {"name": f"Crew {i + 1}", "kind": "Shared", "pool": "Shared Operational Workforce", "jobs": []}
        for i in range(available_crews)
    ]


def take_turns(crews, jobs, choose):
    """Shared crews take turns picking from the global remaining queue."""
    left = list(jobs)
    for stop in range(1, JOBS_PER_CREW + 1):
        for crew in crews:
            if not left:
                continue
            pick, why = choose(crew, left, stop)
            left.remove(pick)
            crew["jobs"].append({
                **pick, "stop": stop, "crew": crew["name"], "kind": crew["kind"], "why": why,
            })
    return crews


def build_our_plan(jobs, available_crews, km_penalty):
    ranked = sorted(jobs, key=importance, reverse=True)

    def choose(crew, candidates, stop):
        if stop == 1 or not crew["jobs"]:
            return candidates[0], "Highest-priority job left (shared workforce)"
        home = crew["jobs"][0]["where"]
        pick = max(
            candidates,
            key=lambda j: (
                j["priorityScore"] - km_penalty * km_between(home, j["where"]),
                j["daysWaiting"] or 0,
            ),
        )
        return pick, f"Next-highest priority, {km_between(home, pick['where']):.1f} km from stop 1"

    return take_turns(make_crews(available_crews), ranked, choose)


def build_oldest_first_plan(jobs, available_crews):
    oldest = sorted(jobs, key=lambda j: (-(j["daysWaiting"] or 0), j["id"]))
    return take_turns(
        make_crews(available_crews),
        oldest,
        lambda crew, cands, stop: (cands[0], "Oldest job left"),
    )


def plan_metrics(crews):
    jobs = [j for c in crews for j in c["jobs"]]
    working = [c for c in crews if c["jobs"]]
    if not jobs or not working:
        return {
            "planned": 0, "high": 0, "points": 0, "avgPriority": 0,
            "avgDays": 0, "kmPerCrew": 0, "quality": 0,
        }
    km_per_crew = [
        sum(km_between(a["where"], b["where"]) for a, b in zip(c["jobs"], c["jobs"][1:]))
        for c in working
    ]
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


def run_loop(jobs, available_crews):
    tries, best = [], None
    for number, penalty in enumerate(LOOP_PENALTIES, start=1):
        crews = build_our_plan(jobs, available_crews, penalty)
        m = plan_metrics(crews)
        if best is None or m["quality"] > best["metrics"]["quality"]:
            best = {"crews": crews, "penalty": penalty, "metrics": m, "try": number}
        tries.append({
            "try": number, "setting": penalty, "highPlanned": m["high"],
            "avgPriority": round(m["avgPriority"], 1), "kmPerCrew": round(m["kmPerCrew"], 1),
            "quality": round(m["quality"], 1), "note": "",
        })
    for t in tries:
        notes = []
        if t["try"] == 1:
            notes.append("First try (priority only)")
        if t["try"] == best["try"]:
            notes.append("Kept (best quality)")
        t["note"] = ", ".join(notes)
    return best["crews"], best["penalty"], tries


def row(job, assignment, crew=None, stop=None, moved_from=None, why=None):
    return {
        "crew": crew or job["crew"],
        "crewKind": job["kind"],
        "crewPool": job.get("serviceArea", "Shared Operational Workforce"),
        "stop": stop or job["stop"],
        "id": job["id"],
        "serviceType": job["serviceType"],
        "community": job["community"],
        "priorityScore": job["priorityScore"],
        "priorityBand": job["priorityBand"],
        "daysWaiting": job["daysWaiting"],
        "assignment": assignment,
        "movedFrom": moved_from,
        "why": why or job["why"],
    }


def pick_sick_crew(crews):
    def unfinished_high(crew):
        late = [j for j in crew["jobs"] if j["stop"] > DONE_BY_NOON]
        return (sum(j["priorityBand"] == "High" for j in late), sum(j["priorityScore"] for j in late))
    return max((c for c in crews if c["jobs"]), key=unfinished_high)


def replan_at_noon(crews, missing):
    """Swap unfinished jobs onto any other shared crew (no pool restriction)."""
    moved_job_ids, rows = set(), []
    replaced = {}

    orphans = sorted((j for j in missing["jobs"] if j["stop"] > DONE_BY_NOON), key=importance, reverse=True)
    pushed = []
    for job in orphans:
        slots = [
            j for c in crews if c["name"] != missing["name"]
            for j in c["jobs"]
            if j["stop"] > DONE_BY_NOON and (j["crew"], j["stop"]) not in replaced
        ]
        weakest = min(slots, key=importance) if slots else None
        if weakest and importance(job) > importance(weakest):
            replaced[(weakest["crew"], weakest["stop"])] = job
            moved_job_ids.add(job["id"])
            rows.append(row(
                job, "Moved", crew=weakest["crew"], stop=weakest["stop"], moved_from=missing["name"],
                why=f"Took over from {missing['name']}: higher priority than the job it replaced",
            ))
            pushed.append(row(
                weakest, "Pushed to tomorrow",
                why=f"Gave its slot to a higher-priority job from {missing['name']}",
            ))
        else:
            pushed.append(row(
                job, "Pushed to tomorrow",
                why=f"{missing['name']} unavailable (sick) and no lower-priority slot was free",
            ))

    pushed_ids = {r["id"] for r in pushed}
    for crew in crews:
        for job in crew["jobs"]:
            if job["id"] in moved_job_ids or job["id"] in pushed_ids:
                continue
            rows.append(row(job, "Done before noon" if job["stop"] <= DONE_BY_NOON else "Planned"))
    rows += pushed
    return rows, len(moved_job_ids), pushed


def crew_summary(crews, noon_rows, missing_name):
    out = []
    for c in crews:
        mine = [r for r in noon_rows if r["crew"] == c["name"]]
        seen = []
        for j in c["jobs"]:
            if j["community"] not in seen:
                seen.append(j["community"])
        out.append({
            "crew": c["name"],
            "crewKind": c["kind"],
            "crewPool": "Shared Operational Workforce",
            "jobsPlanned": len(c["jobs"]),
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


def routes_geojson(crews):
    features = []
    for i, crew in enumerate(crews):
        points = [list(j["where"]) for j in crew["jobs"]]
        line = [p for idx, p in enumerate(points) if idx == 0 or p != points[idx - 1]]
        if len(line) < 2:
            continue
        color = CREW_COLORS[i % len(CREW_COLORS)] if i < len(CREW_COLORS) * 2 else OTHER_COLOR
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": line},
            "properties": {
                "crewId": crew["name"],
                "crewPool": "Shared Operational Workforce",
                "crewColor": color,
                "jobs": len(crew["jobs"]),
                "standIn": True,
            },
        })
    return {"type": "FeatureCollection", "features": features}


def winner(ours, theirs, better_is):
    if round(ours, 1) == round(theirs, 1):
        return "Same"
    ours_better = ours > theirs if better_is == "higher" else ours < theirs
    return "Our plan" if ours_better else "Oldest first"


def build_report(ours, base, tries, noon_summary, pool_size, crew_count, people_per_crew):
    rows = [
        ("High-priority jobs planned", "high", "higher", 0),
        ("Average priority score of planned jobs", "avgPriority", "higher", 1),
        ("Straight-line km per crew", "kmPerCrew", "lower", 1),
        ("Average days waiting of planned jobs", "avgDays", "higher", 1),
    ]
    comparison = []
    for label, key, better, digits in rows:
        o, b = ours[key], base[key]
        comparison.append({
            "label": label,
            "oldestFirst": round(b, digits),
            "ourPlan": round(o, digits),
            "winner": winner(o, b, better),
        })
    return {
        "title": "Dispatch stand-in: shared workforce vs oldest-first",
        "asOf": AS_OF,
        "summary": {
            "crewCount": crew_count,
            "peoplePerCrew": people_per_crew,
            "jobsPerCrew": JOBS_PER_CREW,
            "openJobs": pool_size,
            "plannedOur": ours["planned"],
            "plannedOldest": base["planned"],
        },
        "comparison": comparison,
        "loop": {
            "setting": "Distance penalty (points lost per km from the crew's first job)",
            "qualityFormula": f"Plan quality = total priority points planned - {KM_COST} x total km driven",
            "stoppedBecause": f"tried all {len(tries)} settings",
            "tries": tries,
        },
        "noon": noon_summary,
        "limits": [
            "Workforce headcount is a SIMULATED PLACEHOLDER (default 100), not real City staffing.",
            f"A deployable crew is {people_per_crew} people; each does up to {JOBS_PER_CREW} jobs a day.",
            "crew_pool on tickets is service-area metadata only — it does not limit which crew can take a job.",
            "Distances are straight lines between stops, not driving routes.",
            "Priority scores come from the team scorer (scoring/priority_score.py), measured on Oct 2, 2026.",
        ],
    }


def main():
    jobs = load_jobs()
    base = load_base_workforce()
    people_per_crew = int(base["people_per_crew"])
    morning_crews_count = int(base["available_crews"])
    if morning_crews_count <= 0:
        raise SystemExit("No available_crews in workforce — nothing to dispatch.")

    crews, penalty, tries = run_loop(jobs, morning_crews_count)
    base_crews = build_oldest_first_plan(jobs, morning_crews_count)
    ours_m, base_m = plan_metrics(crews), plan_metrics(base_crews)

    working = [c for c in crews if c["jobs"]]
    busy_morning = len(working) * people_per_crew
    morning_workforce = with_counts(base, busy=busy_morning, sick=int(base.get("sick_people", 0)),
                                    snow=int(base.get("snow_redeployed", 0)))

    morning = [row(j, "Planned") for c in crews for j in c["jobs"]]
    missing = pick_sick_crew(crews)
    noon, moved, pushed = replan_at_noon(crews, missing)

    # Sick call: sick_people += people_per_crew; do not reduce total_people.
    # The missing crew's people leave busy and enter sick.
    busy_noon = max(0, busy_morning - people_per_crew)
    sick_noon = int(base.get("sick_people", 0)) + people_per_crew
    noon_workforce = with_counts(base, busy=busy_noon, sick=sick_noon,
                                 snow=int(base.get("snow_redeployed", 0)))

    high_planned = sum(r["priorityBand"] == "High" for r in morning)
    high_pushed = sum(r["priorityBand"] == "High" for r in pushed)
    noon_summary = {
        "missingCrew": missing["name"],
        "missingPool": "Shared Operational Workforce",
        "moved": moved,
        "pushed": len(pushed),
        "urgentStillCovered": high_planned - high_pushed,
        "sickPeopleAdded": people_per_crew,
    }

    dispatch = {
        "summary": {
            "asOf": AS_OF,
            "crewCount": len(crews),
            "jobsPerCrew": JOBS_PER_CREW,
            "peoplePerCrew": people_per_crew,
            "plannedJobs": len(morning),
            "poolSize": len(jobs),
            "morning": {"highPriorityPlanned": high_planned},
            "noon": noon_summary,
            "isStandIn": True,
            "workforceModel": "shared",
        },
        "crews": [c["name"] for c in crews],
        "crewSummary": crew_summary(crews, noon, missing["name"]),
        "morning": morning,
        "noon": noon,
    }
    report = build_report(ours_m, base_m, tries, noon_summary, len(jobs), len(crews), people_per_crew)

    # Demo scenarios (normal/sick/blizzard) from the unloaded baseline; current = after morning dispatch.
    workforce_out = workforce_file_payload(base)
    workforce_out["workforce"] = morning_workforce
    workforce_out["afterNoon"] = noon_workforce
    workforce_out["scenarios"] = scenarios_from(base)
    workforce_out["scenarios"]["current"] = morning_workforce

    for path, content in (
        (DISPATCH_FILE, dispatch),
        (REPORTS_FILE, report),
        (ROUTES_FILE, routes_geojson(crews)),
        (WORKFORCE_FILE, workforce_out),
    ):
        path.write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")

    print(
        f"Supply: {len(crews)} shared crews of {people_per_crew} people "
        f"(started with {base['available_people']} available / {base['available_crews']} crews); "
        f"{len(morning)} jobs planned ({high_planned} High) out of {len(jobs):,}"
    )
    print(f"Loop kept distance penalty {penalty} (try {next(t['try'] for t in tries if 'Kept' in t['note'])} of {len(tries)})")
    for c in report["comparison"]:
        print(f"  {c['label']:42s} oldest-first {c['oldestFirst']:>6}   ours {c['ourPlan']:>6}   -> {c['winner']}")
    print(
        f"Noon: {missing['name']} sick (sick_people +{people_per_crew}) -> "
        f"{moved} moved, {len(pushed)} pushed, {high_planned - high_pushed} High still covered"
    )
    print(
        f"Workforce noon: available_people={noon_workforce['available_people']}, "
        f"available_crews={noon_workforce['available_crews']}"
    )


if __name__ == "__main__":
    main()
