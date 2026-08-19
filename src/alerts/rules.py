"""
Alerting module: diffs each tiger's current occupancy snapshot against its
previous one and raises alerts for meaningful change, per the brief's four
required triggers. Includes the "new station != deviation" artefact guard
explicitly described in the brief.
"""

import json

from geopy.distance import geodesic
from shapely.geometry import shape, Point

from src.config import (
    BUFFER_ZONE_SHIFT_THRESHOLD_KM,
    CORE_ZONE_SHIFT_THRESHOLD_SQKM,
    CORE_ZONE_SHIFT_THRESHOLD_SQKM_HIGH,
    ABSENCE_MULTIPLIER,
    BASE_DIR,
)
from src.db import get_connection

BOUNDARY_PATH = BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson"
BUFFER_PATH = BASE_DIR / "data" / "samples" / "pench_buffer_approx.geojson"


def _load_zone(path):
    if not path.exists():
        return None
    with open(path) as f:
        geo = json.load(f)["features"][0]["geometry"]
    return shape(geo)


def run_alert_checks(run_id: int):
    conn = get_connection()
    tiger_ids = [row[0] for row in conn.execute("SELECT tiger_id FROM tigers").fetchall()]
    alerts_raised = []

    reserve_geom = _load_zone(BOUNDARY_PATH)
    buffer_geom = _load_zone(BUFFER_PATH)
    if reserve_geom is None or buffer_geom is None:
        print("  (No reserve boundary / buffer zone file found yet — skipping reserve-exit checks. "
              "Run scripts/draw_map.py + scripts/import_drawn_shapes.py to set them.)")

    for tiger_id in tiger_ids:
        if reserve_geom is not None and buffer_geom is not None:
            _check_reserve_exit(conn, tiger_id, run_id, alerts_raised, reserve_geom, buffer_geom)

        snapshots = conn.execute(
            """SELECT snapshot_id, centroid_lat, centroid_lon, area_sq_km, run_id
               FROM occupancy_snapshots WHERE tiger_id = ? ORDER BY run_id DESC LIMIT 2""",
            (tiger_id,),
        ).fetchall()

        if len(snapshots) < 2:
            print(f"  {tiger_id}: only {len(snapshots)} occupancy snapshot(s), skipping (need 2+ runs of history)")
        else:
            _check_range_shift(conn, tiger_id, run_id, alerts_raised, snapshots, reserve_geom)

        _check_new_station(conn, tiger_id, run_id, alerts_raised)
        _check_absence(conn, tiger_id, run_id, alerts_raised)

    conn.close()
    return alerts_raised


def _check_range_shift(conn, tiger_id, run_id, alerts_raised, snapshots, reserve_geom):
    """
    Zone-aware version of the brief's range-centroid-shift trigger:
      - CORE zone: brief gives an area-based tolerance (15-20 sq km), so we
        compare the home-range AREA between this run and the last one.
        15-20 sq km change -> medium confidence, >20 sq km -> high.
      - BUFFER (or unknown) zone: brief gives a straight distance tolerance
        (5 km), so we compare centroid-to-centroid distance instead — near
        village-adjacent stations, exact distance matters more than area.
    Zone is decided by whether the CURRENT centroid falls inside the
    reserve's core boundary polygon; falls back to the buffer/distance
    check if no boundary file has been loaded yet.
    """
    current, previous = snapshots[0], snapshots[1]
    cur_lat, cur_lon = current[1], current[2]
    prev_lat, prev_lon = previous[1], previous[2]
    cur_area, prev_area = current[3], previous[3]

    in_core = reserve_geom is not None and reserve_geom.contains(Point(cur_lon, cur_lat))

    if in_core:
        area_shift = abs((cur_area or 0) - (prev_area or 0))
        if area_shift > CORE_ZONE_SHIFT_THRESHOLD_SQKM_HIGH:
            confidence = "high"
        elif area_shift > CORE_ZONE_SHIFT_THRESHOLD_SQKM:
            confidence = "medium"
        else:
            print(f"  {tiger_id}: core zone, area shift={area_shift:.2f} sq km, within normal range, no alert")
            return
        alert = _raise_alert(
            conn, tiger_id, run_id, "range_shift",
            what_changed=f"Home range area shifted {area_shift:.1f} sq km since last run (core zone)",
            evidence=f"Previous area: {prev_area:.1f} sq km -> Current: {cur_area:.1f} sq km",
            confidence=confidence,
        )
        alerts_raised.append(alert)
        print(f"  ALERT [{tiger_id}] range_shift (core, area-based): {area_shift:.2f} sq km shift")
    else:
        shift_km = geodesic((prev_lat, prev_lon), (cur_lat, cur_lon)).km
        if shift_km > BUFFER_ZONE_SHIFT_THRESHOLD_KM:
            alert = _raise_alert(
                conn, tiger_id, run_id, "range_shift",
                what_changed=f"Centroid shifted {shift_km:.1f} km since last run (buffer zone)",
                evidence=f"Previous centroid: ({prev_lat:.4f},{prev_lon:.4f}) -> Current: ({cur_lat:.4f},{cur_lon:.4f})",
                confidence="high" if shift_km > BUFFER_ZONE_SHIFT_THRESHOLD_KM * 1.5 else "medium",
            )
            alerts_raised.append(alert)
            print(f"  ALERT [{tiger_id}] range_shift (buffer, distance-based): {shift_km:.2f} km shift")
        else:
            print(f"  {tiger_id}: buffer/unknown zone, shift={shift_km:.3f} km, within normal range, no alert")


