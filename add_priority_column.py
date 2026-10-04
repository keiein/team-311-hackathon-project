import re
from pathlib import Path
import pandas as pd

# Primary open tickets dataset
DATA = Path(__file__).parent / "databricks" / "data" / "open_tickets.csv"

# Municipal Criticality Matrix Mapping with Associated Multipliers
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

# Inverted keyword lookup map for O(1) tier resolution
KEYWORD_TO_TIER = {
    kw: tier_num
    for tier_num, info in CRITICALITY_TIERS.items()
    for kw in info["keywords"]
}


def get_criticality_multiplier(service_name: str) -> float:
    """
    Inputs a service_name string and returns its float multiplier
    based strictly on keyword criticality:
      - Tier 4 (Critical Consequence - Safety & Liability):       1.00
      - Tier 3 (Major Consequence - Operational Disruption):      0.70
      - Tier 2 (Moderate Consequence - Nuisance & Sanitation):    0.40
      - Tier 1 (Insignificant Consequence - Aesthetic & Routine): 0.10
    """
    if not isinstance(service_name, str):
        return 0.10

    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", service_name)]
    matched_tiers = [KEYWORD_TO_TIER[t] for t in tokens if t in KEYWORD_TO_TIER]

    if not matched_tiers:
        return 0.10

    # Highest consequence tier takes precedence
    top_tier = max(matched_tiers)
    return CRITICALITY_TIERS[top_tier]["multiplier"]


def get_criticality_details(service_name: str):
    """
    Helper function returning detailed breakdown for a service_name:
    (multiplier, tier_number, matched_tokens_list, tier_title)
    """
    if not isinstance(service_name, str):
        return 0.10, 1, [], CRITICALITY_TIERS[1]["title"]

    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", service_name)]
    matched = [(t, KEYWORD_TO_TIER[t]) for t in tokens if t in KEYWORD_TO_TIER]

    if not matched:
        return 0.10, 1, [], "Unmatched (Default Tier 1)"

    matched.sort(key=lambda x: -x[1])
    top_tier = matched[0][1]
    multiplier = CRITICALITY_TIERS[top_tier]["multiplier"]
    title = CRITICALITY_TIERS[top_tier]["title"]
    return multiplier, top_tier, matched, title



def get_volume_multiplier(count: int) -> float:
    """
    Returns the fixed constant multiplier based on the number of tickets:
      - 1 ticket:     0.10
      - 2 tickets:    0.20
      - 3 tickets:    0.35
      - 4-6 tickets:  0.70
      - 6+ tickets:   1.00
    """
    if count is None or count <= 1:
        return 0.10
    elif count == 2:
        return 0.20
    elif count == 3:
        return 0.35
    elif 4 <= count <= 6:
        return 0.70
    else:  # 6+ tickets
        return 1.00


def check_ticket_count(
    df: pd.DataFrame,
    service_name: str,
    requested_date: str,
    point: str = None,
) -> float:
    """
    Checks the dataset for the number of same-day duplicate tickets
    (multiple citizens reporting the same issue at the same location on the same date),
    and returns its fixed constant volume multiplier.
    """
    mask = (df["service_name"] == service_name) & (df["requested_date"] == requested_date)
    if point and pd.notnull(point):
        mask &= (df["point"] == point)

    match_count = len(df[mask])
    count = max(match_count, 1)
    return get_volume_multiplier(count)


def add_volume_multiplier_column(
    df: pd.DataFrame,
    use_coordinate_rounding: bool = True,
) -> pd.DataFrame:
    """
    Calculates multipliers based strictly on same-day duplicates:
    Groups by requested_date, location, and service_name.
    
    If use_coordinate_rounding is True, rounds latitude/longitude to 3 decimals (~100m)
    to catch near-duplicate reports at the same intersection/block.
    Otherwise, groups by exact point string match.
    """
    if use_coordinate_rounding and "latitude" in df.columns and "longitude" in df.columns:
        lat_bin = df["latitude"].round(3)
        lon_bin = df["longitude"].round(3)
        counts = df.groupby(
            ["requested_date", lat_bin, lon_bin, "service_name"]
        )["service_request_id"].transform("count")
    else:
        counts = df.groupby(
            ["requested_date", "point", "service_name"]
        )["service_request_id"].transform("count")

    # Store same-day duplicate count and constant multiplier
    df["same_day_ticket_count"] = counts.fillna(1).astype(int)
    df["volume_multiplier"] = df["same_day_ticket_count"].map(get_volume_multiplier)
    return df


def interactive_testing():
    """
    Endless interactive loop to test mock service_name strings and ticket counts,
    displaying their keyword-based criticality multiplier and volume multiplier until user inputs -1.
    """
    print("=" * 70)
    print("311 MULTIPLIER TESTER (Criticality + Volume)")
    print("Criticality Tiers: 4: 1.00 | 3: 0.70 | 2: 0.40 | 1: 0.10")
    print("Volume Multiplier: 1: 0.10 | 2: 0.20 | 3: 0.35 | 4-6: 0.70 | 6+: 1.00")
    print("Enter -1 to exit.")
    print("=" * 70)

    while True:
        try:
            user_prompt = input("\nEnter service_name (or -1 to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if user_prompt in ("-1", "exit", "quit"):
            print("Exiting tester. Goodbye!")
            break

        if not user_prompt:
            continue

        vol_in = input("Enter number of clustered tickets (default 1): ").strip()
        if vol_in in ("-1", "exit"):
            break
        ticket_count = int(vol_in) if vol_in and vol_in.isdigit() else 1

        crit_mult, tier_num, matched, title = get_criticality_details(user_prompt)
        vol_mult = get_volume_multiplier(ticket_count)
        composite_score = round(crit_mult * vol_mult * 100, 2)

        print(f"\n[Result for]: \"{user_prompt}\" (Clustered count: {ticket_count})")
        print(f" -> Criticality Multiplier: {crit_mult:.2f}  (Tier {tier_num} - {title})")
        print(f" -> Volume Multiplier:      {vol_mult:.2f}  ({ticket_count} tickets)")
        print(f" -> Combined Score Factor:  {composite_score:.2f} / 100.00")
        if matched:
            matches_str = ", ".join([f"'{w}' (Tier {t})" for w, t in matched])
            print(f" -> Matched Keywords:      {matches_str}")
        else:
            print(f" -> Matched Keywords:      None (Defaulted to Tier 1)")


if __name__ == "__main__":
    interactive_testing()
