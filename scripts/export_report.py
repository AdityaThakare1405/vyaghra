"""
Exports the latest occupancy + alert state into formats forest department
staff can actually use without opening the database or the dashboard:

  outputs/exports/occupancy_summary.csv   -- one row per tiger: sightings,
                                              centroid, area, stations used
  outputs/exports/occupancy_map.geojson   -- home range polygons, importable
                                              straight into QGIS/ArcGIS
  outputs/exports/alerts_log.csv          -- every alert raised, latest run
  outputs/exports/field_report.pdf        -- one-page-per-tiger plain-language
                                              summary (skipped gracefully if
                                              reportlab isn't installed)

Usage:
    python -m scripts.export_report
    python -m scripts.export_report --run-id 3   # export a specific run
"""

import argparse
import csv
import json

from src.config import BASE_DIR
from src.db import get_connection

EXPORTS_DIR = BASE_DIR / "outputs" / "exports"


def _latest_occupancy_run(conn):
    row = conn.execute("SELECT MAX(run_id) FROM occupancy_snapshots").fetchone()
    return row[0]


def export_occupancy_csv(conn, run_id, out_dir):
    rows = conn.execute(
        """SELECT o.tiger_id, o.centroid_lat, o.centroid_lon, o.area_sq_km,
                  o.station_list, t.notes,
                  (SELECT COUNT(*) FROM sightings s WHERE s.tiger_id = o.tiger_id) as sighting_count
           FROM occupancy_snapshots o
           JOIN tigers t ON o.tiger_id = t.tiger_id
           WHERE o.run_id = ?
           ORDER BY o.area_sq_km DESC""",
        (run_id,),
    ).fetchall()

    path = out_dir / "occupancy_summary.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tiger_id", "total_sightings", "centroid_lat", "centroid_lon",
            "home_range_area_sq_km", "stations_used", "notes",
        ])
        for tiger_id, lat, lon, area, stations, notes, sightings in rows:
            writer.writerow([
                tiger_id, sightings, round(lat, 5), round(lon, 5),
                round(area, 2) if area else "", stations or "", notes or "",
            ])
    return path, len(rows)


def export_occupancy_geojson(conn, run_id, out_dir):
    rows = conn.execute(
        """SELECT tiger_id, area_sq_km, centroid_lat, centroid_lon, home_range_geojson, station_list
           FROM occupancy_snapshots WHERE run_id = ?""",
        (run_id,),
    ).fetchall()

    features = []
    for tiger_id, area, lat, lon, geojson_str, stations in rows:
        if not geojson_str:
            continue
        geometry = json.loads(geojson_str)
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "tiger_id": tiger_id,
                "area_sq_km": round(area, 2) if area else None,
                "centroid_lat": round(lat, 5),
                "centroid_lon": round(lon, 5),
                "stations_used": stations or "",
            },
        })

    collection = {"type": "FeatureCollection", "features": features}
    path = out_dir / "occupancy_map.geojson"
    with open(path, "w") as f:
        json.dump(collection, f, indent=2)
    return path, len(features)


def export_alerts_csv(conn, run_id, out_dir):
    rows = conn.execute(
        """SELECT a.tiger_id, a.alert_type, a.what_changed, a.supporting_evidence,
                  a.confidence_level, a.artefact_flag, r.run_timestamp
           FROM alerts a JOIN runs r ON a.run_id = r.run_id
           ORDER BY a.alert_id DESC"""
    ).fetchall()

    path = out_dir / "alerts_log.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tiger_id", "alert_type", "what_changed", "supporting_evidence",
            "confidence_level", "flagged_as_survey_artefact", "run_timestamp",
        ])
        for tiger_id, alert_type, what_changed, evidence, confidence, artefact, ts in rows:
            writer.writerow([
                tiger_id, alert_type, what_changed, evidence,
                confidence, "yes" if artefact else "no", ts,
            ])
    return path, len(rows)