def _check_new_station(conn, tiger_id, run_id, alerts_raised):
    stations_used = conn.execute(
        """SELECT DISTINCT i.station_id, s.install_date FROM sightings sg
           JOIN images i ON sg.image_id = i.image_id
           JOIN stations s ON i.station_id = s.station_id
           WHERE sg.tiger_id = ?""",
        (tiger_id,),
    ).fetchall()

    for station_id, install_date in stations_used:
        first_seen_here = conn.execute(
            """SELECT MIN(i.capture_timestamp) FROM sightings sg
               JOIN images i ON sg.image_id = i.image_id
               WHERE sg.tiger_id = ? AND i.station_id = ?""",
            (tiger_id, station_id),
        ).fetchone()[0]

        # Our test images don't have real EXIF timestamps, so first_seen_here
        # will often be None — skip the artefact check gracefully in that case
        # rather than crashing on a string comparison against None.
        if first_seen_here is None:
            continue

        is_artefact = install_date is not None and install_date >= first_seen_here[:10]

        # (Simplified for demo data: since we don't have reliable "is this the very
        # newest sighting" logic without real timestamps, this checks every
        # tiger/station pairing each run rather than only the latest one.)
        already_alerted = any(
            a["alert_type"] == "new_station" and a["tiger_id"] == tiger_id
            for a in alerts_raised
        )
        if not already_alerted:
            alert = _raise_alert(
                conn, tiger_id, run_id, "new_station",
                what_changed=f"Capture at station {station_id}",
                evidence=f"Station install date: {install_date}, first capture: {first_seen_here}",
                confidence="low" if is_artefact else "medium",
                artefact_flag=is_artefact,
            )
            alerts_raised.append(alert)


def _check_absence(conn, tiger_id, run_id, alerts_raised):
    timestamps = [row[0] for row in conn.execute(
        """SELECT i.capture_timestamp FROM sightings sg
           JOIN images i ON sg.image_id = i.image_id
           WHERE sg.tiger_id = ? ORDER BY i.capture_timestamp""",
        (tiger_id,),
    ).fetchall() if row[0] is not None]

    if len(timestamps) < 3:
        return  # not enough real timestamp history in this test data

    from datetime import datetime
    dates = [datetime.fromisoformat(t) for t in timestamps]
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    avg_gap = sum(gaps) / len(gaps) if gaps else 0
    days_since_last = (datetime.now() - dates[-1]).days

    if avg_gap > 0 and days_since_last > avg_gap * ABSENCE_MULTIPLIER:
        alert = _raise_alert(
            conn, tiger_id, run_id, "prolonged_absence",
            what_changed=f"Not seen for {days_since_last} days (normal interval ~{avg_gap:.0f} days)",
            evidence=f"Last seen: {dates[-1].isoformat()}",
            confidence="medium",
        )
        alerts_raised.append(alert)


