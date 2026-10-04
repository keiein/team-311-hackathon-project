"""Priority score for the 311 dispatcher. Every term of the formula lives in this one file.

    priority = 0.50 * basic_knowledge + 0.15 * geo + 0.10 * age + 0.25 * ticket_count

Every term IS-A ScoreComponent: one ticket in, a score out. Three terms run from 0 to 1; age has no upper limit.
PriorityScorer HAS-A list of components and adds up weight * score.

    1. Shared helpers
    2. ScoreComponent       the parent: the ticket rules, the unique id, the hooks a term fills in
    3. BasicKnowledgeScore  how serious the job type is, from the keywords in its service name
    4. GeoScore             how many people the job's community exposes
    5. AgeScore             time open (now - opened) / SLA for the service type
    6. TicketCountScore     how many tickets report the same job on the same day in the same place
    7. PriorityScorer       the weighted total
    8. Command line

The parent class owns what happens before any term sees a ticket: the rules it must pass
(a crew job, no closed date, a location, ...) and its unique key, service_request_id.
A ticket that fails a rule is skipped with a reason and never scored.

A ticket can be a dict, a DataFrame row, or any object with the fields as attributes.
Missing or unreadable fields never raise; they fall back to the lowest score.
Method notes: PRIORITY_SCORING.md. Loading the result into MySQL: load_scored_tickets.py.

Run it:  python priority_score.py [tickets.csv] [--out ranked.csv]
         python priority_score.py --keywords
"""
import argparse
import re
from abc import ABC, abstractmethod
from bisect import bisect_left
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from numbers import Real
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

DATA = Path(__file__).parent.parent / "data"  # the case folder's data/, beside scoring/
REPO = Path(__file__).parent.parent.parent  # the repo root

WEIGHTS = {"basic_knowledge": 0.50, "geo": 0.15, "age": 0.10, "ticket_count": 0.25}

# ---- ticket source (placeholder). Each is looked for in two places and the first one found is used ----
# The cleaned open-ticket pile: the case's data/ folder, or databricks/data/ where the main branch keeps it.
# The small sample, used when there is no pile: the case's data/ folder, or the repo's data/ folder.
_TICKET_FILES = (DATA / "open_tickets.csv", REPO / "databricks" / "data" / "open_tickets.csv")
_SAMPLE_FILES = (DATA / "311_dispatch_sample.csv", REPO / "data" / "311_dispatch_sample.csv")
TICKETS = next((path for path in _TICKET_FILES if path.exists()), _TICKET_FILES[0])
SAMPLE = next((path for path in _SAMPLE_FILES if path.exists()), _SAMPLE_FILES[0])


# =====================================================================================================
# 1. Shared helpers
# =====================================================================================================

_FLAG_WORDS = {"1": "true", "1.0": "true", "yes": "true", "y": "true",
               "0": "false", "0.0": "false", "no": "false", "n": "false"}


def _blank(value: Any) -> bool:
    """True for None, NaN, NaT and empty strings."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return bool(pd.api.types.is_scalar(value) and pd.isna(value))


def _field(ticket: Any, names: Iterable[str]) -> Any:
    """First non-blank value among `names` on the ticket, else None."""
    read = ticket.get if hasattr(ticket, "get") else lambda name: getattr(ticket, name, None)
    for name in names:
        value = read(name)
        if not _blank(value):
            return value
    return None


def _key(text: Any) -> str:
    """Lookup key that ignores case and spacing ('Scarboro/ Sunalta West' == 'SCARBORO/SUNALTA WEST')."""
    return re.sub(r"\s*/\s*", "/", " ".join(str(text).split())).casefold()


def _text(value: Any) -> str:
    """A field as lowercase text, with yes/no and 1/0 read as true/false."""
    text = str(value).strip().lower()
    return _FLAG_WORDS.get(text, text)


def _number(value: Any) -> Optional[float]:
    """float, or None for blanks and non-numbers ('#REF!', 'n/a')."""
    value = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(value) else float(value)


def _when(value: Any) -> Optional[datetime]:
    """Local datetime from a date, datetime, Timestamp or date string; None if it can't be read."""
    if _blank(value) or isinstance(value, Real):  # a bare number is ambiguous (epoch? Excel serial?)
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    moment = stamp.to_pydatetime()
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def _words(service_name: Any) -> list:
    """The words of a service name, lower-cased ('Roads - Pothole Maintenance' -> roads, pothole, maintenance)."""
    return [word.lower() for word in re.findall(r"[A-Za-z0-9]+", service_name)] if isinstance(service_name, str) else []


