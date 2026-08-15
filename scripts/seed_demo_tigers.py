"""
Seeds the database with 4 known-distinct tigers using their real ATRW
ground-truth identities (not auto-matched), so we can demonstrate
occupancy/map/overlap cleanly. This is separate from and doesn't replace
matcher.py, which was already validated independently (see docs).

Stations are deliberately assigned with overlap between tigers so the map
demonstrates the brief's "territorial overlap is a management signal"
requirement.
"""

import random
from pathlib import Path
from datetime import datetime, timedelta

from src.db import get_connection
from src.classification.blank_detector import classify_image
from src.config import BASE_DIR

BEST_TIGERS_DIR = BASE_DIR / "data" / "samples" / "best_tigers"

# Deliberately overlapping station assignments per tiger.
TIGER_STATIONS = {
    "271": ["ST-001", "ST-002", "ST-003", "ST-004"],
    "201": ["ST-002", "ST-003", "ST-005", "ST-006"],  # overlaps 271 on ST-002, ST-003
    "259": ["ST-004", "ST-005", "ST-001"],              # overlaps 271 on ST-001/004, 201 on ST-005
    "273": ["ST-006", "ST-003", "ST-002"],               # overlaps 201 on ST-002/003/006
}


def seed():
    conn = get_connection()
    run_id_row = conn.execute("INSERT INTO runs (run_timestamp) VALUES (datetime('now'))")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    for real_tiger_id, stations in TIGER_STATIONS.items():
        tiger_folder = BEST_TIGERS_DIR / f"tiger_{real_tiger_id}"
        if not tiger_folder.exists():
            print(f"  Skipping {real_tiger_id}: folder not found")
            continue

        vyaghra_tiger_id = f"T-{real_tiger_id}"
        conn.execute(
            "INSERT OR IGNORE INTO tigers (tiger_id, first_enrolled_run_id, notes) VALUES (?, ?, ?)",
            (vyaghra_tiger_id, run_id, "Ground-truth identity from ATRW labels (demo dataset)"),
        )
        conn.commit()

        images = sorted(tiger_folder.glob("*.jpg"))
        print(f"\n{vyaghra_tiger_id}: seeding {len(images)} images across stations {stations}")

        for i, img_path in enumerate(images):
            result = classify_image(str(img_path))
            station_id = stations[i % len(stations)]  # cycle through assigned stations
            station_row = conn.execute(
                "SELECT lat, lon FROM stations WHERE station_id = ?", (station_id,)
            ).fetchone()

            fake_dt = datetime.now() - timedelta(days=random.randint(0, 30))

            cursor = conn.execute(
                """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                        gps_lat, gps_lon, classification, classification_confidence, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(img_path), station_id, fake_dt.isoformat(), "synthetic",
                 station_row[0], station_row[1], result["label"], result["confidence"], run_id),
            )
            conn.commit()
            image_id = cursor.lastrowid

            if result["label"] == "subject":
                conn.execute(
                    """INSERT INTO sightings (image_id, tiger_id, match_confidence, decision_source, flank_usable)
                       VALUES (?, ?, ?, ?, ?)""",
                    (image_id, vyaghra_tiger_id, result["confidence"], "human", 1),
                )
                conn.commit()
                print(f"  {img_path.name} -> {vyaghra_tiger_id} @ {station_id} (ground truth)")

    conn.close()
    print(f"\nSeeding complete. Run ID: {run_id}")
    return run_id


if __name__ == "__main__":
    seed()