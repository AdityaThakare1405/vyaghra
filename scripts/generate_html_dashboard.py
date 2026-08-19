"""
Replicates the TigerLens Figma reference design as a single-file HTML SPA:
sidebar navigation across 5 pages (Overview, Blank Filter, Tiger ID,
Occupancy, Alerts), sand/forest-green color scheme, with real data from
the Vyaghra database, a REAL Leaflet map with triangle camera-station
markers on the Occupancy page, and EN/HI/MR language toggle.

A separate companion to the working Streamlit app (src/dashboard/app.py),
which is left untouched. Run any time after processing/seeding data to
regenerate with fresh numbers.
"""

import base64
import hashlib
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from datetime import datetime

from PIL import Image
from shapely.geometry import shape

from src.config import DB_PATH, BASE_DIR

OUTPUT_PATH = BASE_DIR / "outputs" / "vyaghra_dashboard.html"
BOUNDARY_PATH = BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson"
BUFFER_PATH = BASE_DIR / "data" / "samples" / "pench_buffer_approx.geojson"
# Small thumb for list rows/avatars; a much bigger, higher-quality size for
# the tiger detail photo gallery so real ATRW photos are actually viewable,
# not just a low-res placeholder circle.
THUMB_SIZE = (280, 280)
GALLERY_SIZE = (900, 900)
GALLERY_MAX_PHOTOS = 8
KM_PER_DEG_LAT = 111.0


def km_per_deg_lon(lat):
    import math
    return 111.0 * math.cos(math.radians(lat))


def polygon_area_sq_km(polygon):
    coords = list(polygon.exterior.coords)
    ref_lon, ref_lat = coords[0]
    km_coords = [((lon - ref_lon) * km_per_deg_lon(ref_lat), (lat - ref_lat) * KM_PER_DEG_LAT) for lon, lat in coords]
    return abs(sum(km_coords[i][0] * km_coords[i + 1][1] - km_coords[i + 1][0] * km_coords[i][1]
                    for i in range(len(km_coords) - 1))) / 2.0


def image_to_data_uri(path_str, size=THUMB_SIZE, quality=80):
    try:
        p = Path(path_str)
        if not p.exists():
            return None
        img = Image.open(p).convert("RGB")
        img.thumbnail(size)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        return None


def stripe_bars(tiger_id, n=28):
    """Deterministic illustrative bar pattern from a hash of the tiger ID —
    NOT a real stripe extraction (we don't have that data), clearly
    labeled as illustrative in the UI."""
    h = hashlib.md5(tiger_id.encode()).hexdigest()
    return [30 + (int(h[i % len(h)], 16) % 5) * 3 for i in range(n)]


