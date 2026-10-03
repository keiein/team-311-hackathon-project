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
            "outage", "damage", "damaged", "seepage", "manhole", "collapse"
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
            "community", "reservoir", "dock", "boat", "storage"
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


def score_open_tickets(csv_path: Path = DATA, top_n: int = 15):
    """
    Loads open_tickets.csv and adds the keyword-based criticality_multiplier
    to each ticket based on its service_name.
    """
    print(f"\nLoading dataset from: {csv_path} ...")
    df = pd.read_csv(csv_path)

    # Calculate criticality multiplier using only service_name keywords
    df["criticality_multiplier"] = df["service_name"].map(get_criticality_multiplier)

    print("=" * 80)
    print(f"SAMPLE SCORED TICKETS (from {len(df):,} total open tickets)")
    print("=" * 80)

    display_cols = ["service_request_id", "service_name", "criticality_multiplier"]
    sample_df = df[display_cols].drop_duplicates(subset=["service_name"]).head(top_n)
    print(sample_df.to_string(index=False))

    print("\nSummary Distribution of Criticality Multipliers in Dataset:")
    counts = df["criticality_multiplier"].value_counts().sort_index(ascending=False)
    for mult, count in counts.items():
        print(f" -> Multiplier {mult:.2f}: {count:>6,} tickets ({count/len(df)*100:.1f}%)")

    return df


def interactive_testing():
    """
    Endless interactive loop to test mock service_name strings
    and display their keyword-based criticality multiplier until user inputs -1.
    """
    print("=" * 65)
    print("311 KEYWORD CRITICALITY MULTIPLIER")
    print("Tier 4: 1.00 | Tier 3: 0.70 | Tier 2: 0.40 | Tier 1: 0.10")
    print("Type 'load' to score open_tickets.csv, or -1 to exit.")
    print("=" * 65)

    while True:
        try:
            user_prompt = input("\nEnter service_name (or 'load', -1 to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if user_prompt in ("-1", "exit", "quit"):
            print("Exiting tester. Goodbye!")
            break

        if not user_prompt:
            continue

        if user_prompt.lower() == "load":
            score_open_tickets()
            continue

        multiplier, tier_num, matched, title = get_criticality_details(user_prompt)

        print(f"\n[Result for]: \"{user_prompt}\"")
        print(f" -> Criticality Multiplier: {multiplier:.2f}")
        print(f" -> Category:              Tier {tier_num} ({title})")
        if matched:
            matches_str = ", ".join([f"'{w}' (Tier {t})" for w, t in matched])
            print(f" -> Matched Keywords:      {matches_str}")
        else:
            print(f" -> Matched Keywords:      None (Defaulted to Tier 1)")


if __name__ == "__main__":
    interactive_testing()