def export_pdf(conn, run_id, out_dir):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
    except ImportError:
        print("  [PDF export skipped -- run: pip install reportlab]")
        return None, 0

    tigers = conn.execute(
        """SELECT o.tiger_id, o.centroid_lat, o.centroid_lon, o.area_sq_km, o.station_list,
                  (SELECT COUNT(*) FROM sightings s WHERE s.tiger_id = o.tiger_id) as sighting_count
           FROM occupancy_snapshots o WHERE o.run_id = ? ORDER BY o.tiger_id""",
        (run_id,),
    ).fetchall()

    alert_rows = conn.execute(
        """SELECT tiger_id, alert_type, what_changed, confidence_level
           FROM alerts WHERE run_id = ?""",
        (run_id,),
    ).fetchall()
    alerts_by_tiger = {}
    for tiger_id, alert_type, what_changed, confidence in alert_rows:
        alerts_by_tiger.setdefault(tiger_id, []).append((alert_type, what_changed, confidence))

    run_row = conn.execute("SELECT run_timestamp FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    run_ts = run_row[0] if run_row else "unknown"

    path = out_dir / "field_report.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, height - 2 * cm, "Vyaghra -- Pench Tiger Reserve Field Report")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 2.7 * cm, f"Run: {run_id}   Generated from data as of: {run_ts}")
    c.drawString(2 * cm, height - 3.3 * cm, f"Individuals in this report: {len(tigers)}")

    y = height - 4.5 * cm
    for tiger_id, lat, lon, area, stations, sightings in tigers:
        if y < 5 * cm:
            c.showPage()
            y = height - 2 * cm
            c.setFont("Helvetica", 10)

        c.setFont("Helvetica-Bold", 12)
        c.drawString(2 * cm, y, tiger_id)
        y -= 0.6 * cm
        c.setFont("Helvetica", 9)
        c.drawString(2.3 * cm, y, f"Total sightings: {sightings}   Home range: {area:.1f} sq km" if area else f"Total sightings: {sightings}   Home range: not yet computed")
        y -= 0.5 * cm
        c.drawString(2.3 * cm, y, f"Activity centre: {lat:.4f}, {lon:.4f}")
        y -= 0.5 * cm
        c.drawString(2.3 * cm, y, f"Stations used: {stations or '(none recorded)'}")
        y -= 0.5 * cm

        for alert_type, what_changed, confidence in alerts_by_tiger.get(tiger_id, []):
            c.setFillColorRGB(0.7, 0.2, 0.1)
            c.drawString(2.3 * cm, y, f"ALERT [{confidence}] {alert_type}: {what_changed}")
            c.setFillColorRGB(0, 0, 0)
            y -= 0.5 * cm

        y -= 0.4 * cm

    c.save()
    return path, len(tigers)


def main(run_id=None):
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()

    if run_id is None:
        run_id = _latest_occupancy_run(conn)
        if run_id is None:
            print("No occupancy snapshots found yet -- run the pipeline (non-triage) first.")
            return

    print(f"Exporting occupancy/alerts for run_id={run_id}...\n")

    csv_path, n_tigers = export_occupancy_csv(conn, run_id, EXPORTS_DIR)
    print(f"  CSV:     {csv_path}  ({n_tigers} tigers)")

    geo_path, n_features = export_occupancy_geojson(conn, run_id, EXPORTS_DIR)
    print(f"  GeoJSON: {geo_path}  ({n_features} home range polygons)")

    alerts_path, n_alerts = export_alerts_csv(conn, run_id, EXPORTS_DIR)
    print(f"  Alerts:  {alerts_path}  ({n_alerts} alerts, all runs)")

    pdf_path, n_pdf = export_pdf(conn, run_id, EXPORTS_DIR)
    if pdf_path:
        print(f"  PDF:     {pdf_path}  ({n_pdf} tigers)")

    conn.close()
    print("\nDone. These files are what you hand to forest department staff --")
    print("CSV/GeoJSON open in Excel/QGIS, the PDF is print-ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, default=None, help="Export a specific run (default: latest occupancy run)")
    args = parser.parse_args()
    main(run_id=args.run_id)