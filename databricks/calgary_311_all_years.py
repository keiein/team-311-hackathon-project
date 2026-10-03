# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # Calgary 311, all years: pull, clean, crew jobs
# MAGIC
# MAGIC Run the cells top to bottom. Each step prints what it did.
# MAGIC
# MAGIC | Step | What it does | Table it writes |
# MAGIC |---|---|---|
# MAGIC | 1 | Checks that Databricks can reach the City of Calgary API | |
# MAGIC | 2 | Pulls every ticket since the start date, one month at a time | |
# MAGIC | 3 | Loads the files exactly as they came | `calgary311.raw_311` |
# MAGIC | 4 | Cleans: real dates and numbers, one row per ticket, helper columns | `calgary311.tickets_clean` |
# MAGIC | 5 | Loads the team's crew / non-crew label for each service type | |
# MAGIC | 6 | Spreadsheet tab **Service Types**: one row per service type | `calgary311.service_types` |
# MAGIC | 7 | Tabs **2026 Remaining Services** and **Crew - All Years** | `calgary311.remaining_services_2026`, `calgary311.crew_all_years` |
# MAGIC | 8 | Tab **Crew by Community** | `calgary311.crew_by_community` |
# MAGIC | 9 | Labels every open ticket as a crew job or not, with the reason | `calgary311.open_tickets` |
# MAGIC | 10 | Splits crew jobs into today's queue and the needs-review list | `calgary311.crew_queue`, `calgary311.crew_needs_review` |
# MAGIC | 11 | Compares the results with the numbers in the team's spreadsheet and guide | |
# MAGIC
# MAGIC The rules follow the team's `311_service_type_reference.xlsx` and its guide.
# MAGIC Severity is NOT decided here. That stays with the algorithm team.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings

# COMMAND ----------

workspace.calgary311.open_ticketsimport csv
import datetime
import io
import os
import time

import requests
from pyspark.sql import functions as F
from pyspark.sql.window import Window

DATASET = "iahh-g8bj"            # 311 Service Requests, all years (2010 to present)
API = f"https://data.calgary.ca/resource/{DATASET}"
SCHEMA = "calgary311"

START_DATE = "2023-01-02"        # first day to pull. Same first day as the team's zip file.
AS_OF = None                     # "today" for ticket ages. None = the day after the newest ticket.
PAGE_SIZE = 50_000               # rows per request
REPULL = False                   # False = skip months already downloaded. True = download everything again.

# Rules from the team's guide and backend steps
MAX_CLOSE_DAYS = 1095            # closing times over 3 years are left out of the averages
REVIEW_AFTER_DAYS = 60           # open longer than this -> needs-review list, not today's queue
MIN_NORMAL_DAYS = 1              # the "normal fixing time" is kept between these two limits
MAX_NORMAL_DAYS = 30
CORE_SET_CUTOFF = 0.95           # a type is in its agency's "core set" until 95% of the agency's tickets are covered
GEO_FLOOR = 0.3                  # lowest geography score a community can get

# The 15 columns the City publishes. We keep all of them.
COLUMNS = ["service_request_id", "requested_date", "updated_date", "closed_date",
           "status_description", "source", "service_name", "agency_responsible", "address",
           "comm_code", "comm_name", "location_type", "longitude", "latitude", "point"]

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {SCHEMA}.landing")
CATALOG = spark.sql("SELECT current_catalog()").first()[0]
LANDING = f"/Volumes/{CATALOG}/{SCHEMA}/landing/all_years"
os.makedirs(LANDING, exist_ok=True)
print(f"Tables go in  {CATALOG}.{SCHEMA}")
print(f"Raw files go in  {LANDING}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1. Can Databricks reach the City of Calgary API?

# COMMAND ----------

def fetch(url: str, params: dict, tries: int = 5) -> requests.Response:
    """One request to the City. Waits and tries again if the City's server is slow."""
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, params=params, timeout=180)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  attempt {attempt} failed: {type(e).__name__}. Waiting {10 * attempt}s.")
            time.sleep(10 * attempt)
    raise RuntimeError(f"The City's API did not answer after {tries} tries.")


try:
    newest = fetch(f"{API}.json", {"$select": "requested_date", "$order": "requested_date DESC", "$limit": 1}, tries=2)
    API_OK = True
    print(f"REACHABLE. Newest ticket in the City's data: {newest.json()[0]['requested_date'][:10]}")
