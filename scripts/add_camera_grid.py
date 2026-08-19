"""
Adds a true equidistant grid of camera stations across the reserve — evenly
spaced rows and columns (like the intersections of an invisible grid),
filtered to only keep points actually inside the reserve boundary and
outside the lake. No randomness — pure uniform spacing.
"""

import json
from shapely.geometry import Point, shape

from src.db import get_connection
from src.config import BASE_DIR

BOUNDARY_PATH = BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson"
LAKE_PATH = BASE_DIR / "data" / "samples" / "pench_lake_approx.geojson"

GRID_COLS = 12  # number of equally-spaced vertical lines
GRID_ROWS = 12  # number of equally-spaced horizontal lines


def main():
    with open(BOUNDARY_PATH) as f:
        boundary = shape(json.load(f)["features"][0]["geometry"])
    with open(LAKE_PATH) as f:
        lake = shape(json.load(f)["features"][0]["geometry"])

    minlon, minlat, maxlon, maxlat = boundary.bounds
    conn = get_connection()

    # Clear any previous grid stations first, so re-running this script
    # never leaves stale/duplicate points behind.
    conn.execute("DELETE FROM stations WHERE station_id LIKE 'GRID-%'")
    conn.commit()

    count = 0
    for i in range(GRID_COLS):
        lon = minlon + (maxlon - minlon) * (i + 0.5) / GRID_COLS
        for j in range(GRID_ROWS):
            lat = minlat + (maxlat - minlat) * (j + 0.5) / GRID_ROWS
            p = Point(lon, lat)
            if boundary.contains(p) and not lake.contains(p):
                station_id = f"GRID-{count:03d}"
                zone = "core" if lake.distance(p) < 0.08 else "buffer"
                conn.execute(
                    "INSERT OR REPLACE INTO stations (station_id, zone, lat, lon, install_date) VALUES (?, ?, ?, ?, ?)",
                    (station_id, zone, lat, lon, "2023-01-15"),
                )
                count += 1
    conn.commit()
    conn.close()
    print(f"Added {count} equidistant grid camera stations ({GRID_COLS}x{GRID_ROWS} grid, filtered to reserve/lake).")


if __name__ == "__main__":
    main()