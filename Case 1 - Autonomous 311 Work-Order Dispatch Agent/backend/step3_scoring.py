"""
STEP 3: SCORING   (the "Scoring" box under Demand/Severity on our whiteboard)
==============================================================================

What this file does, in plain words:
    Give every crew job from step 2 a SCORE, then rank them from highest to lowest.

        score = danger points  +  waiting bonus

    1. Danger points (from the danger word in crew_types.csv):
           urgent = 10, important = 6, low = 1

    2. Waiting bonus (idea from Alvin's guide):
           Every type has a "normal fixing time": how many days the City usually needs
           (9 out of 10 tickets of that type are fixed within this time).
           - waited less than the normal time      -> +0  (on time)
           - waited longer than the normal time    -> +1  (late)
           - waited more than TWICE the normal time -> +2  (very late)

    Why the gaps are big (10, 6, 1) and the bonus is small (max +2):
        The gap between two danger levels (4 or 5) is bigger than the biggest bonus (2).
        So waiting can only break ties INSIDE a danger level. A very late "low" job
        can never jump ahead of an "urgent" one. Otherwise we'd be back to oldest-first.

    Very old jobs go to a "needs review" list, NOT today's ranking:
        Many tickets are still marked "open" after years (e.g. ice from winter 2023).
        They were probably fixed but never closed. So jobs waiting more than 60 days
        go to a separate list for a supervisor to check, instead of sending a crew.
        (60 days = the same "stuck" line Alvin's spreadsheet uses.)

How to run it (from the project folder, AFTER steps 1 and 2):
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/step3_scoring.py"

What comes out:
    backend/output/scored_jobs.csv    (recent crew jobs with their score, best first)
    backend/output/needs_review.csv   (jobs older than 60 days, for a supervisor to check)
"""

from pathlib import Path

import pandas as pd

# -----------------------------------------------------------------------------
# WHERE THE FILES ARE
# -----------------------------------------------------------------------------
HERE = Path(__file__).parent
CASE_FOLDER = HERE.parent
CREW_JOBS_FILE = HERE / "output" / "crew_jobs.csv"            # made by step 2
ALVIN_SPREADSHEET = CASE_FOLDER / "data" / "311_service_type_reference.xlsx"
OUTPUT_FILE = HERE / "output" / "scored_jobs.csv"
REVIEW_FILE = HERE / "output" / "needs_review.csv"

# -----------------------------------------------------------------------------
# THE NUMBERS WE CHOSE (team can change these)
# -----------------------------------------------------------------------------
DANGER_POINTS = {"urgent": 10, "important": 6, "low": 1}

# "Today" = the day the City's data was exported. Alvin's guide counts ticket age to this day.
TODAY = pd.Timestamp("2026-10-02")

# Limits on the "normal fixing time":
#   at least 1 day  -> one type has 0 days, and "how late" doesn't work with 0
#   at most 30 days -> some types show 400+ days because of the City's backlog, not because
#                      that's a fair target. We say: every repair should be done within a month.
MIN_NORMAL_DAYS = 1
MAX_NORMAL_DAYS = 30

# Jobs waiting longer than this go to the "needs review" list instead of today's ranking.
REVIEW_AFTER_DAYS = 60


def load_crew_jobs() -> pd.DataFrame:
    """Read the crew jobs that step 2 saved."""
    if not CREW_JOBS_FILE.exists():
        raise SystemExit("No crew_jobs.csv yet. Run step 1 and step 2 first.")
    return pd.read_csv(CREW_JOBS_FILE, dtype={"service_request_id": str},
                       parse_dates=["requested_date"])


def normal_fixing_days() -> pd.Series:
    """For each type: how many days the City normally needs (from Alvin's spreadsheet).

    We use his 'p90_days_to_close' column: 9 out of 10 tickets of that type close within it.
    Then we apply our limits (at least 1 day, at most 30 days).
    """
    tab = pd.read_excel(ALVIN_SPREADSHEET, sheet_name="Service Types")
    tab = tab.drop_duplicates("service_name").set_index("service_name")
    # clip = squeeze every number into the range [MIN, MAX]
    return tab["p90_days_to_close"].clip(lower=MIN_NORMAL_DAYS, upper=MAX_NORMAL_DAYS)