def fetch_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with open(BOUNDARY_PATH) as f:
        boundary_geom = json.load(f)["features"][0]["geometry"]
    boundary_shape = shape(boundary_geom)
    reserve_area = polygon_area_sq_km(boundary_shape)

    buffer_geom = None
    if BUFFER_PATH.exists():
        with open(BUFFER_PATH) as f:
            buffer_geom = json.load(f)["features"][0]["geometry"]

    tigers = conn.execute("SELECT tiger_id, notes, first_enrolled_run_id FROM tigers").fetchall()
    name_lookup = {t["tiger_id"]: (t["notes"] or t["tiger_id"]) for t in tigers}

    latest_run = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    latest_run_id = latest_run["run_id"] if latest_run else None

    snapshot_run_id = conn.execute("SELECT MAX(run_id) FROM occupancy_snapshots").fetchone()[0]
    snapshots = conn.execute(
        """SELECT tiger_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson
           FROM occupancy_snapshots WHERE run_id = ?""", (snapshot_run_id,)
    ).fetchall() if snapshot_run_id else []

    import colorsys

    def _distinct_color(index, total):
        """Generates a distinct color per index using the golden-angle hue
        step — guarantees every tiger gets a visually distinct color no
        matter how many tigers exist (unlike a fixed short palette, which
        repeats once you run out of entries). Saturation/lightness are
        nudged slightly per index too, so hues that land close together
        (e.g. with 20+ tigers) still read as visually different."""
        hue = (index * 0.618033988749895) % 1.0  # golden ratio conjugate
        lightness = 0.40 + 0.10 * ((index // 3) % 3) / 2.0
        saturation = 0.55 + 0.20 * (index % 3) / 2.0
        r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
        return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))

    tiger_detail = {}
    occupancy_rows = []
    shapely_polys = {}
    tiger_color = {}

    all_stations = conn.execute("SELECT station_id, lat, lon, zone FROM stations").fetchall()
    station_project = [{"id": st["station_id"], "lat": st["lat"], "lon": st["lon"]} for st in all_stations]

    for idx, s in enumerate(snapshots):
        tid = s["tiger_id"]
        geo = json.loads(s["home_range_geojson"])
        poly = shape(geo)
        shapely_polys[tid] = poly

        sightings = conn.execute(
            """SELECT i.gps_lat, i.gps_lon, i.station_id, i.capture_timestamp, i.original_path, sg.match_confidence
               FROM sightings sg JOIN images i ON sg.image_id = i.image_id WHERE sg.tiger_id = ?""", (tid,)
        ).fetchall()
        stations_used = len(set(r["station_id"] for r in sightings if r["station_id"]))
        timestamps = sorted([r["capture_timestamp"] for r in sightings if r["capture_timestamp"]])
        first_seen = timestamps[0][:10] if timestamps else "—"
        last_seen = timestamps[-1][:10] if timestamps else "—"

        photo_rows = [r for r in sightings if r["original_path"] and r["original_path"] != "synthetic"]
        photo_row = photo_rows[0] if photo_rows else None
        avatar = image_to_data_uri(photo_row["original_path"], size=THUMB_SIZE) if photo_row else None

        # Real, higher-resolution image gallery for this tiger — every
        # distinct real ATRW/field photo on file for them, deduplicated and
        # capped so the page stays a reasonable size.
        seen_paths = set()
        gallery = []
        for r in photo_rows:
            path = r["original_path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            data_uri = image_to_data_uri(path, size=GALLERY_SIZE, quality=90)
            if data_uri:
                gallery.append(data_uri)
            if len(gallery) >= GALLERY_MAX_PHOTOS:
                break

        color = _distinct_color(idx, len(snapshots))
        tiger_color[tid] = color
        occupancy_rows.append({
            "id": tid, "name": name_lookup.get(tid, tid), "color": color,
            "area": round(s["area_sq_km"], 1), "geojson": geo,
            "cx": s["centroid_lat"], "cy": s["centroid_lon"],
            "stations_used": stations_used, "centroid_lat": round(s["centroid_lat"], 4),
            "centroid_lon": round(s["centroid_lon"], 4),
        })

        tiger_detail[tid] = {
            "id": tid, "name": name_lookup.get(tid, tid), "sex": "—", "color": color,
            "avatar": avatar, "gallery": gallery, "first_seen": first_seen, "last_seen": last_seen,
            "total_sightings": len(sightings), "stripe_bars": stripe_bars(tid),
        }

    overlaps = []
    tids = list(shapely_polys.keys())
    overlap_tiger_ids = set()
    for i in range(len(tids)):
        for j in range(i + 1, len(tids)):
            inter = shapely_polys[tids[i]].intersection(shapely_polys[tids[j]])
            if not inter.is_empty and inter.geom_type == "Polygon" and inter.area > 0:
                km2 = polygon_area_sq_km(inter)
                if km2 > 0.05:
                    overlaps.append({"a": name_lookup.get(tids[i], tids[i]), "b": name_lookup.get(tids[j], tids[j]),
                                      "sq_km": round(km2, 1)})
                    overlap_tiger_ids.add(tids[i]); overlap_tiger_ids.add(tids[j])

    for row in occupancy_rows:
        row["has_overlap"] = row["id"] in overlap_tiger_ids

    # ── Multi-run occupancy history, for the animated/real-time map ──
    # Every run's snapshot (home range polygon + centroid + area) per tiger,
    # plus the exact sighting points captured specifically during that run.
    # This is what lets the map show each tiger's colored triangle sitting
    # at a different point every time you step to a different run, and the
    # home-range polygon growing/shifting across runs.
    all_snapshot_rows = conn.execute(
        """SELECT run_id, tiger_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson
           FROM occupancy_snapshots ORDER BY run_id ASC"""
    ).fetchall()

    run_points_rows = conn.execute(
        """SELECT i.run_id, sg.tiger_id, i.gps_lat, i.gps_lon, i.station_id, i.capture_timestamp
           FROM sightings sg JOIN images i ON sg.image_id = i.image_id
           WHERE sg.tiger_id IS NOT NULL AND i.gps_lat IS NOT NULL AND i.gps_lon IS NOT NULL
           ORDER BY i.run_id ASC"""
    ).fetchall()

    points_by_run_tiger = {}
    for r in run_points_rows:
        key = (r["run_id"], r["tiger_id"])
        points_by_run_tiger.setdefault(key, []).append({
            "lat": r["gps_lat"], "lon": r["gps_lon"],
            "station": r["station_id"], "ts": (r["capture_timestamp"] or "")[:16],
        })

    occupancy_history = {}
    run_ids_all = sorted({row["run_id"] for row in all_snapshot_rows})
    for row in all_snapshot_rows:
        tid = row["tiger_id"]
        rid = row["run_id"]
        occupancy_history.setdefault(tid, {})[rid] = {
            "cx": row["centroid_lat"], "cy": row["centroid_lon"],
            "area": round(row["area_sq_km"], 2),
            "geojson": json.loads(row["home_range_geojson"]),
            "color": tiger_color.get(tid, "#4A7A3E"),
            "name": name_lookup.get(tid, tid),
            "points": points_by_run_tiger.get((rid, tid), []),
        }

    catalogue = [{"id": tid, "name": d["name"], "sex": d["sex"], "avatar": d["avatar"], "color": d["color"]}
                 for tid, d in tiger_detail.items()]

    frames = []
    if latest_run_id:
        frame_rows = conn.execute(
            """SELECT image_id, original_path, classification, classification_confidence
               FROM images WHERE run_id = ? ORDER BY image_id LIMIT 40""", (latest_run_id,)
        ).fetchall()
        for r in frame_rows:
            thumb = None
            if r["classification"] == "subject" and r["original_path"] != "synthetic":
                thumb = image_to_data_uri(r["original_path"])
            frames.append({
                "id": f"F-{r['image_id']:04d}", "status": r["classification"] or "blank",
                "confidence": round((r["classification_confidence"] or 0) * 100), "thumb": thumb,
            })

    blanks_quarantined = conn.execute("SELECT SUM(images_quarantined) FROM runs").fetchone()[0] or 0
    subjects_retained = conn.execute("SELECT COUNT(*) FROM images WHERE classification = 'subject'").fetchone()[0]

    pending = conn.execute(
        """SELECT sighting_id, match_confidence FROM sightings WHERE tiger_id IS NULL ORDER BY sighting_id DESC LIMIT 12"""
    ).fetchall()
    ambiguous = [{"id": f"S-{r['sighting_id']:04d}", "confidence": round((r["match_confidence"] or 0) * 100)}
                 for r in pending]
    auto_count = conn.execute("SELECT COUNT(*) FROM sightings WHERE decision_source = 'auto'").fetchone()[0]

    alert_rows = conn.execute(
        """SELECT a.tiger_id, a.alert_type, a.what_changed, a.supporting_evidence, a.confidence_level,
                  a.artefact_flag, r.run_timestamp
           FROM alerts a JOIN runs r ON a.run_id = r.run_id ORDER BY a.alert_id DESC LIMIT 30"""
    ).fetchall()
    alerts = []
    for i, a in enumerate(alert_rows):
        severity = "low" if a["artefact_flag"] else (a["confidence_level"] or "medium")
        alerts.append({
            "id": f"ALT-{i+1:03d}", "severity": severity, "title": a["alert_type"].replace("_", " ").title(),
            "tiger": name_lookup.get(a["tiger_id"], a["tiger_id"]), "date": (a["run_timestamp"] or "")[:10],
            "what": a["what_changed"], "evidence": a["supporting_evidence"],
        })
    high_count = len([a for a in alerts if a["severity"] == "high"])
    medium_count = len([a for a in alerts if a["severity"] == "medium"])
    low_count = len([a for a in alerts if a["severity"] == "low"])

    total_images_ever = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    total_stations = len(all_stations)
    covered_area = sum(r["area"] for r in occupancy_rows)

    conn.close()

    return {
        "overview": {
            "images_processed": total_images_ever, "images_today": latest_run["images_processed"] if latest_run else 0,
            "blanks_removed": int(blanks_quarantined),
            "blanks_pct": round((blanks_quarantined / total_images_ever * 100) if total_images_ever else 0, 1),
            "tigers_identified": len(tiger_detail), "active_alerts": high_count + medium_count,
            "high_priority": high_count, "run_started": latest_run["run_timestamp"] if latest_run else "—",
            "run_duration": f"{latest_run['time_taken_sec']:.0f}s" if latest_run and latest_run["time_taken_sec"] else "—",
            "stations": total_stations,
        },
        "blank_filter": {"quarantined": int(blanks_quarantined), "retained": subjects_retained,
                          "awaiting": len(pending), "frames": frames},
        "tiger_id": {"known": len(tiger_detail), "auto_matched": auto_count, "awaiting": len(pending),
                     "catalogue": catalogue, "detail": tiger_detail, "ambiguous": ambiguous},
        "occupancy": {"mapped": len(occupancy_rows), "overlap_pairs": len(overlaps), "total_area": round(covered_area, 1),
                      "reserve_area": round(reserve_area, 1), "rows": occupancy_rows, "overlaps": overlaps,
                      "boundary": boundary_geom, "buffer": buffer_geom, "stations": station_project,
                      "history": occupancy_history, "run_ids": run_ids_all},
        "alerts_page": {"high": high_count, "medium": medium_count, "low": low_count, "alerts": alerts},
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }


I18N = {
    "en": {
        "brand": "TigerLens", "brand_sub": "Pench Tiger Reserve", "pipeline_active": "Pipeline active",
        "nav_overview": "Overview", "nav_overview_sub": "System summary",
        "nav_blank": "Blank Filter", "nav_blank_sub": "Image triage",
        "nav_tiger": "Tiger ID", "nav_tiger_sub": "Stripe matching",
        "nav_occupancy": "Occupancy", "nav_occupancy_sub": "Area mapping",
        "nav_alerts": "Alerts", "nav_alerts_sub": "Deviation & trends",
        "overview_title": "System Overview", "overview_sub": "Camera Trap Intelligence · Pench Tiger Reserve",
        "images_processed": "Images Processed", "blanks_removed": "Blanks Removed",
        "tigers_identified": "Tigers Identified", "active_alerts": "Active Alerts",
        "of_total": "of total", "new_this_cycle": "new this cycle", "high_priority_tag": "high-priority",
        "deliverables": "Deliverables", "operational": "Operational", "view_details": "View details →",
        "d1_title": "Blank Image Filtering", "d1_desc": "Ingests raw SD-card directories and classifies every frame as blank or subject-containing. Safe quarantine with confidence thresholds — no irreversible deletion.",
        "d2_title": "Individual Tiger ID", "d2_desc": "Flank detection → stripe extraction → catalogue matching. Auto-enrols new individuals, surfaces ambiguous matches for human review.",
        "d3_title": "Area Occupancy Map", "d3_desc": "Per-individual home range estimation and centroid mapping, regenerated on every pipeline run. Territorial overlap visible as a management signal.",
        "d4_title": "Deviation & Trend Alerts", "d4_desc": "Compares each run against established individual history. Flags range shifts, novel station visits, buffer-adjacent movement, and prolonged absences.",
        "last_run": "Last Pipeline Run", "started": "Started", "duration": "Duration", "stations": "Stations", "hardware": "Hardware",
        "blank_title": "Blank Image Filter", "blank_sub": "Deliverable 1 — Automated triage and safe removal",
        "quarantined": "Blanks quarantined", "retained": "Subjects retained", "awaiting_review": "Awaiting review",
        "threshold": "Confidence threshold", "threshold_note": "Frames below threshold are staged for human review, not deleted",
        "f_all": "All", "f_blank": "Blank", "f_subject": "Subject",
        "frame_results": "Frame results", "shown": "shown", "quarantine_note": "Blanks are quarantined at ./quarantine/ — safe to restore.",
        "tiger_title": "Individual Tiger ID", "tiger_sub": "Deliverable 2 — Stripe-pattern matching & persistent database",
        "known_individuals": "Known individuals", "auto_matched": "Auto-matched this run", "human_review": "Awaiting human review",
        "catalogue": "Individual catalogue", "known_individual": "Known individual", "sex": "Sex",
        "first_seen": "First seen", "last_seen": "Last seen", "total_sightings": "Total sightings",
        "stripe_sig": "Stripe signature (illustrative)", "stripe_note": "Placeholder pattern — real stripe-extraction visualization not shown here",
        "gallery_title": "Photo gallery (real ATRW images)", "gallery_note": "photo(s) on file — click to view full resolution",
        "gallery_empty": "No real photos on file for this individual yet — showing synthetic/placeholder data only.",
        "ambiguous": "Ambiguous matches — human review queue", "conf": "conf", "review_btn": "Review",
        "low_conf_note": "Low-confidence match — needs human confirmation",
        "occ_title": "Area Occupancy Map", "occ_sub": "Deliverable 3 — Territory visualisation per individual",
        "mapped": "Individuals mapped", "overlaps": "Territorial overlaps", "pairs": "pairs", "area_covered": "Total area covered",
        "filter_individual": "Filter by individual", "all_individuals": "All individuals",
        "map_title": "PENCH TIGER RESERVE — AREA OCCUPANCY MAP",
        "legend_station": "Camera station", "legend_boundary": "Reserve boundary", "legend_buffer": "Buffer zone", "legend_overlap": "Overlap = territorial signal",
        "summary_table": "Individual occupancy summary", "col_area": "Area (km²)",
        "col_centroid": "Centroid lat/lng", "col_stations": "Stations used", "col_overlap": "Overlap",
        "yes": "Yes", "no": "No",
        "alerts_title": "Deviation & Trend Alerts", "alerts_sub": "Deliverable 4 — Movement intelligence and behavioural signals",
        "high": "High priority", "medium": "Medium", "low": "Low / informational", "all_alerts": "All Alerts",
        "supporting_evidence": "Supporting evidence", "mark_resolved": "Mark resolved", "view_frames": "View frames", "export_report": "Export report",
        "artefact_note": "Likely survey artefact — flagged as low/informational rather than a genuine deviation.",
        "footer_v": "v1.0 · Hackathon 2026", "footer_track": "Forest & Wildlife Track", "light": "Light", "dark": "Dark",
    },
    "hi": {
        "brand": "टाइगरलेंस", "brand_sub": "पेंच टाइगर रिज़र्व", "pipeline_active": "पाइपलाइन सक्रिय",
        "nav_overview": "अवलोकन", "nav_overview_sub": "सिस्टम सारांश",
        "nav_blank": "रिक्त फ़िल्टर", "nav_blank_sub": "छवि छँटाई",
        "nav_tiger": "बाघ पहचान", "nav_tiger_sub": "धारी मिलान",
        "nav_occupancy": "क्षेत्र अधिभोग", "nav_occupancy_sub": "क्षेत्र मानचित्रण",
        "nav_alerts": "चेतावनियाँ", "nav_alerts_sub": "विचलन और रुझान",
        "overview_title": "सिस्टम अवलोकन", "overview_sub": "कैमरा ट्रैप बुद्धिमत्ता · पेंच टाइगर रिज़र्व",
        "images_processed": "संसाधित छवियाँ", "blanks_removed": "हटाई गई रिक्त छवियाँ",
        "tigers_identified": "पहचाने गए बाघ", "active_alerts": "सक्रिय चेतावनियाँ",
        "of_total": "कुल का", "new_this_cycle": "इस चक्र में नए", "high_priority_tag": "उच्च-प्राथमिकता",
        "deliverables": "डिलिवरेबल्स", "operational": "चालू", "view_details": "विवरण देखें →",
        "d1_title": "रिक्त छवि फ़िल्टरिंग", "d1_desc": "कच्ची SD-कार्ड निर्देशिकाओं को लेता है और हर फ्रेम को वर्गीकृत करता है। सुरक्षित क्वारंटीन — कोई अपरिवर्तनीय विलोपन नहीं।",
        "d2_title": "व्यक्तिगत बाघ पहचान", "d2_desc": "फ्लैंक पहचान → धारी निष्कर्षण → कैटलॉग मिलान। अस्पष्ट मिलानों को मानव समीक्षा हेतु प्रस्तुत करता है।",
        "d3_title": "क्षेत्र अधिभोग मानचित्र", "d3_desc": "प्रत्येक रन पर पुनर्जीवित गृह क्षेत्र अनुमान। क्षेत्रीय अतिव्यापन एक प्रबंधन संकेत के रूप में दिखाई देता है।",
        "d4_title": "विचलन और रुझान चेतावनियाँ", "d4_desc": "स्थापित इतिहास से तुलना करता है। क्षेत्र बदलाव, नए स्टेशन दौरे, और लंबी अनुपस्थिति चिह्नित करता है।",
        "last_run": "अंतिम पाइपलाइन रन", "started": "प्रारंभ", "duration": "अवधि", "stations": "स्टेशन", "hardware": "हार्डवेयर",
        "blank_title": "रिक्त छवि फ़िल्टर", "blank_sub": "डिलिवरेबल 1 — स्वचालित छँटाई और सुरक्षित निष्कासन",
        "quarantined": "क्वारंटीन की गई", "retained": "बनाए रखे गए विषय", "awaiting_review": "समीक्षा प्रतीक्षित",
        "threshold": "विश्वास सीमा", "threshold_note": "सीमा से नीचे के फ्रेम समीक्षा हेतु रखे जाते हैं",
        "f_all": "सभी", "f_blank": "रिक्त", "f_subject": "विषय",
        "frame_results": "फ्रेम परिणाम", "shown": "दिखाए गए", "quarantine_note": "रिक्त छवियाँ ./quarantine/ में सुरक्षित हैं।",
        "tiger_title": "व्यक्तिगत बाघ पहचान", "tiger_sub": "डिलिवरेबल 2 — धारी-पैटर्न मिलान",
        "known_individuals": "ज्ञात व्यक्ति", "auto_matched": "स्वतः मिलान", "human_review": "समीक्षा प्रतीक्षित",
        "catalogue": "व्यक्तिगत सूची", "known_individual": "ज्ञात व्यक्ति", "sex": "लिंग",
        "first_seen": "पहली बार देखा", "last_seen": "अंतिम बार देखा", "total_sightings": "कुल दृश्य",
        "stripe_sig": "धारी हस्ताक्षर (उदाहरणात्मक)", "stripe_note": "प्रतिनिधि पैटर्न",
        "gallery_title": "फोटो गैलरी (असली ATRW छवियाँ)", "gallery_note": "फ़ोटो उपलब्ध — पूर्ण रिज़ॉल्यूशन देखने हेतु क्लिक करें",
        "gallery_empty": "इस व्यक्ति के लिए अभी कोई असली फ़ोटो उपलब्ध नहीं है — केवल कृत्रिम डेटा दिखाया जा रहा है।",
        "ambiguous": "अस्पष्ट मिलान", "conf": "विश्वास", "review_btn": "समीक्षा करें",
        "low_conf_note": "कम विश्वास मिलान",
        "occ_title": "क्षेत्र अधिभोग मानचित्र", "occ_sub": "डिलिवरेबल 3 — प्रति-व्यक्ति क्षेत्र दृश्यांकन",
        "mapped": "मानचित्रित व्यक्ति", "overlaps": "क्षेत्रीय अतिव्यापन", "pairs": "जोड़े", "area_covered": "कुल क्षेत्र",
        "filter_individual": "व्यक्ति द्वारा फ़िल्टर", "all_individuals": "सभी व्यक्ति",
        "map_title": "पेंच टाइगर रिज़र्व — क्षेत्र अधिभोग मानचित्र",
        "legend_station": "कैमरा स्टेशन", "legend_boundary": "रिज़र्व सीमा", "legend_buffer": "बफर ज़ोन", "legend_overlap": "अतिव्यापन",
        "summary_table": "व्यक्तिगत सारांश", "col_area": "क्षेत्र (किमी²)",
        "col_centroid": "केंद्रक", "col_stations": "स्टेशन", "col_overlap": "अतिव्यापन",
        "yes": "हाँ", "no": "नहीं",
        "alerts_title": "विचलन और रुझान चेतावनियाँ", "alerts_sub": "डिलिवरेबल 4 — गति बुद्धिमत्ता",
        "high": "उच्च", "medium": "मध्यम", "low": "निम्न", "all_alerts": "सभी चेतावनियाँ",
        "supporting_evidence": "सहायक प्रमाण", "mark_resolved": "हल", "view_frames": "फ्रेम देखें", "export_report": "रिपोर्ट",
        "artefact_note": "संभावित सर्वेक्षण त्रुटि।",
        "footer_v": "v1.0 · हैकाथॉन 2026", "footer_track": "वन एवं वन्यजीव ट्रैक", "light": "उजाला", "dark": "अंधेरा",
    },
    "mr": {
        "brand": "टायगरलेन्स", "brand_sub": "पेंच व्याघ्र प्रकल्प", "pipeline_active": "पाइपलाइन सक्रिय",
        "nav_overview": "आढावा", "nav_overview_sub": "प्रणाली सारांश",
        "nav_blank": "रिकामे फिल्टर", "nav_blank_sub": "प्रतिमा छाननी",
        "nav_tiger": "वाघ ओळख", "nav_tiger_sub": "पट्टे जुळणी",
        "nav_occupancy": "क्षेत्र व्याप्ती", "nav_occupancy_sub": "क्षेत्र मॅपिंग",
        "nav_alerts": "इशारे", "nav_alerts_sub": "विचलन आणि कल",
        "overview_title": "प्रणाली आढावा", "overview_sub": "कॅमेरा ट्रॅप बुद्धिमत्ता · पेंच व्याघ्र प्रकल्प",
        "images_processed": "प्रक्रिया केलेल्या प्रतिमा", "blanks_removed": "काढलेल्या रिकाम्या",
        "tigers_identified": "ओळखलेले वाघ", "active_alerts": "सक्रिय इशारे",
        "of_total": "एकूण पैकी", "new_this_cycle": "नवीन", "high_priority_tag": "उच्च-प्राधान्य",
        "deliverables": "डिलिव्हरेबल्स", "operational": "कार्यरत", "view_details": "तपशील पहा →",
        "d1_title": "रिकामी प्रतिमा फिल्टरिंग", "d1_desc": "प्रत्येक फ्रेमला वर्गीकृत करते. सुरक्षित क्वारंटाइन.",
        "d2_title": "वैयक्तिक वाघ ओळख", "d2_desc": "फ्लँक शोध → पट्टे निष्कर्षण → कॅटलॉग जुळणी.",
        "d3_title": "क्षेत्र व्याप्ती नकाशा", "d3_desc": "प्रति-व्यक्ती गृहक्षेत्र अंदाज. आच्छादन व्यवस्थापन संकेत.",
        "d4_title": "विचलन आणि कल इशारे", "d4_desc": "स्थापित इतिहासाशी तुलना. बदल आणि अनुपस्थिती चिन्हांकित करते.",
        "last_run": "शेवटची फेरी", "started": "सुरू", "duration": "कालावधी", "stations": "स्थानके", "hardware": "हार्डवेअर",
        "blank_title": "रिकामी प्रतिमा फिल्टर", "blank_sub": "डिलिव्हरेबल 1 — स्वयंचलित छाननी",
        "quarantined": "क्वारंटाइन केलेल्या", "retained": "राखलेले विषय", "awaiting_review": "पुनरावलोकन प्रलंबित",
        "threshold": "आत्मविश्वास मर्यादा", "threshold_note": "मर्यादेखालील फ्रेम्स पुनरावलोकनासाठी",
        "f_all": "सर्व", "f_blank": "रिकामे", "f_subject": "विषय",
        "frame_results": "फ्रेम निकाल", "shown": "दर्शविलेले", "quarantine_note": "रिकाम्या प्रतिमा सुरक्षित आहेत.",
        "tiger_title": "वैयक्तिक वाघ ओळख", "tiger_sub": "डिलिव्हरेबल 2 — पट्टे-पॅटर्न जुळणी",
        "known_individuals": "ज्ञात व्यक्ती", "auto_matched": "स्वयं-जुळलेले", "human_review": "पुनरावलोकन प्रलंबित",
        "catalogue": "वैयक्तिक यादी", "known_individual": "ज्ञात व्यक्ती", "sex": "लिंग",
        "first_seen": "प्रथम दिसले", "last_seen": "शेवटचे दिसले", "total_sightings": "एकूण नोंदी",
        "stripe_sig": "पट्टे स्वाक्षरी", "stripe_note": "प्रातिनिधिक नमुना",
        "gallery_title": "फोटो गॅलरी (खऱ्या ATRW प्रतिमा)", "gallery_note": "फोटो उपलब्ध — पूर्ण रिझोल्यूशनमध्ये पाहण्यासाठी क्लिक करा",
        "gallery_empty": "या व्यक्तीसाठी अद्याप खरे फोटो उपलब्ध नाहीत — फक्त कृत्रिम डेटा दाखवला जात आहे.",
        "ambiguous": "संदिग्ध जुळणी", "conf": "विश्वास", "review_btn": "पुनरावलोकन करा",
        "low_conf_note": "कमी विश्वास जुळणी",
        "occ_title": "क्षेत्र व्याप्ती नकाशा", "occ_sub": "डिलिव्हरेबल 3 — प्रति-व्यक्ती क्षेत्र",
        "mapped": "मॅप केलेल्या व्यक्ती", "overlaps": "क्षेत्रीय आच्छादन", "pairs": "जोड्या", "area_covered": "एकूण क्षेत्र",
        "filter_individual": "व्यक्तीनुसार फिल्टर", "all_individuals": "सर्व व्यक्ती",
        "map_title": "पेंच व्याघ्र प्रकल्प — क्षेत्र व्याप्ती नकाशा",
        "legend_station": "कॅमेरा स्थानक", "legend_boundary": "प्रकल्प सीमा", "legend_buffer": "बफर झोन", "legend_overlap": "आच्छादन",
        "summary_table": "वैयक्तिक सारांश", "col_area": "क्षेत्र (चौ. किमी)",
        "col_centroid": "केंद्रबिंदू", "col_stations": "स्थानके", "col_overlap": "आच्छादन",
        "yes": "होय", "no": "नाही",
        "alerts_title": "विचलन आणि कल इशारे", "alerts_sub": "डिलिव्हरेबल 4 — हालचाल बुद्धिमत्ता",
        "high": "उच्च", "medium": "मध्यम", "low": "कमी", "all_alerts": "सर्व इशारे",
        "supporting_evidence": "सहाय्यक पुरावा", "mark_resolved": "निकाली", "view_frames": "फ्रेम्स पहा", "export_report": "अहवाल",
        "artefact_note": "संभाव्य सर्वेक्षण त्रुटी.",
        "footer_v": "v1.0 · हॅकाथॉन 2026", "footer_track": "वन आणि वन्यजीव ट्रॅक", "light": "उजेड", "dark": "अंधार",
    },
}


def build_html(data):
    data_json = json.dumps(data, ensure_ascii=False)
    i18n_json = json.dumps(I18N, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TigerLens — Vyaghra</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600;700&family=Noto+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #EDE8DC; --card: #F6F2E7; --sidebar: #E6E0D0; --border: #D8D0BC;
    --text: #2A2A20; --muted: #7A7261; --active: #3B4A2E; --active-text: #F6F2E7;
    --orange: #C2703D; --green: #4A7A3E; --red: #B23A2A; --amber: #C2841A; --cyan: #3D7A8A;
  }}
  [data-theme="dark"] {{
    --bg: #14170F; --card: #1C2016; --sidebar: #191C13; --border: #2E3324;
    --text: #E8E4D6; --muted: #8C9078; --active: #4A7A3E; --active-text: #F6F2E7;
    --orange: #D98A50; --green: #6FCF6F; --red: #E06A5A; --amber: #E0A83A; --cyan: #5AAFC0;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Noto Sans','Noto Sans Devanagari',sans-serif; display: flex; }}
  .font-hi, .font-mr {{ font-family: 'Noto Sans Devanagari', sans-serif; }}
  .mono {{ font-family: 'JetBrains Mono', monospace; }}
  .sidebar {{ width: 220px; flex-shrink: 0; background: var(--sidebar); border-right: 1px solid var(--border); display: flex; flex-direction: column; padding: 20px 14px; }}
  .brand {{ display: flex; align-items: center; gap: 10px; padding: 0 6px 20px; }}
  .brand-icon {{ width: 34px; height: 34px; border-radius: 8px; background: var(--orange); display: flex; align-items: center; justify-content: center; font-size: 17px; }}
  .brand-name {{ font-weight: 700; font-size: 15px; }}
  .brand-sub {{ font-size: 10.5px; color: var(--muted); }}
  .nav-label {{ font-size: 10px; color: var(--muted); letter-spacing: 0.08em; padding: 10px 8px 8px; font-family: 'JetBrains Mono', monospace; }}
  .nav-item {{ display: flex; gap: 10px; align-items: center; padding: 10px 10px; border-radius: 6px; cursor: pointer; margin-bottom: 2px; }}
  .nav-item:hover {{ background: var(--border); }}
  .nav-item.active {{ background: var(--active); color: var(--active-text); }}
  .nav-icon {{ font-size: 14px; width: 16px; text-align: center; color: var(--orange); }}
  .nav-item.active .nav-icon {{ color: var(--active-text); }}
  .nav-title {{ font-size: 13.5px; font-weight: 600; }}
  .nav-sub {{ font-size: 10.5px; color: var(--muted); }}
  .nav-item.active .nav-sub {{ color: #D8D8C8; }}
  .sidebar-footer {{ margin-top: auto; padding: 10px 8px; font-size: 10px; color: var(--muted); font-family: 'JetBrains Mono', monospace; line-height: 1.6; }}
  .main {{ flex: 1; overflow-y: auto; height: 100vh; }}
  .topbar {{ display: flex; justify-content: space-between; align-items: flex-start; padding: 22px 32px 18px; border-bottom: 1px solid var(--border); }}
  .page-title {{ font-size: 25px; font-weight: 700; margin: 0; }}
  .page-sub {{ font-size: 12.5px; color: var(--muted); margin-top: 3px; }}
  .top-controls {{ display: flex; gap: 10px; align-items: center; }}
  .pill {{ display: flex; align-items: center; gap: 6px; background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 6px 14px; font-size: 11.5px; color: var(--green); font-weight: 600; }}
  .pill-dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--green); }}
  .btn {{ background: var(--card); border: 1px solid var(--border); padding: 7px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; font-family: 'JetBrains Mono', monospace; color: var(--text); }}
  .btn.active {{ background: var(--active); color: var(--active-text); border-color: var(--active); }}
  .toggle-group {{ display: flex; gap: 4px; }}
  .page {{ display: none; padding: 24px 32px 50px; }}
  .page.visible {{ display: block; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap: 14px; margin-bottom: 26px; }}
  .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; }}
  .stat-label {{ font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; font-family: 'JetBrains Mono', monospace; }}
  .stat-num {{ font-size: 30px; font-weight: 700; margin-top: 6px; }}
  .stat-note {{ font-size: 11px; color: var(--muted); margin-top: 3px; }}
  h2.section-h {{ font-size: 17px; font-weight: 700; margin: 0 0 14px; }}
  .deliv-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 20px; }}
  .deliv-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 18px 20px; }}
  .deliv-head {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }}
  .deliv-num {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--orange); font-weight: 700; }}
  .deliv-title {{ font-size: 15.5px; font-weight: 700; margin-top: 2px; }}
  .badge {{ font-size: 10px; padding: 3px 9px; border-radius: 10px; font-family: 'JetBrains Mono', monospace; font-weight: 700; }}
  .badge-ok {{ background: rgba(74,122,62,0.15); color: var(--green); }}
  .badge-warn {{ background: rgba(178,58,42,0.15); color: var(--red); }}
  .deliv-desc {{ font-size: 12.5px; color: var(--muted); line-height: 1.55; }}
  .deliv-link {{ font-size: 12px; color: var(--orange); font-weight: 600; margin-top: 10px; display: inline-block; cursor: pointer; }}
  .run-bar {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; display: flex; gap: 40px; flex-wrap: wrap; }}
  .run-item .run-label {{ font-size: 10.5px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }}
  .run-item .run-val {{ font-size: 14px; font-weight: 600; margin-top: 3px; }}
  .toolbar {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; margin-bottom: 18px; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }}
  .slider-track {{ flex: 1; min-width: 200px; height: 5px; background: var(--border); border-radius: 3px; position: relative; }}
  .slider-fill {{ height: 100%; width: 60%; background: var(--green); border-radius: 3px; }}
  .table-panel {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  .table-head {{ padding: 12px 18px; background: var(--border); font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--muted); }}
  .frame-row {{ display: flex; align-items: center; gap: 16px; padding: 12px 18px; border-bottom: 1px solid var(--border); }}
  .frame-thumb {{ width: 44px; height: 44px; border-radius: 6px; object-fit: cover; background: var(--border); flex-shrink: 0; }}
  .frame-id {{ font-family: 'JetBrains Mono', monospace; font-size: 12.5px; width: 70px; flex-shrink: 0; }}
  .frame-bar-wrap {{ flex: 1; display: flex; align-items: center; gap: 8px; max-width: 160px; }}
  .frame-bar {{ flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }}
  .frame-bar-fill {{ height: 100%; }}
  .frame-conf {{ font-size: 11.5px; width: 34px; }}
  .status-tag {{ font-size: 10px; padding: 3px 9px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-weight: 700; margin-left: auto; }}
  .status-blank {{ background: rgba(178,58,42,0.15); color: var(--red); }}
  .status-subject {{ background: rgba(74,122,62,0.15); color: var(--green); }}
  .two-col {{ display: grid; grid-template-columns: 280px 1fr; gap: 16px; }}
  .catalogue-item {{ display: flex; align-items: center; gap: 10px; padding: 12px; border-bottom: 1px solid var(--border); cursor: pointer; }}
  .catalogue-item.active {{ background: var(--active); color: var(--active-text); border-radius: 6px; }}
  .cat-avatar {{ width: 36px; height: 36px; border-radius: 50%; object-fit: cover; background: var(--border); flex-shrink: 0; }}
  .cat-name {{ font-size: 13.5px; font-weight: 600; }}
  .cat-sub {{ font-size: 11px; color: var(--muted); }}
  .catalogue-item.active .cat-sub {{ color: #D8D8C8; }}
  .detail-photo {{ width: 100%; height: 220px; object-fit: cover; border-radius: 8px; background: var(--border); }}
  .photo-gallery {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 8px; }}
  .photo-gallery img {{ width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px; cursor: zoom-in; background: var(--border); transition: opacity .15s; }}
  .photo-gallery img:hover {{ opacity: 0.85; }}
  .gallery-note {{ font-size: 10.5px; color: var(--muted); margin-top: 6px; }}
  .lightbox {{ position: fixed; inset: 0; background: rgba(0,0,0,.85); display: flex; align-items: center; justify-content: center; z-index: 999; cursor: zoom-out; }}
  .lightbox img {{ max-width: 92vw; max-height: 92vh; border-radius: 8px; box-shadow: 0 10px 40px rgba(0,0,0,.5); }}
  .detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 16px 0; }}
  .detail-field .df-label {{ font-size: 10.5px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }}
  .detail-field .df-val {{ font-size: 14.5px; font-weight: 600; margin-top: 2px; }}
  .stripe-row {{ display: flex; gap: 1.5px; align-items: flex-end; height: 48px; margin: 10px 0; padding: 8px; background: var(--bg); border-radius: 6px; border: 1px solid var(--border); }}
  .stripe-bar {{ width: 2.5px; background: var(--text); opacity: 0.9; border-radius: 0.5px; }}
  #occ-map {{ width: 100%; aspect-ratio: 1/1; border-radius: 8px; border: 1px solid var(--border); }}
  .triangle-icon {{ width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 7px solid #9AA88E; }}
  .legend-row {{ display: flex; gap: 20px; padding: 10px 4px; font-size: 11px; color: var(--muted); flex-wrap: wrap; }}
  .legend-swatch {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px; }}
  table.data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.data-table th {{ text-align: left; padding: 10px 14px; font-size: 10.5px; color: var(--muted); text-transform: uppercase; font-family: 'JetBrains Mono', monospace; border-bottom: 2px solid var(--border); }}
  table.data-table td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); }}
  .alert-card {{ background: var(--card); border: 1px solid var(--border); border-left: 4px solid var(--muted); border-radius: 8px; padding: 16px 18px; margin-bottom: 12px; }}
  .alert-card.high {{ border-left-color: var(--red); }} .alert-card.medium {{ border-left-color: var(--amber); }} .alert-card.low {{ border-left-color: var(--green); }}
  .sev-tag {{ font-size: 10px; padding: 3px 9px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-weight: 700; }}
  .sev-tag.high {{ background: rgba(178,58,42,0.15); color: var(--red); }} .sev-tag.medium {{ background: rgba(194,132,26,0.15); color: var(--amber); }} .sev-tag.low {{ background: rgba(74,122,62,0.15); color: var(--green); }}
  .alert-title {{ font-size: 15px; font-weight: 700; margin: 4px 0 2px; }}
  .alert-meta {{ font-size: 11.5px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }}
  .alert-body {{ margin-top: 10px; font-size: 13px; line-height: 1.6; }}
  .evidence-box {{ background: var(--bg); border-radius: 6px; padding: 10px 12px; margin-top: 8px; font-size: 12px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }}
  .alert-actions {{ display: flex; gap: 8px; margin-top: 12px; }}
  .empty {{ color: var(--muted); font-size: 13px; padding: 20px; text-align: center; }}
