"""Copy finished 311 intake calls from ElevenLabs into Databricks.

Run from the repo root:
    python3 "11lab Call Agent/sync_tickets.py"           # one pass
    python3 "11lab Call Agent/sync_tickets.py" --watch   # keep checking every few seconds (for the demo)

Each finished call becomes one row in workspace.calgary311.phone_tickets if the caller
reported a problem or asked for a person. handled_by says who finishes it:
"AI" = the voice agent completed and confirmed it, "Needs agent" = a call centre agent
should pick it up on the dashboard. The first 15 columns match the City's raw 311 columns.
Needs ELEVENLABS_API_KEY in .env and a Databricks CLI login (databricks auth login).
"""
import csv
import datetime
import difflib
import json
import os
import pathlib
import subprocess
import sys
import time
import zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_ID = (pathlib.Path(__file__).resolve().parent / "agent_id.txt").read_text().strip()
ELEVEN = "https://api.elevenlabs.io/v1/convai"
DATABRICKS = os.path.expanduser("~/.local/bin/databricks")
WAREHOUSE_ID = "266fb086a7571831"
TABLE = "workspace.calgary311.phone_tickets"
CALGARY = zoneinfo.ZoneInfo("America/Edmonton")
POLL_SECONDS = 5

# name, SQL type. The first 15 are the City's raw columns, in the City's order.
COLUMNS = [
    ("service_request_id", "STRING"), ("requested_date", "DATE"), ("updated_date", "DATE"),
    ("closed_date", "DATE"), ("status_description", "STRING"), ("source", "STRING"),
    ("service_name", "STRING"), ("agency_responsible", "STRING"), ("address", "STRING"),
    ("comm_code", "STRING"), ("comm_name", "STRING"), ("location_type", "STRING"),
    ("longitude", "DOUBLE"), ("latitude", "DOUBLE"), ("point", "STRING"),
    # extra columns that only phone tickets have
    ("category", "STRING"), ("problem_description", "STRING"), ("is_urgent", "BOOLEAN"),
    ("caller_name", "STRING"), ("callback_number", "STRING"), ("wants_human_agent", "BOOLEAN"),
    ("caller_confirmed", "BOOLEAN"), ("requested_at", "TIMESTAMP"), ("call_summary", "STRING"),
    ("conversation_id", "STRING"), ("handled_by", "STRING"),
]


def eleven_key():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ELEVENLABS_API_KEY not found in .env")


