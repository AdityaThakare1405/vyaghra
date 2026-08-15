"""
Occupancy module: for every tiger, computes home range (Minimum Convex
Polygon), centroid, and area from all its sightings — regenerated fresh
on every run, per the brief's explicit requirement.
"""

import json
from shapely.geometry import MultiPoint, mapping
import geopandas as gpd
from shapely.geometry import MultiPoint, Polygon, mapping

from src.db import get_connection

# UTM zone 44N — covers the Pench Tiger Reserve region, gives much more
# accurate area math than computing directly in raw lat/lon degrees.
UTM_CRS = "EPSG:32644"
WGS84_CRS = "EPSG:4326"


def _chaikin_smooth(points, iterations=4):
    """
    Chaikin's corner-cutting algorithm: repeatedly rounds a polygon's
    corners to produce a smooth, organic curve instead of straight edges
    — used so home range boundaries look like natural animal territories
    rather than a geometric convex hull.
    """
    for _ in range(iterations):
        new_points = []
        n = len(points)
        for i in range(n):
            p0 = points[i]
            p1 = points[(i + 1) % n]
            q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            new_points.extend([q, r])
        points = new_points
    return points

def regenerate_all_occupancy(run_id: int):
    conn = get_connection()

    tiger_ids = [row[0] for row in conn.execute("SELECT tiger_id FROM tigers").fetchall()]
    results = []

    for tiger_id in tiger_ids:
        points = conn.execute(
            """SELECT i.gps_lat, i.gps_lon FROM sightings s
               JOIN images i ON s.image_id = i.image_id
               WHERE s.tiger_id = ? AND i.gps_lat IS NOT NULL AND i.gps_lon IS NOT NULL""",
            (tiger_id,),
        ).fetchall()

        if len(points) < 3:
            print(f"  {tiger_id}: only {len(points)} sighting(s), skipping (need 3+ for a home range)")
            continue

        gdf = gpd.GeoDataFrame(
            geometry=gpd.points_from_xy([p[1] for p in points], [p[0] for p in points]),
            crs=WGS84_CRS,
        ).to_crs(UTM_CRS)

        multipoint = MultiPoint(list(gdf.geometry))
        raw_hull = multipoint.convex_hull

        # Smooth the hull's straight edges into a natural, organic curve.
        if raw_hull.geom_type == "Polygon":
            hull_coords = list(raw_hull.exterior.coords)[:-1]  # drop repeated closing point
            smoothed_coords = _chaikin_smooth(hull_coords, iterations=4)
            hull = Polygon(smoothed_coords)
        else:
            hull = raw_hull  # fallback for degenerate cases (e.g. a line, not enough spread)

        area_sq_km = hull.area / 1_000_000
        centroid_utm = hull.centroid

        centroid_gdf = gpd.GeoDataFrame(geometry=[centroid_utm], crs=UTM_CRS).to_crs(WGS84_CRS)
        centroid_lat, centroid_lon = centroid_gdf.geometry[0].y, centroid_gdf.geometry[0].x

        hull_gdf = gpd.GeoDataFrame(geometry=[hull], crs=UTM_CRS).to_crs(WGS84_CRS)
        hull_geojson = json.dumps(mapping(hull_gdf.geometry[0]))

        conn.execute(
            """INSERT INTO occupancy_snapshots
               (tiger_id, run_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson, station_list)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tiger_id, run_id, centroid_lat, centroid_lon, area_sq_km, hull_geojson, ""),
        )

        results.append({
            "tiger_id": tiger_id,
            "sightings_used": len(points),
            "centroid_lat": round(centroid_lat, 4),
            "centroid_lon": round(centroid_lon, 4),
            "area_sq_km": round(area_sq_km, 2),
        })

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    # Test against whatever's currently in the database from run_pipeline.py.
    latest_run_id = 1  # adjust if you've run the pipeline more than once
    output = regenerate_all_occupancy(run_id=latest_run_id)
    print("\nOccupancy snapshots created:")
    for r in output:
        print(f"  {r}")