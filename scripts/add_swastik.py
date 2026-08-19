"""
Processes real, freshly-captured photos of a specific known individual
("Swastik") through the actual pipeline (real blank/subject classification,
real crop, real embedding) — genuinely testing the system on brand-new,
same-day field photos, not synthetic data. Since we know the ground-truth
identity in advance, sightings are directly assigned to a fixed tiger_id
rather than left to matcher uncertainty (same pattern used for the other
4 named tigers). A real embedding IS stored this time, so future photos of
him could auto-match normally going forward.

SAFE TO RE-RUN: wipes any previous T-SWASTIK data (images, sightings,
occupancy snapshot, tiger row) before re-adding him, so running this again
after dropping new photos into data/samples/swastik/ never produces
duplicates. Nothing belonging to any other tiger is touched.
"""

import math
import random
import pickle
from datetime import datetime, timedelta
from pathlib import Path

from shapely.geometry import Point, shape
import json

from src.db import get_connection
from src.classification.blank_detector import classify_image
from src.identification.detector import detect_and_crop
from src.config import BASE_DIR

SWASTIK_PHOTOS_DIR = BASE_DIR / "data" / "samples" / "swastik"
TIGER_ID = "T-SWASTIK"
NAME = "Swastik"
KM_PER_DEG_LAT = 111.0


def km_per_deg_lon(lat):
    return 111.0 * math.cos(math.radians(lat))


def is_valid_point(lat, lon, reserve, lake):
    p = Point(lon, lat)
    return reserve.contains(p) and not lake.contains(p)


def _clear_previous_swastik(conn):
    """Deletes any prior T-SWASTIK rows (images, sightings, occupancy,
    tiger record) so re-running this script never produces duplicates.
    Scoped strictly to TIGER_ID / SWASTIK_PHOTOS_DIR paths — no other
    tiger's data is touched."""
    existing = conn.execute(
        "SELECT 1 FROM tigers WHERE tiger_id = ?", (TIGER_ID,)
    ).fetchone()
    if not existing:
        return

    print(f"Found existing {NAME} data — clearing it before re-adding.")

    image_ids = [
        row[0] for row in conn.execute(
            "SELECT image_id FROM images WHERE original_path LIKE ?",
            (f"%{SWASTIK_PHOTOS_DIR.name}%",),
        ).fetchall()
    ]
    # Also catch his synthetic movement-track rows, which use original_path
    # = 'synthetic' and are only identifiable via the sightings link.
    linked_image_ids = [
        row[0] for row in conn.execute(
            "SELECT image_id FROM sightings WHERE tiger_id = ?", (TIGER_ID,)
        ).fetchall()
    ]
    all_image_ids = set(image_ids) | set(linked_image_ids)

    conn.execute("DELETE FROM sightings WHERE tiger_id = ?", (TIGER_ID,))
    if all_image_ids:
        conn.executemany(
            "DELETE FROM images WHERE image_id = ?",
            [(iid,) for iid in all_image_ids],
        )
    conn.execute("DELETE FROM occupancy_snapshots WHERE tiger_id = ?", (TIGER_ID,))
    conn.execute("DELETE FROM tigers WHERE tiger_id = ?", (TIGER_ID,))
    conn.commit()
    print(f"  Cleared {len(all_image_ids)} old image(s) and their sightings.\n")


def correlated_random_walk(start_lat, start_lon, n_steps, step_mean_km, turn_std_deg, seed_val, reserve, lake):
    rng = random.Random(seed_val)
    lat, lon = start_lat, start_lon
    heading = rng.uniform(0, 360)
    points = [(lat, lon)]
    for _ in range(n_steps):
        placed, attempts = False, 0
        while not placed and attempts < 15:
            turn = rng.gauss(0, turn_std_deg)
            candidate_heading = (heading + turn) % 360
            step_km = max(0.05, rng.expovariate(1.0 / step_mean_km)) * (0.6 ** attempts)
            rad = math.radians(candidate_heading)
            dlat = (step_km * math.cos(rad)) / KM_PER_DEG_LAT
            dlon = (step_km * math.sin(rad)) / km_per_deg_lon(lat)
            new_lat, new_lon = lat + dlat, lon + dlon
            if is_valid_point(new_lat, new_lon, reserve, lake):
                lat, lon, heading = new_lat, new_lon, candidate_heading
                points.append((lat, lon)); placed = True
            else:
                heading = (heading + 180 + rng.uniform(-40, 40)) % 360
                attempts += 1
        if not placed:
            points.append((lat, lon))
    return points


