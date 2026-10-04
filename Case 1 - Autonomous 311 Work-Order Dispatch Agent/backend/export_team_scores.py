"""
EXPORT TEAM SCORES: the team's official priority score -> the files the website reads
=====================================================================================

What this file does, in plain words:
    1. Runs Alvin's scorer (scoring/priority_score.py), the team's official formula:
           priority = 0.40 x basic knowledge + 0.25 x geography + 0.20 x age + 0.15 x number of tickets
       on the team's cleaned open tickets, with the clock set to the data's snapshot day (Oct 2, 2026).
       This is the same scoring and the same order his MySQL loader (load_scored_tickets.py) writes
       into the scored_tickets table, so the website and the database show the same ranking.
    2. Writes the files the website reads (frontend/public/data/):
           requests.geojson     today's crew jobs with their score, its four parts, and the weights
           needs_review.json    crew jobs open over 60 days (his scorer leaves them out on purpose)
           communities.geojson  neighbourhood outlines with how many jobs sit in each
           workforce.json       shared operational workforce (MySQL when available, else schema placeholder)

    The website shows the score as 0 to 100 (priority x 100), with three levels:
        High   = 80 and above      (the map's red)
        Medium = 50 to 79.9        (the map's amber)
        Low    = below 50          (the map's gray)

How to run it (from the project folder), then rebuild the plan from it:
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/export_team_scores.py"
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/make_dispatch_standin.py"
"""

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CASE_FOLDER = HERE.parent
REPO_ROOT = CASE_FOLDER.parent
OUT_DIR = REPO_ROOT / "frontend" / "public" / "data"
SHAPES_FILE = CASE_FOLDER / "data" / "2021_Federal_Census_Population_and_Dwellings_by_Community_20261003.geojson"

# Alvin's scorer, used as it is (not copied): scoring/ sits beside this backend/ folder.
sys.path.insert(0, str(CASE_FOLDER / "scoring"))
from priority_score import (  # noqa: E402
    TICKETS, WEIGHTS, AgeScore, PriorityScorer, ScoreComponent, get_criticality_details,
)
from workforce_standin import workforce_file_payload  # noqa: E402

# =============================================================================
# SETTINGS
# =============================================================================
SNAPSHOT_DAY = "2026-10-02"        # the day the City's data was exported; ages are measured to this day
HIGH_AT, MEDIUM_AT = 80, 50        # level cut-offs on the 0-100 score, the same as the map's colours
TIER_NAMES = {4: "Critical", 3: "Major", 2: "Moderate", 1: "Minor"}   # Alvin's / keiein's tier titles
NEEDS_REVIEW_REASON = "Waiting over 60 days: needs review"           # the reason text in Alvin's RULES

# The department each job belongs to -> the short crew label the pages use
CREW_LABELS = {
    "OS - Mobility": "roads",
    "OS - Water Services": "water",
    "OS - Waste and Recycling Services": "garbage",
    "OSC - Waste and Recycling Services": "garbage",
    "OS - Parks and Open Spaces": "parks",
    "OS - Calgary Transit": "transit",
    "CS - Emergency Management and Community Safety": "community safety",
}   # anything else shows as "other"


def score_like_the_loader():
    """Score and rank exactly as load_scored_tickets.py does (without needing MySQL).

    Returns (ranked jobs, all tickets, why each ticket was left out).
    """
    tickets = pd.read_csv(TICKETS, low_memory=False)
    scorer = PriorityScorer()
    for component in scorer.components:              # fix the clock, like scorer_at(--now 2026-10-02)
        if isinstance(component, AgeScore):
            component.now = pd.Timestamp(SNAPSHOT_DAY).to_pydatetime()
    scored = scorer.score_frame(tickets)
    # Same order as load_scored_tickets.rank(): priority high->low, then open longest, then ticket id
    ranked = scored.sort_values(["priority", "open_days", ScoreComponent.ID_FIELD], ascending=[False, False, True])
    ranked = ranked.assign(priority_rank=range(1, len(ranked) + 1))
    return ranked, tickets, ScoreComponent.skip_reasons(tickets)


def band(score: float) -> str:
    if score >= HIGH_AT:
        return "High"
    return "Medium" if score >= MEDIUM_AT else "Low"


def why(keywords) -> str:
    """Plain words for the severity part of the score."""
    if isinstance(keywords, str) and keywords.strip():
        return f"Keywords: {keywords.strip()}"
    return "No keyword matched (lowest tier)"


def text(value) -> str:
    return "" if pd.isna(value) else str(value)