</style>
</head>
<body class="font-en" data-theme="light">

<nav class="sidebar">
  <div class="brand">
    <div class="brand-icon">🐅</div>
    <div><div class="brand-name" data-i18n="brand">TigerLens</div><div class="brand-sub" data-i18n="brand_sub">Pench Tiger Reserve</div></div>
  </div>
  <div class="nav-label" data-i18n="deliverables">DELIVERABLES</div>
  <div class="nav-item active" data-page="overview"><span class="nav-icon">◆</span><div><div class="nav-title" data-i18n="nav_overview">Overview</div><div class="nav-sub" data-i18n="nav_overview_sub">System summary</div></div></div>
  <div class="nav-item" data-page="blank"><span class="nav-icon">⊘</span><div><div class="nav-title" data-i18n="nav_blank">Blank Filter</div><div class="nav-sub" data-i18n="nav_blank_sub">Image triage</div></div></div>
  <div class="nav-item" data-page="tiger"><span class="nav-icon">◉</span><div><div class="nav-title" data-i18n="nav_tiger">Tiger ID</div><div class="nav-sub" data-i18n="nav_tiger_sub">Stripe matching</div></div></div>
  <div class="nav-item" data-page="occupancy"><span class="nav-icon">○</span><div><div class="nav-title" data-i18n="nav_occupancy">Occupancy</div><div class="nav-sub" data-i18n="nav_occupancy_sub">Area mapping</div></div></div>
  <div class="nav-item" data-page="alerts"><span class="nav-icon">△</span><div><div class="nav-title" data-i18n="nav_alerts">Alerts</div><div class="nav-sub" data-i18n="nav_alerts_sub">Deviation & trends</div></div></div>
  <div class="sidebar-footer" data-i18n="footer_v">v1.0 · Hackathon 2026<br><span data-i18n="footer_track">Forest & Wildlife Track</span></div>
