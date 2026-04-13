"""
Test download of 2 records on midway3.
Run from: /home/hdashti/projects/shiplog/source/
"""

import sys
sys.path.insert(0, "/home/hdashti/projects/shiplog/source")

from nara_shiplog import *

# Setup
setup("/home/hdashti/projects/shiplog/nara_key.txt")

# Load index
index = load_index("/home/hdashti/projects/shiplog/outputs/shiplog_index.csv")
print(f"Index loaded: {len(index)} records")

# Download first 2 records as test
DOWNLOAD_DIR = "/project/rcc/users/hdashti/projects/shiplogs"

download_batch(
    index,
    start=0,
    end=2,
    output_dir=DOWNLOAD_DIR,
)