except Exception as e:
    API_OK = False
    print(f"BLOCKED or failed: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2. Pull every ticket since the start date
# MAGIC
# MAGIC One month at a time, so a slow answer from the City only repeats one month.
# MAGIC If this cell stops part way, just run it again: finished months are skipped.

# COMMAND ----------

def month_windows(start: str, end: datetime.date):
    """[(label, first day, first day of next month), ...] from the start date to this month."""
    lo = datetime.date.fromisoformat(start)
    out = []
    while lo <= end:
        hi = datetime.date(lo.year + (lo.month == 12), lo.month % 12 + 1, 1)
        out.append((lo.strftime("%Y-%m"), lo.isoformat(), hi.isoformat()))
        lo = hi
    return out


def pull_month(label: str, lo: str, hi: str) -> int:
    """Download one month into the landing folder. Returns the number of tickets."""
    for old in os.listdir(LANDING):                      # clear a half-finished earlier try
        if old.startswith(label):
            os.remove(os.path.join(LANDING, old))
    where = f"requested_date >= '{lo}T00:00:00' AND requested_date < '{hi}T00:00:00'"
    total, part, offset = 0, 0, 0
    while True:
        r = fetch(f"{API}.csv", {"$select": ",".join(COLUMNS), "$where": where, "$order": ":id",
                                 "$limit": PAGE_SIZE, "$offset": offset})
        rows = sum(1 for _ in csv.reader(io.StringIO(r.content.decode("utf-8")))) - 1   # minus the header
        if rows <= 0:
            break
        with open(f"{LANDING}/{label}_part{part}.csv", "wb") as f:
            f.write(r.content)
        total, part, offset = total + rows, part + 1, offset + PAGE_SIZE
        if rows < PAGE_SIZE:
            break
    return total


if API_OK:
    pulled = 0
    for label, lo, hi in month_windows(START_DATE, datetime.date.today()):
        marker = f"{LANDING}/_done_{label}"              # files starting with _ are ignored by Step 3
        if os.path.exists(marker) and not REPULL:
            print(f"{label}: already downloaded, skipped")
            continue
        n = pull_month(label, lo, hi)
        if hi <= datetime.date.today().isoformat():      # the current month is never marked finished
            open(marker, "w").close()
        pulled += n
        print(f"{label}: {n:,} tickets")
    print(f"Pull finished. {pulled:,} tickets downloaded in this run.")
else:
    print("Skipped. Upload the team's CSV into the landing folder, then run Step 3.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3. Raw table: exactly what the City sent
# MAGIC
# MAGIC Every column is kept as text so nothing is lost.

# COMMAND ----------

if not [f for f in os.listdir(LANDING) if f.lower().endswith(".csv")]:
    raise RuntimeError(f"No CSV files in {LANDING}. Run Step 2, or upload the CSV there.")

raw = (spark.read
       .option("header", True).option("multiLine", True)
       .option("quote", '"').option("escape", '"')
       .csv(LANDING))

# A file downloaded from the website uses display names ("Service Request ID"); the API uses field names.
raw = raw.toDF(*[c.strip().lower().replace(" ", "_") for c in raw.columns])
raw = raw.withColumnRenamed("community_code", "comm_code").withColumnRenamed("community_name", "comm_name")
for c in COLUMNS:                               # a column missing from the file becomes empty
    if c not in raw.columns:
        raw = raw.withColumn(c, F.lit(None).cast("string"))

raw = raw.select(*COLUMNS).withColumn("_ingested_at", F.current_timestamp())
raw.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.raw_311")
print(f"{SCHEMA}.raw_311: {spark.table(f'{SCHEMA}.raw_311').count():,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4. Clean table: one row per ticket, real types, helper columns
# MAGIC
# MAGIC All 15 original columns stay, under their original names. Nothing is filtered out here.

# COMMAND ----------

raw = spark.table(f"{SCHEMA}.raw_311")


def to_day(col):
    """Text to a date. Handles '2026-09-09T00:00:00.000', '2026-09-09', '2026/09/09 12:00:00 AM'
    and '09/09/2026 12:00:00 AM'. Anything else becomes empty instead of an error."""
    return F.expr(f"""coalesce(
        try_cast(replace(substring(trim({col}), 1, 10), '/', '-') AS date),
        cast(try_to_timestamp(trim({col}), 'MM/dd/yyyy hh:mm:ss a') AS date),
        cast(try_to_timestamp(substring(trim({col}), 1, 10), 'MM/dd/yyyy') AS date))""")


def to_number(col):
    return F.expr(f"try_cast({col} AS double)")


def blank_to_null(col):
    return F.when(F.trim(F.col(col)) == "", None).otherwise(F.trim(F.col(col)))


typed = raw.select(
    blank_to_null("service_request_id").alias("service_request_id"),
    to_day("requested_date").alias("requested_date"),
    to_day("updated_date").alias("updated_date"),
    to_day("closed_date").alias("closed_date"),
    blank_to_null("status_description").alias("status_description"),
    blank_to_null("source").alias("source"),
    blank_to_null("service_name").alias("service_name"),
    blank_to_null("agency_responsible").alias("agency_responsible"),
    blank_to_null("address").alias("address"),
    blank_to_null("comm_code").alias("comm_code"),
    # Upper case, and "SCARBORO/ SUNALTA WEST" becomes "SCARBORO/SUNALTA WEST" (the fix the guide lists)
    F.regexp_replace(F.upper(blank_to_null("comm_name")), r"/\s+", "/").alias("comm_name"),
    blank_to_null("location_type").alias("location_type"),
    to_number("longitude").alias("longitude"),
    to_number("latitude").alias("latitude"),
    blank_to_null("point").alias("point"),
).where(F.col("service_request_id").isNotNull())

# Keep tickets from the start date on (matters only if a bigger file was uploaded by hand).
typed = typed.where(F.col("requested_date").isNull() | (F.col("requested_date") >= F.lit(START_DATE).cast("date")))

# A few tickets have a community name but no code. Give them the code that name normally has.
by_name = Window.partitionBy("comm_name").orderBy(F.desc("n"), F.asc("usual_code"))
usual_code = (typed.where("comm_name IS NOT NULL AND comm_code IS NOT NULL")
              .groupBy("comm_name", F.col("comm_code").alias("usual_code")).agg(F.count("*").alias("n"))
              .withColumn("_r", F.row_number().over(by_name)).where("_r = 1").select("comm_name", "usual_code"))
typed = (typed.join(F.broadcast(usual_code), "comm_name", "left")
         .withColumn("comm_code", F.coalesce("comm_code", "usual_code")).select(*COLUMNS))

# One row per ticket id. If an id appears twice, keep the most recently updated row.
newest_first = Window.partitionBy("service_request_id").orderBy(F.col("updated_date").desc_nulls_last())
deduped = typed.withColumn("_n", F.row_number().over(newest_first)).where("_n = 1").drop("_n")

# "Today" for ticket ages. The guide uses the export date = the day after the newest ticket.
if AS_OF is None:
    AS_OF = deduped.agg(F.date_add(F.max("requested_date"), 1)).first()[0]
else:
    AS_OF = datetime.date.fromisoformat(str(AS_OF))
THIS_YEAR = AS_OF.year
YEAR_COL = f"tickets_{THIS_YEAR}"          # the spreadsheet calls this column tickets_2026
status = F.lower(F.col("status_description"))

clean = (deduped
    .withColumn("is_open", F.coalesce(status == "open", F.lit(False)))          # guide: Open = status "Open"
    .withColumn("is_duplicate", F.coalesce(status.startswith("duplicate"), F.lit(False)))
    .withColumn("has_location", F.col("latitude").isNotNull() & F.col("longitude").isNotNull())
    .withColumn("service_group", F.trim(F.split("service_name", " - ").getItem(0)))
    .withColumn("days_to_close", F.datediff("closed_date", "requested_date"))   # whole days; same day = 0
    .withColumn("days_waiting", F.datediff(F.lit(AS_OF), F.col("requested_date")))
    .withColumn("as_of_date", F.lit(AS_OF)))

clean.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.tickets_clean")
print(f"{SCHEMA}.tickets_clean: {spark.table(f'{SCHEMA}.tickets_clean').count():,} rows. Today is taken as {AS_OF}.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5. The team's crew / non-crew label for each service type
# MAGIC
# MAGIC **Crew** = a City work crew must go to a location and do hands-on work
# MAGIC (repair, clean, remove, collect, clear snow or ice, fix a utility failure).
# MAGIC **Non-crew** = desk work, officers, inspectors, planners, private vendors.
# MAGIC This long cell is only a lookup list. There is nothing to edit unless the team changes a label.

# COMMAND ----------

# Crew or non-crew for each of the 740 service types.
# Copied from the team's 311_service_type_reference.xlsx (Service Types tab, columns Q to T).
# If the team flips a call in the spreadsheet, change the same row here and re-run from this cell.
CREW_MAP = [
    ('CED - Filming and Drone Activities (Behind The Scenes)', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Calgary Housing - General Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CHO - Affordable Housing', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('AT - Property Tax Account Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - Property Tax Account Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - ONLINE TIPP Agreement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - TIPP Agreement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Assessed Value', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - ONLINE Property Tax Document Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Property Tax Bill and Statement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - ONLINE Property Tax Document Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - TIPP Agreement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - ONLINE TIPP Information Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Property Tax Invoice and Charge Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Assessment General Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - ONLINE TIPP Agreement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Tax Account Maintenance', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Property Tax Payment Adjustments and Tax Programs', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - Tax Account Maintenance', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - BIA Tax Account Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - (PTAP) Property Tax Assistance Program Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Assessment General Inquiry - After Hours and Overflow', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Property Details', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - BIA and Business Tax Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - BTIPP Agreement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('ASMT - Assessment General Concern - After Hours and Overflow', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('AT - School Support Notice Document Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('AT - Assessment Property Details', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - BTIPP Agreement Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - School Support Notice Document Request', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - Credit and Collection Inquiries', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - ONLINE eBill Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - Corporate Billing and eBill Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Finance - Accounts Payable', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Regulatory Affairs - General Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Supply - General Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('AS - Animal Licence - Concerns on Existing', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - No Cost Spay or Neuter Program Inquiries', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Livestock - Bird(s) in the City', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Compliance - BL - Employee Complaint  Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CEMA - Ready Calgary Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Business Licence Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Fire Code and General Inquiries - FHB', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Provincial Licence Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Fire Station Tour', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CFD - Life Safety Systems Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Fire Code Hazard Complaint - FHB', 'Non-crew', 'Inspection (inspector)', 'Borderline', 'A fire inspector visits; no repair crew.'),
    ('CFD - Incident Report Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Special Events Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Lockbox Inquiry - FHB', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Land Search - Property Search', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Fire Safety Plan Review - FHB', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('CFD - Fire Truck Booking', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('CFD - Mobile Food Concession Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Fireworks Pyro Open Flame Blasting Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Occupant Load Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Lockbox Programming or Billing Concern', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('CFD - Smoke Alarm Inquiries & Asst. for Seniors/Disabled', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Fire Drill - Warden Lecture - FHB', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CFD - Safe Housing - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Fire Safety Presentation', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CFD - Request to attend a Fire Drill - FHB', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CFD - Community Safety Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Smoke Alarm Inquiries - Asst. for Seniors/Disabled', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - SCHOOL Fire Drill with Local Fire Station - ONLINE', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CFD - Tank Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Building in Progress Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Invoice Inquiry', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('CFD - Missed Annual Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Compliments / Thank You / Recognition', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CFD - Technical Services Review - FHB', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('CFD - Hazmat Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - Public Affairs Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CFD - 100th Birthday Surprise', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CFD - Provincial Accreditation or Licence Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Pre-Purchase Insurance Inspection- FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CFD - Occupancy Inspection - FHB', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CN - Subsidized Programs - Fair Entry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('CN - Registered Social Worker Letter', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CN - Senior Services Home Maintenance Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CN - Snow Angels Campaign', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CN - Volunteer Request - Summer', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CN - Property Tax Assistance Program (PTAP)', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('CN - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CN - Calgary After School Program Inquiry', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CN - Neighbourhood Services Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Recreation - Athletic Park Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('REC - Pool - Canyon Meadows', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Arena Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Athletic Park Special Event and Tournament Appl', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Recreation - Playfield (D & E) Community Fields Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Recreation - Field Tournament Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('REC - Southland Leisure Centre Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Administration Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Sir Winston Churchill', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Thornhill', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Renfrew', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Killarney', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Athletic Park Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Acadia', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Glenmore', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Program Registration Inquiry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('REC - Pool - Bob Bahan', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Foothills', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Volunteer Request', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('REC - Booking Inquiry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('REC - Village Square Leisure Centre Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Shouldice', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Pool - Inglewood', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Calgary Soccer Centre Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('REC - Golf Course Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Calgary After School Program Inquiries', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Comm Strategies - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CN - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CS - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Comm Strategies - Disability/Accessibility - Meeting & Event', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CS - Disability/Accessibility - Meeting and Event Support', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CN - Disability/Accessibility - Meeting and Event Support', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CS - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Comm Strategies - Disability/Accessibility - Meeting & Eve', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Comm Strategies - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Bylaw - Snow and Ice on Sidewalk', 'Non-crew', 'Enforcement (officer)', 'Borderline', 'An officer issues a notice to the property owner; a City contractor clears it only if the owner does not.'),
    ('Corporate - Graffiti Concerns', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Bylaw - Long Grass - Weeds Infraction', 'Non-crew', 'Enforcement (officer)', 'Clear', "Long grass/weeds on private property: an officer orders the owner to cut it. City mowing of public land is 'Parks - Mowing Request'."),
    ('Bylaw - Material on Public Property', 'Non-crew', 'Enforcement (officer)', 'Borderline', 'An officer orders removal; a crew may clean up later if not removed.'),
    ('Corporate - Encampment Concerns', 'Crew', 'Cleaning & removal', 'Borderline', 'Site clean-up is crew work, but outreach/peace officers lead the response.'),
    ('Bylaw - Noise Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Disturbance and Behavioural Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Pick Up Stray', 'Non-crew', 'Enforcement (officer)', 'Borderline', 'An Animal Services officer picks up the animal: a field dispatch, but officers, not a work crew.'),
    ('Bylaw - Tree - Shrub Infraction', 'Non-crew', 'Enforcement (officer)', 'Clear', "Private trees/shrubs blocking a sidewalk or sightline: an officer orders the owner to trim. City trees are 'Parks - Tree Concern'."),
    ('AS - Animal at Large', 'Non-crew', 'Enforcement (officer)', 'Borderline', 'Animal Services officer response: field dispatch, but officers, not a work crew.'),
    ('Bylaw - Waste and Recycling Infractions', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Residents breaking waste rules: an officer issues a notice. Missed City pickups are the WRS types.'),
    ('Bylaw - Water Misuse / Wasting Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Noise', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Vehicle Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Property Maintenance Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Community Safety - Information Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('ACPL - Animal Licence - Inquiries', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('ACPL - Lost and Found Animal', 'Non-crew', 'Lost and found', 'Clear', 'Lost and found items or animals; handled at a counter or by phone.'),
    ('Business Safety - Business Licence Concern - RMS', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Temporary Signs Infraction on City Property', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Permit - Noise Exemption', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Compliance - Business Licence Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Business Safety - Business Licence Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Evacuated Residents Registration Form', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('AS - Animal Bite', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Chase - Threat', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Dog Defecation', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Damaging Pet or Property', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('VFH - Taxi/Limousine/TNC (Ride Sharing) Concern - RMS', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Compliance - Taxi/Limousine/TNC (Ride Sharing) Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('VFH - Taxi/Limousine/TNC (Ride Sharing) Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Animal / Bylaw - Information Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Bylaw - Spills Concerns', 'Non-crew', 'Enforcement (officer)', 'Borderline', "An officer investigates; clean-up is the responsible party's job."),
    ('AS - Lost and Found Animal', 'Non-crew', 'Lost and found', 'Clear', 'Lost and found items or animals; handled at a counter or by phone.'),
    ('Bylaw - Vandalism and Property Damage Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ACPL - No Cost Spay or Neuter Program Inquiries', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('AS - Urban Livestock Licenses and Permits', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('AS - Animal Public Relations', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Invoice Appeal', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Licence - Inquiries', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Bylaw - Water Services Request', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Community Safety - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('AS - Livestock and Bird(s) in the City', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Bylaw - Advocacy Sign Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ZZZ Business Safety - Business Licence Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Human Injury', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Injured', 'Non-crew', 'Enforcement (officer)', 'Borderline', 'Animal Services officer response: field dispatch, but officers, not a work crew.'),
    ('AS - Animal Tethered -Tied', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ZZZ VFH - Taxi/Limousine/TNC (Ride Sharing) Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Rat Sighting', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Park - Pathway Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ACPL - Bite Prevention Program Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('AS - Animal Services Assistance Required', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - No Control Dog in Off Leash Area', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Unlicensed Animal', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Community Safety - Publications Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CEMA - Non Emergency Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Bylaw - Public Relations', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Animal / Bylaw - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Bylaw - Cannabis Concerns', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Excess Pet Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Animal Vehicle Offences', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Honeybee Swarm or Beekeeping Inquiry', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ACPL - Magpie Trap Information Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('VFH - Taxi/Limousine/TNC (Ride Sharing) Compliment - RMS', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('AS - Animal Interference', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Animal / Bylaw - Publications Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('AS - Professional Dogwalker Permit', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('AS - Excess Pet Permit', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('AS - Magpie Trap Information Request', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('AS - Bee Concern or Inquiry', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Compliance - Taxi or Limousine Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Bylaw - Prohibited Business', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('VFH - Taxi or Limousine Compliment - RMS', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('ACPL - Wise Whiskers  Think Like a Scientist Class Kit', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('VFH - Taxi or Limousine Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('ZZZ VFH - Taxi or Limousine Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Business Safety - Employee Complaint -  Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Compliance - LTS - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Bylaw - Beyond the Badge Program Request', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Community Clean Up Event - Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('VFH - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Partnerships - Community Association Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('BIA Requests', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Partnerships - Festival, Events and Cultural Development', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Partnerships - Arts and Culture', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Partnerships - Sport and Facility Development', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Partnerships - Public Art', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Partnerships - Housing Solutions', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Partnerships - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('RSP - Subsidized Programs - Fair Entry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Recreation - School Facility Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Recreation - Arena Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Recreation - Athletic Park Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Registered Social Worker Letter', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Playfield Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Active Living Program Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Recreation - Pool Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Senior Services Home Maintenance Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Boat Stall Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Recreation - Tennis / Pickleball Court Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Home Services for Seniors Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Arena Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Arena Meeting Room Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Volunteer Request', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Athletic Park Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - LC - Gym/Room/Courts Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Property Tax Assistance Program (PTAP)', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('RSP - Pool - Killarney', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Southland Leisure Centre Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Renfrew', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Canyon Meadows', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Thornhill', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Recreation - Arena Tournament and Special Event Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Pool - Sir Winston Churchill', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Bob Bahan', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Booking Inquiry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Program Registration Inquiry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Pool - Glenmore', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Administration Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Inglewood', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Snow Angels Campaign', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Village Square Leisure Centre Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Calgary AfterSchool Program Inquires', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Pool - Foothills', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Shouldice', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Pool - Acadia', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - School Connections Booking Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Sport Hub Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('RSP - Calgary Soccer Centre Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Recreation - Sailing School Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('RSP - Glenmore Reservoir - Boat Rentals', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('LEAD Program Inquiry', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Recreation - Arena Tournament and Special Event Applicatio', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Mobile Adventure Playground', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Glenmore Sailing School Inquiry', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Glenmore Reservoir - Boat Dock/Storage Repair', 'Crew', 'Facilities', 'Borderline', 'A repair job, but at a recreation facility rather than public infrastructure.'),
    ('RSP - Free Summer Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('RSP - Senior Services Home Maintenance - Bylaw Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('RSP - Home Services for Seniors - Bylaw Concern', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('Opinions on Business Units', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CAI - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Fleet - Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ("Mayor's Office - General Concerns", 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Mayors Office - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ("Mayor's Office - Meeting Request", 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Mayors Office - Meeting Request', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ("Mayor's Office - Neighbour Day Event Invite", 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Mayors Office - Neighbour Day Event Invite', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ("Mayor's Office - Birthday or Anniversary Request", 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Mayors Office - Birthday or Anniversary Request', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Mayors Office - Event Invitation', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ("Mayor's Office - Event Invitation", 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ("Mayor's Office - Proclamation or Recognition Letter Request", 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Mayors Office - Proclamation or Recognition Letter Request', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ("Mayor's Office - Greeting Message Request", 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Mayors Office - Greeting Message Request', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CPBS - Bridge - Tunnel - Underpass Concern', 'Crew', 'Road & structure repair', 'Borderline', 'Same service as Roads - Bridge - Tunnel - Underpass Concern after it moved to Capital Planning; engineers often assess first.'),
    ('CPBS - Addressing Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CPBS - Plus 15 Skywalk', 'Crew', 'Facilities', 'Borderline', 'Skywalk maintenance is crew work; some tickets are building-owner issues.'),
    ('CPBS - Wooden Stairs - Repairs', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('CPBS - Water and Sewer Main Condition Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TP - Future Road Planning and Upgrades', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TP - Noise Barrier Wall', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TP - Neighbourhood Streets Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TP - Transportation Data', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TP - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CPI - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('PD - Noise Barrier Wall', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PD - Future Road Planning and Upgrades', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PD - Neighbourhood Streets Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Project Development - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('PSD - Local Improvement Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Driveway Crossings - Curb Lowering', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Backlane Paving Construction', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Transportation Special Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TI - Special Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Annual Paving Program - Major Roads', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TI - Major Road Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Major Road Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Parks and Open Spaces', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Various Street Improvements - Current Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Special Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TI - Bridges and Structures Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Bridges and Structures Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Buildings - Architecture', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Urban Initiatives General Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Major Transit Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Downtown Major Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Geotechnical Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TI - Major Transit Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Events Centre - Scotia Place', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Eau Claire Area Improvements', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Hillside Stability', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TI - Connections to South West Ring Road', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TI - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('PSD - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Eau Claire Area Improvements', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('PSD - Major Mobility - Paving Program', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Stewardship of City Owned Land', 'Crew', 'Facilities', 'Borderline', 'Clean-up/upkeep of City-owned lots is field work, often by contractors; some tickets are encroachment issues.'),
    ('REDS - Property Leasing and Sales Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('REDS - Encroachment Agreements on City Land', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('REDS - Development Project Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('REDS - Acquisitions and Expropriations', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('UD - Major Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Major Projects Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('UD - Corrosion - Digging Close to Critical Main', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('UD - Utility Inspection - Corrosion - Indemnification', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ("CAO - Chief Administrator's Office Inquiry", 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('City Clerks - Municipal Election Question', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ("City Clerk's - General Concerns", 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ("City Clerk's - Municipal Election Question", 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('City Clerks - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ("City Clerk's - Municipal Complex Tour", 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('City Clerks - Self-Guided Municipal Complex Tour', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ("City Clerk's - Census Inquiry", 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ("CMO - City Manager's Office - General Concerns", 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Law - Risk Management and Claims', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Law - Insurance and Claims', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('Law - General Concern - After Hours', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CT - Lost Property', 'Non-crew', 'Lost and found', 'Clear', 'Lost and found items or animals; handled at a counter or by phone.'),
    ('CT - Bus Route or Bus Schedule', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT - Bus Stops', 'Crew', 'Facilities', 'Borderline', 'Stop repairs/cleaning are crew work; some tickets ask for new or moved stops.'),
    ('CT - Transit Pass Programs', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT AC - Trip Feedback - CTA', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('After Hours Transit - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CT - CTrain Stations', 'Crew', 'Facilities', 'Borderline', 'Station repairs/cleaning are crew work; many tickets are general station feedback.'),
    ('CT - Transit Safety / Public Etiquette', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('CT - Advertising and Communications', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT AC - Activity Report - CTA INTERNAL', 'Non-crew', 'Internal report', 'Clear', 'Internal activity report, not a request from the public.'),
    ('CT - Snow and Ice Control', 'Crew', 'Snow & ice', 'Clear', 'Clearing snow/ice on public roads, pathways, parks or transit stops.'),
    ('CT - Bus or CTrain Vehicle Maintenance', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'Vehicle repairs happen in the transit garage, not at a location a crew is dispatched to.'),
    ('CT - CTrain Schedule', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT - Park and Ride Lot - LRT or Bus', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Borderline', 'Mostly parking/fee feedback; some lot maintenance.'),
    ('CT - Fair Entry Inquiry', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT - Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CT - Shared E-Scooter', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooter/e-bike issues go to the private operator, not City crews.'),
    ('CT - Bikes on Transit', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT AC - Fair Entry Inquiry', 'Non-crew', 'Transit service (routes, schedules, passes, trips)', 'Clear', 'About transit routes, schedules, passes or trips; no field crew.'),
    ('CT AC - Activity Report INTERNAL', 'Non-crew', 'Internal report', 'Clear', 'Internal activity report, not a request from the public.'),
    ('CT - Shared E-Bike', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooter/e-bike issues go to the private operator, not City crews.'),
    ('Facility Mgmt - FMCCC - Customer Care Centre', 'Crew', 'Facilities', 'Borderline', 'Maintenance requests for City buildings (trades crews), internal rather than public infrastructure.'),
    ('Public - Municipal Complex - Atrium or Plaza Use Request', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Facility Mgmt - Facility - Public Use Booking', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Fleet and Inventory - Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Fleet - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Roads - Pothole Maintenance', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Snow and Ice Control', 'Crew', 'Snow & ice', 'Clear', 'Clearing snow/ice on public roads, pathways, parks or transit stops.'),
    ('Roads - Debris on Street/Sidewalk/Boulevard', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Roads - Signs - Missing - Damaged', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Streetlight Maintenance', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Backlane Maintenance', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Dead Animal Pick-Up', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Roads - Sidewalk - Curb and Gutter Repair', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Roadway Maintenance', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Traffic or Pedestrian Light Repair', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Signs - Traffic and Roadmarking', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Signs - Parking', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Traffic Signal Timing Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Traffic engineers review signal timing from the office; no field crew.'),
    ('Roads - Temporary Sign Removal', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Roads - Detour Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Roads - Pathway Concerns', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Detour Urgent (Safety) Concerns', 'Crew', 'Road & structure repair', 'Borderline', "Someone has to go fix detour signs/traffic control, but it is often the construction contractor's job."),
    ('Roads - Street Cleaning Annual Program', 'Non-crew', 'Program / education / event / tour', 'Borderline', 'Questions about the scheduled sweeping program; sweeping itself is planned, not dispatched per ticket.'),
    ('Roads - Safety and Education', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Traffic-safety concerns reviewed by traffic engineers (studies, education), not fixed by a crew.'),
    ('Roads - Pathway Snow and Ice Concerns', 'Crew', 'Snow & ice', 'Clear', 'Clearing snow/ice on public roads, pathways, parks or transit stops.'),
    ('Roads - Fence - Noise Barrier - Retaining Wall Repair', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - NEW Signal, Left Turn or Pedestrian Light Request', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'A request to build a new signal: a traffic-engineering study and capital project, not a repair.'),
    ('Roads - Permits - Requests and Inquiries', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Roads - Streetlight Damage', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Streetlight - General Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Roads - Traffic Operational Improvement Suggestions', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Street Paving Program', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - NEW Sidewalk - Curb and Gutter Repair', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Roads - Pavement Markings - Missing or Faded', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - Repaving Candidate Street and Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Boulevard Maintenance', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Traffic Signal Lane Designation Sign', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Roads - New Signal, Left Turn or Pedestrian Light Request', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', "Same as 'Roads - NEW Signal...' (different capitalization): a request to build a new signal, not a repair."),
    ('Roads - E-Scooter', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooters belong to private operators, who move or fix them.'),
    ('Roads - Feedback - Community Traffic Safety Projects', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Roads - Bridge - Tunnel - Underpass Concern', 'Crew', 'Road & structure repair', 'Borderline', 'Structure repairs are crew work; some tickets are engineering assessments first.'),
    ('Roads - Traffic Signal Construction Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Local Improvement Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Curb Lowering for Existing Driveways', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Sidewalk Installation and Accessibility', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Traffic Signal Operation Report - Intersection Plan', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Wheelchair Slope - Request For', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - BIA Maintenance', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Traffic Control Change Feedback', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Roads - Traffic Operational Improvement Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Indemnification Agreement - Request For', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Minor Projects Construction', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Plus 15 Skywalk', 'Crew', 'Facilities', 'Borderline', 'Skywalk maintenance is crew work; some tickets are building-owner issues.'),
    ('Roads - Utility Placement Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - New Subdivisions', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Backlane Paving Construction', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CPA - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Roads - Shared E-Bike', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooter/e-bike issues go to the private operator, not City crews.'),
    ('Roads - New Audible/Accessible Pedestrian Signal', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Traffic Camera and ATIS Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Roads - Bike Rack Request - NEW', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Stairs - Damage', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('Roads - Boulevard Garden and Landscaping Request', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Traffic Signal Operation Report - Intersection Pla', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Traffic Vibration Concerns', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Transportation Data', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Adaptive Roadways and Seasonal Patio Programs', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Load Ban and Overweight Vehicle on Road Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Shared and Rental E-Scooter Program', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooter/e-bike issues go to the private operator, not City crews.'),
    ('Roads - 5G Wireless Infrastructure Deployment Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Shared and Rental E-Bike Program', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooter/e-bike issues go to the private operator, not City crews.'),
    ('Roads - Agricultural Crossing Request', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Hillside Stability', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Roads - Shared E-Scooter', 'Non-crew', 'Vendor-operated (shared e-scooter/e-bike)', 'Clear', 'Shared e-scooter/e-bike issues go to the private operator, not City crews.'),
    ('Filming and Movie and Drone Activities', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Tree Concern - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Tree Concern - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Garbage - GIS', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Parks - Wildlife Sightings', 'Non-crew', 'Inquiry / information', 'Clear', 'A sighting report for tracking; no crew action.'),
    ('Parks - Wildlife Management', 'Non-crew', 'Inquiry / information', 'Borderline', 'Mostly advice; occasional field response by wildlife staff.'),
    ('Parks - Mowing Request - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Infrastructure - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Maintenance - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Snow and Ice Concerns - WAM', 'Crew', 'Snow & ice', 'Clear', 'Clearing snow/ice on public roads, pathways, parks or transit stops.'),
    ('Parks - Venue Bookings and Inquiries', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Garbage - WAM', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Parks - Parks and Open Spaces Bookings', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Roadside Greens - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Infrastructure - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Maintenance - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Irrigation Maintenance - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Natural Area Maintenance - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Weed Control Issues - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Pathway Concern - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Mowing Request - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Borderline', 'Mixed bag; specific repair issues have their own Parks types.'),
    ('Parks - Tree Planting and Tree Watering Inquiries - GIS', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Parks - Snow and Ice Concerns - GIS', 'Crew', 'Snow & ice', 'Clear', 'Clearing snow/ice on public roads, pathways, parks or transit stops.'),
    ('Parks - Pest Concerns - GIS', 'Crew', 'Parks & trees', 'Borderline', 'Pest treatment is done by Parks crews, but many tickets are reports/advice only.'),
    ('Parks - Planning Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('Parks - Development - Tree Concern - GIS', 'Non-crew', 'Inspection (inspector)', 'Borderline', 'Urban Forestry inspects trees on development sites; no crew work.'),
    ('Parks - Irrigation Maintenance - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - PlayBins', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Parks PlayBins', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Parks - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Parks - Natural Area Inquiries - GIS', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Parks - Golf Course Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Parks - Weed Control Issues - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Lighting Concern - GIS', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Parks - Branching Out Tree Program', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Parks - Lost and Found - GIS', 'Non-crew', 'Lost and found', 'Clear', 'Lost and found items or animals; handled at a counter or by phone.'),
    ('Parks - Natural Area Maintenance - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - School Program Registration', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Pest Concerns - WAM', 'Crew', 'Parks & trees', 'Borderline', 'Pest treatment is done by Parks crews, but many tickets are reports/advice only.'),
    ('Parks - Volunteer Request', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Parks - Community Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Parks - Tree Education Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Parks - Pest Management', 'Crew', 'Parks & trees', 'Borderline', 'Pest treatment is done by Parks crews, but many tickets are reports/advice only.'),
    ('Parks - Lighting Concern - WAM', 'Crew', 'Signs, signals & lights', 'Clear', 'Field repair or replacement of signs, markings, signals or lights.'),
    ('Parks - Pathway Concern - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Development - Tree Concern - WAM', 'Non-crew', 'Inspection (inspector)', 'Borderline', 'Urban Forestry inspects trees on development sites; no crew work.'),
    ('Parks - Irrigation Line Location Request - GIS', 'Non-crew', 'Inquiry / information', 'Borderline', 'Staff mark irrigation lines for contractors; a locate service, not repair.'),
    ('Parks - Lost and Found - WAM', 'Non-crew', 'Lost and found', 'Clear', 'Lost and found items or animals; handled at a counter or by phone.'),
    ('Parks - Natural Area Inquiries - WAM', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Parks - Playfield Usage Concerns', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Parks - Irrigation Line Location Request - WAM', 'Non-crew', 'Inquiry / information', 'Borderline', 'Staff mark irrigation lines for contractors; a locate service, not repair.'),
    ('Parks - NAM - Inactive Camp Clean Up - GIS INTERNAL', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('Parks - Mosquito Concerns', 'Non-crew', 'Inquiry / information', 'Borderline', 'Mosquito program reports; treatment is scheduled, not dispatched per ticket.'),
    ('Parks - Roadside Greens', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Playfield Portisan Placement Request', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Seasonal Vendor Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Cemetery - Maintenance - GIS', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks Seasonal Vendor Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Parks - Cemetery - Maintenance - WAM', 'Crew', 'Parks & trees', 'Clear', 'Parks crew does hands-on work: trees, mowing, park repairs or upkeep.'),
    ('Parks - Playfield Portable Toilet Concern After Placement', 'Crew', 'Parks & trees', 'Borderline', 'Toilet servicing is field work, usually by the rental vendor.'),
    ('Parks - APT Maintenance', 'Crew', 'Parks & trees', 'Borderline', 'Maintenance ticket, but very low volume and unclear scope.'),
    ('WRS - Cart Management', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Waste - Residential', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Recycling - Blue Cart', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Compost - Green Cart', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - New Service - Carts', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Debris in Backlane', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Commercial Collection Services', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Programs', 'Non-crew', 'Program / education / event / tour', 'Borderline', 'Program questions (e.g. seasonal pickups); some may trigger a pickup.'),
    ('WRS - Employee - Complaint Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('WRS - Brochures', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WRS - Landfill - Disposal Information', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WRS - Landfill - Industrial Permit or Inquiry', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('WRS - Landfill - Accounts and Billing', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('WRS - Collection Schedule Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WRS - Landfill - Operations', 'Non-crew', 'Inquiry / information', 'Borderline', 'Landfill site issues handled by landfill staff on site, not a dispatched crew.'),
    ('WRS - Bin Checks', 'Crew', 'Waste collection', 'Borderline', 'A WRS staff member visits the bin, but it is a check, not collection.'),
    ('WRS - Waste Requirements for Businesses', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WRS - Disposal Guide Tool Feedback', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('WRS - School Landfill Tours Lottery', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('WRS - Recycling - Depots', 'Crew', 'Waste collection', 'Borderline', 'Servicing overflowing depot bins is crew work; some tickets are depot questions.'),
    ('WRS - Landfill - Clean Fill', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WRS - Multifamily Recycling and Composting', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WRS - Education Inquiries', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('WRS - Special Collection', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('WRS - Landfill - Diversion Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('WRS - Recycling - Community', 'Crew', 'Waste collection', 'Borderline', 'Servicing community recycling bins is crew work; some tickets are questions.'),
    ('WATR - Utility Inspection - Corrosion - Indemnification', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('WATR - Water Development Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Water and Sewer Main Condition Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Re-Use of Existing Site Services', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATS - Sewage Back-up', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Sewer Maintenance', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Catch Basin Concerns', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Service and Main Valve Issues', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Water Meter Issues', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Water Main Break or Leak', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Water Off-On Appointment', 'Crew', 'Water & sewer', 'Borderline', 'Field job by Water Services, but booked by the customer, not a hazard to prioritize.'),
    ('WATS - Water Outage', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Water Meter Installation Request', 'Crew', 'Water & sewer', 'Borderline', 'Field job by Water Services, but a booked installation, not a hazard.'),
    ('WATS - Fire Hydrant', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Construction Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATS - Emergency Water Temporary Off', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Water Pressure Issues', 'Crew', 'Water & sewer', 'Borderline', 'Usually needs a field investigation; the cause may be on private property.'),
    ('UEP - Odour Inquiries', 'Non-crew', 'Inquiry / information', 'Borderline', 'Odour reports, mostly from treatment plants; no crew dispatch.'),
    ('WATS - Spills Entering Storm System', 'Crew', 'Cleaning & removal', 'Clear', 'A crew physically cleans up or removes something from public property.'),
    ('WATS - Cross Connection Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Water Quality', 'Crew', 'Water & sewer', 'Borderline', 'Usually a field sampling visit; may not need repair work.'),
    ('WATS - Cross Connection Tester Support - ONLINE', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Manhole Concerns', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Erosion and Sediment Control', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('WATS - Urgent Water Reconnect', 'Crew', 'Water & sewer', 'Clear', 'Water/sewer crew goes to the site to fix or respond to a utility problem.'),
    ('WATS - Construction Inquiry - MAX', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATS - Fire Hydrant Flow Test', 'Non-crew', 'Planning / new infrastructure / capital project', 'Borderline', 'A test requested by developers/engineers; a service, not a repair.'),
    ('WATS - Drainage Bylaw', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('WATS - Hydrant Connection Unit - HCU Inspections', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('WATS - Water Wagon Issues', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Property Rehab', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Tap Water Sampling Program', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('WATS - Drainage Concerns', 'Crew', 'Water & sewer', 'Borderline', 'Field investigation of drainage; may lead to repair or to a bylaw issue.'),
    ('WATS - Hydrant Control Unit - HCU Inspections', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('WATS - Basement Seepage', 'Crew', 'Water & sewer', 'Borderline', 'Field investigation to rule out a City main; often a private-property issue.'),
    ('WATS - Storm Pond Concerns', 'Crew', 'Water & sewer', 'Borderline', 'Pond maintenance is crew work; some tickets are questions.'),
    ('WATS - Bulk Water Accounts and Air Gap Vehicle Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('WATS - Water Equipment Pickup', 'Crew', 'Water & sewer', 'Borderline', 'A crew picks up equipment, but it is logistics, not a repair.'),
    ('WATS - Water Billing Concerns', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('WATS - Temporary Water Line Issues', 'Crew', 'Water & sewer', 'Borderline', 'Field fix of temporary water lines, low volume.'),
    ('WATS - Water Service Fee Invoice', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('WATS - Flat to Meter Appointment', 'Crew', 'Water & sewer', 'Borderline', 'Field job by Water Services, but a booked installation, not a hazard.'),
    ('WATS - Water Equipment Pickup - MAX', 'Crew', 'Water & sewer', 'Borderline', 'A crew picks up equipment, but it is logistics, not a repair.'),
    ('WATS - Water Treatment Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Bulk Water Station Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Wastewater Treatment Information', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Water Data Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Industrial Monitoring Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Lot Grading', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('WATS - Water Run Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Developer Request for Parks Irrigation Meter', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATS - Location of Underground Water Lines', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Location of Underground Water Lines - MAX', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Z - OLD - WATS - Construction Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATS - Water Run Inquiry - MAX', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATS - Treatment Plant Tours', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CT AC - Trip Feedback - Checker Taxi', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CT AC - Trip Feedback - Care Calgary', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CT AC - Trip Feedback - Southland', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CT AC - Activity Report - Checker INTERNAL', 'Non-crew', 'Internal report', 'Clear', 'Internal activity report, not a request from the public.'),
    ('CT AC - Activity Report - Care Calgary INTERNAL', 'Non-crew', 'Internal report', 'Clear', 'Internal activity report, not a request from the public.'),
    ('CT AC - Activity Report - Southland INTERNAL', 'Non-crew', 'Internal report', 'Clear', 'Internal activity report, not a request from the public.'),
    ('Green Line - Spill and Substance Release Report (X217)', 'Non-crew', 'Inquiry / information', 'Borderline', 'Spill reports on the Green Line construction project; handled by the project contractor.'),
    ('GFL - Black Cart Collection', 'Crew', 'Waste collection', 'Clear', 'Collection crew work: missed pickups, carts, special or commercial collection.'),
    ('City Auditors - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('City Auditors - General Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAC - Public Infrastructure Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS Inspection - SCP - New Home', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Furnace Replacement', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - Code Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS - RIM - Property Research', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS Concern - Electrical', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Gas Fireplace Installation', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Concern - Plumbing and Gas', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - RIM - Subscription Services', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS - RIM - Policy Document Requests', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS - Public Protection Site Safety Meeting', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CRP - Historical Hydrant Data or Flow Test', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CRP - City and Regional Planning General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CRP - City and Regional Planning General Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CGS - Urban Initiatives General Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CGS - Calgary Growth Strategies - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CE - Water Restrictions', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('CE - Environmental Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATR - Water Restrictions', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('CE - Water Conservation Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CE - Treatment Plant Tours', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('CE - Watershed', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('ESM - Environmental Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CE  - Environmental Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CE - Riparian - Riverbank Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('WATR - Watershed', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Riparian - Riverbank Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CE - Water Brochure', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CE - Dashboard Feedback', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('WATR - Water Brochure', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CP - Indemnification Agreements', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CP - Community Planning - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CP - Water Development Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CP - Community Planning - General Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CP - Re-Use of Existing Site Services', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CP - Public Infrastructure Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('DBBS - RIM - Property Research', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS Inspection - Electrical', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Electrical', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Commercial or Multi-Family', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Commercial or Multi-Family', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Residential Improvement Project - RIP', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Residential Improvement Project - RIP', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Concern - Building Without a Permit', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Gas', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Plumbing', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Infill Construction Concerns', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Code Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('DBBS Inspection - Furnace Replacement', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Plumbing', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Planning and Development - After Hours SR', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('DBBS Inspection - SCP - New Home', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Heating and Ventilation', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Cancellation or Reschedule', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Building Construction Concerns and Inquiries', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Gas', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Cancellation or Reschedule', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Inspection - Heating and Ventilation', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - PRC - Property Research', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('DBBS - Urgent Safety Response', 'Non-crew', 'Inspection (inspector)', 'Borderline', 'A building inspector responds to an unsafe site; no City repair crew.'),
    ('DBBS - SDI - New Subdivision Parks Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - Infill Construction Concerns', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Concern - Building Without a Permit', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Concern - Electrical', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Unsafe Derelict or Grow Op Property', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - Planning and Development - After Hours SR', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('DBBS - Safety Response', 'Non-crew', 'Inspection (inspector)', 'Borderline', 'A building inspector responds to an unsafe site; no City repair crew.'),
    ('DBBS Concern - Heating and Ventilation', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - Urgent Safety Response', 'Non-crew', 'Inspection (inspector)', 'Borderline', 'A building inspector responds to an unsafe site; no City repair crew.'),
    ('DBBS - SDI - New Subdivision Surface Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Unsafe Derelict or Unsecure Property', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Concern - Plumbing and Gas', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - SDI - Utility Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - Building Construction Concerns and Inquiries', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS - Unsafe Derelict or Grow Op Property', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - SDI - Surface Indemnification Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CBS Concern - Heating & Ventilation', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS Inspection - Gas Fireplace Installation', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - SDI - Surface Improvements Inspections', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - SDI - New Subdivisions Inspections', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Unsafe Derelict or Insecure Property', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - Public Protection Site Safety Meeting', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('DBBS - SDI - Surface Improvements Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - RIM - Subscription Services', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('DBBS - Emergency Electrical Reconnection', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('DBBS - RIM - Policy Document Requests', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CBS Concern - Special Event Tent', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('DBBS - SDI - New Subdivision Inspection', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('Downtown Strategy - General Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('ERR - Watering Schedule', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ERR - Water Conservation Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('ERR - Environmental Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('ERR - Riparian - Riverbank Inquiries', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('ERR - Watershed', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('ERR - Treatment Plant Tours', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('ERR - Water Restrictions', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('ERR - Water Brochure', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Corporate Research Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - City Online - Concern', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - GIS Mapping and Analysis Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - Addressing Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - City Online - Feedback Form Only', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CAI - Open Data Catalogue Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - Utility Placement Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CAI - Electronic Data Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - Block Profile Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - Cadastral Mapping Service Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CAI - 5G Wireless Infrastructure Deployment Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CAI - Commercial Electronic Data License Request', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('CAI - Educational Electronic Data License Request', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('311 Contact Us', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Customer Service & Communications - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CSC - Calgary.ca Feedback and Issue Report', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Customer Service and Communications - General Concerns', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('CSC - Corporate Research Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('CSC - Communications and Marketing Initiatives', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('311 Ambassador Program', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('HR - Recruitment and Program Inquiry', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('IT - City Online - Concern', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('IT - Public WiFi - Shaw Go WiFi at City Facilities', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('IT - GIS Mapping and Analysis Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('IT - City Fibre Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('IT - Block Profile Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('IT - Electronic Data Request', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('MC - calgary.ca Feedback', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('MC - Calgary.ca Feedback and Issue Report', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('Partnerships - Neighbourhood Services Programs', 'Non-crew', 'Program / education / event / tour', 'Clear', 'Program, event, tour or education request.'),
    ('Recreation - Food Truck Parking Stall Application', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Green Line Inquiry', 'Non-crew', 'Inquiry / information', 'Clear', 'Question or information request answered by staff.'),
    ('Roads Permits - Requests and Inquiries', 'Non-crew', 'Booking / application / permit / registration', 'Clear', 'Admin: an application, booking, permit, licence or registration.'),
    ('Roads - Speed Education', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('TP - Community Traffic - Cycling - Pedestrian Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('ESM - Employee Complaint - Compliment', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('WRS - Chatbot Feedback', 'Non-crew', 'Feedback / complaint / compliment', 'Clear', 'Feedback, complaint or compliment answered by staff; no field work.'),
    ('WATR - Erosion and Sediment Control', 'Non-crew', 'Enforcement (officer)', 'Clear', 'Handled by a bylaw/animal/licensing officer who issues notices or fines, not a work crew.'),
    ('WATR - Water Billing Concerns', 'Non-crew', 'Billing / tax / accounts / claims', 'Clear', 'Desk work: tax, billing, accounts or claims.'),
    ('WATR - Industrial Monitoring Inquiry', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Water Reporting and Information', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Water Conservation Programs', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATR - Treatment Plant Tours', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('WATS - Air Gap Vehicle Inspection - ONLINE', 'Non-crew', 'Inspection (inspector)', 'Clear', 'An inspector visits to assess or approve; no repair work by a crew.'),
    ('CPI - Bridge - Tunnel - Underpass Concern', 'Crew', 'Road & structure repair', 'Borderline', 'Same service as Roads - Bridge - Tunnel - Underpass Concern (older label); engineers often assess first.'),
    ('CPI - Water and Sewer Main Condition Inquiries', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CPI - Plus 15 Skywalk', 'Crew', 'Facilities', 'Borderline', 'Skywalk maintenance is crew work; some tickets are building-owner issues.'),
    ('CPI - Noise Barrier Wall', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CPI - Future Road Planning and Upgrades', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
    ('CPI - Wooden Stairs - Repairs', 'Crew', 'Road & structure repair', 'Clear', 'A crew physically repairs a road, sidewalk, lane, pathway or structure.'),
    ('CPI - Neighbourhood Streets Projects', 'Non-crew', 'Planning / new infrastructure / capital project', 'Clear', 'Request for new infrastructure, a capital project or engineering review; handled by planners/engineers over weeks or months, not dispatched to a crew.'),
]
crew_map = spark.createDataFrame(
    CREW_MAP, "service_name string, work_type string, work_category string, call_confidence string, why string")
print(f"{len(CREW_MAP)} service types classified: "
      f"{sum(1 for r in CREW_MAP if r[1] == 'Crew')} crew, {sum(1 for r in CREW_MAP if r[1] != 'Crew')} non-crew")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6. Tab "Service Types": one row per service type
# MAGIC
# MAGIC Same rules as the guide:
# MAGIC - **Days to close** uses status "Closed" only (duplicates left out), from 0 to 1,095 days.
# MAGIC - **Open** means status "Open". **Stuck** means open more than 60 days.
# MAGIC - **Agency** is the one that appears most often on that type's tickets (ties: the most recently used).

# COMMAND ----------

clean = spark.table(f"{SCHEMA}.tickets_clean").where("service_name IS NOT NULL")
with_agency = clean.withColumn("agency", F.coalesce("agency_responsible", F.lit("(blank)")))

# The most common agency for each service type
agency_rank = Window.partitionBy("service_name").orderBy(F.desc("n"), F.desc("last_used"), F.asc("agency"))
main_agency = (with_agency.groupBy("service_name", "agency")
               .agg(F.count("*").alias("n"), F.max("requested_date").alias("last_used"))
               .withColumn("_r", F.row_number().over(agency_rank)).where("_r = 1")
               .select("service_name", F.col("agency").alias("agency_responsible")))

counts = with_agency.groupBy("service_name").agg(
    F.countDistinct("agency").alias("agency_count"),
    F.count("*").alias("total_tickets"),
    F.sum((F.year("requested_date") == THIS_YEAR).cast("int")).alias(YEAR_COL),
    F.sum(F.col("is_open").cast("int")).alias("open_now"),
    F.sum((F.col("is_open") & (F.col("days_waiting") > REVIEW_AFTER_DAYS)).cast("int")).alias("open_now_gt60d"))

closed = clean.where((F.lower("status_description") == "closed")
                     & F.col("days_to_close").between(0, MAX_CLOSE_DAYS))
closing = closed.groupBy("service_name").agg(
    F.count("*").alias("closed_tickets_used"),
    F.expr("percentile(days_to_close, 0.5)").alias("median_days_to_close"),      # exact, like the guide
    F.round(F.avg("days_to_close"), 1).alias("mean_days_to_close"),
    F.round(F.expr("percentile(days_to_close, 0.9)"), 1).alias("p90_days_to_close"))

service_types = (main_agency.join(counts, "service_name").join(closing, "service_name", "left")
    .join(crew_map, "service_name", "left")
    .fillna({"closed_tickets_used": 0, "work_type": "Unclassified",
             "work_category": "Not in the team's list", "call_confidence": "Unclassified",
             "why": "This service type is not in the team's reference spreadsheet."})
    # The "normal fixing time" used for lateness: the 90% mark, kept between 1 and 30 days.
    .withColumn("normal_days", F.least(F.greatest(F.coalesce("p90_days_to_close", F.lit(MAX_NORMAL_DAYS)),
                                                  F.lit(MIN_NORMAL_DAYS)), F.lit(MAX_NORMAL_DAYS)))
    .withColumn("used_this_year", F.col(YEAR_COL) > 0))


def add_agency_share(df):
    """The three 'share of agency' columns from the spreadsheet.
    Types are listed biggest first inside each agency:
      pct_of_agency_volume = this type's share of its agency's tickets
      cumulative_pct       = running total of that share
      in_core_set          = True while the running total BEFORE this row is under the cutoff"""
    agency = Window.partitionBy("agency_responsible")
    biggest_first = agency.orderBy(F.desc("total_tickets"), F.asc("service_name"))
    return (df
        .withColumn("pct_of_agency_volume", F.col("total_tickets") / F.sum("total_tickets").over(agency))
        .withColumn("cumulative_pct", F.sum("pct_of_agency_volume").over(
            biggest_first.rowsBetween(Window.unboundedPreceding, Window.currentRow)))
        .withColumn("in_core_set",
                    (F.col("cumulative_pct") - F.col("pct_of_agency_volume")) < F.lit(CORE_SET_CUTOFF)))


service_types = add_agency_share(service_types).select(
    "service_name", "agency_responsible", "agency_count", "total_tickets", YEAR_COL, "open_now", "open_now_gt60d",
    "closed_tickets_used", "median_days_to_close", "mean_days_to_close", "p90_days_to_close",
    "pct_of_agency_volume", "cumulative_pct", "in_core_set",
    "work_type", "work_category", "call_confidence", "why",
    "normal_days", "used_this_year")          # the last two are extra helpers for the queue steps

service_types.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.service_types")
st = spark.table(f"{SCHEMA}.service_types")
n_crew = st.where("work_type = 'Crew'").count()
n_crew_active = st.where("work_type = 'Crew' AND used_this_year").count()
print(f"{SCHEMA}.service_types: {st.count():,} service types, {n_crew} crew, "
      f"{n_crew_active} crew types used in {THIS_YEAR}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7. Tabs "2026 Remaining Services" and "Crew - All Years"
# MAGIC
# MAGIC Both are views of the Service Types table, so the three always agree.
# MAGIC - **Remaining services**: types with at least 1 ticket this year, biggest this year first.
# MAGIC - **Crew - All Years**: crew types only (retired ones included), biggest overall first.

# COMMAND ----------

st = spark.table(f"{SCHEMA}.service_types")
facts = ["open_now", "open_now_gt60d", "closed_tickets_used",
         "median_days_to_close", "mean_days_to_close", "p90_days_to_close"]

by_this_year = Window.orderBy(F.desc(YEAR_COL), F.desc("total_tickets"), F.asc("service_name"))
remaining = (st.where("used_this_year").withColumn("rank", F.row_number().over(by_this_year))
             .select("rank", "service_name", "agency_responsible", YEAR_COL, "total_tickets", *facts, "work_type"))
REMAINING_TABLE = f"{SCHEMA}.remaining_services_{THIS_YEAR}"
remaining.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(REMAINING_TABLE)

by_total = Window.orderBy(F.desc("total_tickets"), F.asc("service_name"))
crew_all = (st.where("work_type = 'Crew'").withColumn("rank", F.row_number().over(by_total))
            .select("rank", "service_name", "agency_responsible", "total_tickets", YEAR_COL, *facts,
                    "work_category", "call_confidence", "why"))
crew_all.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.crew_all_years")

print(f"{REMAINING_TABLE}: {spark.table(REMAINING_TABLE).count():,} service types")
print(f"{SCHEMA}.crew_all_years: {spark.table(f'{SCHEMA}.crew_all_years').count():,} crew service types")
display(spark.table(f"{SCHEMA}.crew_all_years").orderBy("rank").limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8. Tab "Crew by Community"
# MAGIC
# MAGIC One row per community. The ticket counts come from the 311 data (crew service types only).
# MAGIC Population and area are outside facts, listed in the next cell. The density, rank, percentile
# MAGIC and geography score are calculated from them with the spreadsheet's formulas.

# COMMAND ----------

# Population and area for each community. These two numbers do not come from 311 tickets:
# population is the 2021 Federal Census by Community, area is from the 2021 census boundary.
# Copied from the team's spreadsheet (Crew by Community tab). Everything else is calculated below.
COMMUNITY_FACTS = [
    ('BLN', 'BELTLINE', 25880, 2.942846, None),
    ('BOW', 'BOWNESS', 10770, 5.629194, None),
    ('DNC', 'DOWNTOWN COMMERCIAL CORE', 8225, 1.328765, None),
    ('FAL', 'FALCONRIDGE', 10325, 2.156763, None),
    ('SAD', 'SADDLE RIDGE', 24365, 5.595616, None),
    ('CRA', 'CRANSTON', 20850, 8.255538, None),
    ('BRD', 'BRIDGELAND/RIVERSIDE', 6350, 3.049921, None),
    ('TUS', 'TUSCANY', 19700, 6.799964, None),
    ('MAH', 'MAHOGANY', 13860, 6.300511, None),
    ('HIL', 'HILLHURST', 5475, 2.068228, None),
    ('MCT', 'MCKENZIE TOWNE', 17505, 4.824914, None),
    ('HUN', 'HUNTINGTON HILLS', 13120, 4.769946, None),
    ('CRE', 'CRESCENT HEIGHTS', 6240, 1.618686, None),
    ('ING', 'INGLEWOOD', 4130, 2.501208, None),
    ('CNS', 'CORNERSTONE', 6190, 7.643593, None),
    ('VAR', 'VARSITY', 12040, 6.811693, None),
    ('KIL', 'KILLARNEY/GLENGARRY', 7920, 1.844581, None),
    ('OGD', 'OGDEN', 8315, 4.139474, None),
    ('ALT', 'ALTADORE', 7290, 2.131302, None),
    ('DOV', 'DOVER', 10795, 4.151995, None),
    ('EDG', 'EDGEMONT', 15255, 6.620913, None),
    ('WHL', 'WEST HILLHURST', 6635, 2.359116, None),
    ('DDG', 'DOUGLASDALE/GLEN', 12920, 6.440721, None),
    ('PAN', 'PANORAMA HILLS', 25535, 6.335975, None),
    ('REN', 'RENFREW', 6580, 2.657646, None),
    ('EVN', 'EVANSTON', 18710, 4.882337, None),
    ('COV', 'COVENTRY HILLS', 17350, 4.084558, None),
    ('AUB', 'AUBURN BAY', 18090, 4.524795, None),
    ('SIG', 'SIGNAL HILL', 13000, 5.438282, None),
    ('ACA', 'ACADIA', 9915, 3.901022, None),
    ('LKB', 'LAKE BONAVISTA', 10145, 5.262499, None),
    ('WHI', 'WHITEHORN', 11085, 2.642698, None),
    ('THO', 'THORNCLIFFE', 8695, 3.269857, None),
    ('MOP', 'MOUNT PLEASANT', 6325, 1.874144, None),
    ('FLN', 'FOREST LAWN', 7230, 2.313088, None),
    ('SSD', 'SUNNYSIDE', 4000, 1.022688, None),
    ('EVE', 'EVERGREEN', 20780, 4.90651, None),
    ('BED', 'BEDDINGTON HEIGHTS', 11295, 3.200191, None),
    ('MON', 'MONTGOMERY', 4175, 2.953511, None),
    ('RIC', 'RICHMOND', 5250, 1.906059, None),
    ('MCK', 'MCKENZIE LAKE', 13290, 5.066311, None),
    ('HAY', 'HAYSBORO', 6960, 2.67044, None),
    ('TAR', 'TARADALE', 17630, 2.844447, None),
    ('HID', 'HIDDEN VALLEY', 11540, 4.306115, None),
    ('EPK', 'ELBOW PARK', 3285, 1.790415, None),
    ('RIV', 'RIVERBEND', 9205, 4.060517, None),
    ('SIL', 'SILVER SPRINGS', 8570, 5.016891, None),
    ('DAL', 'DALHOUSIE', 8530, 3.344253, None),
    ('TUX', 'TUXEDO PARK', 5165, 1.328655, None),
    ('MRT', 'MARTINDALE', 14540, 2.688573, None),
    ('ALB', 'ALBERT PARK/RADISSON HEIGHTS', 6740, 2.50803, None),
    ('CAN', 'CANYON MEADOWS', 7435, 3.080054, None),
    ('SOW', 'SOUTHWOOD', 6095, 2.66522, None),
    ('RUN', 'RUNDLE', 10545, 2.641711, None),
    ('SCE', 'SCENIC ACRES', 7850, 4.435795, None),
    ('PIN', 'PINERIDGE', 9850, 2.640983, None),
    ('SHN', 'SHAWNESSY', 9055, 3.648471, None),
    ('CHA', 'CHAPARRAL', 12500, 5.447504, None),
    ('MRL', 'MARLBOROUGH', 8910, 2.655826, None),
    ('CAP', 'CAPITOL HILL', 4670, 1.414506, None),
    ('WBN', 'WOODBINE', 8745, 3.227484, None),
    ('ARB', 'ARBOUR LAKE', 10335, 4.39375, None),
    ('MPK', 'MARLBOROUGH PARK', 8290, 2.48816, None),
    ('LIV', 'LIVINGSTON', 3985, 5.664755, None),
    ('SGH', 'SAGE HILL', 9345, 3.722542, None),
    ('LMR', 'LOWER MOUNT ROYAL', 2990, 0.284317, None),
    ('TEM', 'TEMPLE', 10525, 2.625338, None),
    ('SNA', 'SUNALTA', 3090, 0.937197, None),
    ('WSP', 'WEST SPRINGS', 11560, 4.17611, None),
    ('WAL', 'WALDEN', 7650, 2.460379, None),
    ('GBK', 'GLENBROOK', 7240, 1.961068, None),
    ('SDC', 'SUNDANCE', 9590, 3.980144, None),
    ('WIL', 'WILLOW PARK', 5090, 3.400081, None),
    ('RAN', 'RANCHLANDS', 7490, 2.340172, None),
    ('CPF', 'COPPERFIELD', 14095, 4.609046, None),
    ('HAW', 'HAWKWOOD', 9115, 3.208462, None),
    ('CIT', 'CITADEL', 10180, 2.733364, None),
    ('MNI', 'MANCHESTER INDUSTRIAL', None, 4.573283, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SOC', 'SOUTH CALGARY', 4540, 0.887854, None),
    ('BRE', 'BRENTWOOD', 7410, 2.892793, None),
    ('LEG', 'LEGACY', 8000, 6.0854, None),
    ('OAK', 'OAKRIDGE', 5620, 2.411086, None),
    ('SET', 'SETON', 3590, 4.560266, None),
    ('KIN', 'KINGSLAND', 4900, 1.338048, None),
    ('PEN', 'PENBROOKE MEADOWS', 8235, 2.037684, None),
    ('NEB', 'NEW BRIGHTON', 12885, 2.846973, None),
    ('MOR', 'MONTEREY PARK', 10475, 3.446715, None),
    ('RAM', 'RAMSAY', 2155, 0.985977, None),
    ('BNK', 'BANKVIEW', 5125, 0.686613, None),
    ('LKV', 'LAKEVIEW', 5640, 2.240685, None),
    ('BRI', 'BRIDLEWOOD', 12545, 3.14132, None),
    ('SPH', 'SPRINGBANK HILL', 9840, 6.507935, None),
    ('SHG', 'SHAGANAPPI', 1765, 1.481267, None),
    ('CSC', 'CITYSCAPE', 5085, 2.309012, None),
    ('SVO', 'SILVERADO', 7975, 5.97207, None),
    ('BNF', 'BANFF TRAIL', 3805, 1.455182, None),
    ('HPK', 'HIGHLAND PARK', 4105, 1.368344, None),
    ('HAR', 'HARVEST HILLS', 7805, 2.179341, None),
    ('BRA', 'BRAESIDE', 5700, 1.961464, None),
    ('WIN', 'WINSTON HEIGHTS/MOUNTVIEW', 3605, 3.019755, None),
    ('GLA', 'GLAMORGAN', 6575, 2.032795, None),
    ('MAL', 'MAYLAND HEIGHTS', 5925, 2.02273, None),
    ('MIS', 'MISSION', 4505, 0.535295, None),
    ('SKR', 'SKYVIEW RANCH', 12870, 2.310573, None),
    ('CAR', 'CARRINGTON', 2750, 2.988757, None),
    ('ROY', 'ROYAL OAK', 11580, 3.562663, None),
    ('STR', 'STRATHCONA PARK', 6830, 2.705643, None),
    ('GDL', 'GLENDALE', 2715, 1.369473, None),
    ('ASP', 'ASPEN WOODS', 9435, 3.992582, None),
    ('CHW', 'CHARLESWOOD', 3595, 1.831216, None),
    ('ERI', 'ERIN WOODS', 6790, 1.597924, None),
    ('HOU', 'HOUNSFIELD HEIGHTS/BRIAR HILL', 2470, 1.179723, None),
    ('UMR', 'UPPER MOUNT ROYAL', 2735, 1.274841, None),
    ('FHT', 'FOREST HEIGHTS', 5985, 1.505505, None),
    ('NOL', 'NOLAN HILL', 8755, 2.046593, None),
    ('RVW', 'RANGEVIEW', None, 4.823078, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SPR', 'SPRUCE CLIFF', 4195, 1.074366, None),
    ('RCK', 'ROSSCARROCK', 3490, 1.06752, None),
    ('SOV', 'SOUTHVIEW', 1550, 1.592729, None),
    ('WLD', 'WILDWOOD', 2765, 2.563502, None),
    ('GPK', 'GLENMORE PARK', None, 10.161658, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SAN', 'SANDSTONE VALLEY', 5795, 1.800748, None),
    ('CED', 'CEDARBRAE', 5935, 2.030107, None),
    ('MID', 'MIDNAPORE', 6480, 2.954704, None),
    ('ROC', 'ROCKY RIDGE', 8195, 2.808513, None),
    ('PCK', 'PINE CREEK', 245, 2.498575, None),
    ('GLR', 'GLACIER RIDGE', None, 4.623175, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('MLR', 'MILLRISE', 6655, 1.78256, None),
    ('HSN', 'HASKAYNE', None, 5.826607, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('NGM', 'NORTH GLENMORE PARK', 2435, 1.156219, None),
    ('DRN', 'DEER RUN', 4910, 1.91943, None),
    ('DNE', 'DOWNTOWN EAST VILLAGE', 3140, 0.522153, None),
    ('FAI', 'FAIRVIEW', 3675, 1.320583, None),
    ('WOO', 'WOODLANDS', 5830, 2.804512, None),
    ('PKD', 'PARKDALE', 2300, 1.051591, None),
    ('HAM', 'HAMPTONS', 7360, 3.502357, None),
    ('PKH', 'PARKHILL', 1770, 0.657531, None),
    ('ABB', 'ABBEYDALE', 5925, 1.701101, None),
    ('COR', 'CORAL SPRINGS', 5610, 1.817595, None),
    ('WGT', 'WESTGATE', 3225, 1.164263, None),
    ('DRG', 'DEER RIDGE', 3795, 1.417007, None),
    ('CAS', 'CASTLERIDGE', 6130, 1.212386, None),
    ('RSN', 'REDSTONE', 9050, 1.953095, None),
    ('MRN', 'MORAINE', None, 2.670334, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('PKL', 'PARKLAND', 3430, 1.888524, None),
    ('ALP', 'ALPINE PARK', None, 3.921422, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('CLI', 'CLIFF BUNGALOW', 1805, 0.362864, None),
    ('EAU', 'EAU CLAIRE', 1875, 0.516147, None),
    ('DNW', 'DOWNTOWN WEST END', 2825, 0.364555, None),
    ('FHI', 'FOOTHILLS', None, 7.718347, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('QLD', 'QUEENSLAND', 4585, 1.557737, None),
    ('VAL', 'VALLEY RIDGE', 5365, 3.290706, None),
    ('RDL', 'ROSEDALE', 1495, 0.661732, None),
    ('WND', 'WINDSOR PARK', 4410, 1.275915, None),
    ('MAC', 'MACEWAN GLEN', 4740, 1.41837, None),
    ('ERL', 'ERLTON', 1280, 0.505672, None),
    ('SOM', 'SOMERSET', 8320, 2.187442, None),
    ('KCA', 'KINCORA', 7030, 2.271442, None),
    ('ESH', 'EAST SHEPARD INDUSTRIAL', None, 17.340996, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('CGR', 'COUGAR RIDGE', 7150, 2.262833, None),
    ('WWO', 'WOLF WILLOW', 525, 2.854409, None),
    ('BLM', 'BELMONT', 800, 2.845305, None),
    ('DIS', 'DISCOVERY RIDGE', 4330, 3.581198, None),
    ('MPL', 'MAPLE RIDGE', 1830, 2.695283, None),
    ('HKS', 'HOTCHKISS', None, 3.109309, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('COL', 'COLLINGWOOD', 2290, 1.562191, None),
    ('COA', 'COACH HILL', 3275, 1.073119, None),
    ('WES', 'WESTWINDS', None, 1.95527, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SHW', 'SHERWOOD', 6520, 2.393801, None),
    ('CAM', 'CAMBRIAN HEIGHTS', 2000, 0.864019, None),
    ('PAT', 'PATTERSON', 4145, 2.045978, None),
    ('AYB', 'ALYTH/BONNYBROOK', None, 3.801669, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('HSD', 'HOMESTEAD', None, 1.612066, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('GAW', 'GARRISON WOODS', 2860, 0.7773, None),
    ('BVD', 'BELVEDERE', None, 3.667013, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('GRI', 'GREENVIEW INDUSTRIAL PARK', None, 2.139579, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('STA', 'ST. ANDREWS HEIGHTS', 1345, 1.160099, None),
    ('HIW', 'HIGHWOOD', 2205, 0.949908, None),
    ('SHS', 'SHAWNEE SLOPES', 2020, 1.250301, None),
    ('EYA', 'ELBOYA', 1835, 0.721833, None),
    ('APP', 'APPLEWOOD PARK', 6830, 1.55369, None),
    ('COU', 'COUNTRY HILLS', 3660, 1.88878, None),
    ('SCA', 'SCARBORO', 1010, 0.45595, None),
    ('CHK', 'CHINOOK PARK', 1535, 0.581923, None),
    ('RUT', 'RUTLAND PARK', 2140, 0.68128, None),
    ('CHN', 'CHINATOWN', 2250, 0.246719, None),
    ('UNI', 'UNIVERSITY HEIGHTS', 2965, 0.817271, None),
    ('PAL', 'PALLISER', 3285, 0.987738, None),
    ('CUR', 'CURRIE BARRACKS', 1275, 0.985187, None),
    ('RRC', 'RICARDO RANCH', None, 6.008625, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('MEA', 'MEADOWLARK PARK', 610, 0.633184, None),
    ('SUN', 'SUNRIDGE', None, 2.262083, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('YKV', 'YORKVILLE', 715, 1.991748, None),
    ('VIS', 'VISTA HEIGHTS', 2300, 1.13861, None),
    ('BUR', 'BURNS INDUSTRIAL', None, 2.885856, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('CHR', 'CHRISTIE PARK', 1880, 0.819332, None),
    ('PUM', 'PUMP HILL', 1455, 0.942692, None),
    ('SSW', 'SCARBORO/SUNALTA WEST', 465, 0.354647, None),
    ('CHV', 'COUNTRY HILLS VILLAGE', 2480, 0.952215, None),
    ('KEL', 'KELVIN GROVE', 1805, 0.770273, None),
    ('NHV', 'NORTH HAVEN', 2365, 0.845767, None),
    ('CRM', 'CRESTMONT', 2275, 2.697383, None),
    ('ST3', 'STONEY 3', None, 1.316862, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('BYV', 'BAYVIEW', 670, 0.423921, None),
    ('NPK', 'NOSE HILL PARK', None, 11.607792, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('RMT', 'ROSEMONT', 1155, 0.449223, None),
    ('SHI', 'SHEPARD INDUSTRIAL', 265, 4.196307, None),
    ('GAG', 'GARRISON GREEN', 1680, 0.36054, None),
    ('HOR', 'HORIZON', None, 2.310663, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('EFV', 'EAST FAIRVIEW INDUSTRIAL', None, 2.314861, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('FVI', 'FAIRVIEW INDUSTRIAL', None, 1.278927, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SAW', 'SOUTH AIRWAYS', None, 1.89215, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('HIF', 'HIGHFIELD', None, 2.755491, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('ST1', 'STONEY 1', None, 6.239518, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SGL', 'STONEGATE LANDING', None, 5.436291, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('BDO', 'BONAVISTA DOWNS', 830, 0.57093, None),
    ('FRA', 'FRANKLIN', None, 1.465002, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('HUX', 'HUXLEY', None, 4.183118, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SKW', 'SKYLINE WEST', None, 0.826114, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('MLI', 'MAYLAND', None, 1.226525, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('GRV', 'GREENVIEW', 2100, 0.454186, None),
    ('BRT', 'BRITANNIA', 765, 0.501745, None),
    ('ABP', 'AURORA BUSINESS PARK', None, 2.400178, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('LEB', 'LEWISBURG', None, 2.5941, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('MAN', 'MANCHESTER', 950, 0.473613, None),
    ('RID', 'RIDEAU PARK', 675, 0.267126, None),
    ('CIA', 'CALGARY INTERNATIONAL AIRPORT', None, 20.588954, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('GRE', 'GREENWOOD/GREENBRIAR', 1055, 1.190709, None),
    ('UND', 'UNIVERSITY DISTRICT', 960, 1.15347, None),
    ('MCI', 'MCCALL', None, 2.388163, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('LPK', 'LINCOLN PARK', 1590, 1.485457, None),
    ('FPK', 'FISH CREEK PARK', 430, 15.288576, None),
    ('ROX', 'ROXBORO', 415, 0.271964, None),
    ('EAG', 'EAGLE RIDGE', 260, 0.376366, None),
    ('MER', 'MERIDIAN', None, 1.383228, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('FLI', 'FOREST LAWN INDUSTRIAL', None, 1.533306, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('S23', 'SECTION 23', None, 3.073929, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('UOC', 'UNIVERSITY OF CALGARY', None, 1.501181, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('RYV', 'ROYAL VISTA', None, 1.31252, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('NAW', 'NORTH AIRWAYS', None, 1.210832, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SRI', 'SADDLE RIDGE INDUSTRIAL', None, 2.538983, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SFH', 'SOUTH FOOTHILLS', None, 3.560266, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('VAF', 'VALLEYFIELD', None, 1.211319, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('MDH', 'MEDICINE HILL', None, 1.197538, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('09Q', '09Q', None, 6.775219, 'Residual sub-area: land outside a named community'),
    ('DIA', 'DIAMOND COVE', 625, 0.535394, None),
    ('RED', 'RED CARPET', 1745, 0.562991, None),
    ('GPI', 'GREAT PLAINS', None, 4.27072, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('BEL', 'BEL-AIRE', 400, 0.337111, None),
    ('DBC', 'DEERFOOT BUSINESS CENTRE', None, 1.967135, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('MAF', 'MAYFAIR', 410, 0.289495, None),
    ('POI', 'POINT MCKAY', 1330, 0.383263, None),
    ('02F', '02F', None, 3.295559, 'Residual sub-area: land outside a named community'),
    ('12A', '12A', None, 11.647296, 'Residual sub-area: land outside a named community'),
    ('NHU', 'NORTH HAVEN UPPER', 640, 0.269156, None),
    ('ST2', 'STONEY 2', None, 3.951123, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('ABR', 'AMBLERIDGE', None, 3.049373, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('12B', '12B', None, 8.053065, 'Residual sub-area: land outside a named community'),
    ('05D', '05D', None, 1.451963, 'Residual sub-area: land outside a named community'),
    ('STD', 'STARFIELD', None, 5.96974, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('01K', '01K', None, 5.289023, 'Residual sub-area: land outside a named community'),
    ('09H', '09H', None, 0.561505, 'Residual sub-area: land outside a named community'),
    ('PEG', 'PEGASUS', None, 0.256172, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SKE', 'SKYLINE EAST', None, 0.540646, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('KSH', 'KEYSTONE HILLS', None, 1.200051, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('09D', '09D', None, 0.404165, 'Residual sub-area: land outside a named community'),
    ('11B', '11B', None, 3.75331, 'Residual sub-area: land outside a named community'),
    ('09P', '09P', None, 6.536871, 'Residual sub-area: land outside a named community'),
    ('GBP', 'GLENDEER BUSINESS PARK', None, 0.269732, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('EFI', 'EASTFIELD', None, 1.116229, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('QPK', 'QUEENS PARK VILLAGE', 375, 0.619076, None),
    ('OPH', 'OSPREY HILL', None, 0.211814, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('06A', '06A', None, 2.307023, 'Residual sub-area: land outside a named community'),
    ('OSH', 'OGDEN SHOPS', None, 2.223202, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('01B', '01B', None, 1.977243, 'Residual sub-area: land outside a named community'),
    ('ST4', 'STONEY 4', None, 4.335079, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('SVR', 'SYMONS VALLEY RANCH', None, 0.149379, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('STE', 'STARFIELD EAST', None, 1.642708, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('GTI', 'GOLDEN TRIANGLE', None, 0.507563, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('12J', '12J', None, 17.339014, 'Residual sub-area: land outside a named community'),
    ('13F', '13F', None, 2.671105, 'Residual sub-area: land outside a named community'),
    ('02C', '02C', None, 1.478599, 'Residual sub-area: land outside a named community'),
    ('01F', '01F', None, 0.884168, 'Residual sub-area: land outside a named community'),
    ('02E', '02E', None, 2.61886, 'Residual sub-area: land outside a named community'),
    ('03W', '03W', None, 12.95494, 'Residual sub-area: land outside a named community'),
    ('02K', '02K', None, 2.631787, 'Residual sub-area: land outside a named community'),
    ('13G', '13G', None, 5.10868, 'Residual sub-area: land outside a named community'),
    ('12C', '12C', None, 1.655467, 'Residual sub-area: land outside a named community'),
    ('10E', '10E', None, 1.878164, 'Residual sub-area: land outside a named community'),
    ('12L', '12L', None, 2.578032, 'Residual sub-area: land outside a named community'),
    ('13E', '13E', None, 2.69964, 'Residual sub-area: land outside a named community'),
    ('COP', 'CANADA OLYMPIC PARK', None, 0.873247, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('05F', '05F', None, 1.080985, 'Residual sub-area: land outside a named community'),
    ('05E', '05E', None, 3.134342, 'Residual sub-area: land outside a named community'),
    ('01C', '01C', None, 0.642871, 'Residual sub-area: land outside a named community'),
    ('01H', '01H', None, 1.616305, 'Residual sub-area: land outside a named community'),
    ('GPE', 'GREAT PLAINS EAST', None, 1.079775, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('10D', '10D', None, 0.831663, 'Residual sub-area: land outside a named community'),
    ('THS', 'TWINHILLS', None, 1.994777, 'No 2021 population count (industrial/business area, park, or built after 2021)'),
    ('13I', '13I', None, 0.258342, 'Residual sub-area: land outside a named community'),
    ('13N', '13N', None, 0.568131, 'Residual sub-area: land outside a named community'),
    ('02L', '02L', None, 3.918756, 'Residual sub-area: land outside a named community'),
    ('06C', '06C', None, 0.522619, 'Residual sub-area: land outside a named community'),
    ('02B', '02B', None, 2.665279, 'Residual sub-area: land outside a named community'),
    ('13M', '13M', None, 2.845494, 'Residual sub-area: land outside a named community'),
    ('12K', '12K', None, 0.780292, 'Residual sub-area: land outside a named community'),
    ('05G', '05G', None, 0.529748, 'Residual sub-area: land outside a named community'),
    ('13H', '13H', None, 0.3326, 'Residual sub-area: land outside a named community'),
    ('13J', '13J', None, 0.658468, 'Residual sub-area: land outside a named community'),
    ('ABT', 'AMBLETON', None, None, 'Not in the 2021 census'),
    ('06B', '06B', None, 0.43294, 'Residual sub-area: land outside a named community'),
    ('09O', '09O', None, 1.976038, 'Residual sub-area: land outside a named community'),
    ('01I', '01I', None, None, 'Residual sub-area: land outside a named community; Not in the 2021 census'),
    ('13C', '13C', None, 2.656046, 'Residual sub-area: land outside a named community'),
    ('13A', '13A', None, 2.65779, 'Residual sub-area: land outside a named community'),
    ('12I', '12I', None, None, 'Residual sub-area: land outside a named community; Not in the 2021 census'),
]
community_facts = spark.createDataFrame(
    COMMUNITY_FACTS, "comm_code string, ref_name string, population_2021 long, area_km2 double, area_note string")
print(f"{len(COMMUNITY_FACTS)} communities, {sum(1 for r in COMMUNITY_FACTS if r[2] is not None)} with a 2021 population count")

# COMMAND ----------

def score_communities(facts_df, floor):
    """Spreadsheet formulas, for communities that have a population count:
         population_density = population / area_km2
         density_rank       = 1 for the densest
         density_percentile = share of populated communities that are less dense (0 to 1)
         geo_score          = floor + (1 - floor) x density_percentile
       Communities with no population count get the floor."""
    populated = facts_df.where("population_2021 IS NOT NULL AND area_km2 > 0")
    n = populated.count()
    densest_first = Window.orderBy(F.desc("population_density"))
    scored = (populated
        .withColumn("population_density", F.col("population_2021") / F.col("area_km2"))
        .withColumn("density_rank", F.rank().over(densest_first))
        .withColumn("density_percentile", (F.lit(n) - F.col("density_rank")) / F.lit(max(n - 1, 1)))
        .select("comm_code", "population_density", "density_rank", "density_percentile"))
    return (facts_df.join(scored, "comm_code", "left")
            .withColumn("geo_score", F.lit(floor) + (1 - floor) * F.coalesce("density_percentile", F.lit(0.0))))


community_scores = score_communities(community_facts, GEO_FLOOR)

# Crew tickets per community (all 107 crew types, every status), counted from the cleaned tickets
crew_names = spark.table(f"{SCHEMA}.service_types").where("work_type = 'Crew'").select("service_name")
crew_tickets = spark.table(f"{SCHEMA}.tickets_clean").join(F.broadcast(crew_names), "service_name")
per_community = crew_tickets.groupBy("comm_code").agg(
    F.max("comm_name").alias("ticket_name"),
    F.sum((F.year("requested_date") == THIS_YEAR).cast("int")).alias(f"crew_tickets_{THIS_YEAR}"),
    F.count("*").alias("crew_tickets_all_years"),
    F.sum(F.col("is_open").cast("int")).alias("crew_open_now"),
    F.sum((F.col("is_open") & (F.col("days_waiting") > REVIEW_AFTER_DAYS)).cast("int")).alias("crew_open_gt60d"))

busiest_first = Window.orderBy(F.col("comm_code").isNull().cast("int"),          # "no community" goes last
                               F.desc(f"crew_tickets_{THIS_YEAR}"), F.desc("crew_tickets_all_years"), F.asc("comm_name"))
crew_by_community = (per_community.join(community_scores, "comm_code", "left")
    .withColumn("comm_name", F.when(F.col("comm_code").isNull(), F.lit("(no community recorded)"))
                              .otherwise(F.coalesce("ref_name", "ticket_name")))
    .withColumn("geo_score", F.coalesce("geo_score", F.lit(GEO_FLOOR)))
    .withColumn(f"crew_{THIS_YEAR}_per_1000_people",
                F.when(F.col("population_2021") > 0,
                       F.col(f"crew_tickets_{THIS_YEAR}") / F.col("population_2021") * 1000))
    .withColumn("rank", F.row_number().over(busiest_first))
    .select("rank", "comm_code", "comm_name", f"crew_tickets_{THIS_YEAR}", "crew_tickets_all_years",
            "crew_open_now", "crew_open_gt60d", "area_note", "population_2021", "area_km2",
            "population_density", "density_rank", "density_percentile", "geo_score",
            f"crew_{THIS_YEAR}_per_1000_people"))

crew_by_community.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.crew_by_community")
print(f"{SCHEMA}.crew_by_community: {spark.table(f'{SCHEMA}.crew_by_community').count():,} rows")
display(spark.table(f"{SCHEMA}.crew_by_community").orderBy("rank").limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9. Every open ticket: crew job or not, and why
# MAGIC
# MAGIC The same questions as the team's backend step 2, asked in order. The first "no" is the reason for skipping:
# MAGIC 1. Is the service type marked **Crew**?
# MAGIC 2. Did the City still get this type this year? (if not, it is an old retired type)
# MAGIC
# MAGIC Tickets marked Duplicate are left out, and so are tickets with no date or no service type.

# COMMAND ----------

clean = spark.table(f"{SCHEMA}.tickets_clean")
types = spark.table(f"{SCHEMA}.service_types").select(
    "service_name", F.col("agency_responsible").alias("crew_pool"), "work_type", "work_category",
    "call_confidence", "why", "used_this_year", "median_days_to_close", "p90_days_to_close", "normal_days")

open_tickets = (clean.where("is_open AND requested_date IS NOT NULL AND service_name IS NOT NULL")
    .join(types, "service_name", "left")
    .withColumn("skip_reason",
        F.when(F.col("work_type") == "Unclassified", F.lit("Service type is not in the team's list"))
         .when(F.col("work_type") != "Crew", F.concat(F.lit("Not crew work: "), F.col("work_category")))
         .when(~F.col("used_this_year"), F.lit(f"Type not used in {THIS_YEAR} (old leftover)"))
         .otherwise(F.lit("")))
    .withColumn("is_crew_job", F.col("skip_reason") == "")
    # Lateness, from backend step 3 (no severity here):
    #   age_ratio above 1 = waited longer than the normal fixing time for this type
    .withColumn("age_ratio", F.round(F.col("days_waiting") / F.col("normal_days"), 2))
    .withColumn("waiting_bonus", F.when(F.col("days_waiting") > 2 * F.col("normal_days"), 2)
                                  .when(F.col("days_waiting") > F.col("normal_days"), 1).otherwise(0))
    .withColumn("needs_review", F.col("days_waiting") > REVIEW_AFTER_DAYS))

open_tickets.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.open_tickets")
ot = spark.table(f"{SCHEMA}.open_tickets")
print(f"{SCHEMA}.open_tickets: {ot.count():,} open tickets, {ot.where('is_crew_job').count():,} are crew jobs")
display(ot.where("NOT is_crew_job").groupBy("skip_reason").count().orderBy(F.desc("count")).limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10. Today's crew queue and the needs-review list
# MAGIC
# MAGIC Crew jobs open longer than 60 days were probably fixed and never closed.
# MAGIC They go to a list for a supervisor to check, not to a crew.

# COMMAND ----------

ot = spark.table(f"{SCHEMA}.open_tickets").where("is_crew_job")
ot.where("NOT needs_review").write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.crew_queue")
ot.where("needs_review").write.mode("overwrite").option("overwriteSchema", True).saveAsTable(f"{SCHEMA}.crew_needs_review")

queue = spark.table(f"{SCHEMA}.crew_queue")
print(f"{SCHEMA}.crew_queue: {queue.count():,} crew jobs for today's ranking")
print(f"{SCHEMA}.crew_needs_review: {spark.table(f'{SCHEMA}.crew_needs_review').count():,} crew jobs older than {REVIEW_AFTER_DAYS} days")

# Today's queue by crew pool and kind of work
display(queue.groupBy("crew_pool", "work_category").agg(
    F.count("*").alias("jobs"),
    F.sum((F.col("waiting_bonus") >= 1).cast("int")).alias("late"),
    F.sum(F.col("has_location").cast("int")).alias("with_map_point"),
).orderBy(F.desc("jobs")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 11. Does this match the team's spreadsheet and guide?
# MAGIC
# MAGIC The guide's numbers come from a file exported on Oct 2, 2026. The City's data keeps changing
# MAGIC (tickets get closed), so small differences are normal. Large ones mean something is wrong.

# COMMAND ----------

clean = spark.table(f"{SCHEMA}.tickets_clean")
st = spark.table(f"{SCHEMA}.service_types")
ot = spark.table(f"{SCHEMA}.open_tickets")
active = "used_this_year"
crew = "work_type = 'Crew'"


def total(df, col, cond="true"):
    return int(df.where(cond).agg(F.coalesce(F.sum(col), F.lit(0))).first()[0])


pothole = st.where("service_name = 'Roads - Pothole Maintenance'").first()
cbc = spark.table(f"{SCHEMA}.crew_by_community")
beltline = cbc.where("comm_code = 'BLN'").first()
ours_vs_guide = [
    ("Tickets, all years",                       clean.count(),                                 1936033),
    ("Service types",                            st.count(),                                    740),
    ("Service types used this year",             st.where(active).count(),                      456),
    ("Crew service types",                       st.where(crew).count(),                        107),
    ("Crew service types used this year",        st.where(f"{crew} AND {active}").count(),      82),
    ("Crew tickets, all years",                  total(st, "total_tickets", crew),              926871),
    ("Crew tickets this year",                   total(st, YEAR_COL, crew),                     204705),
    ("Open now (types used this year)",          total(st, "open_now", active),                 44158),
    ("Open now, crew",                           total(st, "open_now", f"{crew} AND {active}"), 26474),
    ("Open over 60 days (types used this year)", total(st, "open_now_gt60d", active),           30447),
    ("Open over 60 days, crew",                  total(st, "open_now_gt60d", f"{crew} AND {active}"), 20262),
    ("Marked Open but has a close date",         clean.where("is_open AND closed_date IS NOT NULL").count(), 4192),
    ("Tab 2026 Remaining Services: rows",        spark.table(REMAINING_TABLE).count(),          456),
    ("Tab Crew - All Years: rows",               spark.table(f"{SCHEMA}.crew_all_years").count(), 107),
    ("Tab Crew by Community: rows",              cbc.count(),                                   317),
    ("Crew by Community: tickets this year",     total(cbc, f"crew_tickets_{THIS_YEAR}"),       204705),
    ("Crew by Community: tickets all years",     total(cbc, "crew_tickets_all_years"),          926871),
    ("Crew by Community: open now",              total(cbc, "crew_open_now"),                   26518),
    ("Crew by Community: open over 60 days",     total(cbc, "crew_open_gt60d"),                 20306),
    ("Beltline: crew tickets this year",         beltline[f"crew_tickets_{THIS_YEAR}"] if beltline else 0, 4301),
    ("Potholes: total tickets",                  pothole["total_tickets"] if pothole else 0,    34790),
    ("Potholes: open now",                       pothole["open_now"] if pothole else 0,         990),
    ("Potholes: closed tickets used",            pothole["closed_tickets_used"] if pothole else 0, 30396),
    ("Potholes: median days to close",           pothole["median_days_to_close"] if pothole else 0, 1),
    ("Potholes: 90% closed within (days)",       pothole["p90_days_to_close"] if pothole else 0, 6),
]
rows = []
for name, ours, guide in ours_vs_guide:
    ours = float(ours or 0)
    gap = abs(ours - guide) / max(guide, 1)
    verdict = "same" if ours == guide else "close" if gap <= 0.02 else "DIFFERENT"
    rows.append((name, ours, float(guide), verdict))
display(spark.createDataFrame(rows, "measure string, databricks double, guide double, verdict string"))

# COMMAND ----------

# Service types in the City's data that the team's spreadsheet does not list (should be empty or tiny)
display(st.where("work_type = 'Unclassified'").select("service_name", "total_tickets", YEAR_COL, "open_now")
        .orderBy(F.desc("total_tickets")))

# COMMAND ----------

# Three basic checks on the cleaned data. PASS = nothing odd. CHECK = pass the number to the team.
total_rows = clean.count()
checks = {
    "Map points outside Calgary": clean.where(
        "has_location AND NOT (latitude BETWEEN 50.8 AND 51.3 AND longitude BETWEEN -114.4 AND -113.8)"),
    "Closed before it was requested": clean.where("closed_date < requested_date"),
    "Status is Closed but no closed date": clean.where("lower(status_description) = 'closed' AND closed_date IS NULL"),
}
for name, rows_ in checks.items():
    n = rows_.count()
    print(f"{'PASS ' if n == 0 else 'CHECK'}  {name}: {n:,} tickets ({100 * n / total_rows:.2f}%)")

print("\nTables in", f"{CATALOG}.{SCHEMA}:")
for row in spark.sql(f"SHOW TABLES IN {SCHEMA}").collect():
    print("  ", row["tableName"], f"{spark.table(f'{SCHEMA}.' + row['tableName']).count():,} rows")