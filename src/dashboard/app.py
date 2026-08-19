"""
Full-featured Streamlit dashboard — mirrors the HTML TigerLens-style
report but fully interactive: real Leaflet-equivalent map (via
streamlit-folium), live filters, a working human-review loop that writes
back to the database, and real tiger photo galleries you can actually
open and browse. EN/HI/MR language toggle included.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

import json
import sqlite3
from datetime import datetime

import streamlit as st
import folium
from streamlit_folium import st_folium
from shapely.geometry import shape

from src.db import get_connection
from src.config import DB_PATH, BASE_DIR
from src.identification.matcher import record_human_decision

BOUNDARY_PATH = BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson"
LAKE_PATH = BASE_DIR / "data" / "samples" / "pench_lake_approx.geojson"

st.set_page_config(page_title="Vyaghra — Pench Tiger Reserve", layout="wide", initial_sidebar_state="expanded")

# ── Language dictionary ──────────────────────────────────
I18N = {
    "en": {
        "title": "🐅 Vyaghra — Camera Trap Intelligence", "tagline": "Pench Tiger Reserve",
        "nav_overview": "Overview", "nav_blank": "Blank Filter", "nav_tiger": "Tiger ID",
        "nav_occupancy": "Occupancy", "nav_alerts": "Alerts", "nav_review": "Review Queue",
        "images_processed": "Images Processed", "blanks_removed": "Blanks Removed",
        "tigers_identified": "Tigers Identified", "active_alerts": "Active Alerts",
        "quarantined": "Blanks Quarantined", "retained": "Subjects Retained", "awaiting": "Awaiting Review",
        "known_individuals": "Known Individuals", "select_tiger": "Select a tiger",
        "first_seen": "First seen", "last_seen": "Last seen", "total_sightings": "Total sightings",
        "gallery": "Real Captured Photos", "mapped": "Individuals Mapped", "overlap_pairs": "Overlapping Pairs",
        "total_area": "Total Area Covered", "filter_individual": "Filter by individual", "all": "All",
        "high": "High", "medium": "Medium", "low": "Low", "no_alerts": "No alerts.",
        "no_reviews": "No sightings need review.", "confirm": "Confirm", "which_tiger": "Which tiger is this?",
        "new_individual": "-- New Individual --",
    },
    "hi": {
        "title": "🐅 व्याघ्र — कैमरा ट्रैप बुद्धिमत्ता", "tagline": "पेंच टाइगर रिज़र्व",
        "nav_overview": "अवलोकन", "nav_blank": "रिक्त फ़िल्टर", "nav_tiger": "बाघ पहचान",
        "nav_occupancy": "क्षेत्र अधिभोग", "nav_alerts": "चेतावनियाँ", "nav_review": "समीक्षा कतार",
        "images_processed": "संसाधित छवियाँ", "blanks_removed": "हटाई गई रिक्त छवियाँ",
        "tigers_identified": "पहचाने गए बाघ", "active_alerts": "सक्रिय चेतावनियाँ",
        "quarantined": "क्वारंटीन की गई", "retained": "बनाए रखे गए विषय", "awaiting": "समीक्षा प्रतीक्षित",
        "known_individuals": "ज्ञात व्यक्ति", "select_tiger": "एक बाघ चुनें",
        "first_seen": "पहली बार देखा", "last_seen": "अंतिम बार देखा", "total_sightings": "कुल दृश्य",
        "gallery": "वास्तविक कैप्चर की गई तस्वीरें", "mapped": "मानचित्रित व्यक्ति", "overlap_pairs": "अतिव्यापन जोड़े",
        "total_area": "कुल आच्छादित क्षेत्र", "filter_individual": "व्यक्ति द्वारा फ़िल्टर करें", "all": "सभी",
        "high": "उच्च", "medium": "मध्यम", "low": "निम्न", "no_alerts": "कोई चेतावनी नहीं।",
        "no_reviews": "किसी समीक्षा की आवश्यकता नहीं।", "confirm": "पुष्टि करें", "which_tiger": "यह कौन सा बाघ है?",
        "new_individual": "-- नया व्यक्ति --",
    },
    "mr": {
        "title": "🐅 व्याघ्र — कॅमेरा ट्रॅप बुद्धिमत्ता", "tagline": "पेंच व्याघ्र प्रकल्प",
        "nav_overview": "आढावा", "nav_blank": "रिकामे फिल्टर", "nav_tiger": "वाघ ओळख",
        "nav_occupancy": "क्षेत्र व्याप्ती", "nav_alerts": "इशारे", "nav_review": "पुनरावलोकन रांग",
        "images_processed": "प्रक्रिया केलेल्या प्रतिमा", "blanks_removed": "काढलेल्या रिकाम्या",
        "tigers_identified": "ओळखलेले वाघ", "active_alerts": "सक्रिय इशारे",
        "quarantined": "क्वारंटाइन केलेल्या", "retained": "राखलेले विषय", "awaiting": "पुनरावलोकन प्रलंबित",
        "known_individuals": "ज्ञात व्यक्ती", "select_tiger": "वाघ निवडा",
        "first_seen": "प्रथम दिसले", "last_seen": "शेवटचे दिसले", "total_sightings": "एकूण नोंदी",
        "gallery": "खऱ्या टिपलेल्या प्रतिमा", "mapped": "मॅप केलेल्या व्यक्ती", "overlap_pairs": "आच्छादन जोड्या",
        "total_area": "एकूण व्याप्त क्षेत्र", "filter_individual": "व्यक्तीनुसार फिल्टर करा", "all": "सर्व",
        "high": "उच्च", "medium": "मध्यम", "low": "कमी", "no_alerts": "कोणतेही इशारे नाहीत.",
        "no_reviews": "कोणतीही नोंद प्रलंबित नाही.", "confirm": "पुष्टी करा", "which_tiger": "हा कोणता वाघ आहे?",
        "new_individual": "-- नवीन व्यक्ती --",
    },
}

if "lang" not in st.session_state:
    st.session_state.lang = "en"
T = I18N[st.session_state.lang]

# ── Sidebar: language + nav ──────────────────────────────
with st.sidebar:
    st.markdown(f"### {T['title']}")
    st.caption(T["tagline"])
    lang_choice = st.radio("Language", ["EN", "हिं", "मरा"], horizontal=True, label_visibility="collapsed")
    st.session_state.lang = {"EN": "en", "हिं": "hi", "मरा": "mr"}[lang_choice]
    T = I18N[st.session_state.lang]
    st.divider()
    page = st.radio("Navigate", [T["nav_overview"], T["nav_review"], T["nav_tiger"], T["nav_occupancy"], T["nav_alerts"]])

conn = get_connection()

# ── OVERVIEW ──────────────────────────────────────────────
if page == T["nav_overview"]:
    st.title(T["nav_overview"])
    total_images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    blanks = conn.execute("SELECT SUM(images_quarantined) FROM runs").fetchone()[0] or 0
    tigers_count = conn.execute("SELECT COUNT(*) FROM tigers").fetchone()[0]
    alerts_count = conn.execute("SELECT COUNT(*) FROM alerts WHERE artefact_flag = 0").fetchone()[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(T["images_processed"], f"{total_images:,}")
    c2.metric(T["blanks_removed"], f"{int(blanks):,}")
    c3.metric(T["tigers_identified"], tigers_count)
    c4.metric(T["active_alerts"], alerts_count)

    st.divider()
    latest_run = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    if latest_run:
        st.subheader("Last Pipeline Run")
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.write(f"**Started:** {latest_run[1]}")
        rc2.write(f"**Duration:** {latest_run[5]:.0f}s" if latest_run[5] else "—")
        rc3.write(f"**Images:** {latest_run[2]}")
        rc4.write("**Hardware:** No GPU (CPU-only)")

# ── REVIEW QUEUE ──────────────────────────────────────────
elif page == T["nav_review"]:
    st.title(T["nav_review"])
    pending = conn.execute(
        """SELECT sg.sighting_id, i.original_path, sg.match_confidence
           FROM sightings sg JOIN images i ON sg.image_id = i.image_id
           WHERE sg.tiger_id IS NULL"""
    ).fetchall()

    if not pending:
        st.success(T["no_reviews"])
    else:
        known_tigers = conn.execute("SELECT tiger_id, notes FROM tigers").fetchall()
        options = {f"{name or tid} ({tid})": tid for tid, name in known_tigers}

        for sighting_id, image_path, confidence in pending:
            col1, col2 = st.columns([1, 2])
            with col1:
                if image_path and image_path != "synthetic" and Path(image_path).exists():
                    st.image(image_path, width=250)
                else:
                    st.write("(no image on file)")
            with col2:
                st.write(f"Confidence: **{confidence:.0%}**" if confidence else "New sighting")
                choice = st.selectbox(T["which_tiger"], [T["new_individual"]] + list(options.keys()), key=f"sel_{sighting_id}")
                if st.button(T["confirm"], key=f"conf_{sighting_id}"):
                    tiger_id = options.get(choice) if choice != T["new_individual"] else None
                    record_human_decision(sighting_id, tiger_id, reviewer_name="Field Staff")
                    st.rerun()
            st.divider()

# ── TIGER ID (with real photo gallery) ───────────────────
elif page == T["nav_tiger"]:
    st.title(T["nav_tiger"])
    tigers = conn.execute("SELECT tiger_id, notes FROM tigers ORDER BY notes").fetchall()
    st.metric(T["known_individuals"], len(tigers))

    if tigers:
        name_options = {f"{name or tid}": tid for tid, name in tigers}
        selected_name = st.selectbox(T["select_tiger"], list(name_options.keys()))
        selected_id = name_options[selected_name]

        sightings = conn.execute(
            """SELECT i.original_path, i.station_id, i.capture_timestamp, sg.match_confidence
               FROM sightings sg JOIN images i ON sg.image_id = i.image_id
               WHERE sg.tiger_id = ? ORDER BY i.capture_timestamp""",
            (selected_id,),
        ).fetchall()

        timestamps = sorted([s[2] for s in sightings if s[2]])
        c1, c2, c3 = st.columns(3)
        c1.metric(T["first_seen"], timestamps[0][:10] if timestamps else "—")
        c2.metric(T["last_seen"], timestamps[-1][:10] if timestamps else "—")
        c3.metric(T["total_sightings"], len(sightings))

        st.divider()
        st.subheader(T["gallery"])
        real_photos = [s for s in sightings if s[0] and s[0] != "synthetic" and Path(s[0]).exists()]

        if not real_photos:
            st.info("No real photos on file for this individual (synthetic/demo sightings only).")
        else:
            cols = st.columns(4)
            for idx, (path, station, ts, conf) in enumerate(real_photos):
                with cols[idx % 4]:
                    st.image(path, use_container_width=True)
                    st.caption(f"{station} · {ts[:10] if ts else '—'}")

# ── OCCUPANCY (real Leaflet-equivalent map) ──────────────
elif page == T["nav_occupancy"]:
    st.title(T["nav_occupancy"])
    latest_snapshot_run = conn.execute("SELECT MAX(run_id) FROM occupancy_snapshots").fetchone()[0]
    rows = conn.execute(
        """SELECT o.tiger_id, o.centroid_lat, o.centroid_lon, o.area_sq_km, o.home_range_geojson, t.notes
           FROM occupancy_snapshots o JOIN tigers t ON o.tiger_id = t.tiger_id WHERE o.run_id = ?""",
        (latest_snapshot_run,),
    ).fetchall() if latest_snapshot_run else []

    shapely_polys = {r[0]: shape(json.loads(r[4])) for r in rows}
    overlaps = 0
    ids = list(shapely_polys.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            inter = shapely_polys[ids[i]].intersection(shapely_polys[ids[j]])
            if not inter.is_empty and inter.area > 0:
                overlaps += 1

    c1, c2, c3 = st.columns(3)
    c1.metric(T["mapped"], len(rows))
    c2.metric(T["overlap_pairs"], overlaps)
    c3.metric(T["total_area"], f"{sum(r[3] for r in rows):.1f} km²")

    tiger_names = [T["all"]] + [r[5] or r[0] for r in rows]
    filter_choice = st.selectbox(T["filter_individual"], tiger_names)

    if rows:
        m = folium.Map(location=[rows[0][1], rows[0][2]], zoom_start=11)
        colors = ["#4A7A3E", "#C2703D", "#3D7A8A", "#8A5AA8", "#B23A2A", "#2E9E7A", "#D98A50", "#5AAFC0", "#9B59B6", "#16A085"]

        with open(BOUNDARY_PATH) as f:
            boundary_geo = json.load(f)
        folium.GeoJson(boundary_geo, style_function=lambda x: {"color": "#C2841A", "weight": 2.5, "dashArray": "8,8", "fillOpacity": 0}).add_to(m)

        for idx, (tid, lat, lon, area, geojson_str, name) in enumerate(rows):
            display_name = name or tid
            if filter_choice != T["all"] and display_name != filter_choice:
                continue
            color = colors[idx % len(colors)]
            folium.GeoJson(json.loads(geojson_str), style_function=lambda x, c=color: {"color": c, "fillOpacity": 0.3, "weight": 2.5}).add_to(m)
            folium.Marker([lat, lon], popup=f"{display_name}: {area:.1f} sq km", tooltip=display_name).add_to(m)

            station_points = conn.execute(
                """SELECT DISTINCT i.gps_lat, i.gps_lon, i.station_id FROM sightings sg
                   JOIN images i ON sg.image_id = i.image_id WHERE sg.tiger_id = ? AND i.gps_lat IS NOT NULL""",
                (tid,),
            ).fetchall()
            for plat, plon, station_id in station_points:
                folium.CircleMarker([plat, plon], radius=4, color=color, fill=True, fill_color=color, fill_opacity=0.9).add_to(m)

        st_folium(m, width=1100, height=550)

    st.divider()
    st.subheader("Individual Summary")
    table_data = [{"Tiger": r[5] or r[0], "Area (km²)": round(r[3], 1), "Centroid": f"{r[1]:.4f}°N, {r[2]:.4f}°E"} for r in rows]
    st.dataframe(table_data, use_container_width=True)

# ── ALERTS ────────────────────────────────────────────────
elif page == T["nav_alerts"]:
    st.title(T["nav_alerts"])
    alerts = conn.execute(
        """SELECT tiger_id, alert_type, what_changed, supporting_evidence, confidence_level, artefact_flag
           FROM alerts ORDER BY alert_id DESC LIMIT 30"""
    ).fetchall()

    high = len([a for a in alerts if a[4] == "high" and not a[5]])
    medium = len([a for a in alerts if a[4] == "medium" and not a[5]])
    low = len([a for a in alerts if a[5]])
    c1, c2, c3 = st.columns(3)
    c1.metric(T["high"], high)
    c2.metric(T["medium"], medium)
    c3.metric(T["low"], low)

    if not alerts:
        st.success(T["no_alerts"])
    else:
        name_lookup = {t[0]: (t[1] or t[0]) for t in conn.execute("SELECT tiger_id, notes FROM tigers").fetchall()}
        for tiger_id, alert_type, what, evidence, confidence, artefact in alerts:
            icon = "ℹ️" if artefact else ("🔴" if confidence == "high" else "🟡")
            with st.expander(f"{icon} {name_lookup.get(tiger_id, tiger_id)} — {alert_type.replace('_', ' ').title()}"):
                st.write(f"**Change:** {what}")
                st.write(f"**Evidence:** {evidence}")
                st.write(f"**Confidence:** {confidence}")
                if artefact:
                    st.caption("Likely survey artefact — not a genuine deviation.")

conn.close()