def waiting_bonus(days_waiting: int, normal_days: float) -> int:
    """+0 if on time, +1 if late, +2 if very late (more than twice the normal time)."""
    if days_waiting > 2 * normal_days:
        return 2
    if days_waiting > normal_days:
        return 1
    return 0


def score(jobs: pd.DataFrame, normal_days: pd.Series) -> pd.DataFrame:
    """Add days_waiting, normal_days, danger_points, bonus and score to every job."""
    jobs = jobs.copy()

    # How long has each job been waiting? (today minus the day it was reported)
    jobs["days_waiting"] = (TODAY - jobs["requested_date"]).dt.days

    # Look up each job's normal fixing time by its type.
    # If a type is somehow missing from Alvin's sheet, use the 30-day limit.
    jobs["normal_days"] = jobs["service_name"].map(normal_days).fillna(MAX_NORMAL_DAYS)

    # Danger word -> points.
    jobs["danger_points"] = jobs["danger"].map(DANGER_POINTS)

    # Bonus for waiting, worked out row by row.
    jobs["bonus"] = [waiting_bonus(d, n) for d, n in zip(jobs["days_waiting"], jobs["normal_days"])]

    jobs["score"] = jobs["danger_points"] + jobs["bonus"]

    # Rank: highest score first. If two scores are equal, the one waiting longer goes first.
    jobs = jobs.sort_values(["score", "days_waiting"], ascending=[False, False])
    jobs["rank"] = range(1, len(jobs) + 1)
    return jobs


def split_old_jobs(jobs: pd.DataFrame):
    """Split into (recent jobs, very old jobs) using REVIEW_AFTER_DAYS.

    Old jobs are NOT deleted. They go on a separate list for a supervisor to check.
    """
    is_old = jobs["days_waiting"] > REVIEW_AFTER_DAYS
    return jobs[~is_old], jobs[is_old]


def main():
    jobs = load_crew_jobs()
    all_scored = score(jobs, normal_fixing_days())

    scored, needs_review = split_old_jobs(all_scored)
    scored = scored.copy()
    scored["rank"] = range(1, len(scored) + 1)   # re-number the ranking after the split

    print(f"Crew jobs from step 2:              {len(all_scored):>7,}")
    print(f"  Waiting over {REVIEW_AFTER_DAYS} days -> needs review: {len(needs_review):>7,}")
    print(f"  Recent -> today's ranking:        {len(scored):>7,}\n")

    print("How many jobs got each score:")
    print(scored.groupby(["danger", "score"]).size().rename("jobs").to_string())

    # Safety check for Rule 2: the lowest urgent score must beat the highest important score, etc.
    lowest = scored.groupby("danger")["score"].min()
    highest = scored.groupby("danger")["score"].max()
    ok = lowest["urgent"] > highest["important"] > 0 and lowest["important"] > highest["low"]
    print(f"\nCheck: a lower danger level never beats a higher one -> {'OK' if ok else 'PROBLEM'}")

    print("\nTop 10 jobs right now:")
    cols = ["rank", "service_name", "crew", "danger", "days_waiting", "normal_days", "bonus", "score"]
    print(scored[cols].head(10).to_string(index=False))

    keep_cols = ["rank", "service_request_id", "service_name", "crew", "danger", "danger_points",
                 "days_waiting", "normal_days", "bonus", "score", "comm_name", "latitude", "longitude"]
    scored[keep_cols].to_csv(OUTPUT_FILE, index=False)
    needs_review[keep_cols[1:]].to_csv(REVIEW_FILE, index=False)   # no rank: not in today's plan
    print(f"\nSaved to: {OUTPUT_FILE.relative_to(CASE_FOLDER)}")
    print(f"Saved to: {REVIEW_FILE.relative_to(CASE_FOLDER)}")


if __name__ == "__main__":
    main()