</nav>

<div class="main">
  <div class="topbar">
    <div><h1 class="page-title" id="page-title" data-i18n="overview_title">System Overview</h1><div class="page-sub" id="page-sub" data-i18n="overview_sub">Camera Trap Intelligence · Pench Tiger Reserve</div></div>
    <div class="top-controls">
      <div class="pill"><span class="pill-dot"></span><span data-i18n="pipeline_active">Pipeline active</span></div>
      <div class="toggle-group">
        <button class="btn active" data-theme-btn="light" data-i18n="light">Light</button>
        <button class="btn" data-theme-btn="dark" data-i18n="dark">Dark</button>
      </div>
      <div class="toggle-group">
        <button class="btn active" data-lang="en">EN</button>
        <button class="btn" data-lang="hi">हिं</button>
        <button class="btn" data-lang="mr">मरा</button>
      </div>
    </div>
  </div>
  <div class="page visible" id="page-overview"></div>
  <div class="page" id="page-blank"></div>
  <div class="page" id="page-tiger"></div>
  <div class="page" id="page-occupancy"></div>
  <div class="page" id="page-alerts"></div>
</div>

<script>
const DATA = {data_json};
const I18N = {i18n_json};
let currentLang = "en", selectedTiger = null, selectedFilter = "all", blankFilter = "all", alertFilter = "all";
function T(k) {{ return I18N[currentLang][k] || k; }}