def main():
    photos = sorted([p for p in SWASTIK_PHOTOS_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".jfif")])
    if not photos:
        print(f"No photos found in {SWASTIK_PHOTOS_DIR} — add his images there first.")
        return

    conn = get_connection()

    _clear_previous_swastik(conn)

    conn.execute("INSERT INTO runs (run_timestamp) VALUES (datetime('now'))")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Reuse the SAME run_id the original 4 tigers' occupancy snapshots were
    # written under, so Swastik's territory shows up alongside theirs
    # (the dashboard only displays the single latest occupancy run_id).
    existing_snapshot_run = conn.execute("SELECT MAX(run_id) FROM occupancy_snapshots").fetchone()[0]
    if existing_snapshot_run is None:
        existing_snapshot_run = run_id

    # Create the tiger row BEFORE processing any photos. Sightings inserted
    # below reference tiger_id via a foreign key, so the tiger must already
    # exist in the tigers table or the insert fails (PRAGMA foreign_keys=ON
    # in src/db.py enforces this immediately, not just at commit time).
    conn.execute(
        "INSERT INTO tigers (tiger_id, first_enrolled_run_id, embedding_vector, notes) VALUES (?, ?, NULL, ?)",
        (TIGER_ID, run_id, NAME),
    )
    conn.commit()

    embedding_to_store = None
    quarantined, subjects, blanks = 0, 0, 0

    for i, img_path in enumerate(photos):
        result = classify_image(str(img_path))
        station_row = conn.execute("SELECT station_id, lat, lon FROM stations ORDER BY RANDOM() LIMIT 1").fetchone()

        cursor = conn.execute(
            """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                    gps_lat, gps_lon, classification, classification_confidence, run_id)
               VALUES (?, ?, datetime('now'), 'real_field_photo', ?, ?, ?, ?, ?)""",
            (str(img_path), station_row[0], station_row[1], station_row[2], result["label"], result["confidence"], run_id),
        )
        conn.commit()
        image_id = cursor.lastrowid

        if result["label"] == "blank":
            blanks += 1
            print(f"  {img_path.name}: BLANK (confidence {result['confidence']})")
            continue
        elif result["label"] == "human":
            print(f"  {img_path.name}: HUMAN — privacy flagged, excluded")
            continue

        subjects += 1
        crop_path, usable = detect_and_crop(str(img_path))
        crop_result = classify_image(crop_path, skip_person_check=True) if crop_path else result

        if crop_result["embedding"] is not None and embedding_to_store is None:
            embedding_to_store = crop_result["embedding"]

        conn.execute(
            """INSERT INTO sightings (image_id, tiger_id, match_confidence, decision_source, flank_usable)
               VALUES (?, ?, 1.0, 'human', ?)""",
            (image_id, TIGER_ID, int(usable)),
        )
        conn.commit()
        print(f"  {img_path.name}: SUBJECT -> assigned to {NAME} (real photo, real classification)")

    # Fill in the real embedding now that photos have been processed. The
    # tiger row itself was already created above (before the sightings loop).
    blob = pickle.dumps(embedding_to_store.detach().numpy()) if embedding_to_store is not None else None
    conn.execute(
        "UPDATE tigers SET embedding_vector = ? WHERE tiger_id = ?",
        (blob, TIGER_ID),
    )
    conn.commit()

    print(f"\nProcessed {len(photos)} real photos: {subjects} subject, {blanks} blank.")

    # Generate an organic territory for him, same method as the other 4.
    with open(BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson") as f:
        reserve = shape(json.load(f)["features"][0]["geometry"])
    with open(BASE_DIR / "data" / "samples" / "pench_lake_approx.geojson") as f:
        lake = shape(json.load(f)["features"][0]["geometry"])

    start_lat, start_lon = 21.705, 79.358  # a spot east of the lake, near the others
    if not is_valid_point(start_lat, start_lon, reserve, lake):
        print("WARNING: Swastik's start point invalid — adjust coordinates manually.")
        conn.close()
        return

    walk_points = correlated_random_walk(start_lat, start_lon, 50, 0.45, 35, seed_val=55, reserve=reserve, lake=lake)

    from shapely.geometry import LineString, mapping
    path_line = LineString([(lon, lat) for lat, lon in walk_points])
    hull = path_line.buffer(0.016, cap_style=1, join_style=1, resolution=8).simplify(0.002, preserve_topology=True)

    area = 0.0
    if hull.geom_type == "Polygon":
        ref_lon, ref_lat = hull.exterior.coords[0]
        km_coords = [((lon - ref_lon) * km_per_deg_lon(ref_lat), (lat - ref_lat) * KM_PER_DEG_LAT) for lon, lat in hull.exterior.coords]
        area = abs(sum(km_coords[i][0]*km_coords[i+1][1] - km_coords[i+1][0]*km_coords[i][1] for i in range(len(km_coords)-1))) / 2.0

    rng = random.Random(555)
    sighting_points = rng.sample(walk_points, min(20, len(walk_points)))
    for plat, plon in sighting_points:
        fake_dt = datetime.now() - timedelta(days=random.randint(0, 10))
        cursor = conn.execute(
            """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                    gps_lat, gps_lon, classification, classification_confidence, run_id)
               VALUES (?, 'ST-012', ?, 'synthetic', ?, ?, 'subject', 0.9, ?)""",
            ("synthetic", fake_dt.isoformat(), plat, plon, run_id),
        )
        conn.commit()
        image_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO sightings (image_id, tiger_id, match_confidence, decision_source, flank_usable) VALUES (?, ?, 0.9, 'human', 1)",
            (image_id, TIGER_ID),
        )
        conn.commit()

    conn.execute(
        """INSERT INTO occupancy_snapshots (tiger_id, run_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson, station_list)
           VALUES (?, ?, ?, ?, ?, ?, '')""",
        (TIGER_ID, existing_snapshot_run, start_lat, start_lon, round(area, 1), json.dumps(mapping(hull))),
    )
    conn.commit()
    conn.close()
    print(f"Swastik's territory generated: {round(area,1)} sq km, added to run_id {existing_snapshot_run} (alongside the other 4).")


if __name__ == "__main__":
    main()