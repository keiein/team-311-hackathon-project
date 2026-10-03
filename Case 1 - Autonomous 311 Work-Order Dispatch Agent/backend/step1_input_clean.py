"""
STEP 1: INPUT -> CLEAN   (the first box on our whiteboard)
==========================================================

What this file does, in plain words:
    1. Read every 311 complaint from Alvin's zip file (about 2 million).
    2. Keep only the columns we need.
    3. Turn the date text into real dates.
    4. Remove junk: tickets listed twice, and tickets marked "Duplicate".
    5. Keep only OPEN tickets (still waiting = today's pile of work).
    6. Save the result to a small file, so the next steps don't re-read 2 million rows.

Two ways to get the data:
    - From Alvin's zip file (default): a copy downloaded on Oct 2, 2026.
    - From the City's website (--api): live data, downloaded fresh every time you run it.
      The City does the "open only" filter for us, so we only download ~57k rows, not 2 million.

How to run it (from the project folder):
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/step1_input_clean.py"         (zip)
    python "Case 1 - Autonomous 311 Work-Order Dispatch Agent/backend/step1_input_clean.py" --api   (live)

What comes out:
    backend/output/open_tickets.csv   (the cleaned pile of open complaints)
"""

import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests   # a tool for asking websites for data

# -----------------------------------------------------------------------------
# WHERE THE FILES ARE
# -----------------------------------------------------------------------------
# Path(__file__).parent = the folder this file lives in (backend/).
# .parent again        = one folder up (the "Case 1" folder).
HERE = Path(__file__).parent
CASE_FOLDER = HERE.parent
ZIP_FILE = CASE_FOLDER / "data" / "311_Service_Requests_20261002.zip"
OUTPUT_FILE = HERE / "output" / "open_tickets.csv"

# -----------------------------------------------------------------------------
# THE COLUMNS WE KEEP (the file has 15, we only need these 9)
# -----------------------------------------------------------------------------
COLUMNS_WE_NEED = [
    "service_request_id",   # the ticket number, like an order number
    "requested_date",       # when someone reported it
    "closed_date",          # when it was fixed (empty if not fixed yet)
    "status_description",   # Open / Closed / Duplicate ...
    "service_name",         # WHAT the problem is, e.g. "Roads - Pothole Maintenance"
    "agency_responsible",   # WHICH City department handles it
    "comm_name",            # WHICH neighbourhood
    "latitude",             # map location (north-south)
    "longitude",            # map location (east-west)
]

# The dates in the file look like "2024/10/17 12:00:00 AM".
# This pattern tells Python how to read them:
#   %Y = year, %m = month, %d = day, %I = hour (1-12), %M = minute, %S = second, %p = AM/PM
DATE_PATTERN = "%Y/%m/%d %I:%M:%S %p"

# -----------------------------------------------------------------------------
# THE CITY'S WEBSITE (API)
# -----------------------------------------------------------------------------
# Open Calgary "311 Service Requests" (all years). Same table Alvin's zip came from.
CITY_API_URL = "https://data.calgary.ca/resource/iahh-g8bj.csv"
# Only complaints from this date on. Alvin's zip starts on Jan 2, 2023 (not Jan 1),
# so we use the same day to get exactly the same complaints.
SINCE = "2023-01-02"


def read_complaints(zip_path=ZIP_FILE) -> pd.DataFrame:
    """Read the big complaints file straight out of the zip (no need to unzip it).

    A DataFrame is just a table, like an Excel sheet, that Python can work with.
    """
    with zipfile.ZipFile(zip_path) as z:
        csv_name = z.namelist()[0]   # the zip holds one file; take its name
        with z.open(csv_name) as f:
            # usecols = only load the columns we need (saves memory and time)
            # dtype=str for the id = keep ticket numbers as text, e.g. "24-00809595"
            table = pd.read_csv(f, usecols=COLUMNS_WE_NEED,
                                dtype={"service_request_id": str}, low_memory=False)
    return table


