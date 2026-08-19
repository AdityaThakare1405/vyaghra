"""
One-time helper: builds a larger sample folder from the ATRW dataset so you
can run run_pipeline.py on more images at once and get richer numbers on
the dashboard (more sightings, more tigers, more occupancy/alert data).

Generalizes scripts/prepare_test_tigers.py: instead of a fixed 5 tigers x 5
photos, this takes --tigers and --per-tiger counts so you control batch size.

Usage:
    python -m scripts.prepare_bigger_batch --tigers 25 --per-tiger 6
    python run_pipeline.py --input data/samples/big_batch
    python -m scripts.generate_html_dashboard
"""

import argparse
import csv
import shutil
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "samples" / "reid_list_train.csv"
IMAGES_DIR = PROJECT_ROOT / "data" / "raw" / "atrw_tigers" / "train"
OUTPUT_DIR = PROJECT_ROOT / "data" / "samples" / "big_batch"


def main(n_tigers: int, per_tiger: int, min_photos: int):
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing {CSV_PATH} -- expected the ATRW reid_list_train.csv here.")
    if not IMAGES_DIR.exists():
        raise SystemExit(f"Missing {IMAGES_DIR} -- expected the ATRW train images here.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tiger_to_files = defaultdict(list)
    with open(CSV_PATH, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            tiger_id, filename = row[0], row[1]
            tiger_to_files[tiger_id].append(filename)

    candidates = {tid: files for tid, files in tiger_to_files.items() if len(files) >= min_photos}
    selected = dict(list(candidates.items())[:n_tigers])

    print(f"Found {len(candidates)} tigers with {min_photos}+ photos. "
          f"Using {len(selected)} of them, up to {per_tiger} photos each.\n")

    total_copied = 0
    for tiger_id, files in selected.items():
        tiger_folder = OUTPUT_DIR / f"tiger_{tiger_id}"
        tiger_folder.mkdir(exist_ok=True)
        copied = 0
        for filename in files[:per_tiger]:
            src = IMAGES_DIR / filename
            if src.exists():
                shutil.copy(src, tiger_folder / filename)
                copied += 1
        total_copied += copied
        print(f"  Tiger {tiger_id}: {len(files)} total photos available, copied {copied}")

    print(f"\nDone. {total_copied} images staged at: {OUTPUT_DIR}")
    print("Next steps:")
    print(f"  python run_pipeline.py --input {OUTPUT_DIR}")
    print("  python -m scripts.generate_html_dashboard")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tigers", type=int, default=25, help="How many distinct tiger IDs to include")
    parser.add_argument("--per-tiger", type=int, default=6, help="Max photos per tiger")
    parser.add_argument("--min-photos", type=int, default=4, help="Only include tigers with at least this many photos")
    args = parser.parse_args()
    main(args.tigers, args.per_tiger, args.min_photos)