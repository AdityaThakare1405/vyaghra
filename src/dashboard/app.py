"""
Dashboard: the forest-staff-facing interface. Plain language throughout,
no exposed ML jargon, per the brief's usability requirement.
"""

import sys
from pathlib import Path

# Streamlit runs this file directly rather than as a package module, so we
# need to explicitly add the project root to the path for "src." imports
# to resolve correctly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

import streamlit as st
import folium
from streamlit_folium import st_folium
import json as _json

from src.db import get_connection
from src.identification.matcher import record_human_decision

st.set_page_config(page_title="Vyaghra — Pench Tiger Reserve", layout="wide")
st.title("🐅 Vyaghra — Camera Trap Intelligence Dashboard")
st.caption("Automated Camera Trap Triage and Individual Tiger Movement Intelligence — Pench Tiger Reserve")

conn = get_connection()

# ── Top summary bar ──────────────────────────────────────
latest_run = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
if latest_run:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Images Processed (last run)", latest_run[2] or 0)
    col2.metric("Quarantined", latest_run[3] or 0)
    col3.metric("Throughput", f"{latest_run[6] or 0:.0f} img/min" if latest_run[6] else "N/A")
    col4.metric("Time Taken", f"{latest_run[5] or 0:.1f}s" if latest_run[5] else "N/A")

tab1, tab2, tab3 = st.tabs(["🔍 Review Queue", "🗺️ Occupancy Map", "⚠️ Alerts"])

# ── TAB 1: Review Queue ──────────────────────────────────
with tab1:
    st.header("Sightings needing your review")
    st.write("These images had an ambiguous match — please confirm which tiger this is, or mark as new.")

    pending = conn.execute(
        """SELECT sg.sighting_id, i.original_path, sg.match_confidence
           FROM sightings sg JOIN images i ON sg.image_id = i.image_id
           WHERE sg.tiger_id IS NULL"""
    ).fetchall()

    if not pending:
        st.success("No sightings currently need review.")
    else:
        known_tigers = conn.execute("SELECT tiger_id, notes FROM tigers").fetchall()
        tiger_options = [f"{name or tid} ({tid})" for tid, name in known_tigers]
        tiger_id_lookup = {f"{name or tid} ({tid})": tid for tid, name in known_tigers}

        for sighting_id, image_path, confidence in pending:
            col1, col2 = st.columns([1, 2])
            with col1:
                try:
                    st.image(image_path, width=250)
                except Exception:
                    st.write(f"(image not found: {image_path})")
            with col2:
                st.write(f"Confidence this matches a known tiger: **{confidence:.0%}**" if confidence else "New sighting")
                choice = st.selectbox(
                    "Which tiger is this?", ["-- New Individual --"] + tiger_options, key=f"select_{sighting_id}"
                )
                if st.button("Confirm", key=f"confirm_{sighting_id}"):
                    tiger_id = tiger_id_lookup.get(choice) if choice != "-- New Individual --" else None
                    record_human_decision(sighting_id, tiger_id, reviewer_name="Field Staff")
                    st.rerun()
            st.divider()

# ── TAB 2: Occupancy Map ─────────────────────────────────
with tab2:
    st.header("Tiger-wise Territory Map")

    latest_snapshot_run = conn.execute("SELECT MAX(run_id) FROM occupancy_snapshots").fetchone()[0]
    snapshots = conn.execute(
        """SELECT o.tiger_id, o.centroid_lat, o.centroid_lon, o.area_sq_km, o.home_range_geojson, t.notes
           FROM occupancy_snapshots o JOIN tigers t ON o.tiger_id = t.tiger_id
           WHERE o.run_id = ?""",
        (latest_snapshot_run,),
    ).fetchall() if latest_snapshot_run else []

    if not snapshots:
        st.info("No occupancy data yet — run the pipeline and regenerate occupancy first.")
    else:
        m = folium.Map(location=[snapshots[0][1], snapshots[0][2]], zoom_start=11)
        colors = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue"]

        # Overlay an approximate Pench Tiger Reserve boundary, built from
        # publicly documented coordinates (official WDPA boundary geometry
        # is licensed and not redistributable — see docs/README.md).
        try:
            with open("data/samples/pench_boundary_approx.geojson") as f:
                boundary = _json.load(f)
            folium.GeoJson(
                boundary,
                name="Reserve Boundary (approximate)",
                style_function=lambda x: {"color": "black", "weight": 2, "dashArray": "5,5", "fillOpacity": 0},
            ).add_to(m)
        except FileNotFoundError:
            pass

        

        for idx, (tiger_id, lat, lon, area, geojson_str, display_name) in enumerate(snapshots):
            name = display_name if display_name else tiger_id
            color = colors[idx % len(colors)]

            # Shaded, smoothed territory polygon.
            folium.GeoJson(
                _json.loads(geojson_str),
                style_function=lambda x, c=color: {"color": c, "fillOpacity": 0.3},
            ).add_to(m)

            # Centroid marker.
            folium.Marker(
                [lat, lon],
                popup=f"{name}: {area:.1f} sq km",
                icon=folium.Icon(color=color if color in ["red", "blue", "green", "orange"] else "gray"),
            ).add_to(m)

            # Individual sighting points — shows exactly where and when the
            # tiger was actually captured, alongside the summarized territory.
            sighting_points = conn.execute(
                """SELECT i.gps_lat, i.gps_lon, i.station_id, i.capture_timestamp
                   FROM sightings s JOIN images i ON s.image_id = i.image_id
                   WHERE s.tiger_id = ?""",
                (tiger_id,),
            ).fetchall()

            for plat, plon, station_id, timestamp in sighting_points:
                if plat is None or plon is None:
                    continue
                folium.CircleMarker(
                    location=[plat, plon],
                    radius=5,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.9,
                    popup=f"{name} @ {station_id}<br>{timestamp}",
                ).add_to(m)

            st.write(f"🐅 **{name}** ({tiger_id}) — home range: **{area:.1f} sq km**, centroid: ({lat:.4f}, {lon:.4f})")

        st_folium(m, width=1100, height=550)

        # Export button — satisfies the brief's requirement that occupancy
        # data be "exported in a form usable by forest department staff."
        export_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"tiger_id": tid, "name": nm or tid, "area_sq_km": ar},
                    "geometry": _json.loads(gj),
                }
                for tid, lat, lon, ar, gj, nm in snapshots
            ],
        }
        st.download_button(
            label="📥 Download Occupancy Data (GeoJSON)",
            data=_json.dumps(export_data, indent=2),
            file_name="vyaghra_occupancy_export.geojson",
            mime="application/geo+json",
        )

# ── TAB 3: Alerts ─────────────────────────────────────────
with tab3:
    st.header("Deviation Alerts")

    alerts = conn.execute(
        """SELECT tiger_id, alert_type, what_changed, supporting_evidence, confidence_level, artefact_flag
           FROM alerts ORDER BY alert_id DESC LIMIT 20"""
    ).fetchall()

    if not alerts:
        st.success("No alerts raised.")
    else:
        for tiger_id, alert_type, what_changed, evidence, confidence, artefact_flag in alerts:
            icon = "ℹ️" if artefact_flag else "⚠️"
            label = "Possible survey artefact (not a real deviation)" if artefact_flag else alert_type.replace("_", " ").title()
            with st.expander(f"{icon} {tiger_id} — {label}"):
                st.write(f"**What changed:** {what_changed}")
                st.write(f"**Evidence:** {evidence}")
                st.write(f"**Confidence:** {confidence}")

conn.close()