# =====================================================================================================
# 2. The parent: ticket rules, the unique id, and the hooks every term fills in
# =====================================================================================================

class ScoreComponent(ABC):
    """One term of the priority formula: a ticket in, a score out (0..1; age alone can go above 1).

    The parent decides whether a ticket is scored at all. score() and score_frame() check
    RULES first and only then hand the ticket to the term's own _score(), so every term
    inherits the same gate and none of them can score a ticket that fails it.
    """

    # ---- ticket rules, checked before anything is scored ----
    ID_FIELD = "service_request_id"  # the unique key of a ticket; in a table, a blank or repeated id is skipped
    # (field, the value it must have, why the ticket is skipped when it doesn't). None = must be empty.
    # A ticket that doesn't carry the field passes that rule.
    RULES = (
        ("status_description", "Open", "Not open"),
        ("is_crew_job", True, "Not a crew job"),
        ("closed_date", None, "Has a closed date"),
        ("has_location", True, "No location"),
        ("needs_review", False, "Waiting over 60 days: needs review"),
    )
    # ---- ticket fields more than one term reads (first non-blank one wins) ----
    SERVICE_FIELDS = ("service_name",)
    OPENED_FIELDS = ("requested_date", "opened_date", "opened")

    name: str
    weight: float

    @classmethod
    def skip_reason(cls, ticket: Any) -> Optional[str]:
        """Why this ticket must not be scored (the first rule it fails), or None when it passes them all."""
        for field, wanted, reason in cls.RULES:
            value = _field(ticket, (field,))
            if value is not None and (wanted is None or _text(value) != _text(wanted)):
                return reason
        return None

    @classmethod
    def skip_reasons(cls, tickets: pd.DataFrame) -> pd.Series:
        """skip_reason for every row of a table ('' = passes), plus the id checks a single ticket can't have."""
        has_id = cls.ID_FIELD in tickets
        columns = [field for field, _, _ in cls.RULES if field in tickets] + [cls.ID_FIELD] * has_id
        rows = tickets[columns].to_dict("records") if columns else [{}] * len(tickets)
        reasons, seen = [], set()
        for row in rows:
            reason = cls.skip_reason(row)
            if reason is None and has_id:
                ticket_id = str(row[cls.ID_FIELD]).strip()
                if _blank(row[cls.ID_FIELD]):
                    reason = "No ticket id"
                elif ticket_id in seen:
                    reason = "Repeated ticket id"
                seen.add(ticket_id)
            reasons.append(reason or "")
        return pd.Series(reasons, index=tickets.index, dtype=object, name="skipped_because")

    @classmethod
    def queue(cls, tickets: pd.DataFrame) -> pd.DataFrame:
        """The rows that pass every rule: one per ticket id, with the id as the row label."""
        passed = tickets[(cls.skip_reasons(tickets) == "").to_numpy()]
        if cls.ID_FIELD in passed:
            passed = passed.set_axis(passed[cls.ID_FIELD].astype(str).str.strip().to_numpy(), axis=0)
        return passed

    def score(self, ticket: Any) -> Optional[float]:
        """The score for one ticket, or None when it fails a rule (skip_reason says which)."""
        return None if self.skip_reason(ticket) else self._score(ticket)

    def explain(self, ticket: Any) -> dict:
        """The score and the inputs behind it, or {'skipped_because': ...} when the ticket fails a rule."""
        reason = self.skip_reason(ticket)
        return {"skipped_because": reason} if reason else self._explain(ticket)

    def score_frame(self, tickets: pd.DataFrame) -> pd.Series:
        """Scores for the rows of a table that pass the rules, labelled by ticket id."""
        queue = self.queue(tickets)
        self.fit(queue)
        scores = [self._score(ticket) for ticket in queue.to_dict("records")]
        return pd.Series(scores, index=queue.index, dtype=float, name=f"{self.name}_score")

    def fit(self, queue: pd.DataFrame) -> None:
        """Called once with the whole queue before its tickets are scored.

        A term that compares a ticket with the others (TicketCountScore) overrides this. The rest need nothing from it.
        """

    @abstractmethod
    def _score(self, ticket: Any) -> float:
        """The score, from 0, for a ticket that passed the rules. This is the one method every term writes."""

    def _explain(self, ticket: Any) -> dict:
        """The score as '<name>_score'. A term may override this to add the inputs behind it."""
        return {f"{self.name}_score": self._score(ticket)}


