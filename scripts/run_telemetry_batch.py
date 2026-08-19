"""
Processes a batch of images purely for TELEMETRY numbers (Overview page:
images processed, blanks removed; Blank Filter page: frame results) —
does NOT touch tiger identification/matching/occupancy at all. No
sightings are written, so this can never pollute the real named tigers'
data. Safe to run with any size batch, any number of times.
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

import argparse
import time
import json
import shutil
from pathlib import Path

from src.db import get_connection
from src.ingestion.scanner import find_images
from src.classification.blank_detector import classify_image
from src.config import OUTPUTS_DIR, QUARANTINE_DIR


def main(input_folder: str):
    start_time = time.time()
    conn = get_connection()
    conn.execute("INSERT INTO runs (run_timestamp, images_processed, images_quarantined) VALUES (datetime('now'), 0, 0)")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    images = find_images(Path(input_folder))
    print(f"Telemetry run #{run_id}: {len(images)} images (identification NOT touched)\n")

    quarantined_count, space_freed, subject_count, human_count = 0, 0, 0, 0

    for img_path in images:
        result = classify_image(str(img_path))
        conn.execute(
            """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                    gps_lat, gps_lon, classification, classification_confidence, run_id)
               VALUES (?, NULL, datetime('now'), 'telemetry_only', NULL, NULL, ?, ?, ?)""",
            (str(img_path), result["label"], result["confidence"], run_id),
        )
        conn.commit()

        if result["label"] == "blank":
            try:
                shutil.copy(str(img_path), str(QUARANTINE_DIR / img_path.name))
            except Exception:
                pass
            quarantined_count += 1
            space_freed += img_path.stat().st_size
        elif result["label"] == "subject":
            subject_count += 1
        elif result["label"] == "human":
            human_count += 1

    elapsed = time.time() - start_time
    throughput = (len(images) / elapsed) * 60 if elapsed > 0 else 0
    conn.execute(
        """UPDATE runs SET images_processed=?, images_quarantined=?, space_freed_mb=?,
                            time_taken_sec=?, throughput_img_per_min=? WHERE run_id=?""",
        (len(images), quarantined_count, round(space_freed / (1024*1024), 2), round(elapsed, 1), round(throughput, 1), run_id),
    )
    conn.commit()

    report = {"run_id": run_id, "images_processed": len(images), "images_quarantined": quarantined_count,
              "subjects_identified": subject_count, "humans_flagged": human_count,
              "throughput_img_per_min": round(throughput, 1)}
    with open(OUTPUTS_DIR / f"run_report_{run_id}.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\n--- TELEMETRY RUN REPORT ---")
    print(json.dumps(report, indent=2))
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    main(args.input)