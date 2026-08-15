"""
Selects the 4 best tiger IDs from the ATRW dataset for the demo — chosen by
photo count (need enough for a real home range) and average classifier
confidence (so we show our cleanest, most reliable detections).
"""

import csv
import shutil
from pathlib import Path
from collections import defaultdict

from src.classification.blank_detector import classify_image
from src.config import BASE_DIR

CSV_PATH = BASE_DIR / "data" / "samples" / "reid_list_train.csv"
IMAGES_DIR = BASE_DIR / "data" / "raw" / "atrw_tigers" / "train"
OUTPUT_DIR = BASE_DIR / "data" / "samples" / "best_tigers"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Group filenames by tiger_id
tiger_to_files = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    reader = csv.reader(f)
    for row in reader:
        tiger_id, filename = row[0], row[1]
        tiger_to_files[tiger_id].append(filename)

# Only consider tigers with a solid number of photos (need 3+ for a home
# range, so require more than that for a comfortable margin).
candidates = {tid: files for tid, files in tiger_to_files.items() if len(files) >= 10}
print(f"Found {len(candidates)} tigers with 10+ photos. Scoring by classifier confidence...\n")

scored = []
for tiger_id, files in candidates.items():
    # Sample up to 6 photos per tiger to keep this fast, rather than scoring every photo.
    sample_files = files[:6]
    confidences = []
    for filename in sample_files:
        img_path = IMAGES_DIR / filename
        if img_path.exists():
            result = classify_image(str(img_path))
            if result["label"] == "subject":
                confidences.append(result["confidence"])
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        scored.append((tiger_id, avg_conf, len(files)))

# Rank by average confidence, take the top 4
scored.sort(key=lambda x: x[1], reverse=True)
top_4 = scored[:4]

print("Top 4 tigers selected:\n")
for tiger_id, avg_conf, total_photos in top_4:
    print(f"  {tiger_id}: avg_confidence={avg_conf:.3f}, total_photos={total_photos}")

    tiger_folder = OUTPUT_DIR / f"tiger_{tiger_id}"
    tiger_folder.mkdir(exist_ok=True)
    for filename in tiger_to_files[tiger_id][:6]:  # 6 clean photos each
        src = IMAGES_DIR / filename
        if src.exists():
            shutil.copy(src, tiger_folder / filename)

print(f"\nDone. Images copied to: {OUTPUT_DIR}")