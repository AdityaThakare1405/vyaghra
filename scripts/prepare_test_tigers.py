"""
One-time helper: picks a handful of tiger IDs that have multiple photos
in the ATRW dataset, and copies those photos into data/samples/tigers/
so we have a meaningful test set for the matcher (same tiger, multiple images).
"""

import csv
import shutil
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "samples" / "reid_list_train.csv"
IMAGES_DIR = PROJECT_ROOT / "data" / "raw" / "atrw_tigers" / "train"
OUTPUT_DIR = PROJECT_ROOT / "data" / "samples" / "tigers_multi"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Group filenames by tiger_id
tiger_to_files = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    reader = csv.reader(f)
    for row in reader:
        tiger_id, filename = row[0], row[1]
        tiger_to_files[tiger_id].append(filename)

# Pick tiger IDs that have at least 4 photos, take the first 5 such tigers
candidates = {tid: files for tid, files in tiger_to_files.items() if len(files) >= 4}
selected = dict(list(candidates.items())[:5])

print(f"Selected {len(selected)} tigers with multiple photos:\n")

for tiger_id, files in selected.items():
    tiger_folder = OUTPUT_DIR / f"tiger_{tiger_id}"
    tiger_folder.mkdir(exist_ok=True)
    for filename in files[:5]:  # up to 5 photos per tiger
        src = IMAGES_DIR / filename
        if src.exists():
            shutil.copy(src, tiger_folder / filename)
    print(f"  Tiger {tiger_id}: {len(files)} total photos, copied {min(5, len(files))}")

print(f"\nDone. Check: {OUTPUT_DIR}")