# =============================================================================
# THE FILES
# =============================================================================
def requests_geojson(ranked: pd.DataFrame) -> dict:
    features = []
    for r in ranked.itertuples(index=False):
        score = round(float(r.priority) * 100, 1)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(float(r.longitude), 6), round(float(r.latitude), 6)]},
            "properties": {
                "id": str(r.service_request_id),
                "serviceType": str(r.service_name),
                "priorityScore": score,
                "priorityBand": band(score),
                "priorityRank": int(r.priority_rank),
                "severityTier": int(r.criticality_tier),
                "severityName": TIER_NAMES.get(int(r.criticality_tier), "Minor"),
                "severityWhy": why(r.criticality_keywords),
                "crew": CREW_LABELS.get(r.crew_pool, "other"),
                "crewPool": str(r.crew_pool),
                "community": text(r.comm_name),
                "status": "Open",
                "daysWaiting": int(r.open_days) if not pd.isna(r.open_days) else None,
                "slaDays": round(float(r.sla_days), 1) if not pd.isna(r.sla_days) else None,
                "overdue": bool(r.overdue) if not pd.isna(r.overdue) else None,
                "sameDayTickets": int(r.same_day_ticket_count) if not pd.isna(r.same_day_ticket_count) else None,
                # the four parts of the score, each 0 to 1 (meta.weights says how much each counts)
                "basicKnowledgeScore": round(float(r.basic_knowledge_score), 3),
                "geoScore": round(float(r.geo_score), 3),
                "ageScore": round(float(r.age_score), 3),
                "ticketCountScore": round(float(r.ticket_count_score), 3),
            }})
    return {
        "type": "FeatureCollection",
        # "meta" is extra information about the whole file (GeoJSON allows this)
        "meta": {
            "asOf": SNAPSHOT_DAY,
            "source": "scoring/priority_score.py (team scorer)",
            "formula": "priority = " + " + ".join(f"{w:.2f} x {k}" for k, w in WEIGHTS.items()),
            "weights": {"basicKnowledgeScore": WEIGHTS["basic_knowledge"], "geoScore": WEIGHTS["geo"],
                        "ageScore": WEIGHTS["age"], "ticketCountScore": WEIGHTS["ticket_count"]},
            "levels": {"High": HIGH_AT, "Medium": MEDIUM_AT},
        },
        "features": features,
    }


def needs_review_json(tickets: pd.DataFrame, reasons: pd.Series) -> dict:
    """Crew jobs open over 60 days: most dangerous type first, then oldest."""
    old = tickets[reasons == NEEDS_REVIEW_REASON]
    rows = []
    for r in old.itertuples(index=False):
        _, tier, _, _ = get_criticality_details(r.service_name)
        rows.append({
            "id": str(r.service_request_id), "serviceType": str(r.service_name), "community": text(r.comm_name),
            "daysWaiting": int(r.days_waiting) if not pd.isna(r.days_waiting) else None,
            "severityTier": int(tier), "severityName": TIER_NAMES.get(int(tier), "Minor"),
            "crew": CREW_LABELS.get(r.crew_pool, "other"),
        })
    rows.sort(key=lambda x: (-x["severityTier"], -(x["daysWaiting"] or 0), x["id"]))
    return {"asOf": SNAPSHOT_DAY, "count": len(rows),
            "note": "Open over 60 days. A supervisor checks these before sending a crew.", "rows": rows}


def round_coords(geometry: dict, digits: int = 5) -> dict:
    """Fewer decimals = a smaller file (5 decimals is about 1 metre)."""
    def walk(c):
        return [walk(x) for x in c] if isinstance(c[0], list) else [round(c[0], digits), round(c[1], digits)]
    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"])}


def communities_geojson(ranked: pd.DataFrame, review: dict) -> dict:
    shapes = json.loads(SHAPES_FILE.read_text(encoding="utf-8"))
    jobs = ranked.groupby("comm_name").size()
    high = ranked.assign(h=ranked["priority"] * 100 >= HIGH_AT).groupby("comm_name")["h"].sum()
    old = pd.Series([r["community"] for r in review["rows"]]).value_counts()
    features = []
    for f in shapes["features"]:
        name = f["properties"]["community_name"]
        features.append({"type": "Feature", "geometry": round_coords(f["geometry"]),
                         "properties": {"code": f["properties"]["community_code"], "name": name,
                                        "jobs": int(jobs.get(name, 0)), "highPriorityJobs": int(high.get(name, 0)),
                                        "needsReview": int(old.get(name, 0))}})
    return {"type": "FeatureCollection", "features": features}


def main():
    ranked, tickets, reasons = score_like_the_loader()
    review = needs_review_json(tickets, reasons)
    workforce = workforce_file_payload()
    files = {
        "requests.geojson": requests_geojson(ranked),
        "needs_review.json": review,
        "communities.geojson": communities_geojson(ranked, review),
        "workforce.json": workforce,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = OUT_DIR / name
        path.write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8")
        print(f"  wrote {path.relative_to(REPO_ROOT)}  ({path.stat().st_size / 1e6:.2f} MB)")

    props = [f["properties"] for f in files["requests.geojson"]["features"]]
    bands = pd.Series([p["priorityBand"] for p in props]).value_counts().reindex(["High", "Medium", "Low"], fill_value=0)
    w = workforce["workforce"]
    print(f"Scored {len(props):,} of {len(tickets):,} open tickets with the team scorer (as of {SNAPSHOT_DAY}).")
    print(f"Levels: High {bands['High']:,} | Medium {bands['Medium']:,} | Low {bands['Low']:,}")
    print(f"Needs review: {review['count']:,}")
    print(f"Workforce: {w['available_people']} available people, {w['available_crews']} crews "
          f"(source: {w['source']})")


if __name__ == "__main__":
    main()
