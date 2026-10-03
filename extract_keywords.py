import re
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd

DATA = (
    Path(__file__).parent
    / "Case 1 - Autonomous 311 Work-Order Dispatch Agent"
    / "data"
    / "311_service_type_reference.csv"
)
df = pd.read_csv(DATA)

# 1. Unique service names
service_names = df["service_name"].dropna().drop_duplicates()

# 2. Define unnecessary boilerplate to filter out
UNNECESSARY_WORDS = {
    # Conjunctions, prepositions, articles
    "and", "in", "on", "of", "to", "or", "after", "up",
    
    # Generic operational / administrative boilerplate
    "maintenance", "service", "services", "concern", "concerns",
    "issue", "issues", "request", "management", "mgmt", "facility",
    "customer", "care", "centre", "appointment", "new", "internal",
    "checks", "stewardship", "city", "owned", "land", "repair", "repairs",
    
    # Department prefixes (already in agency_responsible column)
    "roads", "parks", "wats", "wrs", "corporate",
    
    # System codes, acronyms, numbers
    "gis", "wam", "cpbs", "cpi", "ct", "gfl", "rsp", "nam", "fmccc", "apt", "bia", "max", "15"
}

# 3. Extract meaningful keyword frequencies
word_service_counts = Counter()

for name in service_names:
    tokens = re.findall(r"[A-Za-z0-9]+", name)
    unique_tokens = set(t.lower() for t in tokens)
    for word in unique_tokens:
        if word not in UNNECESSARY_WORDS:
            word_service_counts[word] += 1

# 4. Municipal Criticality Matrix Mapping (Tiers 4 down to 1)
CRITICALITY_TIERS = {
    4: {
        "title": "TIER 4: Critical Consequence (Safety & Liability)",
        "desc": "Immediate public safety threat, high legal liability, severe hazard",
        "keywords": {
            "ice", "snow", "pothole", "emergency", "fire", "hydrant", "spills",
            "sewage", "break", "leak", "safety", "dead", "animal", "urgent",
            "outage", "damage", "damaged", "seepage", "manhole", "collapse"
        }
    },
    3: {
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
        "title": "TIER 1: Insignificant Consequence (Aesthetic & Routine)",
        "desc": "Cosmetic maintenance, routine landscape stewardship, zero liability",
        "keywords": {
            "mowing", "weed", "greens", "roadside", "boulevard", "irrigation",
            "natural", "area", "cemetery", "playfield", "placement", "inactive",
            "community", "reservoir", "dock", "boat", "storage"
        }
    }
}

# 5. Segregate keywords into Tiers
print(f"Total Unique Service Names: {len(service_names)}")
print(f"Total Meaningful Keywords: {len(word_service_counts)}\n")

for tier_num in [4, 3, 2, 1]:
    tier_info = CRITICALITY_TIERS[tier_num]
    tier_words = [
        (w, word_service_counts.get(w, 0))
        for w in tier_info["keywords"]
        if w in word_service_counts
    ]
    # Sort by frequency descending, then alphabetically
    tier_words.sort(key=lambda x: (-x[1], x[0]))
    
    print("=" * 65)
    print(f"{tier_info['title']} ({len(tier_words)} keywords)")
    print(f"[{tier_info['desc']}]")
    print("=" * 65)
    print(f"{'Keyword':<20}{'Occurrences':<12}")
    print("-" * 32)
    for word, count in tier_words:
        print(f"{word:<20}{count:<12}")
    print()

# 6. Interactive Mock Service Name Classifier Loop
keyword_to_tier = {}
for tier_num, info in CRITICALITY_TIERS.items():
    for kw in info["keywords"]:
        keyword_to_tier[kw] = tier_num


def classify_service(text: str):
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text)]
    matched = [(t, keyword_to_tier[t]) for t in tokens if t in keyword_to_tier]
    
    if not matched:
        return 1, [], "Unmatched (Default Category 1 - Routine / Review)"
    
    # Sort matched tokens by tier descending (highest risk first)
    matched.sort(key=lambda x: -x[1])
    top_tier = matched[0][1]
    return top_tier, matched, CRITICALITY_TIERS[top_tier]["title"]


print("=" * 65)
print("INTERACTIVE SERVICE REQUEST CLASSIFIER")
print("Enter mock service names to test classification. Enter -1 to exit.")
print("=" * 65)

while True:
    try:
        user_prompt = input("\nEnter service_name (or -1 to exit): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nExiting.")
        break

    if user_prompt in ("-1", "exit", "quit"):
        print("Exiting classifier. Goodbye!")
        break
    
    if not user_prompt:
        continue

    assigned_tier, matched_tokens, tier_title = classify_service(user_prompt)
    
    print(f"\n[Result for]: \"{user_prompt}\"")
    print(f" -> Assigned Category: TIER {assigned_tier}")
    print(f" -> Category Title:    {CRITICALITY_TIERS[assigned_tier]['title']}")
    print(f" -> Severity Summary:  {CRITICALITY_TIERS[assigned_tier]['desc']}")
    if matched_tokens:
        matches_str = ", ".join([f"'{w}' (Tier {tier})" for w, tier in matched_tokens])
        print(f" -> Matched Keywords:  {matches_str}")
    else:
        print(f" -> Matched Keywords:  None (No risk keywords detected, defaulted to Tier 1)")
# 