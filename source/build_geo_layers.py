"""Build geo layers for Old Weather ship log data.

Outputs (in /project/rcc/users/hdashti/projects/shiplogs/oldweather/geo/):
    points/<Ship>_points.{parquet,geojson}   — one file per ship
    tracks/<Ship>_tracks.{parquet,geojson}   — one file per ship
    all_points.{parquet,geojson}             — combined across all ships
    all_tracks.{parquet,geojson}             — combined across all ships
    manifest.json                            — per-ship metadata
"""

import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString
import json
import os
import time

SRC = "/project/rcc/users/hdashti/projects/shiplogs/oldweather/oldweather_clean/oldweather_cleaned_dedup.parquet"
OUT_DIR = "/project/rcc/users/hdashti/projects/shiplogs/oldweather/geo"
PTS_DIR = f"{OUT_DIR}/points"
TRK_DIR = f"{OUT_DIR}/tracks"
os.makedirs(PTS_DIR, exist_ok=True)
os.makedirs(TRK_DIR, exist_ok=True)

PROPS = [
    "ship",
    "date",
    "hour",
    "datetime",
    "at_anchor",
    "speed",
    "course",
    "baro",
    "temp_dry",
    "temp_wet",
    "temp_water",
    "wind_kts",
    "wind_dir_true",
    "wind_dir_mag",
    "weather",
    "clouds",
    "clear_sky",
    "note",
    "url_w",
    "coord_flag",
    "temp_dry_flag",
]


