"""
ow_utils.py — Old Weather Data Processing Utilities
=====================================================
Master utility module for ingesting, standardizing, and cleaning the
Old Weather citizen-science ship log transcriptions.

Source data: 356 TSV files across 42 US Navy / Coast Guard ships (1859–1955),
organized as Cleaned_L2_Spreadsheets/<ShipName>/Ship_YYYY_Type.tsv

Usage:
    from ow_utils import load_raw, clean, summary

    df_raw = load_raw()          # merge all TSVs into one DataFrame
    df     = clean(df_raw)       # parse datetimes, convert types, flag QC issues
    summary(df)                  # print dataset statistics
"""

import csv
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — update these if the data moves
# ---------------------------------------------------------------------------
DATA_DIR = Path(
    "/project/rcc/users/hdashti/projects/shiplogs/oldweather/Cleaned_L2_Spreadsheets/"
)
OUTPUT_DIR = Path("/project/rcc/users/hdashti/projects/shiplogs/oldweather")

# ---------------------------------------------------------------------------
# Column name mapping
# ---------------------------------------------------------------------------
# The 356 source files use 153 distinct column-name sets.  Most variation is
# cosmetic (e.g. "Orig Lon" vs "Orig_Lon" vs "OrigLon").  This dictionary
# maps every known variant to a single canonical name.

COL_MAP = {
    # Position & time
    "YYYYMMDD": "date",
    "Hour": "hour",
    "Lat": "lat",
    "Long": "lon",
    "Course": "course",
    " Course": "course",  # leading-space variant
    "Distance": "distance",  # numeric = speed/dist; "a" = at anchor
    # Wind (kept as text — cardinal dirs not always converted to degrees)
    "DirM": "wind_dir_mag",
    "DirT": "wind_dir_true",
    "Dir": "wind_dir_mag",
    "Kts": "wind_kts",
    # Pressure
    "Baro": "baro",
    # Temperature
    "Dry": "temp_dry",
    "Wet": "temp_wet",
    "Water": "temp_water",
    "SeaT": "temp_water",  # Burton Island, Omaha, Sacramento
    "Sea": "temp_water",  # Bear 1899-1900
    # Sky & weather
    "Weather": "weather",
    "Clouds": "clouds",
    "Amount": "cloud_amount",  # post-1900: cloud amount (0-10)
    "Clear": "clear_sky",  # pre-1900: clear sky amount (0-10)
    # Metadata & OCR reference
    "Note": "note",  # transcriber notes, port names, events
    "URL_W": "url_w",  # link to NARA scan image (west page)
    # Original transcribed values (useful for OCR validation)
    "Orig Lat": "orig_lat",
    "Orig_Lat": "orig_lat",
    "OrigLat": "orig_lat",
    "jOrig Lat": "orig_lat",  # typo variant in one file
    "Orig Lon": "orig_lon",
    "Orig_Lon": "orig_lon",
    "OrigLon": "orig_lon",
    "Orig Long": "orig_lon",
    "Orig Course": "orig_course",
    "Orig_Course": "orig_course",
    "OrigCourse": "orig_course",
    " Orig Course": "orig_course",  # leading-space variant
}

# Columns to retain in the merged output (drop ice, fauna, refueling, etc.)
KEEP_COLS = list(set(COL_MAP.values())) + ["ship", "source_file"]