def _check_reserve_exit(conn, tiger_id, run_id, alerts_raised, reserve_geom, buffer_geom):
    """Checks this tiger's most recent sightings against the reserve
    boundary and the buffer zone drawn/generated around it:
      - a point outside the buffer zone entirely -> high-confidence
        'reserve_exit' alert (the tiger has left the whole reserve system —
        the scenario the person asked to be alerted about)
      - a point outside the core reserve but still inside the buffer zone
        -> medium-confidence 'buffer_zone_entry' alert (still on the
        reserve's periphery, worth flagging early rather than waiting for
        a full exit)
    Only the tiger's most recent 10 sightings are checked, so this reflects
    current behaviour rather than raising alerts for old, already-reviewed
    positions.
    """
    recent_points = conn.execute(
        """SELECT i.gps_lat, i.gps_lon, i.capture_timestamp, i.station_id
           FROM sightings sg JOIN images i ON sg.image_id = i.image_id
           WHERE sg.tiger_id = ? AND i.gps_lat IS NOT NULL AND i.gps_lon IS NOT NULL
           ORDER BY i.capture_timestamp DESC LIMIT 10""",
        (tiger_id,),
    ).fetchall()

    outside_buffer = None
    outside_reserve_only = None
    for lat, lon, ts, station_id in recent_points:
        p = Point(lon, lat)
        if not buffer_geom.contains(p):
            outside_buffer = (lat, lon, ts, station_id)
            break
        if not reserve_geom.contains(p):
            if outside_reserve_only is None:
                outside_reserve_only = (lat, lon, ts, station_id)

    if outside_buffer is not None:
        lat, lon, ts, station_id = outside_buffer
        alert = _raise_alert(
            conn, tiger_id, run_id, "reserve_exit",
            what_changed=f"Sighting recorded outside the reserve buffer zone at ({lat:.4f}, {lon:.4f})",
            evidence=f"Station: {station_id or '—'}, timestamp: {ts or '—'}",
            confidence="high",
        )
        alerts_raised.append(alert)
        print(f"  ALERT [{tiger_id}] reserve_exit: sighting at ({lat:.4f},{lon:.4f}) is outside the buffer zone")
    elif outside_reserve_only is not None:
        lat, lon, ts, station_id = outside_reserve_only
        alert = _raise_alert(
            conn, tiger_id, run_id, "buffer_zone_entry",
            what_changed=f"Sighting recorded outside the core reserve, in the buffer zone, at ({lat:.4f}, {lon:.4f})",
            evidence=f"Station: {station_id or '—'}, timestamp: {ts or '—'}",
            confidence="medium",
        )
        alerts_raised.append(alert)
        print(f"  ALERT [{tiger_id}] buffer_zone_entry: sighting at ({lat:.4f},{lon:.4f}) is in the buffer zone")
    else:
        print(f"  {tiger_id}: all recent sightings within the reserve boundary, no zone alert")


def _raise_alert(conn, tiger_id, run_id, alert_type, what_changed, evidence, confidence, artefact_flag=False):
    conn.execute(
        """INSERT INTO alerts (tiger_id, run_id, alert_type, what_changed, supporting_evidence,
                                confidence_level, artefact_flag)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (tiger_id, run_id, alert_type, what_changed, evidence, confidence, int(artefact_flag)),
    )
    conn.commit()
    return {"tiger_id": tiger_id, "alert_type": alert_type, "what_changed": what_changed,
            "confidence": confidence, "artefact_flag": artefact_flag}


if __name__ == "__main__":
    _conn = get_connection()
    _latest_run = _conn.execute("SELECT MAX(run_id) FROM runs").fetchone()[0] or 1
    _conn.close()
    print(f"Running alert checks for run_id={_latest_run}...\n")
    alerts = run_alert_checks(run_id=_latest_run)
    print(f"\n{len(alerts)} alert(s) raised:")
    for a in alerts:
        print(f"  {a}")