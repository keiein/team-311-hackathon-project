"""
EXPORT TEAM SCORES: the team's official priority score -> the file the website reads
====================================================================================

What this file does, in plain words:
    1. Runs Alvin's scorer (scoring/priority_score.py), the team's official formula:
           priority = 0.40 x basic knowledge + 0.25 x geography + 0.20 x age + 0.15 x number of tickets
       on the team's cleaned open tickets, with the clock set to the data's snapshot day (Oct 2, 2026).
       This is the same scoring and the same order his MySQL loader (load_scored_tickets.py) writes
       into the scored_tickets table, so the website and the database show the same ranking.
    2. Writes frontend/public/data/requests.geojson, the file the Requests page reads and that
       make_dispatch_standin.py builds the Dispatch, Crews and Reports data from.

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
OUT_FILE = REPO_ROOT / "frontend" / "public" / "data" / "requests.geojson"

# Alvin's scorer, used as it is (not copied): scoring/ sits beside this backend/ folder.
sys.path.insert(0, str(CASE_FOLDER / "scoring"))
from priority_score import TICKETS, AgeScore, PriorityScorer, ScoreComponent  # noqa: E402

# =============================================================================
# SETTINGS
# =============================================================================
SNAPSHOT_DAY = "2026-10-02"        # the day the City's data was exported; ages are measured to this day
HIGH_AT, MEDIUM_AT = 80, 50        # level cut-offs on the 0-100 score, the same as the map's colours
TIER_NAMES = {4: "Critical", 3: "Major", 2: "Moderate", 1: "Minor"}   # Alvin's / keiein's tier titles

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


def score_like_the_loader() -> pd.DataFrame:
    """Score and rank exactly as load_scored_tickets.py does (without needing MySQL)."""
    tickets = pd.read_csv(TICKETS, low_memory=False)
    scorer = PriorityScorer()
    for component in scorer.components:              # fix the clock, like scorer_at(--now 2026-10-02)
        if isinstance(component, AgeScore):
            component.now = pd.Timestamp(SNAPSHOT_DAY).to_pydatetime()
    scored = scorer.score_frame(tickets)
    # Same order as load_scored_tickets.rank(): priority high->low, then open longest, then ticket id
    ranked = scored.sort_values(["priority", "open_days", ScoreComponent.ID_FIELD], ascending=[False, False, True])
    return ranked.assign(priority_rank=range(1, len(ranked) + 1)), len(tickets)


def band(score: float) -> str:
    if score >= HIGH_AT:
        return "High"
    return "Medium" if score >= MEDIUM_AT else "Low"


def why(keywords) -> str:
    """Plain words for the severity part of the score."""
    if isinstance(keywords, str) and keywords.strip():
        return f"Keywords: {keywords.strip()}"
    return "No keyword matched (lowest tier)"


def as_geojson(ranked: pd.DataFrame) -> dict:
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
                "community": "" if pd.isna(r.comm_name) else str(r.comm_name),
                "status": "Open",
                "daysWaiting": int(r.open_days) if not pd.isna(r.open_days) else None,
                "overdue": bool(r.overdue) if not pd.isna(r.overdue) else None,
                # the four parts of the score, each 0 to 1 (for anyone who asks "why this number?")
                "basicKnowledgeScore": round(float(r.basic_knowledge_score), 3),
                "geoScore": round(float(r.geo_score), 3),
                "ageScore": round(float(r.age_score), 3),
                "ticketCountScore": round(float(r.ticket_count_score), 3),
            }})
    return {"type": "FeatureCollection", "features": features}


def main():
    ranked, total = score_like_the_loader()
    data = as_geojson(ranked)
    OUT_FILE.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    props = [f["properties"] for f in data["features"]]
    bands = pd.Series([p["priorityBand"] for p in props]).value_counts().reindex(["High", "Medium", "Low"], fill_value=0)
    print(f"Scored {len(props):,} of {total:,} open tickets with the team scorer (as of {SNAPSHOT_DAY}).")
    print(f"Levels: High {bands['High']:,} | Medium {bands['Medium']:,} | Low {bands['Low']:,}")
    print(f"wrote {OUT_FILE.relative_to(REPO_ROOT)}  ({OUT_FILE.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