function switchPage(page) {{
  document.querySelectorAll('.page').forEach(p => p.classList.remove('visible'));
  document.getElementById('page-' + page).classList.add('visible');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
  const titles = {{overview:['overview_title','overview_sub'], blank:['blank_title','blank_sub'], tiger:['tiger_title','tiger_sub'], occupancy:['occ_title','occ_sub'], alerts:['alerts_title','alerts_sub']}};
  document.getElementById('page-title').textContent = T(titles[page][0]);
  document.getElementById('page-sub').textContent = T(titles[page][1]);
  if (page === 'occupancy') setTimeout(drawOccMap, 60);
}}
document.querySelectorAll('.nav-item').forEach(n => n.addEventListener('click', () => switchPage(n.dataset.page)));

function applyTheme(theme) {{
  document.body.dataset.theme = theme;
  document.querySelectorAll('[data-theme-btn]').forEach(b => b.classList.toggle('active', b.dataset.themeBtn === theme));
  occMap = null;
  const el = document.getElementById('occ-map'); if (el) el.innerHTML = '';
  setTimeout(drawOccMap, 60);
}}
document.querySelectorAll('[data-theme-btn]').forEach(b => b.addEventListener('click', () => applyTheme(b.dataset.themeBtn)));

function applyLang(lang) {{
  currentLang = lang;
  document.body.className = lang === 'en' ? 'font-en' : 'font-' + lang;
  document.querySelectorAll('[data-lang]').forEach(b => b.classList.toggle('active', b.dataset.lang === lang));
  document.querySelectorAll('[data-i18n]').forEach(el => {{ const k = el.getAttribute('data-i18n'); if (I18N[lang][k]) {{
    if (el.children.length) {{ el.childNodes[0].textContent = I18N[lang][k]; }} else {{ el.textContent = I18N[lang][k]; }}
  }} }});
  renderAll();
}}
document.querySelectorAll('[data-lang]').forEach(b => b.addEventListener('click', () => applyLang(b.dataset.lang)));