def eleven_get(path, key):
    out = subprocess.run(["curl", "-sS", f"{ELEVEN}{path}", "-H", f"xi-api-key: {key}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def sql(statement, parameters=None):
    body = {"warehouse_id": WAREHOUSE_ID, "statement": statement, "wait_timeout": "50s"}
    if parameters:
        body["parameters"] = parameters
    out = subprocess.run([DATABRICKS, "api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"Databricks call failed: {out.stderr.strip()[:500]}")
    result = json.loads(out.stdout)
    statement_id = result["statement_id"]
    while result["status"]["state"] in ("PENDING", "RUNNING"):   # warehouse is still starting
        time.sleep(3)
        out = subprocess.run([DATABRICKS, "api", "get", f"/api/2.0/sql/statements/{statement_id}"],
                             capture_output=True, text=True, check=True)
        result = json.loads(out.stdout)
    if result["status"]["state"] != "SUCCEEDED":
        raise SystemExit(f"SQL failed: {json.dumps(result['status'])[:800]}")
    return result.get("result", {}).get("data_array") or []


def load_communities():
    with open(ROOT / "databricks" / "data" / "communities.csv") as f:
        return {row["comm_name"].upper(): row for row in csv.DictReader(f)}


def load_agencies():
    """service_name -> agency_responsible, from the team's service type table."""
    with open(ROOT / "databricks" / "data" / "service_types.csv") as f:
        return {row["service_name"]: row["agency_responsible"] for row in csv.DictReader(f)}


def build_row(conversation, communities, agencies):
    """Turn one finished call into a ticket row, or None if there is nothing to act on."""
    fields = {name: item.get("value")
              for name, item in conversation["analysis"]["data_collection_results"].items()}
    problem = (fields.get("problem_description") or "").strip()
    wants_human = bool(fields.get("wants_human_agent"))
    if not problem and not wants_human:
        return None
    confirmed = bool(fields.get("caller_confirmed"))

    started = datetime.datetime.fromtimestamp(conversation["metadata"]["start_time_unix_secs"], CALGARY)
    conversation_id = conversation["conversation_id"]
    comm_name = (fields.get("comm_name") or "").strip().upper()
    if comm_name and comm_name not in communities:
        # e.g. the caller says "Bridgeland", the City calls it "BRIDGELAND/RIVERSIDE"
        close = ([n for n in communities if n.startswith(comm_name)]
                 or difflib.get_close_matches(comm_name, communities, n=1, cutoff=0.8))
        if close:
            comm_name = close[0]
    community = communities.get(comm_name)
    service_name = (fields.get("service_name") or "").strip()
    if service_name not in agencies:
        service_name = None   # only accept a name that exists in the City's list

    row = {
        "service_request_id": f"PH-{started:%y%m%d}-{conversation_id[-6:].upper()}",
        "requested_date": f"{started:%Y-%m-%d}",
        "updated_date": f"{started:%Y-%m-%d}",
        "closed_date": None,
        "status_description": "Open",
        "source": "Phone",
        "service_name": service_name,
        "agency_responsible": agencies[service_name] if service_name else None,
        "address": (fields.get("address") or "").strip() or None,
        "comm_code": community["comm_code"] if community else None,
        "comm_name": comm_name or None,
        "location_type": "Community Centrepoint" if community else None,
        "longitude": community["longitude"] if community else None,
        "latitude": community["latitude"] if community else None,
        "point": f"POINT ({community['longitude']} {community['latitude']})" if community else None,
        "category": fields.get("category") or None,
        "problem_description": problem or None,
        "is_urgent": fields.get("is_urgent"),
        "caller_name": fields.get("caller_name") or None,
        "callback_number": fields.get("callback_number") or None,
        "wants_human_agent": fields.get("wants_human_agent"),
        "caller_confirmed": fields.get("caller_confirmed"),
        "requested_at": f"{started:%Y-%m-%d %H:%M:%S}",
        "call_summary": conversation["analysis"].get("transcript_summary"),
        "conversation_id": conversation_id,
        "handled_by": "AI" if confirmed and not wants_human else "Needs agent",
    }
    return row


def insert(row):
    names = ", ".join(name for name, _ in COLUMNS)
    values = ", ".join(f":{name}" for name, _ in COLUMNS)
    parameters = []
    for name, sql_type in COLUMNS:
        value = row[name]
        if isinstance(value, bool):
            value = "true" if value else "false"
        parameters.append({"name": name, "type": sql_type, "value": None if value is None else str(value)})
    sql(f"INSERT INTO {TABLE} ({names}) VALUES ({values})", parameters)


def sync_once(key, communities, agencies, seen):
    """Insert any finished calls we have not stored yet. Returns how many were added."""
    listing = eleven_get(f"/conversations?agent_id={AGENT_ID}&page_size=50", key)
    added = 0
    for item in listing.get("conversations", []):
        conversation_id = item["conversation_id"]
        if conversation_id in seen or item.get("status") != "done":
            continue   # not done yet = still in the call or still being analysed; try again next pass
        row = build_row(eleven_get(f"/conversations/{conversation_id}", key), communities, agencies)
        seen.add(conversation_id)
        if row is None:
            print(f"  skipped {conversation_id}: no problem reported and no agent requested")
            continue
        insert(row)
        added += 1
        print(f"  + {row['service_request_id']}  [{row['handled_by']}]  {row['service_name'] or row['category']}  "
              f"{row['comm_name']}  \"{row['problem_description']}\"")
    return added


def main():
    watch = "--watch" in sys.argv
    key = eleven_key()
    communities = load_communities()
    agencies = load_agencies()

    column_sql = ", ".join(f"{name} {sql_type}" for name, sql_type in COLUMNS)
    sql(f"CREATE TABLE IF NOT EXISTS {TABLE} ({column_sql})")
    existing = {r[0] for r in sql(f"DESCRIBE {TABLE}")}
    for name, sql_type in COLUMNS:   # add columns introduced after the table was first created
        if name not in existing:
            sql(f"ALTER TABLE {TABLE} ADD COLUMNS ({name} {sql_type})")
    seen = {r[0] for r in sql(f"SELECT conversation_id FROM {TABLE}")}
    print(f"{TABLE}: {len(seen)} phone tickets already stored")

    while True:
        added = sync_once(key, communities, agencies, seen)
        if not watch:
            print(f"Done. {added} new ticket(s).")
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
