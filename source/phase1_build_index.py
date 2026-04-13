#!/usr/bin/env python3
"""
Phase 1 - Parse NARA RG 24 catalog into master_index.csv
Reads all .jsonl files in rg_24/, filters for ship log series
(581208 and 594258), extracts fields, writes CSV.
"""

import os
import json
import csv
import re
import time

# ── Config ──
CATALOG_DIR = "/project/rcc/users/hdashti/projects/shiplogs/catalog/rg_24"
OUTPUT_DIR = "/project/rcc/users/hdashti/projects/shiplogs/index"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "master_index.csv")
TARGET_SERIES = {581208, 594258}

# ── Title parsing (adapted from to_csv.py) ──

MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def get_ship_name(title):
    name = title
    idx = name.find(":")
    if idx > 0:
        name = name[:idx]
    idx = name.find("(")
    if idx > 0:
        name = name[:idx]
    rx = re.search(r"\d+/\d+/", name)
    if rx:
        name = name[: rx.span()[0]]
    rx = re.search(r"- \w+ \d{4}/", name)
    if rx:
        name = name[: rx.span()[0]]
    idx = name.find(" of the ")
    if idx > 0:
        name = name[idx + 8 :]
    idx = name.find(" of ")
    if idx > 0:
        name = name[idx + 4 :]
    idx = name.find("U.S.S.")
    if idx > -1:
        name = "USS " + name[idx + 6 :]
    # Clean up trailing commas, extra spaces
    name = re.sub(r"\s+", " ", name).strip().rstrip(",").strip()
    return name


def get_hull_number(title):
    # First try parenthesized form: (DD-119)
    rx = re.search(r"\((\w+-\d+)\)", title)
    if rx:
        return rx.group(1)
    # Then try hull-number-as-name: "LSM-175 - April 1951"
    rx = re.match(r"^([A-Z]+-\d+)\b", title.strip())
    if rx:
        return rx.group(1)
    return None


# ── Date parsing from title (fallback) ──


def parse_date_from_title(title):
    """Extract (start_date, end_date) from title string. Returns (str, str) or (None, None)."""
    # Try mm/dd/yyyy - mm/dd/yyyy
    rx = re.search(r"(\d+)/(\d+)/(\d+)\s*-\s*(\d+)/(\d+)/(\d+)", title)
    if rx:
        g = rx.groups()
        start = f"{int(g[2]):04d}-{int(g[0]):02d}-{int(g[1]):02d}"
        end = f"{int(g[5]):04d}-{int(g[3]):02d}-{int(g[4]):02d}"
        return start, end
    # Try "Month YYYY" pattern
    rx = re.search(r"- (\w+) (\d{4})", title)
    if rx:
        month_str, year_str = rx.group(1).lower(), int(rx.group(2))
        for i, mn in enumerate(MONTH_NAMES):
            if mn == month_str:
                from calendar import monthrange

                m = i + 1
                start = f"{year_str:04d}-{m:02d}-01"
                end = f"{year_str:04d}-{m:02d}-{monthrange(year_str, m)[1]:02d}"
                return start, end
    return None, None


# ── Field extraction ──


def get_series_naid(record):
    for ancestor in record.get("ancestors", []):
        if ancestor.get("levelOfDescription") == "series":
            return ancestor.get("naId")
    return None


def get_date(date_dict):
    if not date_dict:
        return None
    if "logicalDate" in date_dict:
        return date_dict["logicalDate"]
    y = date_dict.get("year")
    m = date_dict.get("month", 1)
    d = date_dict.get("day", 1)
    return f"{y:04d}-{m:02d}-{d:02d}" if y else None


def get_dates(record):
    """Get start and end dates, falling back to title parsing."""
    start = get_date(record.get("coverageStartDate"))
    end = get_date(record.get("coverageEndDate"))
    if not start or not end:
        t_start, t_end = parse_date_from_title(record.get("title", ""))
        start = start or t_start
        end = end or t_end
    return start, end


def get_container_id(record):
    for po in record.get("physicalOccurrences", []):
        for mo in po.get("mediaOccurrences", []):
            cid = mo.get("containerId")
            if cid:
                return cid
    return None


def get_pdf_url(record):
    for obj in record.get("digitalObjects", []):
        url = obj.get("objectUrl", "")
        if url.lower().endswith(".pdf"):
            return url
    return None


def get_image_count(record):
    count = 0
    for obj in record.get("digitalObjects", []):
        url = obj.get("objectUrl", "")
        if not url.lower().endswith(".pdf"):
            count += 1
    return count


# ── Main ──


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    files = sorted(os.listdir(CATALOG_DIR))
    print(f"Found {len(files)} jsonl files in {CATALOG_DIR}")

    fieldnames = [
        "ship_name",
        "hull_number",
        "record_group",
        "series_naid",
        "naid",
        "container",
        "start_date",
        "end_date",
        "nara_url",
        "n_images",
        "pdf_url",
    ]

    total = 0
    skipped = 0
    errors = 0
    t0 = time.time()

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for fi, fname in enumerate(files):
            fpath = os.path.join(CATALOG_DIR, fname)
            file_count = 0

            with open(fpath, "r") as jf:
                for line_num, line in enumerate(jf):
                    try:
                        rec = json.loads(line)["record"]
                    except Exception:
                        errors += 1
                        continue

                    series = get_series_naid(rec)
                    if series not in TARGET_SERIES:
                        skipped += 1
                        continue

                    title = rec.get("title", "")
                    start_date, end_date = get_dates(rec)

                    writer.writerow(
                        {
                            "ship_name": get_ship_name(title),
                            "hull_number": get_hull_number(title),
                            "record_group": 24,
                            "series_naid": series,
                            "naid": rec.get("naId"),
                            "container": get_container_id(rec),
                            "start_date": start_date,
                            "end_date": end_date,
                            "nara_url": f"https://catalog.archives.gov/id/{rec.get('naId')}",
                            "n_images": get_image_count(rec),
                            "pdf_url": get_pdf_url(rec),
                        }
                    )
                    file_count += 1
                    total += 1

            elapsed = time.time() - t0
            print(
                f"  [{fi + 1}/{len(files)}] {fname}: {file_count} ship logs found ({elapsed:.0f}s elapsed)"
            )

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  Ship log records: {total}")
    print(f"  Skipped (other series): {skipped}")
    print(f"  Parse errors: {errors}")
    print(f"  Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
