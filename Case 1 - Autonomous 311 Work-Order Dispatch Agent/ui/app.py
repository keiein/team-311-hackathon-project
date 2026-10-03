"""
UI DRAFT: the screen supervisors (and judges) will see
=======================================================

How to run it (from the project folder):
    python -m streamlit run "Case 1 - Autonomous 311 Work-Order Dispatch Agent/ui/app.py"

Rule for this file: it does NO thinking. It only reads the backend's result files
and shows them. All the decisions (scoring, matching, re-planning) live in backend/.

Right now it reads backend/output/scored_jobs.csv (made by step 3) as STAND-IN data.
When the team's final dataset is ready, we only change the file name and column names below.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# WHERE THE DATA IS
# -----------------------------------------------------------------------------
HERE = Path(__file__).parent
DATA_FILE = HERE.parent / "backend" / "output" / "scored_jobs.csv"   # swap this later
REVIEW_FILE = HERE.parent / "backend" / "output" / "needs_review.csv"   # old tickets (step 3)

# One consistent order and wording for danger levels, everywhere on screen.
DANGER_ORDER = ["urgent", "important", "low"]

# -----------------------------------------------------------------------------
# THE DATA CONTRACT: the column names the rest of this file relies on
# -----------------------------------------------------------------------------
# These are OUR names. Everything below this block only uses these names.
REQUIRED_COLUMNS = ["service_request_id", "service_name", "crew", "danger", "score",
                    "days_waiting", "comm_name", "latitude", "longitude"]

# If the team's final table calls a column something else, fill it in here, ONE line each:
#     "their_name": "our_name"
# Example:  "severity_score": "score",   "community": "comm_name"
THEIR_NAMES_TO_OURS = {
    # (empty for now: our stand-in data already uses our names)
}

st.set_page_config(page_title="311 Crew Dispatcher", layout="wide")


def read_table(path) -> pd.DataFrame:
    """Read a CSV and rename any of their columns to ours.

    This is the ONLY place that knows where the data comes from. To read a Databricks
    table later, only this function changes (e.g. spark.table("name").toPandas()).
    """
    table = pd.read_csv(path, dtype={"service_request_id": str})
    return table.rename(columns=THEIR_NAMES_TO_OURS)


@st.cache_data   # remember the file after the first read, so the page reacts fast
def load_jobs() -> pd.DataFrame:
    return read_table(DATA_FILE)


# -----------------------------------------------------------------------------
# PAGE HEADER
# -----------------------------------------------------------------------------
st.title("311 Crew Dispatcher")
st.caption("Who should 311 send next? Dangerous jobs first, re-planned when a crew goes missing.")

if not DATA_FILE.exists():
    st.error("No data yet. Run backend steps 1, 2 and 3 first (see the backend folder).")
    st.stop()

jobs = load_jobs()

# Check the data has every column we need. If not, say exactly which ones are missing,
# instead of crashing later with a confusing message.
missing = [c for c in REQUIRED_COLUMNS if c not in jobs.columns]
if missing:
    st.error(f"The data is missing these columns: {', '.join(missing)}. "
             "Add them to THEIR_NAMES_TO_OURS at the top of app.py.")
    st.stop()

# -----------------------------------------------------------------------------
# THE 4 TABS (one per question the supervisor asks)
# -----------------------------------------------------------------------------
tab_queue, tab_plan, tab_noon, tab_review = st.tabs(
    ["1. Today's queue", "2. Our plan vs oldest-first", "3. A crew goes missing", "4. Needs review"])

# ---- TAB 1: "What is waiting today, and what comes first?" ------------------
with tab_queue:
    # Big numbers first: the judge should get the point in 5 seconds.
    left, mid, right = st.columns(3)
    left.metric("Jobs in today's queue", f"{len(jobs):,}")
    mid.metric("Urgent jobs", f"{(jobs['danger'] == 'urgent').sum():,}")
    right.metric("Longest wait (days)", f"{jobs['days_waiting'].max():,}")

    # Filters
    f1, f2 = st.columns(2)
    crews = f1.multiselect("Crew", sorted(jobs["crew"].unique()), default=sorted(jobs["crew"].unique()))
    levels = f2.multiselect("Danger", DANGER_ORDER, default=DANGER_ORDER)

    shown = jobs[jobs["crew"].isin(crews) & jobs["danger"].isin(levels)]
    st.write(f"Showing **{len(shown):,}** jobs, best score first.")
    st.dataframe(
        shown[["rank", "service_name", "crew", "danger", "score", "days_waiting", "comm_name"]],
        hide_index=True, use_container_width=True)

# ---- TABS 2 and 3 need the backend's matching step, which isn't built yet ---
with tab_plan:
    st.info("Coming next: which crew does which job, side by side with oldest-first, "
            "plus the big numbers (urgent jobs fixed, kilometres driven).")

with tab_noon:
    st.info("Coming next: pick a crew, send it home at noon, and see which jobs move "
            "and which wait until tomorrow.")

# ---- TAB 4: "Which old tickets should a supervisor check?" ------------------
with tab_review:
    if not REVIEW_FILE.exists():
        st.info("No needs-review file yet. Run backend step 3.")
    else:
        old = read_table(REVIEW_FILE)

        st.markdown(
            "These tickets are still marked open after **more than 60 days**. Many were probably "
            "fixed but never closed (for example, ice from a past winter). We do **not** send crews "
            "to them blindly. A supervisor checks them instead, **dangerous types first**.")

        a, b, c = st.columns(3)
        a.metric("Tickets to review", f"{len(old):,}")
        b.metric("Urgent types among them", f"{(old['danger'] == 'urgent').sum():,}")
        c.metric("Oldest (days)", f"{old['days_waiting'].max():,}")

        # Which types have the biggest pile? A supervisor can close a whole type at once.
        by_type = (old.groupby(["service_name", "danger"]).size().rename("tickets").reset_index()
                   .sort_values("tickets", ascending=False))
        st.subheader("Biggest piles, by type")
        st.dataframe(by_type.head(15), hide_index=True, use_container_width=True)

        st.subheader("Review list, most dangerous first")
        order = {level: i for i, level in enumerate(DANGER_ORDER)}
        review_list = old.sort_values(
            ["danger", "days_waiting"], key=lambda col: col.map(order) if col.name == "danger" else -col)
        st.dataframe(review_list[["service_request_id", "service_name", "crew", "danger",
                                  "days_waiting", "comm_name"]],
                     hide_index=True, use_container_width=True)
