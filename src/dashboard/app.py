"""
Dashboard: the forest-staff-facing interface. Plain language throughout,
no exposed ML jargon, per the brief's usability requirement.
"""

import streamlit as st
import folium
from streamlit_folium import st_folium
import json

from src.db import get_connection
from src.identification.matcher import record_human_decision

st.set_page_config(page_title="Vyaghra — Pench Tiger Reserve", layout="wide")
st.title("🐅 Vyaghra — Camera Trap Intelligence Dashboard")

conn = get_connection()

tab1, tab2, tab3 = st.tabs(["Review Queue", "Occupancy Map", "Alerts"])

# ── TAB 1: Review Queue ──────────────────────────────────
with tab1:
    st.header("Sightings needing your review")
    pending = conn.execute(
        """SELECT sg.sighting_id, i.original_path, sg.match_confidence
           FROM sightings sg JOIN images i ON sg.image_id = i.image_id
           WHERE sg.tiger_id IS NULL"""
    ).fetchall()

    if not pending:
        st.success("No sightings currently need review.")
    else:
        for sighting_id, image_path, confidence in pending:
            col1, col2 = st.columns([1, 2])
            with col1:
                st.image(image_path, width=250)
            with col2:
                st.write(f"Confidence this matches a known tiger: **{confidence:.0%}**" if confidence else "New sighting")
                known_tigers = [row[0] for row in conn.execute("SELECT tiger_id FROM tigers").fetchall()]
                choice = st.selectbox(
                    "Which tiger is this?", ["-- New Individual --"] + known_tigers, key=f"select_{sighting_id}"
                )
                if st.button("Confirm", key=f"confirm_{sighting_id}"):
                    tiger_id = choice if choice != "-- New Individual --" else None
                    record_human_decision(sighting_id, tiger_id, reviewer_name="Field Staff")
                    st.rerun()

# ── TAB 2: Occupancy Map ─────────────────────────────────
with tab2:
    st.header("Tiger-wise Territory Map")
    snapshots = conn.execute(
        """SELECT tiger_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson
           FROM occupancy_snapshots
           WHERE run_id = (SELECT MAX(run_id) FROM occupancy_snapshots)"""
    ).fetchall()

    if not snapshots:
        st.info("No occupancy data yet — run the pipeline first.")
    else:
        m = folium.Map(location=[snapshots[0][1], snapshots[0][2]], zoom_start=11)
        colors = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue"]

        for idx, (tiger_id, lat, lon, area, geojson_str) in enumerate(snapshots):
            color = colors[idx % len(colors)]
            folium.GeoJson(
                json.loads(geojson_str),
                style_function=lambda x, c=color: {"color": c, "fillOpacity": 0.3},
            ).add_to(m)
            folium.Marker([lat, lon], popup=f"{tiger_id}: {area:.1f} sq km").add_to(m)
            st.write(f"**{tiger_id}** — home range: {area:.1f} sq km, centroid: ({lat:.4f}, {lon:.4f})")

        st_folium(m, width=900, height=500)

# ── TAB 3: Alerts ─────────────────────────────────────────
with tab3:
    st.header("Deviation Alerts")
    alerts = conn.execute(
        """SELECT tiger_id, alert_type, what_changed, supporting_evidence, confidence_level, artefact_flag
           FROM alerts ORDER BY alert_id DESC LIMIT 20"""
    ).fetchall()

    if not alerts:
        st.success("No alerts on the latest run.")
    else:
        for tiger_id, alert_type, what_changed, evidence, confidence, artefact_flag in alerts:
            icon = "⚠️" if not artefact_flag else "ℹ️"
            label = "Possible survey artefact (not a real deviation)" if artefact_flag else alert_type.replace("_", " ").title()
            with st.expander(f"{icon} {tiger_id} — {label}"):
                st.write(f"**What changed:** {what_changed}")
                st.write(f"**Evidence:** {evidence}")
                st.write(f"**Confidence:** {confidence}")

conn.close()