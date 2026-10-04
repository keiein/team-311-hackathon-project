"""Shared operational workforce for the hackathon JSON stand-in.

Source of truth order:
  1. MySQL `workforce` row (workforce_id = 1), when the local DB is reachable
  2. Otherwise the same SIMULATED PLACEHOLDER values as scoring/schema.sql

Frontend never hardcodes headcounts; it reads frontend/public/data/workforce.json.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Matches scoring/schema.sql — SIMULATED PLACEHOLDER, not real City staffing.
DEFAULT_TOTAL_PEOPLE = 100
DEFAULT_PEOPLE_PER_CREW = 5
DEFAULT_BUSY = 0
DEFAULT_SICK = 0
DEFAULT_SNOW = 0

# Demo disruptions for the Crews page (precomputed; React must not recalculate).
DEMO_SICK = 7
DEMO_SNOW = 30


def _available(total: int, busy: int, sick: int, snow: int, people_per_crew: int) -> tuple[int, int]:
    people = total - busy - sick - snow
    crews = people // people_per_crew if people_per_crew > 0 else 0
    return people, crews


def snapshot(
    *,
    total_people: int = DEFAULT_TOTAL_PEOPLE,
    busy_people: int = DEFAULT_BUSY,
    sick_people: int = DEFAULT_SICK,
    snow_redeployed: int = DEFAULT_SNOW,
    people_per_crew: int = DEFAULT_PEOPLE_PER_CREW,
    source: str = "scoring/schema.sql simulated placeholder",
) -> dict[str, Any]:
    available_people, available_crews = _available(
        total_people, busy_people, sick_people, snow_redeployed, people_per_crew
    )
    return {
        "workforce_id": 1,
        "total_people": total_people,
        "busy_people": busy_people,
        "sick_people": sick_people,
        "snow_redeployed": snow_redeployed,
        "people_per_crew": people_per_crew,
        "available_people": available_people,
        "available_crews": available_crews,
        "isSimulatedPlaceholder": True,
        "source": source,
        "note": (
            "SIMULATED PLACEHOLDER workforce for the hackathon — not real City of Calgary staffing. "
            "All workers are assumed able to take any selected 311 job."
        ),
    }


def load_from_mysql() -> Optional[dict[str, Any]]:
    """Return the live workforce row, or None if MySQL is unavailable / empty."""
    try:
        import mysql.connector
    except ImportError:
        return None
    config = {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DATABASE", "dispatch_311"),
    }
    try:
        connection = mysql.connector.connect(**config)
    except Exception:
        return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT workforce_id, total_people, busy_people, sick_people, snow_redeployed,
                   people_per_crew, available_people, available_crews
            FROM workforce
            WHERE workforce_id = 1
            """
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "workforce_id": int(row["workforce_id"]),
            "total_people": int(row["total_people"]),
            "busy_people": int(row["busy_people"]),
            "sick_people": int(row["sick_people"]),
            "snow_redeployed": int(row["snow_redeployed"]),
            "people_per_crew": int(row["people_per_crew"]),
            "available_people": int(row["available_people"]),
            "available_crews": int(row["available_crews"]),
            "isSimulatedPlaceholder": True,
            "source": "MySQL dispatch_311.workforce",
            "note": (
                "Loaded from MySQL workforce table. total_people is a SIMULATED PLACEHOLDER "
                "unless you changed it — not a real City staffing figure."
            ),
        }
    except Exception:
        return None
    finally:
        connection.close()


def load_workforce() -> dict[str, Any]:
    """One source for generators: MySQL when possible, else schema defaults."""
    live = load_from_mysql()
    if live is not None:
        return live
    return snapshot(source="scoring/schema.sql simulated placeholder (MySQL not reachable)")


def with_counts(base: dict[str, Any], *, busy: Optional[int] = None, sick: Optional[int] = None,
                snow: Optional[int] = None) -> dict[str, Any]:
    """Derive a workforce snapshot from a base row (keeps total_people / people_per_crew)."""
    return snapshot(
        total_people=int(base["total_people"]),
        busy_people=int(base["busy_people"] if busy is None else busy),
        sick_people=int(base["sick_people"] if sick is None else sick),
        snow_redeployed=int(base["snow_redeployed"] if snow is None else snow),
        people_per_crew=int(base["people_per_crew"]),
        source=base.get("source", "derived"),
    )


def scenarios_from(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Precomputed Normal / Sick / Blizzard views for the Crews page."""
    total = int(base["total_people"])
    ppc = int(base["people_per_crew"])
    busy = int(base.get("busy_people", 0))
    return {
        "normal": snapshot(
            total_people=total, busy_people=0, sick_people=0, snow_redeployed=0,
            people_per_crew=ppc, source=base.get("source", ""),
        ),
        "sick": snapshot(
            total_people=total, busy_people=0, sick_people=DEMO_SICK, snow_redeployed=0,
            people_per_crew=ppc, source=base.get("source", ""),
        ),
        "blizzard": snapshot(
            total_people=total, busy_people=0, sick_people=DEMO_SICK, snow_redeployed=DEMO_SNOW,
            people_per_crew=ppc, source=base.get("source", ""),
        ),
        # Keep a copy of "current" operational state (may include busy from dispatch).
        "current": with_counts(base, busy=busy),
    }


def workforce_file_payload(base: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Shape written to frontend/public/data/workforce.json."""
    workforce = base if base is not None else load_workforce()
    return {
        "workforce": workforce,
        "scenarios": scenarios_from(workforce),
        "rules": [
            "One shared operational workforce; tickets are not limited by specialized crew_pool.",
            "crew_pool on a ticket is service-area metadata only.",
            f"Each dispatched job uses people_per_crew people (default {DEFAULT_PEOPLE_PER_CREW}).",
            "Sick call: sick_people += N (do not reduce total_people).",
            "Snow event: snow_redeployed += N (no dedicated snow crew).",
            "Job dispatched: busy_people += people_per_crew; released: busy_people -= people_per_crew.",
            "available_people and available_crews come from the generator/MySQL — not recalculated in React.",
        ],
    }