# =====================================================================================================
# 3. Basic knowledge (weight 0.50): how serious the job type is, from the keywords in its service name
# =====================================================================================================

# ---- data source: the team's municipal criticality matrix. A keyword puts a job in a tier; the tier sets the score ----
CRITICALITY_TIERS = {
    4: {
        "multiplier": 1.00,
        "title": "TIER 4: Critical Consequence (Safety & Liability)",
        "desc": "Immediate public safety threat, high legal liability, severe hazard",
        "keywords": {
            "ice", "snow", "pothole", "emergency", "fire", "hydrant", "spills",
            "sewage", "break", "leak", "safety", "dead", "animal", "urgent",
            "outage", "damage", "seepage", "manhole", "collapse"
        }
    },
    3: {
        "multiplier": 0.70,
        "title": "TIER 3: Major Consequence (Operational Disruption)",
        "desc": "Navigational flow interruption, transit delays, infrastructure issues",
        "keywords": {
            "traffic", "signal", "light", "streetlight", "lighting", "bridge",
            "tunnel", "underpass", "skywalk", "plus", "ctrain", "bus", "stations",
            "stops", "detour", "lane", "roadway", "street", "sidewalk", "pathway",
            "pedestrian", "curb", "gutter", "catch", "basin", "drainage", "storm",
            "pond", "sewer", "pressure", "main", "valve", "meter", "water",
            "system", "stairs", "wooden", "retaining", "wall", "barrier", "fence",
            "pavement", "markings", "roadmarking", "faded", "missing", "signs",
            "sign", "designation", "debris", "control", "infrastructure",
            "reconnect", "temporary", "line", "tree"
        }
    },
    2: {
        "multiplier": 0.40,
        "title": "TIER 2: Moderate Consequence (Nuisance & Sanitation)",
        "desc": "Public nuisance, waste management, property damage, standard maintenance",
        "keywords": {
            "waste", "garbage", "cart", "carts", "recycling", "compost", "bin",
            "collection", "commercial", "residential", "depots", "graffiti",
            "encampment", "camp", "pest", "backlane", "clean", "removal", "pick",
            "pickup", "toilet", "portable", "quality", "installation", "equipment",
            "flat", "special", "parking", "black", "blue", "green", "entering",
            "basement", "back", "off"
        }
    },
    1: {
        "multiplier": 0.10,
        "title": "TIER 1: Insignificant Consequence (Aesthetic & Routine)",
        "desc": "Cosmetic maintenance, routine landscape stewardship, zero liability",
        "keywords": {
            "mowing", "weed", "greens", "roadside", "boulevard", "irrigation",
            "natural", "area", "cemetery", "playfield", "placement", "inactive",
            "community", "reservoir", "dock", "boat", "storage", "damaged"
        }
    }
}

KEYWORD_TO_TIER = {keyword: tier for tier, info in CRITICALITY_TIERS.items() for keyword in info["keywords"]}

# Words in a service name that say nothing about how serious the job is. The keyword report leaves them out.
UNNECESSARY_WORDS = {
    # Conjunctions, prepositions, articles
    "and", "in", "on", "of", "to", "or", "after", "up",
    # Generic operational / administrative boilerplate
    "maintenance", "service", "services", "concern", "concerns",
    "issue", "issues", "request", "management", "mgmt", "facility",
    "customer", "care", "centre", "appointment", "new", "internal",
    "checks", "stewardship", "city", "owned", "land", "repair", "repairs",
    # Department prefixes (already in agency_responsible)
    "roads", "parks", "wats", "wrs", "corporate",
    # System codes, acronyms, numbers
    "gis", "wam", "cpbs", "cpi", "ct", "gfl", "rsp", "nam", "fmccc", "apt", "bia", "max", "15"
}


