"""
Single entry point for the Vyaghra pipeline.
Usage: python run_pipeline.py --input data/samples/tigers_multi
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

import argparse
import time
import json
import random
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from src.db import get_connection
from src.ingestion.scanner import find_images, extract_metadata
from src.classification.blank_detector import classify_image
from src.identification.detector import detect_and_crop
from src.identification.matcher import match_or_enroll
from src.config import OUTPUTS_DIR, QUARANTINE_DIR


def _assign_random_station(conn):
    stations = conn.execute("SELECT station_id, lat, lon FROM stations").fetchall()
    return random.choice(stations)


def main(input_folder: str):
    start_time = time.time()
    conn = get_connection()

    conn.execute("INSERT INTO runs (run_timestamp, images_processed, images_quarantined) VALUES (datetime('now'), 0, 0)")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    images = find_images(Path(input_folder))
    print(f"Run #{run_id}: found {len(images)} images in {input_folder}\n")

    quarantined_count = 0
    space_freed = 0
    subject_count = 0
    human_count = 0

    for img_path in images:
        meta = extract_metadata(img_path)
        result = classify_image(str(img_path))
        station_id, station_lat, station_lon = _assign_random_station(conn)

        gps_lat = meta["gps_lat"] if meta["gps_lat"] else station_lat
        gps_lon = meta["gps_lon"] if meta["gps_lon"] else station_lon

        # Our ATRW test images have no real EXIF timestamps (academic re-ID
        # dataset, not real field data). Simulate a realistic capture time
        # spread across recent days so the alert engine has something
        # meaningful to compare across runs.
        capture_timestamp = meta["capture_timestamp"]
        if capture_timestamp is None:
            fake_dt = datetime.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
            capture_timestamp = fake_dt.isoformat()

        cursor = conn.execute(
            """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                    gps_lat, gps_lon, classification, classification_confidence, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meta["original_path"], station_id, capture_timestamp, meta["timestamp_confidence"],
             gps_lat, gps_lon, result["label"], result["confidence"], run_id),
        )
        conn.commit()
        image_id = cursor.lastrowid

        if result["label"] == "blank":
            file_size = img_path.stat().st_size
            dest = QUARANTINE_DIR / img_path.name
            shutil.copy(str(img_path), str(dest))
            conn.execute("UPDATE images SET quarantined = 1 WHERE image_id = ?", (image_id,))
            conn.commit()
            quarantined_count += 1
            space_freed += file_size
            print(f"  [BLANK -> quarantined] {img_path.name}")

        elif result["label"] == "subject":
            crop_path, usable = detect_and_crop(str(img_path))
            crop_result = classify_image(crop_path, skip_person_check=True) if crop_path else result

            if crop_result["embedding"] is None:
                print(f"  [SUBJECT -> no embedding, skipped] {img_path.name}")
                continue

            match = match_or_enroll(crop_result["embedding"], run_id)

            conn.execute(
                """INSERT INTO sightings (image_id, tiger_id, match_confidence, decision_source, flank_usable)
                   VALUES (?, ?, ?, ?, ?)""",
                (image_id, match["tiger_id"], match["confidence"],
                 "auto" if match["decision"] != "needs_review" else None, int(usable)),
            )
            conn.commit()
            subject_count += 1
            print(f"  [SUBJECT -> {match['decision']}] {img_path.name} -> {match['tiger_id']} "
                  f"(confidence={match['confidence']:.2f}) @ {station_id}")

        elif result["label"] == "human":
            human_count += 1
            print(f"  [HUMAN -> privacy flagged, excluded] {img_path.name}")

    elapsed = time.time() - start_time
    throughput = (len(images) / elapsed) * 60 if elapsed > 0 else 0

    conn.execute(
        """UPDATE runs SET images_processed=?, images_quarantined=?, space_freed_mb=?,
                            time_taken_sec=?, throughput_img_per_min=? WHERE run_id=?""",
        (len(images), quarantined_count, round(space_freed / (1024 * 1024), 2), round(elapsed, 1), round(throughput, 1), run_id),
    )
    conn.commit()

    report = {
        "run_id": run_id,
        "images_processed": len(images),
        "images_quarantined": quarantined_count,
        "subjects_identified": subject_count,
        "humans_flagged": human_count,
        "space_freed_mb": round(space_freed / (1024 * 1024), 2),
        "time_taken_sec": round(elapsed, 1),
        "throughput_img_per_min": round(throughput, 1),
    }
    with open(OUTPUTS_DIR / f"run_report_{run_id}.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n--- RUN REPORT ---")
    print(json.dumps(report, indent=2))
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    main(args.input)