def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def build_tracks(df_ship):
    """Segment underway rows into LineStrings. Returns GeoDataFrame."""
    t = df_ship.sort_values("datetime").reset_index(drop=True).copy()
    t["dlon"] = t["lon"].diff().abs()
    t["dt_hours"] = t["datetime"].diff().dt.total_seconds() / 3600

    new_segment = (
        (t.index == 0)
        | t["at_anchor"]
        | t["at_anchor"].shift(1).fillna(False)
        | t["coord_flag"]
        | t["coord_flag"].shift(1).fillna(False)
        | (t["dlon"] > 180)
        | (t["dt_hours"] > 6)
        | (t["dt_hours"] <= 0)
    )
    t["segment_id"] = new_segment.cumsum()
    underway = t[~t["at_anchor"]].copy()

    tracks = []
    for seg_id, g in underway.groupby("segment_id"):
        if len(g) < 2:
            continue
        g = g.sort_values("datetime")
        coords = list(zip(g["lon"], g["lat"]))
        dists = haversine_nm(
            g["lat"].shift(1), g["lon"].shift(1), g["lat"], g["lon"]
        ).dropna()
        tracks.append(
            {
                "ship": g["ship"].iloc[0],
                "segment_id": int(seg_id),
                "start_time": g["datetime"].iloc[0].strftime("%Y-%m-%dT%H:%M:%S"),
                "end_time": g["datetime"].iloc[-1].strftime("%Y-%m-%dT%H:%M:%S"),
                "n_points": int(len(g)),
                "distance_nm": round(float(dists.sum()), 2),
                "geometry": LineString(coords),
            }
        )
    if not tracks:
        return gpd.GeoDataFrame(
            columns=[
                "ship",
                "segment_id",
                "start_time",
                "end_time",
                "n_points",
                "distance_nm",
                "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )
    return gpd.GeoDataFrame(tracks, crs="EPSG:4326")


# ============================================================
print(f"Loading {SRC}...")
df = pd.read_parquet(SRC)
ships = sorted(df["ship"].unique())
print(f"Loaded {len(df):,} rows, {len(ships)} ships\n")

manifest = {"ships": []}
all_points_gdfs = []
all_tracks_gdfs = []
t0 = time.time()

for i, ship in enumerate(ships, 1):
    s = df[df["ship"] == ship].copy()
    s_geo = s.dropna(subset=["lat", "lon"]).copy()
    n_with_coords = len(s_geo)
    n_without = len(s) - n_with_coords

    if n_with_coords == 0:
        print(f"[{i:2d}/{len(ships)}] {ship}: SKIPPED (no coords)")
        continue

    # --- Points ---
    pts_gdf = gpd.GeoDataFrame(
        s_geo[PROPS].copy(),
        geometry=gpd.points_from_xy(s_geo["lon"], s_geo["lat"]),
        crs="EPSG:4326",
    )
    pts_parquet = f"{PTS_DIR}/{ship}_points.parquet"
    pts_gdf.to_parquet(pts_parquet)

    pts_json_gdf = pts_gdf.copy()
    pts_json_gdf["datetime"] = pts_json_gdf["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    pts_geojson = f"{PTS_DIR}/{ship}_points.geojson"
    pts_json_gdf.to_file(pts_geojson, driver="GeoJSON")

    # Collect for combined file (use string-datetime version)
    all_points_gdfs.append(pts_json_gdf)

    # --- Tracks ---
    trk_gdf = build_tracks(s_geo)
    trk_parquet = f"{TRK_DIR}/{ship}_tracks.parquet"
    trk_geojson = f"{TRK_DIR}/{ship}_tracks.geojson"
    if len(trk_gdf) > 0:
        trk_gdf.to_parquet(trk_parquet)
        trk_gdf.to_file(trk_geojson, driver="GeoJSON")
        all_tracks_gdfs.append(trk_gdf)

    # --- Manifest entry ---
    bounds = pts_gdf.total_bounds
    manifest["ships"].append(
        {
            "ship": ship,
            "n_points": int(n_with_coords),
            "n_dropped_no_coords": int(n_without),
            "n_anchored": int(s_geo["at_anchor"].sum()),
            "n_underway": int((~s_geo["at_anchor"]).sum()),
            "start_date": s_geo["datetime"].min().strftime("%Y-%m-%d"),
            "end_date": s_geo["datetime"].max().strftime("%Y-%m-%d"),
            "years": sorted(s_geo["datetime"].dt.year.unique().tolist()),
            "bounds": [round(float(b), 4) for b in bounds],
            "n_track_segments": int(len(trk_gdf)),
            "total_track_nm": round(float(trk_gdf["distance_nm"].sum()), 1)
            if len(trk_gdf)
            else 0.0,
            "n_coord_flags": int(s_geo["coord_flag"].sum()),
            "pts_geojson_kb": round(os.path.getsize(pts_geojson) / 1024, 1),
            "pts_parquet_kb": round(os.path.getsize(pts_parquet) / 1024, 1),
        }
    )

    elapsed = time.time() - t0
    print(
        f"[{i:2d}/{len(ships)}] {ship:15s} "
        f"pts={n_with_coords:>7,}  segs={len(trk_gdf):>4}  "
        f"geojson={manifest['ships'][-1]['pts_geojson_kb']:>8,.1f} KB  "
        f"({elapsed:.1f}s)"
    )

# ============================================================
# Combined outputs
# ============================================================
print("\nBuilding combined files...")

all_points = gpd.GeoDataFrame(
    pd.concat(all_points_gdfs, ignore_index=True), crs="EPSG:4326"
)
# parquet wants datetime back as native type; keep geojson as string
all_points_parquet = f"{OUT_DIR}/all_points.parquet"
all_points_pq = all_points.copy()
all_points_pq["datetime"] = pd.to_datetime(all_points_pq["datetime"])
all_points_pq.to_parquet(all_points_parquet)
print(
    f"  all_points.parquet:  {os.path.getsize(all_points_parquet) / 1024 / 1024:>7.1f} MB  ({len(all_points):,} features)"
)

all_points_geojson = f"{OUT_DIR}/all_points.geojson"
all_points.to_file(all_points_geojson, driver="GeoJSON")
print(
    f"  all_points.geojson:  {os.path.getsize(all_points_geojson) / 1024 / 1024:>7.1f} MB"
)

all_tracks = gpd.GeoDataFrame(
    pd.concat(all_tracks_gdfs, ignore_index=True), crs="EPSG:4326"
)
all_tracks_parquet = f"{OUT_DIR}/all_tracks.parquet"
all_tracks.to_parquet(all_tracks_parquet)
print(
    f"  all_tracks.parquet:  {os.path.getsize(all_tracks_parquet) / 1024 / 1024:>7.1f} MB  ({len(all_tracks):,} features)"
)

all_tracks_geojson = f"{OUT_DIR}/all_tracks.geojson"
all_tracks.to_file(all_tracks_geojson, driver="GeoJSON")
print(
    f"  all_tracks.geojson:  {os.path.getsize(all_tracks_geojson) / 1024 / 1024:>7.1f} MB"
)

# --- Manifest ---
manifest_path = f"{OUT_DIR}/manifest.json"
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"\n{'=' * 60}")
print(f"DONE in {time.time() - t0:.1f}s")
print(f"Manifest: {manifest_path}")

total_pts_gj = sum(s["pts_geojson_kb"] for s in manifest["ships"]) / 1024
total_pts_pq = sum(s["pts_parquet_kb"] for s in manifest["ships"]) / 1024
print(
    f"\nPer-ship totals — GeoJSON: {total_pts_gj:.1f} MB  GeoParquet: {total_pts_pq:.1f} MB"
)
