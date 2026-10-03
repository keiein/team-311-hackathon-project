"""
STEP 2: CATEGORY   (the box after Input -> Clean on our whiteboard)
==================================================================

What this file does, in plain words:
    For every open complaint from step 1, decide:
      - Is it a CREW job (something broken outside that a crew fixes)?
      - If yes, WHICH crew (roads, water or garbage) and HOW DANGEROUS (urgent, important, low)?

    The decisions come from ONE list file, crew_types.csv, that anyone on the team can
    open in Excel and change. No code changes needed.

The 3 questions we ask about each complaint type:
    1. Is it in our list as a Roads / Water / Garbage repair?   (name + department)
    2. Does our list say "keep"?                                (repair, not a question or request)
    3. Did the City still get this type in 2026?                (not an old, retired type)
    If any answer is NO, we skip it and write down why.

!! The danger levels in crew_types.csv are TEMPORARY guesses.
!! When Alvin's severity list is ready, update the "danger" column. Nothing else changes.

How to run it (from the project folder, AFTER step 1):
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/step2_category.py"

What comes out:
    backend/output/crew_jobs.csv   (only the open complaints that ARE crew jobs, with crew + danger)
"""

from pathlib import Path

import pandas as pd

# -----------------------------------------------------------------------------
# WHERE THE FILES ARE
# -----------------------------------------------------------------------------
HERE = Path(__file__).parent
CASE_FOLDER = HERE.parent
OPEN_TICKETS_FILE = HERE / "output" / "open_tickets.csv"      # made by step 1
CREW_TYPES_FILE = HERE / "crew_types.csv"                     # our keep/skip list
ALVIN_SPREADSHEET = CASE_FOLDER / "data" / "311_service_type_reference.xlsx"
OUTPUT_FILE = HERE / "output" / "crew_jobs.csv"


def load_open_tickets() -> pd.DataFrame:
    """Read the open complaints that step 1 saved."""
    if not OPEN_TICKETS_FILE.exists():
        raise SystemExit("No open_tickets.csv yet. Run step1_input_clean.py first.")
    return pd.read_csv(OPEN_TICKETS_FILE, dtype={"service_request_id": str},
                       parse_dates=["requested_date", "closed_date"])


def load_crew_types() -> pd.DataFrame:
    """Read our keep/skip list (crew_types.csv)."""
    return pd.read_csv(CREW_TYPES_FILE)


def types_used_in_2026() -> set:
    """The complaint types the City still received in 2026, from Alvin's spreadsheet.

    His '2026 Remaining Services' tab only lists types with at least 1 ticket in 2026.
    A set is just a list where we can quickly check "is this name in it?".
    """
    tab = pd.read_excel(ALVIN_SPREADSHEET, sheet_name="2026 Remaining Services")
    return set(tab["service_name"])


def categorize(tickets: pd.DataFrame, crew_types: pd.DataFrame, still_used: set) -> pd.DataFrame:
    """Add crew / danger / keep / skip_reason to every ticket.

    We look each ticket's type up in our list, like looking up a word in a dictionary.
    """
    # merge = join two tables on a shared column (here: the type name).
    # how="left" = keep EVERY ticket, even if its type isn't in our list
    #              (those get empty values, and we skip them below).
    table = tickets.merge(crew_types, on="service_name", how="left")

    in_list = table["keep"].notna()           # question 1: is the type in our list?
    list_says_keep = table["keep"] == "yes"   # question 2: does the list say keep?
    used_2026 = table["service_name"].isin(still_used)   # question 3: still used this year?

    # Write down WHY we skip, so we can explain every decision to the judges.
    # We check the questions in order; the first "no" is the reason.
    table["skip_reason"] = ""
    table.loc[~in_list, "skip_reason"] = "Not a Roads/Water/Garbage repair type"
    table.loc[in_list & ~list_says_keep, "skip_reason"] = "Our list says skip: " + table["reason"]
    table.loc[in_list & list_says_keep & ~used_2026, "skip_reason"] = "Type not used in 2026 (old leftover)"

    table["is_crew_job"] = table["skip_reason"] == ""
    return table


def main():
    tickets = load_open_tickets()
    crew_types = load_crew_types()
    still_used = types_used_in_2026()

    table = categorize(tickets, crew_types, still_used)
    crew_jobs = table[table["is_crew_job"]]
    skipped = table[~table["is_crew_job"]]

    print(f"Open complaints from step 1: {len(table):>7,}")
    print(f"  Skipped (not crew jobs):   {len(skipped):>7,}")
    print(f"  Crew jobs (kept):          {len(crew_jobs):>7,}")

    # Biggest reasons for skipping (top 8), so we can see what we threw out.
    print("\nWhy we skipped (biggest reasons):")
    print(skipped["skip_reason"].value_counts().head(8).to_string())

    # The kept jobs, by crew and danger level.
    print("\nCrew jobs by crew and danger:")
    print(crew_jobs.groupby(["crew", "danger"]).size().to_string())

    # Save only the kept jobs, with the columns later steps need.
    keep_cols = ["service_request_id", "requested_date", "service_name", "agency_responsible",
                 "comm_name", "latitude", "longitude", "crew", "danger"]
    crew_jobs[keep_cols].to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved to: {OUTPUT_FILE.relative_to(CASE_FOLDER)}")


if __name__ == "__main__":
    main()
