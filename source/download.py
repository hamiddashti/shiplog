#!/usr/bin/env python3
"""
Phase 1 - Step 1: Download NARA bulk catalog from AWS
Downloads and unzips both descriptions and authorities zips.
Run from login node: python phase1_download.py
"""

import subprocess
import sys
import os

# ── Paths ──
CATALOG_DIR = "/project/rcc/users/hdashti/projects/shiplogs/catalog"
BUCKET = "s3://nara-national-archives-catalog/zip"

FILES = [
    "nac_export_descriptions_2020-11-20.zip",
    "nac_export_authorities_2020-11-20.zip",
]


def run(cmd, description):
    """Run a shell command, print status, exit on failure."""
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print(f"  $ {cmd}")
    print(f"{'=' * 60}\n")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"\nERROR: {description} failed (exit code {result.returncode})")
        sys.exit(1)


def main():
    # ── Check AWS CLI ──
    result = subprocess.run("aws --version", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print("ERROR: aws CLI not found.")
        print("  Try: module load awscli   (or whatever your cluster uses)")
        print("  Then re-run this script.")
        sys.exit(1)
    print(f"AWS CLI found: {result.stdout.strip()}")

    # ── Check S3 access (no credentials needed — bucket is public) ──
    print("\nTesting S3 access (public bucket, no credentials needed)...")
    test = subprocess.run(
        f"aws s3 ls {BUCKET}/ --no-sign-request",
        shell=True,
        capture_output=True,
        text=True,
    )
    if test.returncode != 0:
        print("ERROR: Cannot list S3 bucket.")
        print(f"  stderr: {test.stderr.strip()}")
        print("  The bucket may require --no-sign-request or network access.")
        sys.exit(1)
    print("S3 access OK.\n")

    # ── Create catalog directory ──
    os.makedirs(CATALOG_DIR, exist_ok=True)
    print(f"Catalog directory: {CATALOG_DIR}")

    # ── Download and unzip each file ──
    for filename in FILES:
        zip_path = os.path.join(CATALOG_DIR, filename)

        # Skip download if zip already exists
        if os.path.exists(zip_path):
            print(f"\nSkipping download (already exists): {zip_path}")
        else:
            run(
                f"aws s3 cp {BUCKET}/{filename} {zip_path} --no-sign-request",
                f"Downloading {filename}",
            )

        # Unzip (-DD preserves no timestamps, -o overwrites without prompting)
        run(
            f"unzip -DD -o {zip_path} -d {CATALOG_DIR}",
            f"Unzipping {filename}",
        )

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print("  Download complete. Contents of catalog directory:")
    print(f"{'=' * 60}")
    for entry in sorted(os.listdir(CATALOG_DIR)):
        full = os.path.join(CATALOG_DIR, entry)
        if os.path.isdir(full):
            print(f"  [DIR]  {entry}")
        else:
            size_mb = os.path.getsize(full) / (1024 * 1024)
            print(f"  [FILE] {entry}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
