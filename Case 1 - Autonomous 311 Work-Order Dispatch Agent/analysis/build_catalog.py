"""Build service-name and agency catalogs from the FULL 311 export (read straight from the zip).

Note: the 245 MB CSV at the repo root is truncated at 1,048,575 rows (Excel's row limit).
The zip holds all ~1.94M rows - always load from the zip.

Run from this case folder:  python analysis/build_catalog.py
"""
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
ZIP = HERE.parent / "data" / "311_Service_Requests_20261002.zip"
AS_OF = pd.Timestamp("2026-10-02")
COLS = ["service_request_id", "requested_date", "closed_date", "status_description",
        "service_name", "agency_responsible", "comm_code", "comm_name", "latitude"]
CATS = ["status_description", "service_name", "agency_responsible", "comm_code", "comm_name"]
FMT = "%Y/%m/%d %I:%M:%S %p"


def load() -> pd.DataFrame:
    with zipfile.ZipFile(ZIP) as z, z.open(z.namelist()[0]) as f:
        parts = []
        for ch in pd.read_csv(f, usecols=COLS, dtype=str, chunksize=500_000):
            for c in CATS:
                ch[c] = ch[c].astype("category")
            ch["requested_date"] = pd.to_datetime(ch["requested_date"], format=FMT)
            ch["closed_date"] = pd.to_datetime(ch["closed_date"], format=FMT, errors="coerce")
            ch["latitude"] = pd.to_numeric(ch["latitude"], errors="coerce")
            parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    for c in CATS:
        df[c] = df[c].astype("category")
    df["days_to_close"] = (df["closed_date"] - df["requested_date"]).dt.days
    df["is_open"] = df["status_description"].eq("Open")
    df["is_open_60d"] = df["is_open"] & (df["requested_date"] >= AS_OF - pd.Timedelta(days=60))
    df["is_2026"] = df["requested_date"].dt.year.eq(2026)
    return df


def variants(s: pd.Series) -> str:
    vc = s.value_counts()
    vc = vc[vc > 0]
    return " | ".join(f"{k} ({v})" for k, v in vc.items())


def service_catalog(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("service_name", observed=True)
    closed = df[df["status_description"].eq("Closed")].groupby("service_name", observed=True)["days_to_close"]
    latest = df.sort_values("requested_date").groupby("service_name", observed=True)["agency_responsible"].last()
    out = pd.DataFrame({
        "category_prefix": g.size().index.astype(str).str.split(" - ").str[0],
        "agency_current": latest.astype(str),
        "total_requests": g.size(),
        "requests_2026": g["is_2026"].sum(),
        "open_now": g["is_open"].sum(),
        "open_last_60d": g["is_open_60d"].sum(),
        "pct_with_location": (g["latitude"].apply(lambda s: s.notna().mean()) * 100).round(1),
        "median_days_to_close": closed.median(),
        "p90_days_to_close": closed.quantile(0.9).round(0),
        "first_seen": g["requested_date"].min().dt.date,
        "last_seen": g["requested_date"].max().dt.date,
        "agency_variants": g["agency_responsible"].apply(variants),
    })
    out.index.name = "service_name"
    return out.sort_values(["category_prefix", "total_requests"], ascending=[True, False])


def agency_catalog(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("agency_responsible", observed=True)
    top = g["service_name"].apply(lambda s: " | ".join(s.value_counts().head(3).index.astype(str)))
    out = pd.DataFrame({
        "dept_code": g.size().index.astype(str).str.split(" - ").str[0],
        "total_requests": g.size(),
        "requests_2026": g["is_2026"].sum(),
        "open_now": g["is_open"].sum(),
        "n_service_names": g["service_name"].nunique(),
        "first_seen": g["requested_date"].min().dt.date,
        "last_seen": g["requested_date"].max().dt.date,
        "top_service_names": top,
    })
    out.index.name = "agency_responsible"
    return out.sort_values("total_requests", ascending=False)


def main():
    df = load()
    svc, agy = service_catalog(df), agency_catalog(df)
    svc.to_csv(HERE / "service_catalog.csv")
    agy.to_csv(HERE / "agency_catalog.csv")
    print(f"rows={len(df):,}  service_names={len(svc)}  agencies={len(agy)}  open={int(df['is_open'].sum()):,}")


if __name__ == "__main__":
    main()