function renderOverview() {{
  const o = DATA.overview;
  document.getElementById('page-overview').innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-label">${{T('images_processed')}}</div><div class="stat-num">${{o.images_processed.toLocaleString()}}</div><div class="stat-note">+${{o.images_today}} today</div></div>
      <div class="stat-card"><div class="stat-label">${{T('blanks_removed')}}</div><div class="stat-num" style="color:var(--orange)">${{o.blanks_removed.toLocaleString()}}</div><div class="stat-note">${{o.blanks_pct}}% ${{T('of_total')}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('tigers_identified')}}</div><div class="stat-num" style="color:var(--green)">${{o.tigers_identified}}</div><div class="stat-note">${{T('new_this_cycle')}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('active_alerts')}}</div><div class="stat-num" style="color:var(--red)">${{o.active_alerts}}</div><div class="stat-note">${{o.high_priority}} ${{T('high_priority_tag')}}</div></div>
    </div>
    <h2 class="section-h">${{T('deliverables')}}</h2>
    <div class="deliv-grid">
      <div class="deliv-card"><div class="deliv-head"><div><div class="deliv-num">01</div><div class="deliv-title">${{T('d1_title')}}</div></div><span class="badge badge-ok">${{T('operational')}}</span></div><div class="deliv-desc">${{T('d1_desc')}}</div><div class="deliv-link" onclick="switchPage('blank')">${{T('view_details')}}</div></div>
      <div class="deliv-card"><div class="deliv-head"><div><div class="deliv-num">02</div><div class="deliv-title">${{T('d2_title')}}</div></div><span class="badge badge-ok">${{T('operational')}}</span></div><div class="deliv-desc">${{T('d2_desc')}}</div><div class="deliv-link" onclick="switchPage('tiger')">${{T('view_details')}}</div></div>
      <div class="deliv-card"><div class="deliv-head"><div><div class="deliv-num">03</div><div class="deliv-title">${{T('d3_title')}}</div></div><span class="badge badge-ok">${{T('operational')}}</span></div><div class="deliv-desc">${{T('d3_desc')}}</div><div class="deliv-link" onclick="switchPage('occupancy')">${{T('view_details')}}</div></div>
      <div class="deliv-card"><div class="deliv-head"><div><div class="deliv-num">04</div><div class="deliv-title">${{T('d4_title')}}</div></div><span class="badge badge-warn">${{o.active_alerts}} ${{T('active_alerts').toLowerCase()}}</span></div><div class="deliv-desc">${{T('d4_desc')}}</div><div class="deliv-link" onclick="switchPage('alerts')">${{T('view_details')}}</div></div>
    </div>
    <div class="run-bar">
      <div class="run-item"><div class="run-label">${{T('started')}}</div><div class="run-val mono">${{o.run_started}}</div></div>
      <div class="run-item"><div class="run-label">${{T('duration')}}</div><div class="run-val mono">${{o.run_duration}}</div></div>
      <div class="run-item"><div class="run-label">${{T('stations')}}</div><div class="run-val mono">${{o.stations}} cameras</div></div>
      <div class="run-item"><div class="run-label">${{T('hardware')}}</div><div class="run-val mono">No GPU (CPU-only)</div></div>
    </div>`;
}}

function renderBlank() {{
  const b = DATA.blank_filter;
  const filtered = blankFilter === 'all' ? b.frames : b.frames.filter(f => f.status === blankFilter);
  document.getElementById('page-blank').innerHTML = `
    <div class="stat-grid" style="grid-template-columns:repeat(3,1fr)">
      <div class="stat-card"><div class="stat-label">${{T('quarantined')}}</div><div class="stat-num" style="color:var(--red)">${{b.quarantined}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('retained')}}</div><div class="stat-num" style="color:var(--green)">${{b.retained}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('awaiting_review')}}</div><div class="stat-num" style="color:var(--amber)">${{b.awaiting}}</div></div>
    </div>
    <div class="toolbar">
      <div style="min-width:160px"><span class="mono" style="font-size:11px;color:var(--muted)">${{T('threshold')}}: <b style="color:var(--green)">0.60</b></span><div class="slider-track"><div class="slider-fill"></div></div></div>
      <div class="toggle-group" id="blank-filters">
        <button class="btn ${{blankFilter==='all'?'active':''}}" data-bf="all">${{T('f_all')}}</button>
        <button class="btn ${{blankFilter==='blank'?'active':''}}" data-bf="blank">${{T('f_blank')}}</button>
        <button class="btn ${{blankFilter==='subject'?'active':''}}" data-bf="subject">${{T('f_subject')}}</button>
      </div>
      <span style="font-size:11px;color:var(--muted)">${{T('threshold_note')}}</span>
    </div>
    <div class="table-panel">
      <div class="table-head">${{T('frame_results')}} — ${{filtered.length}} ${{T('shown')}}</div>
      ${{filtered.map(f => `<div class="frame-row">
        ${{f.thumb ? `<img class="frame-thumb" src="${{f.thumb}}">` : `<div class="frame-thumb" style="display:flex;align-items:center;justify-content:center;color:var(--muted)">–</div>`}}
        <div class="frame-id mono">${{f.id}}</div>
        <div class="frame-bar-wrap"><div class="frame-bar"><div class="frame-bar-fill" style="width:${{f.confidence}}%;background:${{f.status==='blank'?'var(--red)':'var(--green)'}}"></div></div><span class="frame-conf mono">${{f.confidence}}%</span></div>
        <span class="status-tag status-${{f.status}}">${{f.status === 'blank' ? T('f_blank') : T('f_subject')}}</span>
      </div>`).join('')}}
      <div style="padding:12px 18px;font-size:11.5px;color:var(--muted)">${{T('quarantine_note')}}</div>
    </div>`;
  document.querySelectorAll('#blank-filters button').forEach(btn => btn.addEventListener('click', () => {{ blankFilter = btn.dataset.bf; renderBlank(); }}));
}}

function renderTiger() {{
  const tg = DATA.tiger_id;
  if (!selectedTiger && tg.catalogue.length) selectedTiger = tg.catalogue[0].id;
  const d = tg.detail[selectedTiger];
  document.getElementById('page-tiger').innerHTML = `
    <div class="stat-grid" style="grid-template-columns:repeat(3,1fr)">
      <div class="stat-card"><div class="stat-label">${{T('known_individuals')}}</div><div class="stat-num">${{tg.known}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('auto_matched')}}</div><div class="stat-num" style="color:var(--green)">${{tg.auto_matched}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('human_review')}}</div><div class="stat-num" style="color:var(--amber)">${{tg.awaiting}}</div></div>
    </div>
    <div class="two-col">
      <div class="table-panel"><div class="table-head">${{T('catalogue')}}</div>
        ${{tg.catalogue.map(c => `<div class="catalogue-item ${{c.id===selectedTiger?'active':''}}" data-tid="${{c.id}}">
          ${{c.avatar ? `<img class="cat-avatar" src="${{c.avatar}}">` : `<div class="cat-avatar" style="background:${{c.color}}"></div>`}}
          <div><div class="cat-name">${{c.name}}</div><div class="cat-sub mono">${{c.id}} · ${{c.sex}}</div></div>
        </div>`).join('')}}
      </div>
      <div>
        ${{d ? `<div class="table-panel" style="padding:20px">
          ${{d.avatar ? `<img class="detail-photo" src="${{d.avatar}}">` : `<div class="detail-photo" style="background:${{d.color}}"></div>`}}
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px">
            <span style="font-size:20px;font-weight:700">${{d.name}}</span><span class="badge badge-ok">${{T('known_individual')}}</span>
          </div>
          <div class="detail-grid">
            <div class="detail-field"><div class="df-label mono">ID</div><div class="df-val mono">${{d.id}}</div></div>
            <div class="detail-field"><div class="df-label mono">${{T('sex')}}</div><div class="df-val">${{d.sex}}</div></div>
            <div class="detail-field"><div class="df-label mono">${{T('first_seen')}}</div><div class="df-val">${{d.first_seen}}</div></div>
            <div class="detail-field"><div class="df-label mono">${{T('last_seen')}}</div><div class="df-val">${{d.last_seen}}</div></div>
            <div class="detail-field"><div class="df-label mono">${{T('total_sightings')}}</div><div class="df-val">${{d.total_sightings}}</div></div>
          </div>
          <div style="border-top:1px solid var(--border);padding-top:14px;margin-bottom:14px">
            <div class="df-label mono">${{T('gallery_title')}}</div>
            ${{d.gallery && d.gallery.length ? `<div class="photo-gallery">${{d.gallery.map(g => `<img src="${{g}}" data-full="${{g}}">`).join('')}}</div>
              <div class="gallery-note">${{d.gallery.length}} ${{T('gallery_note')}}</div>`
              : `<div class="gallery-note">${{T('gallery_empty')}}</div>`}}
          </div>
          <div style="border-top:1px solid var(--border);padding-top:14px">
            <div class="df-label mono">${{T('stripe_sig')}}</div>
            <div class="stripe-row">${{d.stripe_bars.map(h => `<div class="stripe-bar" style="height:${{h}}px"></div>`).join('')}}</div>
            <div style="font-size:10.5px;color:var(--muted)">${{T('stripe_note')}}</div>
          </div>
        </div>` : ''}}
        <div class="table-panel" style="margin-top:14px"><div class="table-head">${{T('ambiguous')}}</div>
          ${{tg.ambiguous.length === 0 ? `<div class="empty">—</div>` : tg.ambiguous.map(a => `<div class="frame-row">
            <div class="frame-id mono">${{a.id}}</div><span style="flex:1;font-size:12.5px;color:var(--muted)">${{T('low_conf_note')}}</span>
            <span class="mono" style="font-size:11.5px">${{a.confidence}}% ${{T('conf')}}</span><button class="btn">${{T('review_btn')}}</button>
          </div>`).join('')}}
        </div>
      </div>
    </div>`;
  document.querySelectorAll('.catalogue-item').forEach(item => item.addEventListener('click', () => {{ selectedTiger = item.dataset.tid; renderTiger(); }}));
  document.querySelectorAll('.photo-gallery img').forEach(img => img.addEventListener('click', () => openLightbox(img.dataset.full)));
}}

function openLightbox(src) {{
  const box = document.createElement('div');
  box.className = 'lightbox';
  box.innerHTML = `<img src="${{src}}">`;
  box.addEventListener('click', () => box.remove());
  document.body.appendChild(box);
}}

let occMap = null, occLayers = [], occPlayTimer = null, occBaseLayer = null, occBaseType = 'terrain';

// Two colourful basemap options — OpenTopoMap gives a shaded, contoured,
// vegetation-tinted terrain map (not the flat grey CARTO tiles this used
// to use), and Esri World Imagery gives true satellite photography.
const OCC_BASEMAPS = {{
  terrain: {{
    url: 'https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png',
    attribution: 'Map: &copy; OpenTopoMap (CC-BY-SA) — Data: &copy; OpenStreetMap contributors, SRTM',
    maxZoom: 17
  }},
  satellite: {{
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
    attribution: 'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, GIS User Community',
    maxZoom: 19
  }}
}};

function setOccBasemap(type) {{
  if (!occMap || !OCC_BASEMAPS[type]) return;
  occBaseType = type;
  if (occBaseLayer) occMap.removeLayer(occBaseLayer);
  const cfg = OCC_BASEMAPS[type];
  occBaseLayer = L.tileLayer(cfg.url, {{ attribution: cfg.attribution, maxZoom: cfg.maxZoom }}).addTo(occMap);
  occBaseLayer.bringToBack();
  document.querySelectorAll('.occ-base-btn').forEach(b => b.classList.toggle('active', b.dataset.base === type));
}}

// Colored triangle marker — unique per-tiger color, used for both the
// running centroid (large) and individual per-run sighting points (small).
function triangleDivIcon(color, size) {{
  return L.divIcon({{
    className: '',
    html: `<div style="width:0;height:0;border-left:${{size / 2}}px solid transparent;` +
          `border-right:${{size / 2}}px solid transparent;border-bottom:${{size}}px solid ${{color}};` +
          `filter:drop-shadow(0 1px 1px rgba(0,0,0,0.6));"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  }});
}}

function currentOccRunId() {{
  const o = DATA.occupancy;
  const sel = document.getElementById('occ-run-select');
  if (sel && sel.value) return parseInt(sel.value, 10);
  return o.run_ids.length ? o.run_ids[o.run_ids.length - 1] : null;
}}

function drawOccMap() {{
  const o = DATA.occupancy;
  const mapEl = document.getElementById('occ-map');
  if (!mapEl) return;
  if (!occMap) {{
    occMap = L.map('occ-map', {{ zoomControl: true }});
    const firstRow = o.rows[0];
    occMap.setView(firstRow ? [firstRow.cx, firstRow.cy] : [21.70, 79.35], 11);
    setOccBasemap(occBaseType);
  }}
  occLayers.forEach(l => occMap.removeLayer(l)); occLayers = [];

  if (o.buffer) {{
    occLayers.push(L.geoJSON(o.buffer, {{ style: {{ color: '#B23A2A', weight: 2, dashArray: '3,7', fillOpacity: 0.03 }} }}).addTo(occMap));
  }}
  occLayers.push(L.geoJSON(o.boundary, {{ style: {{ color: '#C2841A', weight: 2.5, dashArray: '8,8', fillOpacity: 0 }} }}).addTo(occMap));

  const stationIcon = L.divIcon({{ className: 'triangle-icon', iconSize: [8, 7] }});
  o.stations.forEach(s => occLayers.push(L.marker([s.lat, s.lon], {{ icon: stationIcon }}).bindPopup(s.id).addTo(occMap)));

  const runId = currentOccRunId();
  const runLabel = document.getElementById('occ-run-label');
  if (runLabel) runLabel.textContent = runId !== null ? `Showing run #${{runId}}` : 'No runs yet';

  const tigerIds = Object.keys(o.history || {{}});
  const visibleIds = selectedFilter === 'all' ? tigerIds : tigerIds.filter(t => t === selectedFilter);

  visibleIds.forEach(tid => {{
    const hist = o.history[tid];
    const runsForTiger = Object.keys(hist).map(Number).sort((a, b) => a - b);
    const upToRuns = runsForTiger.filter(r => r <= runId);
    const latestRun = upToRuns.length ? upToRuns[upToRuns.length - 1] : null;
    if (latestRun === null) return;

    const snap = hist[latestRun];

    // Home range polygon: most recent snapshot at or before the selected
    // run — overlapping tiger polygons naturally stack up and darken
    // where two territories overlap (the brief's overlap-visibility need).
    occLayers.push(L.geoJSON(snap.geojson, {{ style: {{ color: snap.color, fillOpacity: 0.3, weight: 2.5 }} }})
      .bindPopup(`<b>${{snap.name}}</b><br>${{snap.area}} sq km (as of run #${{latestRun}})`)
      .addTo(occMap));

    // Exactly ONE triangle marker per tiger: its approximate location for
    // the selected run. If it was actually sighted this run, use the
    // (averaged, if multiple captures) sighting position; otherwise fall
    // back to its last-known centroid, so the marker never disappears
    // between runs but also never multiplies into several triangles.
    let markerLat = snap.cx, markerLon = snap.cy;
    let posLabel = `Last known centroid (as of run #${{latestRun}})`;
    const thisRun = hist[runId];
    if (thisRun && thisRun.points && thisRun.points.length) {{
      const n = thisRun.points.length;
      markerLat = thisRun.points.reduce((s, p) => s + p.lat, 0) / n;
      markerLon = thisRun.points.reduce((s, p) => s + p.lon, 0) / n;
      posLabel = n > 1
        ? `Sighted in run #${{runId}} (${{n}} captures, avg. position)`
        : `Sighted in run #${{runId}} @ ${{thisRun.points[0].station || '—'}}`;
    }}

    occLayers.push(L.marker([markerLat, markerLon], {{ icon: triangleDivIcon(snap.color, 18) }})
      .bindPopup(`<b>${{snap.name}}</b><br>${{posLabel}}<br>Home range: ${{snap.area}} sq km`)
      .addTo(occMap));
  }});

  setTimeout(() => occMap.invalidateSize(), 120);
}}

