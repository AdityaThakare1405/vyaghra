"""
Seeds a handful of REAL photos into the human review queue on purpose.

Why this exists: the matcher's three-way logic (auto-match / auto-enroll /
needs_review) only produces review-queue entries when a photo's similarity
genuinely lands in the mid-band. For a demo, that band might not get hit by
chance in a small run. This script runs real photos through the real
classifier + crop + embedding pipeline (same as run_pipeline.py), and only
keeps ones whose real similarity score lands in the review band -- it does
NOT fabricate confidence numbers. If too few land there naturally, it widens
the search rather than faking a score.

Usage:
    python -m scripts.seed_review_batch --count 5
"""

import argparse
import random
from pathlib import Path

from src.db import get_connection
from src.classification.blank_detector import classify_image
from src.identification.detector import detect_and_crop
from src.identification.matcher import match_or_enroll
from src.config import BASE_DIR

ATRW_TRAIN_DIR = BASE_DIR / "data" / "raw" / "atrw_tigers" / "train"


def _candidate_pool(exclude_dirs=None):
    """All jpg/png files under the raw ATRW train folder, shuffled."""
    if not ATRW_TRAIN_DIR.exists():
        raise SystemExit(f"Raw ATRW folder not found: {ATRW_TRAIN_DIR}")
    files = [p for p in ATRW_TRAIN_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    random.shuffle(files)
    return files


def main(count: int, max_attempts: int):
    conn = get_connection()
    conn.execute("INSERT INTO runs (run_timestamp) VALUES (datetime('now'))")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    pool = _candidate_pool()
    found = 0
    attempts = 0

    print(f"Run #{run_id}: scanning for real photos that land in the review band...\n")

    for img_path in pool:
        if found >= count or attempts >= max_attempts:
            break
        attempts += 1

        result = classify_image(str(img_path))
        if result["label"] != "subject":
            continue

        crop_path, usable = detect_and_crop(str(img_path))
        crop_result = classify_image(crop_path, skip_person_check=True) if crop_path else result
        if crop_result["embedding"] is None:
            continue

        match = match_or_enroll(crop_result["embedding"], run_id)
        if match["decision"] != "needs_review":
            continue

        station_row = conn.execute(
            "SELECT station_id, lat, lon FROM stations ORDER BY RANDOM() LIMIT 1"
        ).fetchone()

        cursor = conn.execute(
            """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                    gps_lat, gps_lon, classification, classification_confidence, run_id)
               VALUES (?, ?, datetime('now'), 'synthetic', ?, ?, ?, ?, ?)""",
            (str(img_path), station_row[0], station_row[1], station_row[2],
             result["label"], result["confidence"], run_id),
        )
        conn.commit()
        image_id = cursor.lastrowid

        conn.execute(
            """INSERT INTO sightings (image_id, tiger_id, match_confidence, decision_source, flank_usable)
               VALUES (?, NULL, ?, NULL, ?)""",
            (image_id, match["confidence"], int(usable)),
        )
        conn.commit()

        found += 1
        candidates = ", ".join(f"{tid}:{sim:.2f}" for tid, sim in match["candidates"])
        print(f"  [{found}/{count}] {img_path.name} -> needs_review "
              f"(best_sim={match['confidence']:.2f}, candidates=[{candidates}])")

    conn.close()

    if found < count:
        print(f"\nOnly found {found}/{count} photos that genuinely land in the review band "
              f"after {attempts} attempts. Try raising --max-attempts, or loosen "
              f"MATCH_REVIEW_LOWER/MATCH_AUTO_THRESHOLD in src/config.py if you need more.")
    else:
        print(f"\nDone. {found} review-queue sightings added under run_id {run_id}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5, help="How many review-queue photos to add")
    parser.add_argument("--max-attempts", type=int, default=200, help="Safety cap on photos scanned")
    args = parser.parse_args()
    main(args.count, args.max_attempts)