def get_criticality_details(service_name: Any) -> tuple:
    """(score, tier, [(keyword, tier), ...] highest tier first, tier title) for a service name.

    The highest tier among the matched keywords wins. A name with no keyword gets tier 1.
    """
    matched = sorted(((word, KEYWORD_TO_TIER[word]) for word in _words(service_name) if word in KEYWORD_TO_TIER),
                     key=lambda match: -match[1])
    if not matched:
        return CRITICALITY_TIERS[1]["multiplier"], 1, [], "Unmatched (Default Tier 1)"
    tier = matched[0][1]
    return CRITICALITY_TIERS[tier]["multiplier"], tier, matched, CRITICALITY_TIERS[tier]["title"]


def keyword_report(service_names: Iterable[Any]) -> pd.DataFrame:
    """Every word in the service names that isn't an unnecessary one: its tier, and how many service types use it.

    A blank tier is a word no tier lists yet. Those come first, as the list still to sort.
    """
    counts = Counter(word for name in dict.fromkeys(service_names) for word in set(_words(name))
                     if word not in UNNECESSARY_WORDS)
    report = pd.DataFrame({"keyword": list(counts), "service_types": list(counts.values())})
    report["tier"] = report["keyword"].map(KEYWORD_TO_TIER).astype("Int64")
    order = report.sort_values(["tier", "service_types", "keyword"], ascending=[False, False, True], na_position="first")
    return order.reset_index(drop=True)


class BasicKnowledgeScore(ScoreComponent):
    """How serious a job of this type is, read from the words in its service name.

    tier 4 safety = 1.00, tier 3 disruption = 0.70, tier 2 nuisance = 0.40, tier 1 routine = 0.10.
    The tiers and keywords are CRITICALITY_TIERS above.
    """

    name = "basic_knowledge"
    weight = WEIGHTS["basic_knowledge"]

    def _explain(self, ticket: Any) -> dict:
        """The tier, the keywords that set it, and the score. keyword_found False = tier 1 by default."""
        score, tier, matched, _ = get_criticality_details(_field(ticket, self.SERVICE_FIELDS))
        return {
            "keyword_found": bool(matched),
            "criticality_tier": tier,
            "criticality_keywords": ", ".join(dict.fromkeys(word for word, level in matched if level == tier)),
            "basic_knowledge_score": score,
        }

    def _score(self, ticket: Any) -> float:
        """The tier's multiplier, 0.10 to 1.00."""
        return self._explain(ticket)["basic_knowledge_score"]


# =====================================================================================================
# 4. Geography (weight 0.15): how many people the job's community exposes
# =====================================================================================================

FLOOR = 0.3  # the lowest geo_score: a community with no residents and no businesses


def density(count: Optional[float], area_km2: Optional[float]) -> Optional[float]:
    """Per-km2 density; None when the count or area is missing or zero."""
    if not count or not area_km2 or count <= 0 or area_km2 <= 0:
        return None
    return count / area_km2


def percentile(value: Optional[float], all_values: Iterable[Optional[float]]) -> Optional[float]:
    """Share of the other communities (with a value) that are strictly lower, 0..1."""
    if value is None:
        return None
    values = sorted(v for v in all_values if v is not None)
    if len(values) < 2:
        return None
    return bisect_left(values, value) / (len(values) - 1)


def geo_score_from_percentiles(resident_percentile: Optional[float], business_percentile: Optional[float],
                               floor: float = FLOOR) -> float:
    """The higher of the two percentiles (0..1, None if no data), scaled up from the floor."""
    exposure = max((p for p in (resident_percentile, business_percentile) if p is not None), default=0.0)
    return floor + (1 - floor) * exposure


@dataclass(frozen=True)
class Community:
    """One community, keyed by the City of Calgary's 3-character community code (BLN = Beltline)."""

    code: str
    name: str
    population: Optional[float]
    business_licences: Optional[float]
    area_km2: Optional[float]
    geo_score: float

    @property
    def resident_density(self) -> Optional[float]:
        """Residents per km2."""
        return density(self.population, self.area_km2)

    @property
    def business_density(self) -> Optional[float]:
        """Business licences per km2."""
        return density(self.business_licences, self.area_km2)