function toggleOccPlay() {{
  const btn = document.getElementById('occ-play-btn');
  const sel = document.getElementById('occ-run-select');
  if (!btn || !sel) return;
  if (occPlayTimer) {{
    clearInterval(occPlayTimer); occPlayTimer = null;
    btn.textContent = '▶ Play';
    return;
  }}
  btn.textContent = '⏸ Pause';
  occPlayTimer = setInterval(() => {{
    const opts = Array.from(sel.options);
    if (!opts.length) return;
    let idx = opts.findIndex(opt => opt.value === sel.value);
    idx = (idx + 1) % opts.length;
    sel.selectedIndex = idx;
    drawOccMap();
    if (idx === opts.length - 1) {{
      clearInterval(occPlayTimer); occPlayTimer = null; btn.textContent = '▶ Play';
    }}
  }}, 1400);
}}

function renderOccupancy() {{
  const o = DATA.occupancy;
  document.getElementById('page-occupancy').innerHTML = `
    <div class="stat-grid" style="grid-template-columns:repeat(3,1fr)">
      <div class="stat-card"><div class="stat-label">${{T('mapped')}}</div><div class="stat-num">${{o.mapped}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('overlaps')}}</div><div class="stat-num" style="color:var(--orange)">${{o.overlap_pairs}} ${{T('pairs')}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('area_covered')}}</div><div class="stat-num" style="color:var(--green)">${{o.total_area}} km²</div></div>
    </div>
    <div class="two-col">
      <div class="table-panel"><div class="table-head">${{T('filter_individual')}}</div>
        <div class="catalogue-item ${{selectedFilter==='all'?'active':''}}" data-fid="all"><div class="cat-name">${{T('all_individuals')}}</div></div>
        ${{o.rows.map(r => `<div class="catalogue-item ${{selectedFilter===r.id?'active':''}}" data-fid="${{r.id}}">
          <div class="cat-avatar" style="width:14px;height:14px;background:${{r.color}}"></div>
          <div><div class="cat-name">${{r.name}}</div><div class="cat-sub mono">${{r.area}} km²</div></div>
        </div>`).join('')}}
      </div>
      <div>
        <div class="table-panel" style="padding:14px">
          <div class="mono" style="font-size:10.5px;color:var(--muted);margin-bottom:8px">${{T('map_title')}}</div>
          <div class="toggle-group" style="margin-bottom:10px;align-items:center;gap:8px;display:flex;flex-wrap:wrap">
            <span class="mono" style="font-size:11px;color:var(--muted)">Run:</span>
            <select id="occ-run-select" class="btn mono" style="padding:4px 8px">
              ${{o.run_ids.length
                ? o.run_ids.map(r => `<option value="${{r}}" ${{r === o.run_ids[o.run_ids.length - 1] ? 'selected' : ''}}>#${{r}}</option>`).join('')
                : `<option value="">—</option>`}}
            </select>
            <button class="btn" id="occ-play-btn">▶ Play</button>
            <span class="mono" style="font-size:11px;color:var(--muted);margin-left:auto">Map:</span>
            <button class="btn occ-base-btn ${{occBaseType==='terrain'?'active':''}}" data-base="terrain">🗺 Terrain</button>
            <button class="btn occ-base-btn ${{occBaseType==='satellite'?'active':''}}" data-base="satellite">🛰 Satellite</button>
          </div>
          <div class="mono" id="occ-run-label" style="font-size:11px;color:var(--muted);margin-bottom:6px;text-align:right"></div>
          <div id="occ-map"></div>
          <div class="legend-row">
            <span><span class="legend-swatch" style="background:#9AA88E"></span>${{T('legend_station')}}</span>
            <span><span class="legend-swatch" style="background:#C2841A"></span>${{T('legend_boundary')}}</span>
            ${{o.buffer ? `<span><span class="legend-swatch" style="background:#B23A2A"></span>${{T('legend_buffer')}}</span>` : ''}}
            <span>${{T('legend_overlap')}}</span>
          </div>
          <div class="legend-row" style="margin-top:6px">
            ${{o.rows.map(r => `<span><span class="legend-swatch" style="background:${{r.color}}"></span>${{r.name}}</span>`).join('')}}
          </div>
        </div>
      </div>
    </div>
    <h2 class="section-h" style="margin-top:20px">${{T('summary_table')}}</h2>
    <div class="table-panel"><table class="data-table">
      <tr><th></th><th>${{T('col_area')}}</th><th>${{T('col_centroid')}}</th><th>${{T('col_stations')}}</th><th>${{T('col_overlap')}}</th></tr>
      ${{o.rows.map(r => `<tr><td><span class="legend-swatch" style="background:${{r.color}}"></span>${{r.name}}</td><td>${{r.area}}</td><td class="mono">${{r.centroid_lat}}°N, ${{r.centroid_lon}}°E</td><td>${{r.stations_used}}</td><td><span class="badge ${{r.has_overlap?'badge-warn':'badge-ok'}}">${{r.has_overlap?T('yes'):T('no')}}</span></td></tr>`).join('')}}
    </table></div>`;
  document.querySelectorAll('[data-fid]').forEach(item => item.addEventListener('click', () => {{ selectedFilter = item.dataset.fid; drawOccMap(); document.querySelectorAll('[data-fid]').forEach(el => el.classList.toggle('active', el.dataset.fid === selectedFilter)); }}));
  const runSel = document.getElementById('occ-run-select');
  if (runSel) runSel.addEventListener('change', drawOccMap);
  const playBtn = document.getElementById('occ-play-btn');
  if (playBtn) playBtn.addEventListener('click', toggleOccPlay);
  document.querySelectorAll('.occ-base-btn').forEach(b => b.addEventListener('click', () => setOccBasemap(b.dataset.base)));
  occMap = null;
  setTimeout(drawOccMap, 80);
}}

function renderAlerts() {{
  const a = DATA.alerts_page;
  const filtered = alertFilter === 'all' ? a.alerts : a.alerts.filter(x => x.severity === alertFilter);
  document.getElementById('page-alerts').innerHTML = `
    <div class="stat-grid" style="grid-template-columns:repeat(3,1fr)">
      <div class="stat-card"><div class="stat-label">${{T('high')}}</div><div class="stat-num" style="color:var(--red)">${{a.high}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('medium')}}</div><div class="stat-num" style="color:var(--amber)">${{a.medium}}</div></div>
      <div class="stat-card"><div class="stat-label">${{T('low')}}</div><div class="stat-num" style="color:var(--green)">${{a.low}}</div></div>
    </div>
    <div class="toggle-group" id="alert-filters" style="margin-bottom:16px">
      <button class="btn ${{alertFilter==='all'?'active':''}}" data-af="all">${{T('all_alerts')}}</button>
      <button class="btn ${{alertFilter==='high'?'active':''}}" data-af="high">${{T('high')}}</button>
      <button class="btn ${{alertFilter==='medium'?'active':''}}" data-af="medium">${{T('medium')}}</button>
      <button class="btn ${{alertFilter==='low'?'active':''}}" data-af="low">${{T('low')}}</button>
    </div>
    ${{filtered.length === 0 ? `<div class="empty">—</div>` : filtered.map(al => `<div class="alert-card ${{al.severity}}">
      <div><span class="sev-tag ${{al.severity}}">${{T(al.severity)}}</span>
        <div class="alert-title">${{al.title}}</div><div class="alert-meta">${{al.id}} · ${{al.tiger}} · ${{al.date}}</div></div>
      <div class="alert-body">${{al.what}}${{al.severity==='low' ? `<br><i style="color:var(--muted);font-size:12px">${{T('artefact_note')}}</i>` : ''}}
        <div class="evidence-box"><b>${{T('supporting_evidence')}}:</b> ${{al.evidence}}</div>
      </div>
      <div class="alert-actions"><button class="btn active">${{T('mark_resolved')}}</button><button class="btn">${{T('view_frames')}}</button><button class="btn">${{T('export_report')}}</button></div>
    </div>`).join('')}}`;
  document.querySelectorAll('#alert-filters button').forEach(btn => btn.addEventListener('click', () => {{ alertFilter = btn.dataset.af; renderAlerts(); }}));
}}

function renderAll() {{ renderOverview(); renderBlank(); renderTiger(); renderOccupancy(); renderAlerts(); }}
renderAll();
</script>
</body>
</html>"""


def main():
    data = fetch_data()
    html = build_html(data)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"Dashboard generated: {OUTPUT_PATH} ({size_kb:.0f} KB)")
    print(f"  Tigers: {data['tiger_id']['known']}, Alerts: {len(data['alerts_page']['alerts'])}, "
          f"Overlaps: {data['occupancy']['overlap_pairs']}")


if __name__ == "__main__":
    main()