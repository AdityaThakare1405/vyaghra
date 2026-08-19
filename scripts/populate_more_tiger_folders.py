"""
Copies real ATRW photos for additional tiger IDs into data/samples/best_tigers/,
same pattern as the original 4 — needed before seed_demo_tigers.py can find
their photos.
"""

import csv
import shutil
from pathlib import Path
from collections import defaultdict

from src.config import BASE_DIR

CSV_PATH = BASE_DIR / "data" / "samples" / "reid_list_train.csv"
IMAGES_DIR = BASE_DIR / "data" / "raw" / "atrw_tigers" / "train"
OUTPUT_DIR = BASE_DIR / "data" / "samples" / "best_tigers"

NEEDED_IDS = ["250", "256", "171", "247", "238"]

tiger_to_files = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    reader = csv.reader(f)
    for row in reader:
        tiger_id, filename = row[0], row[1]
        tiger_to_files[tiger_id].append(filename)

for tid in NEEDED_IDS:
    files = tiger_to_files.get(tid, [])
    if not files:
        print(f"  {tid}: no photos found in CSV at all — check the ID is correct")
        continue
    folder = OUTPUT_DIR / f"tiger_{tid}"
    folder.mkdir(parents=True, exist_ok=True)
    copied = 0
    for filename in files[:6]:
        src = IMAGES_DIR / filename
        if src.exists():
            shutil.copy(src, folder / filename)
            copied += 1
    print(f"  {tid}: {len(files)} total photos available, copied {copied}")

print("Done.")