class GeoScore(ScoreComponent):
    """How many people an open job affects: residents or businesses per km2, whichever ranks higher.

    Method: ../data/311_service_type_reference_GUIDE.md, 'How geo_score is calculated'.
        density    = count / area_km2
        percentile = (# communities with a lower density) / (communities with a value - 1)
        geo_score  = floor + (1 - floor) * max(resident percentile, business percentile)
    Scores are rebuilt from the raw counts, so a refreshed community table needs no Excel recalculation.
    """

    # ---- data source (placeholder: point these at the API / DB table when there is one) ----
    SOURCE = DATA / "311_service_type_reference.xlsx"
    SHEET = "Crew by Community"
    CODE_COL = "comm_code"  # the City's own community code; the same code is on every ticket and in the census
    NAME_COL = "comm_name"
    POPULATION_COL = "population_2021"
    BUSINESS_COL = "business_licences"
    AREA_COL = "area_km2"
    # ---- ticket fields that say where the job is (first one that matches a community wins) ----
    COMMUNITY_FIELDS = ("comm_code", "comm_name", "community")

    name = "geo"
    weight = WEIGHTS["geo"]

    def __init__(self, communities: Any = None, floor: float = FLOOR):
        """communities: one row per community (DataFrame or list of dicts); None reads SOURCE."""
        table = self.load_source() if communities is None else pd.DataFrame(communities)
        self.floor = floor
        self._communities, self._code_of = self._build(table)

    @classmethod
    def load_source(cls) -> pd.DataFrame:
        """One row per community. Swap the body to read from somewhere else."""
        table = pd.read_excel(cls.SOURCE, sheet_name=cls.SHEET)
        return table.dropna(subset=[cls.CODE_COL])  # the tab's last row is the 'no community recorded' total

    def _build(self, table: pd.DataFrame) -> tuple:
        """({code: Community}, {code or name: code}) for the table. A row with no code is keyed by its name."""
        rows = [row for row in table.to_dict("records")
                if not (_blank(row.get(self.CODE_COL)) and _blank(row.get(self.NAME_COL)))]
        people = [_number(row.get(self.POPULATION_COL)) for row in rows]
        licences = [_number(row.get(self.BUSINESS_COL)) for row in rows]
        areas = [_number(row.get(self.AREA_COL)) for row in rows]
        residents = [density(count, area) for count, area in zip(people, areas)]
        businesses = [density(count, area) for count, area in zip(licences, areas)]
        communities, code_of = {}, {}
        for i, row in enumerate(rows):
            name = row.get(self.NAME_COL)
            code = name if _blank(row.get(self.CODE_COL)) else row[self.CODE_COL]
            if _key(code) in communities:
                raise ValueError(f"community {code!r} is in the community table more than once")
            score = geo_score_from_percentiles(
                percentile(residents[i], residents), percentile(businesses[i], businesses), self.floor)
            communities[_key(code)] = Community(
                str(code).strip(), str(code if _blank(name) else name).strip(), people[i], licences[i], areas[i], score)
            code_of[_key(code)] = code_of[_key(communities[_key(code)].name)] = _key(code)
        return communities, code_of

    def community(self, code_or_name: Any) -> Optional[Community]:
        """The community with this City code (a name works too). None when it isn't in the table."""
        if _blank(code_or_name):
            return None
        return self._communities.get(self._code_of.get(_key(code_or_name)))

    @property
    def communities(self) -> pd.DataFrame:
        """Every community, one row per City code: name, population, business licences, area, geo_score."""
        columns = [field.name for field in fields(Community)]
        table = pd.DataFrame([asdict(community) for community in self._communities.values()], columns=columns)
        return table.set_index("code")

    def _find(self, ticket: Any) -> Optional[Community]:
        """The ticket's community; None when the ticket has none or it isn't in the table."""
        if isinstance(ticket, str):
            return self.community(ticket)
        for name in self.COMMUNITY_FIELDS:
            found = self.community(_field(ticket, (name,)))
            if found is not None:
                return found
        return None

    def _explain(self, ticket: Any) -> dict:
        """The community's numbers and its score. community_found False = it got the floor by default."""
        found = self._find(ticket)
        return {
            "community_found": found is not None,
            "population": found.population if found else None,
            "business_licences": found.business_licences if found else None,
            "area_km2": found.area_km2 if found else None,
            "geo_score": found.geo_score if found else self.floor,
        }

    def _score(self, ticket: Any) -> float:
        """geo_score of the ticket's community, floor..1.0. Also takes a bare community code or name.

        No community, or one that isn't in the table, gets the floor.
        """
        return self._explain(ticket)["geo_score"]


