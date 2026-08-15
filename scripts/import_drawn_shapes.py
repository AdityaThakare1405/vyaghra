"""
Reads the .geojson file you exported from scripts/draw_map.py and applies
it to the project:
  - The rectangle you drew becomes the reserve boundary.
  - Each polygon you drew becomes that tiger's home range, with 20
    sighting points scattered inside it and written to the database.
"""

import json
import glob
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from shapely.geometry import shape, mapping, Point

from src.db import get_connection
from src.classification.blank_detector import classify_image
from src.config import BASE_DIR

BEST_TIGERS_DIR = BASE_DIR / "data" / "samples" / "best_tigers"
TIGER_ORDER = ["Virat", "Bheem", "Yuvraj", "Bajirao"]
TIGER_ID_MAP = {"Virat": "T-271", "Bheem": "T-201", "Yuvraj": "T-259", "Bajirao": "T-273"}
KM_PER_DEG_LAT = 111.0


def km_per_deg_lon(lat):
    import math
    return 111.0 * math.cos(math.radians(lat))


def find_downloaded_file():
    downloads = str(Path.home() / "Downloads")
    candidates = glob.glob(os.path.join(downloads, "*vyaghra_drawn_shapes*.geojson")) + \
                 glob.glob(os.path.join(downloads, "*.geojson"))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)  # most recently downloaded


def polygon_area_sq_km(polygon):
    coords = list(polygon.exterior.coords)
    ref_lon, ref_lat = coords[0]
    km_coords = [((lon - ref_lon) * km_per_deg_lon(ref_lat), (lat - ref_lat) * KM_PER_DEG_LAT) for lon, lat in coords]
    return abs(sum(km_coords[i][0] * km_coords[i + 1][1] - km_coords[i + 1][0] * km_coords[i][1]
                    for i in range(len(km_coords) - 1))) / 2.0


def scatter_points_in_polygon(polygon, n_points=20, seed_val=0):
    rng = random.Random(seed_val)
    minx, miny, maxx, maxy = polygon.bounds
    points = []
    attempts = 0
    while len(points) < n_points and attempts < n_points * 50:
        p = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if polygon.contains(p):
            points.append((p.y, p.x))  # (lat, lon)
        attempts += 1
    return points


def main():
    file_path = input("Path to your downloaded .geojson file (press Enter to auto-detect from Downloads): ").strip()
    if not file_path:
        file_path = find_downloaded_file()
        if not file_path:
            print("Could not find a .geojson file in your Downloads folder. Please provide the path manually.")
            return
        print(f"Using: {file_path}")

    with open(file_path) as f:
        data = json.load(f)

    features = data["features"]
    print(f"\nFound {len(features)} drawn shape(s).")

    rectangle_feature = None
    polygon_features = []

    for feat in features:
        geom = shape(feat["geometry"])
        coords = list(geom.exterior.coords)
        # A rectangle drawn with Leaflet.draw has exactly 5 coordinate
        # pairs (4 corners + closing point) forming near-right angles.
        if len(coords) == 5 and rectangle_feature is None:
            rectangle_feature = geom
        else:
            polygon_features.append(geom)

    if rectangle_feature is None:
        print("WARNING: no rectangle detected — skipping boundary update. Draw a rectangle and export again if needed.")
    else:
        boundary_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "Pench Tiger Reserve boundary (user-drawn)"},
                "geometry": mapping(rectangle_feature),
            }],
        }
        boundary_path = BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson"
        with open(boundary_path, "w") as f:
            json.dump(boundary_geojson, f, indent=2)
        print(f"Reserve boundary updated from your drawn rectangle -> {boundary_path}")

    if len(polygon_features) != 4:
        print(f"\nWARNING: expected 4 territory polygons, found {len(polygon_features)}.")
        print("You'll be asked to match each one manually below.")

    conn = get_connection()
    conn.execute("INSERT INTO runs (run_timestamp) VALUES (datetime('now'))")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    print("\nMatching your drawn polygons to tigers (in the order you drew them):")
    for i, poly in enumerate(polygon_features):
        default_name = TIGER_ORDER[i] if i < len(TIGER_ORDER) else None
        centroid = poly.centroid
        prompt = f"  Polygon {i+1} (centroid ~{centroid.y:.4f},{centroid.x:.4f}) -> tiger name"
        prompt += f" [{default_name}]: " if default_name else ": "
        chosen = input(prompt).strip() or default_name

        if chosen not in TIGER_ID_MAP:
            print(f"    Unknown tiger name '{chosen}', skipping this polygon.")
            continue

        tiger_id = TIGER_ID_MAP[chosen]
        area = polygon_area_sq_km(poly)
        points = scatter_points_in_polygon(poly, n_points=20, seed_val=i + 1)

        conn.execute(
            "INSERT OR REPLACE INTO tigers (tiger_id, first_enrolled_run_id, notes) VALUES (?, ?, ?)",
            (tiger_id, run_id, chosen),
        )
        conn.commit()

        tiger_folder = BEST_TIGERS_DIR / f"tiger_{tiger_id.split('-')[1]}"
        images = sorted(tiger_folder.glob("*.jpg")) if tiger_folder.exists() else []

        for j, (plat, plon) in enumerate(points):
            if images:
                img_path = images[j % len(images)]
                result = classify_image(str(img_path))
                conf = result["confidence"]
                original_path = str(img_path)
            else:
                conf = 0.85
                original_path = "synthetic"

            fake_dt = datetime.now() - timedelta(days=random.randint(0, 45))
            cursor = conn.execute(
                """INSERT INTO images (original_path, station_id, capture_timestamp, timestamp_confidence,
                                        gps_lat, gps_lon, classification, classification_confidence, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (original_path, "ST-012", fake_dt.isoformat(), "synthetic", plat, plon, "subject", conf, run_id),
            )
            conn.commit()
            image_id = cursor.lastrowid

            conn.execute(
                """INSERT INTO sightings (image_id, tiger_id, match_confidence, decision_source, flank_usable)
                   VALUES (?, ?, ?, ?, ?)""",
                (image_id, tiger_id, conf, "human", 1),
            )
            conn.commit()

        conn.execute(
            """INSERT INTO occupancy_snapshots
               (tiger_id, run_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson, station_list)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tiger_id, run_id, centroid.y, centroid.x, area, json.dumps(mapping(poly)), ""),
        )
        conn.commit()
        print(f"    -> {chosen}: area={area:.1f} sq km, {len(points)} points scattered inside your drawn shape")

    conn.close()
    print(f"\nDone. Run ID: {run_id}. Launch the dashboard to see your hand-drawn territories.")


if __name__ == "__main__":
    main()