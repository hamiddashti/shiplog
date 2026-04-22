# Old Weather Cleaned Dataset

## What is this?

Hourly ship log observations from 42 US Navy and Coast Guard vessels (1859–1955), transcribed by citizen-science volunteers in the Old Weather project. Contains position, weather, sea conditions, ice observations, and wildlife sightings recorded by officers on watch.

- **2,051,185 rows** (hourly observations)
- **42 ships**, 356 source files
- **1859–1955** coverage
- 68.5% at anchor, 31.5% underway
- ~322K sea surface temperature observations when underway

## Files

| File | Description |
|---|---|
| `oldweather_cleaned.parquet` | Cleaned dataset |
| `merged_raw.parquet` | Pre-cleaning merged dataset (all strings) |
| `Cleaned_L2_Spreadsheets/` | Original 356 TSV files by ship |

## Columns

### Position & time
| Column | Type | Description |
|---|---|---|
| `date` | str | Log date (YYYY-MM-DD) |
| `hour` | str | Log hour (1–24, where 1 = midnight–1am, 24 = 11pm–midnight) |
| `datetime` | datetime | Parsed timestamp (hour 1 → 00:00, hour 24 → 23:00) |
| `lat` | float | Latitude (decimal degrees, -78.5 to 82.7) |
| `lon` | float | Longitude (decimal degrees, -180 to 180) |
| `course` | str | Ship course — degrees or cardinal text (e.g. "sexe", "nw1/2w", "v" = variable) |
| `distance` | str | "a" = at anchor; numeric = speed/distance underway |
| `speed` | float | Numeric speed (NaN when at anchor) |
| `at_anchor` | bool | True = ship in port |

### Weather observations
| Column | Type | Description |
|---|---|---|
| `baro` | float | Barometric pressure (inches of mercury, 27–32 range) |
| `temp_dry` | float | Dry bulb air temperature (°F assumed) |
| `temp_wet` | float | Wet bulb temperature (°F assumed) |
| `temp_water` | float | Sea surface temperature (°F assumed) |
| `wind_dir_mag` | str | Wind direction magnetic (degrees or cardinal text) |
| `wind_dir_true` | str | Wind direction true (degrees or cardinal text) |
| `wind_kts` | float | Wind speed (knots) |
| `weather` | str | Weather code (e.g. "bc" = broken clouds, "ocr" = overcast rain) |
| `clouds` | str | Cloud type description |
| `cloud_amount` | float | Cloud cover 0–10 (post-1900 files only) |
| `clear_sky` | float | Clear sky amount 0–10 (pre-1900 files only) |

### Ice observations
| Column | Type | Description |
|---|---|---|
| `ice_log` | str | Ice log entry indicator (354 files) |
| `ice_1` | str | Primary ice observation (337 files) |
| `ice_2` | str | Secondary ice observation (337 files) |
| `ice_index` | str | Ice index value (7 files) |
| `ice_terms` | str | Ice terminology notes (7 files) |

### People, flora & fauna
| Column | Type | Description |
|---|---|---|
| `people` | str | People encountered or crew events (163 files) |
| `flora_fauna` | str | Wildlife and plant sightings (75 files) |
| `animals` | str | Animal sightings (4 files) |

### Metadata
| Column | Type | Description |
|---|---|---|
| `ship` | str | Ship name |
| `source_file` | str | Original TSV filename |
| `note` | str | Transcriber notes, port names, events |
| `url_w` | str | URL to original NARA scan image |
| `orig_lat` | str | Raw transcribed latitude (for OCR validation) |
| `orig_lon` | str | Raw transcribed longitude |
| `orig_course` | str | Raw transcribed course |

### Quality flags
| Column | Type | Description |
|---|---|---|
| `temp_dry_flag` | bool | True if air temp suspect (>140°F or <-60°F) — 1 row |
| `coord_flag` | bool | True if position jump >100 nm in 1 hour — 479 rows |

## Cleaning applied

1. **Schema standardization** — 153 column-name variants across files mapped to canonical names
2. **Datetime parsing** — Navy hours 1–24 converted to clock time (hour - 1). 22 rows unparseable out of 2M
3. **Numeric conversion** — lat, lon, baro, temps, wind speed converted to float. Course and wind direction kept as text (cardinal notation not fully converted in all files)
4. **Anchor detection** — `distance = "a"` flagged as at_anchor
5. **Quality flagging** — suspect values flagged, not deleted (480 total flags out of 2M rows)
6. **Missing columns** — files that lack certain columns (e.g. ice, people, flora_fauna) have NaN for those fields

## Notes

- **Temperature units are assumed °F** — not explicitly documented in the source, inferred from US Navy context and value ranges
- **888 in wind columns** = calm / variable wind
- **Date line crossings** — ships near 180° longitude wrap between +179 and -179. Real, not errors
- **Prior QC** — data was already cleaned by the Old Weather team before we received it (barometer checked against scan images, winds converted from Beaufort to knots, magnetic to true)
- **Ice data** — many ships were Arctic/Antarctic patrol vessels (Bear, Storis, Eastwind, Northwind, etc.). Ice columns are populated primarily for these ships
- **Flora/fauna split** — most wildlife sightings are in `flora_fauna` (75 files); `animals` is a separate column used in only 4 files