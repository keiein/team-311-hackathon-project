"""Load the scored queue into MySQL. One run of the scorer becomes one run_id in scored_tickets.

    tickets.csv -> PriorityScorer -> rank -> scored_tickets

The loader keeps the columns the table has and adds the three the scorer doesn't return:
run_id, scored_at and priority_rank. A run goes in whole or not at all, and every run is
kept, so loading twice gives two runs.
Table notes: SCORED_TICKETS.md. The table itself: schema.sql.

Run it:  python load_scored_tickets.py [tickets.csv] [--now 2026-10-02]
"""
import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

import mysql.connector
import pandas as pd

from priority_score import TICKETS, AgeScore, PriorityScorer, ScoreComponent, _when

# ---- where the scores go (placeholder: the local MySQL that schema.sql sets up; MYSQL_* in the environment override it) ----
DATABASE = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "dispatch_311"),
}
TABLE = "scored_tickets"

# ---- the table's columns, in the table's order. A column the scorer didn't return is loaded empty ----
# crew_pool is kept as service-area metadata for reporting; it does not gate dispatch capacity.
COLUMNS = (
    "run_id", "service_request_id", "scored_at",
    "service_name", "requested_date", "comm_code", "comm_name", "longitude", "latitude",
    "crew_pool", "work_category", "call_confidence",
    "priority", "priority_rank", "basic_knowledge_score", "geo_score", "age_score", "ticket_count_score",
    "criticality_tier", "criticality_keywords", "same_day_ticket_count",
    "open_days", "open_hours", "sla_days", "sla_ratio", "overdue", "overdue_days", "overdue_hours",
    "keyword_found", "community_found", "sla_found",
)
INSERT = f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))})"


def scorer_at(now: datetime) -> PriorityScorer:
    """The default scorer with its clock fixed, so every ticket of a run is aged against the same moment."""
    scorer = PriorityScorer()
    for component in scorer.components:
        if isinstance(component, AgeScore):
            component.now = now
    return scorer


def rank(scored: pd.DataFrame) -> pd.DataFrame:
    """The scored queue in dispatch order, with priority_rank 1..n.

    Ties on priority go to the ticket open longest, then to the lower ticket id, so the order never changes between reads.
    """
    ranked = scored.sort_values(["priority", "open_days", ScoreComponent.ID_FIELD], ascending=[False, False, True])
    return ranked.assign(priority_rank=range(1, len(ranked) + 1))


def _cell(value: Any) -> Any:
    """A value the connector can send: None for NaN and NaT, a plain Python value for the rest."""
    if value is None or isinstance(value, str):
        return value
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _rows(ranked: pd.DataFrame, run_id: int, scored_at: datetime) -> Iterator[tuple]:
    """One tuple per ticket, in COLUMNS order."""
    for record in ranked.to_dict("records"):
        record.update(run_id=run_id, scored_at=scored_at, requested_date=_when(record.get("requested_date")))
        yield tuple(_cell(record.get(column)) for column in COLUMNS)


def load(scored: pd.DataFrame, scored_at: datetime, run_id: Optional[int] = None) -> int:
    """Write one scoring run to the table and return its run_id (the next free one unless given).

    scored: what PriorityScorer.score_frame() returns; it is ranked here unless it already has priority_rank.
    crew_pool on each ticket is stored as metadata only; dispatch capacity comes from workforce.
    """
    ranked = scored if "priority_rank" in scored else rank(scored)
    connection = mysql.connector.connect(**DATABASE)
    try:
        cursor = connection.cursor()
        if run_id is None:
            cursor.execute(f"SELECT COALESCE(MAX(run_id), 0) + 1 FROM {TABLE}")
            run_id = int(cursor.fetchone()[0])
        cursor.executemany(INSERT, list(_rows(ranked, run_id, scored_at)))
        connection.commit()
    finally:
        connection.close()  # closing before the commit drops the whole run
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score open 311 crew jobs and load them into MySQL.")
    parser.add_argument("tickets", nargs="?", type=Path, default=TICKETS,
                        help="ticket CSV (default: open_tickets.csv, where priority_score.py finds it)")
    parser.add_argument("--now", help="score as of this date or time (default: the machine clock)")
    args = parser.parse_args()

    scored_at = _when(args.now) if args.now else datetime.now()
    if scored_at is None:
        parser.error(f"--now is not a readable date: {args.now!r}")
    scored_at = scored_at.replace(microsecond=0)  # the table keeps whole seconds

    tickets = pd.read_csv(args.tickets, low_memory=False)
    scored = scorer_at(scored_at).score_frame(tickets)
    run_id = load(scored, scored_at)

    print(f"{args.tickets.name}: {len(tickets):,} tickets, {len(scored):,} scored")
    print(f"Loaded into {DATABASE['database']}.{TABLE} as run {run_id}, scored at {scored_at}")
