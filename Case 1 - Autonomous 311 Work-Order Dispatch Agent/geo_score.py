"""Geography score for the 311 dispatcher (0.3 to 1.0). Pure functions, no file or table loading.

Method (data/311_service_type_reference_GUIDE.md, 'How geo_score is calculated'):
    resident_density = population_2021 / area_km2
    business_density = business_licences / area_km2
    percentile       = (# communities with a lower density) / (n communities with a value - 1)
    exposure         = max(resident_percentile, business_percentile)
    geo_score        = floor + (1 - floor) * exposure      (no data -> floor)

The caller supplies the community's numbers and the citywide density lists
(from the API, DB or wherever they live).
"""
from bisect import bisect_left
from typing import Iterable, Optional

FLOOR = 0.3


def density(count: Optional[float], area_km2: Optional[float]) -> Optional[float]:
    """Per-km2 density; None when the count or area is missing or zero."""
    if not count or not area_km2 or count <= 0 or area_km2 <= 0:
        return None
    return count / area_km2


def percentile(value: Optional[float], all_values: Iterable[Optional[float]]) -> Optional[float]:
    """Share of the other communities (with a value) that are strictly lower, 0..1."""
    if value is None:
        return None
    vals = sorted(v for v in all_values if v is not None)
    if len(vals) < 2:
        return None
    return bisect_left(vals, value) / (len(vals) - 1)


def geo_score(
    population: Optional[float],
    business_licences: Optional[float],
    area_km2: Optional[float],
    all_resident_densities: Iterable[Optional[float]],
    all_business_densities: Iterable[Optional[float]],
    floor: float = FLOOR,
) -> float:
    """geo_score for one community, 0.3 (floor) to 1.0.

    all_*_densities: densities of every community (include this one), as built by density().
    """
    res_pct = percentile(density(population, area_km2), all_resident_densities)
    biz_pct = percentile(density(business_licences, area_km2), all_business_densities)
    exposure = max((p for p in (res_pct, biz_pct) if p is not None), default=0.0)
    return floor + (1 - floor) * exposure


def geo_score_from_percentiles(
    resident_percentile: Optional[float],
    business_percentile: Optional[float],
    floor: float = FLOOR,
) -> float:
    """Use this if the API already returns the two percentiles (0..1, None if no data)."""
    exposure = max((p for p in (resident_percentile, business_percentile) if p is not None), default=0.0)
    return floor + (1 - floor) * exposure