def read_open_complaints_from_api() -> pd.DataFrame:
    """Ask the City's website for every OPEN complaint since SINCE (live data).

    We send the City a question, like a search filter:
        $select = which columns we want
        $where  = only status "Open", only since 2023
        $limit  = how many rows at most (the City sends only 1,000 unless we ask for more)
    Duplicates have the status "Duplicate (Open)", not "Open", so they are left out automatically.
    """
    question = {
        "$select": ", ".join(COLUMNS_WE_NEED),
        "$where": f"status_description='Open' AND requested_date >= '{SINCE}'",
        "$limit": 200000,
    }
    answer = requests.get(CITY_API_URL, params=question, timeout=300)
    answer.raise_for_status()   # stop with a clear error if the website said no

    # The answer is CSV text; read it into a table just like a file.
    table = pd.read_csv(io.StringIO(answer.text), dtype={"service_request_id": str})

    # The website writes dates like "2024-11-05T00:00:00.000" (a different style from the zip),
    # so we turn them into real dates here.
    for col in ("requested_date", "closed_date"):
        table[col] = pd.to_datetime(table[col], errors="coerce")
    return table


def clean(table: pd.DataFrame) -> pd.DataFrame:
    """Fix the dates and remove junk. Returns a cleaner table."""
    table = table.copy()   # work on a copy so we never change the original by accident

    # 1. Text -> real dates. errors="coerce" = if a date is broken, leave it empty
    #    instead of crashing.
    #    (Skip columns that are already real dates, e.g. when the data came from the API.)
    for col in ("requested_date", "closed_date"):
        if not pd.api.types.is_datetime64_any_dtype(table[col]):
            table[col] = pd.to_datetime(table[col], format=DATE_PATTERN, errors="coerce")

    # 2. Same ticket number twice? Keep only the first one.
    table = table.drop_duplicates(subset="service_request_id")

    # 3. The City marks repeat reports as "Duplicate (Open)" or "Duplicate (Closed)".
    #    They are the same problem reported again, so a crew should not go twice.
    is_duplicate = table["status_description"].str.contains("Duplicate", case=False, na=False)
    table = table[~is_duplicate]   # ~ means "NOT", so: keep the rows that are NOT duplicates

    # 4. A ticket with no date or no type can't be planned, so drop it.
    table = table.dropna(subset=["requested_date", "service_name"])

    return table


def keep_open(table: pd.DataFrame) -> pd.DataFrame:
    """Keep only tickets that are still waiting to be fixed (status = "Open")."""
    return table[table["status_description"] == "Open"]


def main():
    # --api on the command line = get live data from the City instead of the zip.
    parser = argparse.ArgumentParser(description="Step 1: read and clean 311 complaints")
    parser.add_argument("--api", action="store_true", help="download live data from the City's website")
    args = parser.parse_args()

    if args.api:
        print("Downloading open complaints from the City's website (a few seconds)...")
        everything = read_open_complaints_from_api()
    else:
        print("Reading complaints from the zip (this takes about a minute)...")
        everything = read_complaints()
    print(f"  Read:                {len(everything):>10,} complaints")

    cleaned = clean(everything)
    print(f"  After removing junk: {len(cleaned):>10,} complaints")

    open_now = keep_open(cleaned)
    print(f"  Still open (today's pile): {len(open_now):>4,} complaints")

    # Save the result, so the next step can start from this small file.
    OUTPUT_FILE.parent.mkdir(exist_ok=True)   # make the output/ folder if it doesn't exist
    open_now.to_csv(OUTPUT_FILE, index=False)
    print(f"  Saved to: {OUTPUT_FILE.relative_to(CASE_FOLDER)}")

    # A quick look: the 10 most common types of open complaint.
    print("\nMost common open complaints:")
    print(open_now["service_name"].value_counts().head(10).to_string())


# This line means: only run main() when you run THIS file directly
# (not when another file borrows functions from it).
if __name__ == "__main__":
    main()