# =====================================================================================================
# 5. Age (weight 0.10): time open against the deadline for the service type
# =====================================================================================================

@dataclass(frozen=True)
class OpenAge:
    """How long a ticket has been open: now - opened."""

    opened: datetime
    now: datetime
    total_hours: float

    @property
    def days(self) -> int:
        """Whole days open."""
        return int(self.total_hours // 24)

    @property
    def hours(self) -> int:
        """Hours left over after the whole days, 0..23."""
        return int(self.total_hours % 24)

    @property
    def total_days(self) -> float:
        return self.total_hours / 24

    def __str__(self) -> str:
        return f"{self.days}d {self.hours}h"


class AgeScore(ScoreComponent):
    """How much of its deadline a ticket has used up: time open (now - opened) / SLA for its service type.

    0 = just opened, 1.0 = at its SLA, 3.0 = open for three times its SLA. The score is that division and
    nothing else: it is never capped, so this is the one term that can go above 1.
    """

    # ---- data source (placeholder: point these at the API / DB table when there is one) ----
    SOURCE = DATA / "crew_sla_reference.xlsx"
    SHEET = "Crew SLA"
    SERVICE_COL = "service_name"
    SLA_DAYS_COL = "age_deadline_days"  # published standard-tier SLA; observed p90 where the City publishes none
    # ---- settings ----
    DEFAULT_SLA_DAYS = 14.0  # service type that isn't in the SLA table (14 is the table's most common SLA)

    name = "age"
    weight = WEIGHTS["age"]

    def __init__(self, sla: Any = None, now: Any = None):
        """sla: one row per service type (DataFrame or list of dicts); None reads SOURCE.

        now: fixed 'current time' for replaying an old export; None uses the machine clock at scoring time.
        """
        table = self.load_source() if sla is None else pd.DataFrame(sla)
        self.now = _when(now)
        if now is not None and self.now is None:
            raise ValueError(f"now is not a readable date: {now!r}")
        self._sla_days = {}
        for row in table.to_dict("records"):
            days = _number(row.get(self.SLA_DAYS_COL))
            if _blank(row.get(self.SERVICE_COL)) or not days or days <= 0:
                continue
            if _key(row[self.SERVICE_COL]) in self._sla_days:
                raise ValueError(f"service type {row[self.SERVICE_COL]!r} is in the SLA table more than once")
            self._sla_days[_key(row[self.SERVICE_COL])] = days

    @classmethod
    def load_source(cls) -> pd.DataFrame:
        """One row per service type. Swap the body to read from somewhere else."""
        return pd.read_excel(cls.SOURCE, sheet_name=cls.SHEET)

    def sla_days(self, service_name: Any) -> float:
        """Deadline for a service type, in days (DEFAULT_SLA_DAYS when the type isn't in the table)."""
        if _blank(service_name):
            return self.DEFAULT_SLA_DAYS
        return self._sla_days.get(_key(service_name), self.DEFAULT_SLA_DAYS)

    def open_age(self, opened: Any) -> Optional[OpenAge]:
        """now - opened, in days and hours. None when `opened` isn't a readable date."""
        opened = _when(opened)
        if opened is None:
            return None
        now = self.now or datetime.now()
        hours = max((now - opened).total_seconds() / 3600, 0.0)  # an open date in the future counts as just opened
        return OpenAge(opened, now, hours)

    def _explain(self, ticket: Any) -> dict:
        """Time open (days + hours), the SLA it was measured against, time past the SLA, the ratio and the score.

        overdue_days and overdue_hours count from the SLA, not from the open date: both are 0 until the SLA passes.
        sla_found is False when the service type isn't in the SLA table and DEFAULT_SLA_DAYS was used.
        """
        age = self.open_age(_field(ticket, self.OPENED_FIELDS))
        service = _field(ticket, self.SERVICE_FIELDS)
        sla_days = self.sla_days(service)
        ratio = age.total_days / sla_days if age else None
        late_hours = max(age.total_hours - sla_days * 24, 0.0) if age else None
        return {
            "open_days": age.days if age else None,
            "open_hours": age.hours if age else None,
            "sla_days": sla_days,
            "sla_found": service is not None and _key(service) in self._sla_days,
            "sla_ratio": ratio,
            "overdue": ratio > 1 if age else None,
            "overdue_days": int(late_hours // 24) if age else None,
            "overdue_hours": int(late_hours % 24) if age else None,
            "age_score": ratio if age else 0.0,
        }

    def _score(self, ticket: Any) -> float:
        """Time open / SLA, from 0 with no upper limit. A ticket with no readable open date scores 0."""
        return self._explain(ticket)["age_score"]


# =====================================================================================================
# 6. Number of tickets (weight 0.25): how many tickets report the same job, the same day, the same place
# =====================================================================================================

# ---- settings: (tickets in the group, score), largest group first. A ticket on its own gets VOLUME_ALONE ----
VOLUME_STEPS = ((7, 1.00), (4, 0.70), (3, 0.35), (2, 0.20))
VOLUME_ALONE = 0.10


def get_volume_multiplier(count: Any) -> float:
    """Score for a number of same-day tickets: 1 -> 0.10, 2 -> 0.20, 3 -> 0.35, 4 to 6 -> 0.70, 7 or more -> 1.00."""
    count = _number(count) or 0
    return next((score for at_least, score in VOLUME_STEPS if count >= at_least), VOLUME_ALONE)


class TicketCountScore(ScoreComponent):
    """How many tickets report the same job: the same service type, on the same day, in the same place.

    Several people reporting one problem on one day is a sign it is real and in the way.
    The count is taken over the queue being scored (fit), so a ticket scored on its own counts as 1.
    """

    # ---- ticket fields that say where the job is ----
    LATITUDE_FIELDS = ("latitude",)
    LONGITUDE_FIELDS = ("longitude",)
    POINT_FIELDS = ("point",)  # used when the ticket has no latitude / longitude
    # ---- settings ----
    PLACE_DECIMALS = 3  # two tickets are in the same place when their coordinates agree to 3 decimals (about 100 m)

    name = "ticket_count"
    weight = WEIGHTS["ticket_count"]

    def __init__(self):
        self._counts = Counter()

    def _group(self, ticket: Any) -> Optional[tuple]:
        """What makes two tickets the same job: (service type, day, place). None when a part is missing."""
        service = _field(ticket, self.SERVICE_FIELDS)
        opened = _when(_field(ticket, self.OPENED_FIELDS))
        latitude = _number(_field(ticket, self.LATITUDE_FIELDS))
        longitude = _number(_field(ticket, self.LONGITUDE_FIELDS))
        if latitude is not None and longitude is not None:
            place = (round(latitude, self.PLACE_DECIMALS), round(longitude, self.PLACE_DECIMALS))
        else:
            place = _field(ticket, self.POINT_FIELDS)
        if service is None or opened is None or place is None:
            return None
        return _key(service), opened.date(), place

    def fit(self, queue: pd.DataFrame) -> None:
        """Count the queue's tickets per (service type, day, place)."""
        groups = map(self._group, queue.to_dict("records"))
        self._counts = Counter(group for group in groups if group is not None)

    def _explain(self, ticket: Any) -> dict:
        """How many tickets of the queue are the same job as this one (itself included), and the score."""
        count = max(self._counts.get(self._group(ticket), 1), 1)
        return {"same_day_ticket_count": count, "ticket_count_score": get_volume_multiplier(count)}

    def _score(self, ticket: Any) -> float:
        """0.10 for a ticket on its own, up to 1.00 for 7 or more of the same job."""
        return self._explain(ticket)["ticket_count_score"]


# =====================================================================================================
# 7. The total
# =====================================================================================================

class PriorityScorer:
    """priority = sum of weight * score over the components it holds.

    It applies the parent class's ticket rules once, shows each component the queue, then asks each for its score.
    """

    def __init__(self, components: Optional[Iterable[ScoreComponent]] = None):
        default = [BasicKnowledgeScore, GeoScore, AgeScore, TicketCountScore]
        self.components = list(components) if components is not None else [term() for term in default]

    @property
    def weight_covered(self) -> float:
        """Share of the full formula the components add up to (1.0 with all four)."""
        return sum(component.weight for component in self.components)

    def score(self, ticket: Any) -> Optional[float]:
        """The ticket's priority, or None when it fails a rule."""
        return self.breakdown(ticket).get("priority")

    def breakdown(self, ticket: Any) -> dict:
        """Every component's fields plus the total, or {'skipped_because': ...} when the ticket fails a rule."""
        reason = ScoreComponent.skip_reason(ticket)
        return {"skipped_because": reason} if reason else self._breakdown(ticket)

    def _breakdown(self, ticket: Any) -> dict:
        out = {}
        for component in self.components:
            out.update(component._explain(ticket))
        out["priority"] = sum(c.weight * out[f"{c.name}_score"] for c in self.components)
        return out

    def score_frame(self, tickets: pd.DataFrame) -> pd.DataFrame:
        """The tickets that pass the rules, labelled by ticket id, with the breakdown columns added.

        Sort by `priority` to rank. ScoreComponent.skip_reasons(tickets) says why the others were left out.
        """
        queue = ScoreComponent.queue(tickets)
        for component in self.components:
            component.fit(queue)
        columns = list(self._breakdown({}))  # so an empty queue still gets the columns
        rows = [self._breakdown(ticket) for ticket in queue.to_dict("records")]
        return queue.assign(**pd.DataFrame(rows, index=queue.index, columns=columns))


# =====================================================================================================
# 8. Command line
# =====================================================================================================

def _print_keyword_report() -> None:
    """The keywords of the crew service types by tier, with how many types use each."""
    names = AgeScore.load_source()[AgeScore.SERVICE_COL]
    report = keyword_report(names)
    print(f"{len(report)} keywords in {names.nunique()} crew service types (unnecessary words left out)")
    print("No tier yet: " + (", ".join(report.loc[report["tier"].isna(), "keyword"]) or "none"))
    for tier in sorted(CRITICALITY_TIERS, reverse=True):
        part = report[report["tier"] == tier]
        print(f"\n{CRITICALITY_TIERS[tier]['title']}: score {CRITICALITY_TIERS[tier]['multiplier']:.2f}, {len(part)} keywords")
        print(", ".join(f"{keyword} ({uses})" for keyword, uses in zip(part["keyword"], part["service_types"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score and rank open 311 crew jobs.")
    parser.add_argument("tickets", nargs="?", type=Path, default=TICKETS if TICKETS.exists() else SAMPLE,
                        help="ticket CSV (default: open_tickets.csv, or the small sample when that isn't there)")
    parser.add_argument("--out", type=Path, help="save the ranked queue to this CSV")
    parser.add_argument("--keywords", action="store_true", help="print the keyword report and stop")
    args = parser.parse_args()
    if args.keywords:
        _print_keyword_report()
        raise SystemExit

    tickets = pd.read_csv(args.tickets, low_memory=False)
    skipped = ScoreComponent.skip_reasons(tickets)
    scorer = PriorityScorer()
    ranked = scorer.score_frame(tickets)
    ranked = ranked.sort_values(["priority", "open_days"], ascending=False)  # ties: longest open first

    print(f"{args.tickets.name}: {len(tickets):,} tickets")
    for reason, count in skipped[skipped != ""].value_counts().items():
        print(f"  {count:>7,}  skipped: {reason}")
    print(f"  {len(ranked):>7,}  scored")
    names = ", ".join(component.name for component in scorer.components)
    print(f"Scored on: {names} ({scorer.weight_covered:.0%} of the formula)")
    print(f"Fell back to a default: {(~ranked['keyword_found']).sum():,} with no keyword, "
          f"{(~ranked['community_found']).sum():,} with no community, {(~ranked['sla_found']).sum():,} with no SLA\n")
    show = ["service_request_id", "service_name", "comm_code" if "comm_code" in ranked else "comm_name", "open_days",
            "same_day_ticket_count", "basic_knowledge_score", "geo_score", "age_score", "ticket_count_score", "priority"]
    print(ranked[show].head(10).round(2).to_string(index=False))
    if args.out:
        ranked.to_csv(args.out, index=False)
        print(f"\nSaved to: {args.out}")
