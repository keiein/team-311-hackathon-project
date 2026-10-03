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

# One consistent order and wording for danger levels, everywhere on screen.
DANGER_ORDER = ["urgent", "important", "low"]

st.set_page_config(page_title="311 Crew Dispatcher", layout="wide")


@st.cache_data   # remember the file after the first read, so the page reacts fast
def load_jobs() -> pd.DataFrame:
    return pd.read_csv(DATA_FILE, dtype={"service_request_id": str})


# -----------------------------------------------------------------------------
# PAGE HEADER
# -----------------------------------------------------------------------------
st.title("311 Crew Dispatcher")
st.caption("Who should 311 send next? Dangerous jobs first, re-planned when a crew goes missing.")

if not DATA_FILE.exists():
    st.error("No data yet. Run backend steps 1, 2 and 3 first (see the backend folder).")
    st.stop()

jobs = load_jobs()

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
    st.info("Coming next: the old tickets (waiting over 60 days) that need a supervisor to check "
            "whether they are still real.")
