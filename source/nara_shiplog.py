"""
nara_shiplog.py
===============
All functions for downloading Navy ship logs from the NARA Catalog API.

Usage: import this module in a Jupyter notebook or script.

    from nara_shiplog import *
    
    setup("nara_key.txt")
    index = build_index()
    result = download_record(169781174, "Log of U.S.S. SEMINOLE")
"""

import os
import json
import csv
import time
import re
import requests
from pathlib import Path

# ---- Global config ----
BASE_URL = "https://catalog.archives.gov"
HEADERS = {}
API_DELAY = 1.0
DOWNLOAD_DELAY = 0.3
OUTPUT_DIR = Path("shiplog_downloads")


def setup(key_file="nara_key.txt"):
    """Load API key and set up headers."""
    global HEADERS
    key = open(key_file).read().strip()
    HEADERS = {
        "Content-Type": "application/json",
        "x-api-key": key,
    }
    print(f"API key loaded from {key_file}")


# ==========================================================
# INDEX FUNCTIONS
# ==========================================================

def fetch_index_page(query, offset, limit=100):
    """Fetch one page of search results from NARA API."""
    url = (
        f"{BASE_URL}/api/v2/records/search"
        f"?q={query}"
        f"&levelOfDescription=fileUnit"
        f"&availableOnline=true"
        f"&limit={limit}"
        f"&offset={offset}"
    )
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def parse_dates_from_title(title):
    """
    Try to extract start and end dates from title string.
    Handles formats like:
        "Log of U.S.S. VERMONT: 8/8/1868-7/21/1869"
        "USS Constitution, 9/21/1845 - 9/30/1845"
        "Log of U.S.S. HARTFORD: 1918"
    """
    # Pattern: M/D/YYYY - M/D/YYYY or M/D/YYYY-M/D/YYYY
    match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})', title)
    if match:
        return match.group(1), match.group(2)

    # Pattern: just a year like ": 1918"
    match = re.search(r':\s*(\d{4})\s*$', title)
    if match:
        return match.group(1), match.group(1)

    return "", ""


def parse_ship_name(title):
    """
    Extract ship name from title.
    "Log of U.S.S. SEMINOLE: 4/25/1860-7/28/1860" -> "USS SEMINOLE"
    "USS Constitution, 9/21/1845 - 9/30/1845" -> "USS Constitution"
    "Rough Log of USS Ossipee, 11/18/1871" -> "USS Ossipee"
    """
    # Try "U.S.S. NAME" pattern
    match = re.search(r'U\.?S\.?S\.?\s+([A-Za-z][A-Za-z\s\-]+)', title)
    if match:
        name = match.group(1).split(":")[0].split(",")[0].strip()
        return f"USS {name}"

    # Try "USS NAME" pattern
    match = re.search(r'USS\s+([A-Za-z][A-Za-z\s\-]+)', title)
    if match:
        name = match.group(1).split(":")[0].split(",")[0].strip()
        return f"USS {name}"

    return ""


def parse_hit(hit):
    """Turn one API hit into a flat dict row."""
    rec = hit["_source"]["record"]
    na_id = hit["_id"]

    objects = rec.get("digitalObjects", [])
    num_images = 0
    has_pdf = False
    pdf_url = ""

    for obj in objects:
        fname = obj.get("objectFilename", "")
        if fname.lower().endswith(".pdf"):
            has_pdf = True
            pdf_url = obj.get("objectUrl", "")
        else:
            num_images += 1

    # Try API date fields first
    start_date = rec.get("coverageStartDate", {})
    end_date = rec.get("coverageEndDate", {})
    start_str = start_date.get("logicalDate", "") if isinstance(start_date, dict) else ""
    end_str = end_date.get("logicalDate", "") if isinstance(end_date, dict) else ""

    # Fallback: parse dates from title
    title = rec.get("title", "")
    if not start_str or not end_str:
        title_start, title_end = parse_dates_from_title(title)
        if not start_str:
            start_str = title_start
        if not end_str:
            end_str = title_end

    ship_name = parse_ship_name(title)

    return {
        "naId": na_id,
        "ship_name": ship_name,
        "title": title,
        "start_date": start_str,
        "end_date": end_str,
        "nara_url": f"https://catalog.archives.gov/id/{na_id}",
        "num_images": num_images,
        "has_pdf": has_pdf,
        "num_total_objects": len(objects),
        "pdf_url": pdf_url,
    }