# ---------------------------------------------------------------------------
# Load & merge
# ---------------------------------------------------------------------------
def load_raw(data_dir=None):
    """
    Read all TSV files from the Old Weather Cleaned L2 directory,
    standardize column names, and concatenate into a single DataFrame.

    All columns are loaded as strings to avoid type-coercion surprises.

    Known file-level issues handled:
      - Duplicate columns (Omaha_1889_WX, Yantic_1882_WX): dropped
      - Unescaped quotes (Eastwind_1947_Ice): quoting disabled
      - Non-UTF-8 bytes in some files: replaced

    Returns:
        pd.DataFrame with unified column names, all dtypes = object (str)
    """
    base = Path(data_dir) if data_dir else DATA_DIR
    all_dfs = []

    for ship_dir in sorted(base.iterdir()):
        if not ship_dir.is_dir():
            continue
        ship_name = ship_dir.name

        for f in sorted(ship_dir.glob("*.tsv")):
            try:
                df = pd.read_csv(
                    f,
                    sep="\t",
                    dtype=str,
                    encoding="utf-8",
                    encoding_errors="replace",
                    quoting=csv.QUOTE_NONE,  # handles unescaped quotes
                )
                # Drop duplicate columns from source (keep first)
                df = df.loc[:, ~df.columns.duplicated()]

                # Rename to canonical names
                rename = {c: COL_MAP[c] for c in df.columns if c in COL_MAP}
                df.rename(columns=rename, inplace=True)

                # Drop duplicates created by renaming (e.g. Water + Sea → temp_water)
                df = df.loc[:, ~df.columns.duplicated()]

                # Keep only the columns we care about
                df = df[[c for c in KEEP_COLS if c in df.columns]]

                # Add metadata
                df["ship"] = ship_name
                df["source_file"] = f.name
                all_dfs.append(df)

            except Exception as e:
                print(f"ERROR {f.name}: {e}")

    df_all = pd.concat(all_dfs, ignore_index=True)
    print(
        f"Loaded: {len(all_dfs)} files, {len(df_all):,} rows, "
        f"{df_all['ship'].nunique()} ships"
    )
    return df_all


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
def clean(df):
    """
    Clean and type-convert a raw Old Weather DataFrame.

    Steps:
      1. Parse datetime from date + hour columns
         - Navy logs use hours 1–24 where hour 1 = 00:00, hour 24 = 23:00
         - Clock hour = hour - 1
      2. Create at_anchor boolean flag from distance column
         - distance = "a" means ship is in port (68.5% of rows)
      3. Convert numeric columns (lat, lon, baro, temps, wind speed)
         - Course and wind direction kept as text (cardinal notation)
      4. Flag quality issues (suspect data kept, not deleted)
         - temp_dry > 140°F or < -60°F → flagged
         - Coordinate jumps > 100 nm in 1 hour → flagged

    Returns:
        pd.DataFrame with added columns: datetime, at_anchor, speed,
        temp_dry_flag, coord_flag
    """
    df = df.copy()

    # --- 1. Datetime parsing ---
    # Navy log convention: hour 1 = 00:00–01:00, hour 24 = 23:00–00:00
    # So clock_hour = hour - 1
    hour_int = pd.to_numeric(df["hour"], errors="coerce")
    # Only process valid whole hours 1-24
    valid_hour = hour_int.between(1, 24) & (hour_int == hour_int.round(0))
    clock_hour = (hour_int[valid_hour] - 1).astype(int)

    df["datetime"] = pd.NaT
    df.loc[valid_hour, "datetime"] = pd.to_datetime(
        df.loc[valid_hour, "date"] + " " + clock_hour.astype(str).str.zfill(2) + ":00",
        format="%Y-%m-%d %H:%M",
        errors="coerce",
    )

    n_bad_dt = df["datetime"].isna().sum()
    print(f"Datetime: {df['datetime'].notna().sum():,} valid, {n_bad_dt} missing")

    # --- 2. Anchor flag + speed ---
    df["at_anchor"] = df["distance"] == "a"
    df["speed"] = pd.to_numeric(df["distance"], errors="coerce")

    # --- 3. Numeric conversions ---
    # Course and wind direction are intentionally kept as text.
    # With hourly lat/lon we can derive course; original cardinal
    # directions (e.g. "sexe", "nw1/2w") are useful metadata.
    numeric_cols = [
        "lat",
        "lon",
        "baro",
        "temp_dry",
        "temp_wet",
        "temp_water",
        "wind_kts",
        "cloud_amount",
        "clear_sky",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"Lat range:  {df['lat'].min():.1f} to {df['lat'].max():.1f}")
    print(f"Lon range:  {df['lon'].min():.1f} to {df['lon'].max():.1f}")
    print(f"Baro range: {df['baro'].min():.2f} to {df['baro'].max():.2f}")

    # --- 4. Quality flags ---
    # Temperature flags
    df["temp_dry_flag"] = (df["temp_dry"] > 140) | (df["temp_dry"] < -60)
    n_temp_flag = df["temp_dry_flag"].sum()
    print(f"Suspect air temps: {n_temp_flag}")

    # Coordinate jump flags (>100 nm in 1 hour)
    # Process per-ship to avoid sorting the entire DataFrame (memory-safe)
    df["coord_flag"] = False
    for ship, idx in df.groupby("ship").groups.items():
        grp = df.loc[idx].sort_values("datetime")
        lat_diff = grp["lat"].diff()
        lon_diff = grp["lon"].diff()
        # Fix date line wrapping
        lon_diff = lon_diff.where(
            lon_diff.abs() <= 180,
            lon_diff - 360 * (lon_diff / lon_diff.abs()),
        )
        hours_gap = grp["datetime"].diff().dt.total_seconds() / 3600
        jump_nm = ((lat_diff * 60) ** 2 + (lon_diff * 60) ** 2) ** 0.5
        bad = (jump_nm > 100) & (hours_gap <= 1)
        df.loc[bad[bad].index, "coord_flag"] = True

    n_coord_flag = df["coord_flag"].sum()
    print(f"Suspect coord jumps: {n_coord_flag}")

    return df


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def summary(df):
    """Print a comprehensive summary of a cleaned Old Weather DataFrame."""
    print(f"{'=' * 55}")
    print(f"  OLD WEATHER CLEANED DATASET SUMMARY")
    print(f"{'=' * 55}")
    print(f"  Total rows:     {len(df):,}")
    print(f"  Ships:          {df['ship'].nunique()}")
    print(f"  Files:          {df['source_file'].nunique()}")

    dates = df["datetime"].dropna()
    print(f"  Date range:     {dates.min()} to {dates.max()}")

    at_anchor = df["at_anchor"].sum()
    uw_count = len(df) - at_anchor
    print(f"  At anchor:      {at_anchor:,} ({100 * at_anchor / len(df):.1f}%)")
    print(f"  Underway:       {uw_count:,} ({100 * uw_count / len(df):.1f}%)")

    # Quality flags
    if "coord_flag" in df.columns:
        print(f"  Suspect coords: {df['coord_flag'].sum():,}")
    if "temp_dry_flag" in df.columns:
        print(f"  Suspect temps:  {df['temp_dry_flag'].sum()}")

    # Weather coverage
    print(f"\n  Weather coverage (all / underway only):")
    uw = df[~df["at_anchor"]]
    for col, label in [
        ("baro", "Barometer"),
        ("wind_kts", "Wind speed"),
        ("temp_dry", "Air temp"),
        ("temp_wet", "Wet bulb"),
        ("temp_water", "Sea temp"),
        ("weather", "Weather code"),
        ("clouds", "Clouds"),
    ]:
        if col in df.columns:
            # For numeric columns use notna(); for text columns also exclude ""
            if df[col].dtype == "object":
                n_all = df[col].replace("", pd.NA).notna().sum()
                n_uw = uw[col].replace("", pd.NA).notna().sum()
            else:
                n_all = df[col].notna().sum()
                n_uw = uw[col].notna().sum()
            print(
                f"    {label:>14}: {n_all:>10,} ({100 * n_all / len(df):5.1f}%)"
                f"  |  {n_uw:>8,} ({100 * n_uw / len(uw):5.1f}%)"
            )

    print(f"\n  Top 10 ships by underway rows:")
    uw_counts = uw.groupby("ship").size().sort_values(ascending=False)
    for ship, n in uw_counts.head(10).items():
        if "temp_water" in uw.columns:
            sst = uw[uw["ship"] == ship]["temp_water"].notna().sum()
            print(f"    {ship:>20}: {n:>7,} rows, SST {100 * sst / n:.0f}%")
        else:
            print(f"    {ship:>20}: {n:>7,} rows")


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------
def save_parquet(df, filename="oldweather_cleaned.parquet", output_dir=None):
    """Save DataFrame to parquet and print file size."""
    out = Path(output_dir) if output_dir else OUTPUT_DIR
    path = out / filename
    df.to_parquet(path, index=False)
    size_mb = path.stat().st_size / 1e6
    print(f"Saved: {path} ({size_mb:.1f} MB)")
    return path


def load_parquet(filename="oldweather_cleaned.parquet", output_dir=None):
    """Load a previously saved parquet file."""
    out = Path(output_dir) if output_dir else OUTPUT_DIR
    path = out / filename
    df = pd.read_parquet(path)
    print(f"Loaded: {path} ({len(df):,} rows)")
    return df