def build_index(csv_path="shiplog_index.csv"):
    """
    Fetch all digitized ship log records and save to CSV.
    Returns list of dicts.
    """
    query = '"log of U.S.S" OR "log of USS"'
    limit = 100
    offset = 0

    # First call to get total
    data = fetch_index_page(query, 0, limit)
    total = data["body"]["hits"]["total"]["value"]
    pages = (total // limit) + 1
    print(f"Total records: {total:,}")
    print(f"Pages to fetch: {pages} ({pages} API calls)")

    all_rows = []
    api_calls = 0

    while offset < total:
        if offset == 0:
            page_data = data  # reuse first call
        else:
            page_data = fetch_index_page(query, offset, limit)

        api_calls += 1
        hits = page_data["body"]["hits"]["hits"]
        if not hits:
            break

        for hit in hits:
            row = parse_hit(hit)
            all_rows.append(row)

        print(f"  Page {api_calls}/{pages} | {len(all_rows):,}/{total:,} records")
        offset += limit
        time.sleep(API_DELAY)

    # Save CSV
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nDone! {len(all_rows):,} records saved to {csv_path}")
    print(f"API calls used: {api_calls}")
    return all_rows


def load_index(csv_path="shiplog_index.csv"):
    """Load the index CSV into a list of dicts."""
    with open(csv_path, "r") as f:
        return list(csv.DictReader(f))


# ==========================================================
# METADATA / TEXT / TRANSCRIPTION FUNCTIONS
# ==========================================================

def get_metadata(na_id):
    """Fetch record metadata from NARA API."""
    url = f"{BASE_URL}/api/v2/records/search?naId={na_id}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("body", {}).get("hits", {}).get("hits", [])
    if not hits:
        return None
    return data


def get_extracted_text(na_id):
    """Fetch all extracted text (OCR) for a record."""
    url = f"{BASE_URL}/proxy/extractedText/{na_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"    Warning (extracted text): {e}")
        return {"total": 0, "digitalObjects": []}


def get_transcriptions(na_id):
    """Fetch all transcriptions for a record."""
    url = f"{BASE_URL}/proxy/transcriptions/{na_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"    Warning (transcriptions): {e}")
        return {"body": {"hits": {"total": {"value": 0}, "hits": []}}}


# ==========================================================
# DOWNLOAD FUNCTIONS
# ==========================================================

def download_file(url, dest_path):
    """Download a single file. Skip if already exists."""
    dest_path = Path(dest_path)
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True

    try:
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    FAILED: {dest_path.name} - {e}")
        return False


def clean_folder_name(na_id, title):
    """Make a safe folder name."""
    clean = re.sub(r'[^\w\s-]', '', title).strip()
    clean = re.sub(r'\s+', '_', clean)
    return f"{na_id}_{clean}"[:120]


def download_record(na_id, title, skip_images=False, output_dir=None):
    """
    Full download pipeline for one record.
    Returns a dict with results for the master CSV.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    output_dir = Path(output_dir)

    na_id = str(na_id)
    folder = clean_folder_name(na_id, title)
    record_dir = output_dir / folder
    record_dir.mkdir(parents=True, exist_ok=True)
    images_dir = record_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Skip if already done
    done_flag = record_dir / "_done.flag"
    if done_flag.exists():
        print(f"  SKIP (already done): {na_id}")
        return None

    # 1. Metadata (1 API call)
    print(f"  [1/3] Metadata...")
    metadata = get_metadata(na_id)
    if metadata is None:
        print(f"  No record found.")
        return {
            "naId": na_id, "title": title,
            "start_date": "", "end_date": "",
            "nara_url": f"https://catalog.archives.gov/id/{na_id}",
            "local_dir": str(record_dir),
            "num_images": 0, "has_pdf": False,
            "has_extracted_text": False, "has_transcription": False,
            "num_extracted_text": 0, "num_transcriptions": 0,
            "download_status": "no_record",
        }

    record = metadata["body"]["hits"]["hits"][0]["_source"]["record"]
    with open(record_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    time.sleep(API_DELAY)

    # 2. Extracted text (1 API call)
    print(f"  [2/3] Extracted text...")
    extracted = get_extracted_text(na_id)
    ext_total = extracted.get("total", 0)
    with open(record_dir / "extracted_text.json", "w") as f:
        json.dump(extracted, f, indent=2)
    time.sleep(API_DELAY)

    # 3. Transcriptions (1 API call)
    print(f"  [3/3] Transcriptions...")
    transcriptions = get_transcriptions(na_id)
    trans_total = (
        transcriptions
        .get("body", {})
        .get("hits", {})
        .get("total", {})
        .get("value", 0)
    )
    with open(record_dir / "transcriptions.json", "w") as f:
        json.dump(transcriptions, f, indent=2)
    time.sleep(API_DELAY)

    # 4. Download files (free S3 calls)
    objects = record.get("digitalObjects", [])
    num_images = 0
    has_pdf = False
    failures = 0

    if objects:
        print(f"  Downloading {len(objects)} files...")
        for i, obj in enumerate(objects):
            obj_url = obj.get("objectUrl", "")
            obj_fname = obj.get("objectFilename", "")
            if not obj_url or not obj_fname:
                continue

            if obj_fname.lower().endswith(".pdf"):
                dest = record_dir / obj_fname
                has_pdf = True
            else:
                num_images += 1
                if skip_images:
                    continue
                dest = images_dir / obj_fname

            ok = download_file(obj_url, dest)
            if not ok:
                failures += 1

            if (i + 1) % 10 == 0:
                print(f"    {i+1}/{len(objects)} files...")

            time.sleep(DOWNLOAD_DELAY)

    # 5. Status
    if not objects:
        status = "no_digital_objects"
    elif failures == 0:
        status = "success"
    elif failures < len(objects):
        status = "partial"
    else:
        status = "failed"

    # 6. Dates
    start_date = record.get("coverageStartDate", {})
    end_date = record.get("coverageEndDate", {})
    start_str = start_date.get("logicalDate", "") if isinstance(start_date, dict) else ""
    end_str = end_date.get("logicalDate", "") if isinstance(end_date, dict) else ""

    done_flag.touch()

    result = {
        "naId": na_id,
        "title": title,
        "start_date": start_str,
        "end_date": end_str,
        "nara_url": f"https://catalog.archives.gov/id/{na_id}",
        "local_dir": str(record_dir),
        "num_images": num_images,
        "has_pdf": has_pdf,
        "has_extracted_text": ext_total > 0,
        "has_transcription": trans_total > 0,
        "num_extracted_text": ext_total,
        "num_transcriptions": trans_total,
        "download_status": status,
    }

    print(f"  DONE: images={num_images}, pdf={has_pdf}, "
          f"ocr={ext_total}, transcriptions={trans_total}, status={status}")

    return result


# ==========================================================
# BATCH DOWNLOAD
# ==========================================================

MASTER_COLUMNS = [
    "naId", "title", "start_date", "end_date", "nara_url",
    "local_dir", "num_images", "has_pdf",
    "has_extracted_text", "has_transcription",
    "num_extracted_text", "num_transcriptions",
    "download_status",
]


def download_batch(index_rows, start=0, end=None, skip_images=False, output_dir=None):
    """
    Download a batch of records from the index.

    Args:
        index_rows: list of dicts from load_index() or build_index()
        start: first row to process (0-based)
        end: last row (exclusive), None = all
        skip_images: if True, skip JPGs, only download PDFs
        output_dir: override output directory
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    if end is None:
        end = len(index_rows)
    subset = index_rows[start:end]

    master_csv = output_dir / "master_index.csv"
    write_header = not master_csv.exists()
    f = open(master_csv, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=MASTER_COLUMNS)
    if write_header:
        writer.writeheader()

    success = 0
    skipped = 0
    failed = 0

    for i, row in enumerate(subset):
        na_id = row["naId"]
        title = row["title"]
        print(f"\n[{start + i + 1}/{end}] {na_id}: {title}")

        try:
            result = download_record(na_id, title, skip_images=skip_images, output_dir=output_dir)
            if result is None:
                skipped += 1
            else:
                writer.writerow(result)
                f.flush()
                if result["download_status"] in ("success", "no_digital_objects"):
                    success += 1
                else:
                    failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    f.close()
    print(f"\nBatch done: success={success}, skipped={skipped}, failed={failed}")
    print(f"Master CSV: {master_csv}")
