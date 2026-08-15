"""
Generates a futuristic, data-rich, multi-language (EN/HI/MR) HTML
dashboard styled around real camera-trap / night-vision / GPS-telemetry
visual language — a separate, more visually striking companion to the
working Streamlit app (src/dashboard/app.py), which is left untouched.

Run this any time after processing/seeding data to regenerate with fresh
numbers. Open the output file directly in any browser — no server needed.
"""

import base64
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from datetime import datetime

from PIL import Image

from src.config import DB_PATH, BASE_DIR

OUTPUT_PATH = BASE_DIR / "outputs" / "vyaghra_dashboard.html"
BOUNDARY_PATH = BASE_DIR / "data" / "samples" / "pench_boundary_approx.geojson"
THUMB_SIZE = (260, 260)


def image_to_data_uri(path_str):
    try:
        p = Path(path_str)
        if not p.exists():
            return None
        img = Image.open(p).convert("RGB")
        img.thumbnail(THUMB_SIZE)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=72)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def fetch_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    tigers = conn.execute("SELECT tiger_id, notes FROM tigers").fetchall()
    name_lookup = {t["tiger_id"]: (t["notes"] or t["tiger_id"]) for t in tigers}

    latest_run_id = conn.execute("SELECT MAX(run_id) FROM occupancy_snapshots").fetchone()[0]
    snapshots = conn.execute(
        """SELECT tiger_id, centroid_lat, centroid_lon, area_sq_km, home_range_geojson
           FROM occupancy_snapshots WHERE run_id = ?""",
        (latest_run_id,),
    ).fetchall() if latest_run_id else []

    tiger_cards = []
    for s in snapshots:
        points = conn.execute(
            """SELECT i.gps_lat, i.gps_lon, i.station_id, i.capture_timestamp
               FROM sightings sg JOIN images i ON sg.image_id = i.image_id
               WHERE sg.tiger_id = ? AND i.gps_lat IS NOT NULL""",
            (s["tiger_id"],),
        ).fetchall()
        tiger_cards.append({
            "id": s["tiger_id"], "name": name_lookup.get(s["tiger_id"], s["tiger_id"]),
            "area": round(s["area_sq_km"], 1), "lat": s["centroid_lat"], "lon": s["centroid_lon"],
            "geojson": json.loads(s["home_range_geojson"]),
            "points": [{"lat": p["gps_lat"], "lon": p["gps_lon"], "station": p["station_id"]} for p in points],
            "sighting_count": len(points),
        })

    # Recent capture thumbnails — most recent sighting per tiger, real DB images.
    captures = []
    for s in snapshots:
        row = conn.execute(
            """SELECT i.original_path, i.station_id, i.capture_timestamp, sg.match_confidence, sg.tiger_id
               FROM sightings sg JOIN images i ON sg.image_id = i.image_id
               WHERE sg.tiger_id = ? AND i.original_path != 'synthetic'
               ORDER BY sg.sighting_id DESC LIMIT 2""",
            (s["tiger_id"],),
        ).fetchall()
        for r in row:
            data_uri = image_to_data_uri(r["original_path"])
            if data_uri:
                captures.append({
                    "tiger": name_lookup.get(r["tiger_id"], r["tiger_id"]),
                    "station": r["station_id"], "timestamp": r["capture_timestamp"] or "—",
                    "confidence": round(r["match_confidence"] or 0, 2), "image": data_uri,
                })

    pending_reviews = conn.execute(
        "SELECT sighting_id, match_confidence FROM sightings WHERE tiger_id IS NULL"
    ).fetchall()

    alerts = conn.execute(
        """SELECT tiger_id, alert_type, what_changed, supporting_evidence, confidence_level, artefact_flag
           FROM alerts ORDER BY alert_id DESC LIMIT 20"""
    ).fetchall()
    alert_list = [{
        "tiger": name_lookup.get(a["tiger_id"], a["tiger_id"]), "type": a["alert_type"],
        "what": a["what_changed"], "evidence": a["supporting_evidence"],
        "confidence": a["confidence_level"], "artefact": bool(a["artefact_flag"]),
    } for a in alerts]

    recent_confirmed = conn.execute(
        """SELECT tiger_id, reviewed_by, reviewed_at FROM sightings
           WHERE decision_source = 'human' AND reviewed_at IS NOT NULL
           ORDER BY reviewed_at DESC LIMIT 8"""
    ).fetchall()
    review_list = [{"tiger": name_lookup.get(r["tiger_id"], r["tiger_id"]),
                     "reviewer": r["reviewed_by"], "when": r["reviewed_at"]} for r in recent_confirmed]

    # Forest telemetry — real aggregate stats, not decorative filler.
    latest_run = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    station_counts = conn.execute("SELECT zone, COUNT(*) c FROM stations GROUP BY zone").fetchall()
    zone_split = {r["zone"]: r["c"] for r in station_counts}
    total_stations = sum(zone_split.values())
    total_sightings = conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
    avg_conf_row = conn.execute("SELECT AVG(match_confidence) FROM sightings WHERE match_confidence IS NOT NULL").fetchone()
    avg_confidence = round((avg_conf_row[0] or 0) * 100, 1)
    total_quarantined = conn.execute("SELECT SUM(images_quarantined) FROM runs").fetchone()[0] or 0
    total_space_saved = conn.execute("SELECT SUM(space_freed_mb) FROM runs").fetchone()[0] or 0

    conn.close()

    with open(BOUNDARY_PATH) as f:
        boundary_geojson = json.load(f)["features"][0]["geometry"]

    return {
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        "tiger_count": len(tiger_cards),
        "pending_review_count": len(pending_reviews),
        "alert_count": len([a for a in alert_list if not a["artefact"]]),
        "throughput": round(latest_run["throughput_img_per_min"], 0) if latest_run and latest_run["throughput_img_per_min"] else 0,
        "images_processed": latest_run["images_processed"] if latest_run else 0,
        "tigers": tiger_cards, "alerts": alert_list, "reviews": review_list, "captures": captures,
        "boundary": boundary_geojson,
        "telemetry": {
            "total_stations": total_stations, "core_stations": zone_split.get("core", 0),
            "buffer_stations": zone_split.get("buffer", 0), "total_sightings": total_sightings,
            "avg_confidence": avg_confidence, "total_quarantined": total_quarantined,
            "total_space_saved": round(total_space_saved, 1),
        },
    }


I18N = {
    "en": {
        "app_name": "VYAGHRA", "tagline": "Camera Trap Intelligence Network — Pench Tiger Reserve",
        "active_tigers": "Active Tigers", "pending_review": "Pending Review", "alerts_raised": "Alerts Raised",
        "images_processed": "Images Processed", "territory_map": "Territory Map",
        "sq_km": "sq km", "alerts_heading": "Alert Log", "no_alerts": "No alerts on the latest run.",
        "reviews_heading": "Recent Reviews", "no_reviews": "No reviews recorded yet.",
        "confirmed_by": "Confirmed by", "artefact_note": "Likely survey artefact — not a real deviation",
        "what_changed": "Change detected", "evidence": "Evidence", "confidence": "Confidence",
        "generated": "Last sync", "recent_captures": "Recent Captures", "telemetry": "Network Telemetry",
        "stations": "Camera Stations", "core_buffer": "Core / Buffer", "total_sightings": "Total Sightings",
        "avg_match": "Avg Match Confidence", "frames_cleared": "Frames Auto-Cleared", "space_saved": "Storage Reclaimed",
        "throughput": "Throughput", "img_per_min": "img/min", "mb": "MB", "station": "Station", "captured": "Captured",
    },
    "hi": {
        "app_name": "व्याघ्र", "tagline": "कैमरा ट्रैप निगरानी नेटवर्क — पेंच टाइगर रिज़र्व",
        "active_tigers": "सक्रिय बाघ", "pending_review": "समीक्षा लंबित", "alerts_raised": "चेतावनियाँ",
        "images_processed": "संसाधित छवियाँ", "territory_map": "क्षेत्र मानचित्र",
        "sq_km": "वर्ग किमी", "alerts_heading": "चेतावनी लॉग", "no_alerts": "अंतिम रन में कोई चेतावनी नहीं।",
        "reviews_heading": "हाल की समीक्षाएँ", "no_reviews": "अभी तक कोई समीक्षा दर्ज नहीं हुई।",
        "confirmed_by": "द्वारा पुष्टि", "artefact_note": "सर्वेक्षण त्रुटि हो सकती है, वास्तविक बदलाव नहीं",
        "what_changed": "परिवर्तन", "evidence": "प्रमाण", "confidence": "विश्वास स्तर",
        "generated": "अंतिम समन्वय", "recent_captures": "हाल की तस्वीरें", "telemetry": "नेटवर्क टेलीमेट्री",
        "stations": "कैमरा स्टेशन", "core_buffer": "कोर / बफर", "total_sightings": "कुल दृश्य",
        "avg_match": "औसत मिलान विश्वास", "frames_cleared": "स्वतः साफ़ फ्रेम", "space_saved": "बचाया गया स्थान",
        "throughput": "प्रसंस्करण गति", "img_per_min": "चित्र/मिनट", "mb": "MB", "station": "स्टेशन", "captured": "समय",
    },
    "mr": {
        "app_name": "व्याघ्र", "tagline": "कॅमेरा ट्रॅप देखरेख नेटवर्क — पेंच व्याघ्र प्रकल्प",
        "active_tigers": "सक्रिय वाघ", "pending_review": "पुनरावलोकन प्रलंबित", "alerts_raised": "इशारे",
        "images_processed": "प्रक्रिया केलेली छायाचित्रे", "territory_map": "क्षेत्र नकाशा",
        "sq_km": "चौ. किमी", "alerts_heading": "इशारा नोंदी", "no_alerts": "शेवटच्या फेरीत कोणतेही इशारे नाहीत.",
        "reviews_heading": "अलीकडील पुनरावलोकने", "no_reviews": "अद्याप कोणतीही नोंद नाही.",
        "confirmed_by": "यांनी पुष्टी केली", "artefact_note": "सर्वेक्षण त्रुटी असू शकते, खरा बदल नाही",
        "what_changed": "बदल", "evidence": "पुरावा", "confidence": "विश्वासार्हता",
        "generated": "शेवटचे समक्रमण", "recent_captures": "अलीकडील छायाचित्रे", "telemetry": "नेटवर्क टेलीमेट्री",
        "stations": "कॅमेरा स्थानके", "core_buffer": "गाभा / बफर", "total_sightings": "एकूण नोंदी",
        "avg_match": "सरासरी जुळणी विश्वास", "frames_cleared": "स्वयं-साफ फ्रेम्स", "space_saved": "वाचवलेली जागा",
        "throughput": "प्रक्रिया वेग", "img_per_min": "प्रतिमा/मिनिट", "mb": "MB", "station": "स्थानक", "captured": "वेळ",
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
<title>Vyaghra — Pench Tiger Reserve</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;600;700&family=Noto+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {{
    --void: #0A0E0C; --panel: #10161380; --panel-solid: #101613; --line: rgba(111,255,176,0.14);
    --phosphor: #6FFFB0; --phosphor-dim: #3D8A66; --amber: #FFB347; --cyan: #4FD8E8;
    --danger: #FF5C5C; --text: #DCEDE3; --muted: #6B8478;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--void); color: var(--text);
    font-family: 'Noto Sans', 'Noto Sans Devanagari', sans-serif;
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size: 42px 42px;
  }}
  .font-hi h1,.font-hi h2,.font-hi h3,.font-mr h1,.font-mr h2,.font-mr h3 {{ font-family: 'Noto Sans Devanagari', sans-serif; font-weight: 700; }}
  .font-en h1,.font-en h2,.font-en h3 {{ font-family: 'Chakra Petch', sans-serif; }}
  .mono {{ font-family: 'JetBrains Mono', monospace; }}

  header {{
    background: linear-gradient(180deg, #0D1310, #0A0E0C);
    border-bottom: 1px solid var(--line); padding: 18px 32px;
    display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10;
  }}
  .brand {{ display: flex; align-items: baseline; gap: 16px; }}
  .brand h1 {{
    margin: 0; font-size: 26px; font-weight: 700; letter-spacing: 0.08em; color: var(--phosphor);
    text-shadow: 0 0 18px rgba(111,255,176,0.45);
  }}
  .tagline {{ font-size: 12px; color: var(--muted); letter-spacing: 0.03em; }}
  .lang-toggle {{ display: flex; gap: 6px; }}
  .lang-toggle button {{
    background: transparent; border: 1px solid var(--phosphor-dim); color: var(--muted);
    padding: 6px 14px; cursor: pointer; font-size: 12px; font-family: 'JetBrains Mono', monospace; letter-spacing: 0.05em;
  }}
  .lang-toggle button.active {{ background: var(--phosphor); border-color: var(--phosphor); color: #04140C; font-weight: 700; }}

  main {{ max-width: 1360px; margin: 0 auto; padding: 26px 32px 60px; }}

  .ledger {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }}
  .card {{ background: var(--panel); border: 1px solid var(--line); backdrop-filter: blur(6px); }}
  .ledger-card {{ padding: 16px 18px; position: relative; }}
  .ledger-card::after {{ content: ""; position: absolute; top: 10px; right: 10px; width: 6px; height: 6px; border-radius: 50%; background: var(--phosphor); box-shadow: 0 0 8px var(--phosphor); }}
  .ledger-card.alert::after {{ background: var(--danger); box-shadow: 0 0 8px var(--danger); }}
  .ledger-card.pending::after {{ background: var(--amber); box-shadow: 0 0 8px var(--amber); }}
  .ledger-num {{ font-family: 'JetBrains Mono', monospace; font-size: 36px; font-weight: 600; color: var(--phosphor); }}
  .ledger-card.alert .ledger-num {{ color: var(--danger); }}
  .ledger-card.pending .ledger-num {{ color: var(--amber); }}
  .ledger-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 4px; }}

  .telemetry-bar {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 20px; }}
  .telemetry-item {{ padding: 12px 14px; text-align: center; }}
  .telemetry-val {{ font-family: 'JetBrains Mono', monospace; font-size: 19px; color: var(--cyan); font-weight: 600; }}
  .telemetry-label {{ font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-top: 3px; }}

  .grid {{ display: grid; grid-template-columns: 1.5fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .panel {{ padding: 18px; }}
  .panel h2 {{ margin: 0 0 14px; font-size: 15px; color: var(--phosphor); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
    border-bottom: 1px solid var(--line); padding-bottom: 10px; }}
  #map {{ height: 440px; border: 1px solid var(--line); filter: saturate(0.85); }}

  .entry {{ display: flex; gap: 12px; padding: 11px 0; border-bottom: 1px solid var(--line); }}
  .entry:last-child {{ border-bottom: none; }}
  .entry-title {{ font-weight: 600; font-size: 13.5px; color: var(--text); margin-bottom: 3px; }}
  .entry-meta {{ font-size: 11.5px; color: var(--muted); line-height: 1.5; }}
  .entry-meta b {{ color: var(--text); }}
  .badge {{
    display: inline-flex; align-items: center; padding: 3px 9px; font-size: 9.5px; font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase; letter-spacing: 0.06em; border-radius: 2px; height: fit-content; flex-shrink: 0;
  }}
  .badge-alert {{ background: rgba(255,92,92,0.15); color: var(--danger); border: 1px solid var(--danger); }}
  .badge-check {{ background: rgba(107,132,120,0.15); color: var(--muted); border: 1px solid var(--muted); }}
  .empty {{ color: var(--muted); font-size: 13px; padding: 8px 0; }}

  .captures-row {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }}
  .capture-card {{ position: relative; border: 1px solid var(--phosphor-dim); overflow: hidden; background: #04140C; }}
  .capture-card img {{
    width: 100%; height: 160px; object-fit: cover; display: block;
    filter: grayscale(0.55) sepia(0.35) hue-rotate(60deg) saturate(2.2) brightness(0.9) contrast(1.1);
  }}
  .capture-scan {{
    position: absolute; top: 0; left: 0; right: 0; height: 2px; background: rgba(111,255,176,0.65);
    box-shadow: 0 0 8px rgba(111,255,176,0.8); animation: scan 3.2s linear infinite;
  }}
  @keyframes scan {{ 0% {{ top: 0; }} 100% {{ top: 100%; }} }}
  .reticle {{ position: absolute; width: 14px; height: 14px; border-color: var(--phosphor); opacity: 0.85; }}
  .reticle.tl {{ top: 6px; left: 6px; border-top: 2px solid; border-left: 2px solid; }}
  .reticle.tr {{ top: 6px; right: 6px; border-top: 2px solid; border-right: 2px solid; }}
  .reticle.bl {{ bottom: 6px; left: 6px; border-bottom: 2px solid; border-left: 2px solid; }}
  .reticle.br {{ bottom: 6px; right: 6px; border-bottom: 2px solid; border-right: 2px solid; }}
  .capture-meta {{
    padding: 8px 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--phosphor);
    background: rgba(4,20,12,0.9); display: flex; justify-content: space-between;
  }}
  .capture-meta .tname {{ color: var(--text); font-weight: 600; }}

  footer {{ text-align: center; color: var(--muted); font-size: 11px; margin-top: 30px; font-family: 'JetBrains Mono', monospace; }}

  @media (max-width: 900px) {{
    .ledger, .telemetry-bar {{ grid-template-columns: repeat(2, 1fr); }}
    .grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body class="font-en">

<header>
  <div class="brand">
    <h1 data-i18n="app_name">VYAGHRA</h1>
    <span class="tagline" data-i18n="tagline">Camera Trap Intelligence Network — Pench Tiger Reserve</span>
  </div>
  <div class="lang-toggle">
    <button data-lang="en" class="active">EN</button>
    <button data-lang="hi">हिं</button>
    <button data-lang="mr">मरा</button>
  </div>
</header>

<main>
  <div class="ledger">
    <div class="ledger-card card">
      <div class="ledger-num" id="stat-tigers">0</div>
      <div class="ledger-label" data-i18n="active_tigers">Active Tigers</div>
    </div>
    <div class="ledger-card card pending">
      <div class="ledger-num" id="stat-pending">0</div>
      <div class="ledger-label" data-i18n="pending_review">Pending Review</div>
    </div>
    <div class="ledger-card card alert">
      <div class="ledger-num" id="stat-alerts">0</div>
      <div class="ledger-label" data-i18n="alerts_raised">Alerts Raised</div>
    </div>
    <div class="ledger-card card">
      <div class="ledger-num" id="stat-images">0</div>
      <div class="ledger-label" data-i18n="images_processed">Images Processed</div>
    </div>
  </div>

  <div class="telemetry-bar">
    <div class="telemetry-item card"><div class="telemetry-val" id="tel-stations">0</div><div class="telemetry-label" data-i18n="stations">Camera Stations</div></div>
    <div class="telemetry-item card"><div class="telemetry-val" id="tel-corebuffer">0/0</div><div class="telemetry-label" data-i18n="core_buffer">Core / Buffer</div></div>
    <div class="telemetry-item card"><div class="telemetry-val" id="tel-sightings">0</div><div class="telemetry-label" data-i18n="total_sightings">Total Sightings</div></div>
    <div class="telemetry-item card"><div class="telemetry-val" id="tel-confidence">0%</div><div class="telemetry-label" data-i18n="avg_match">Avg Match Confidence</div></div>
    <div class="telemetry-item card"><div class="telemetry-val" id="tel-cleared">0</div><div class="telemetry-label" data-i18n="frames_cleared">Frames Auto-Cleared</div></div>
    <div class="telemetry-item card"><div class="telemetry-val" id="tel-throughput">0</div><div class="telemetry-label" data-i18n="throughput">Throughput</div></div>
  </div>

  <div class="panel card" style="margin-bottom:16px;">
    <h2 data-i18n="recent_captures">Recent Captures</h2>
    <div class="captures-row" id="captures-row"></div>
  </div>

  <div class="grid">
    <div class="panel card">
      <h2 data-i18n="territory_map">Territory Map</h2>
      <div id="map"></div>
    </div>
    <div>
      <div class="panel card" style="margin-bottom:16px;">
        <h2 data-i18n="alerts_heading">Alert Log</h2>
        <div id="alerts-list"></div>
      </div>
      <div class="panel card">
        <h2 data-i18n="reviews_heading">Recent Reviews</h2>
        <div id="reviews-list"></div>
      </div>
    </div>
  </div>

  <footer><span data-i18n="generated">Last sync</span>: {data['generated_at']}</footer>
</main>

<script>
const DATA = {data_json};
const I18N = {i18n_json};
let currentLang = "en";
const COLORS = ["#6FFFB0", "#4FD8E8", "#FFB347", "#FF9E9E", "#B08FFF", "#7FE0C4"];

function applyLang(lang) {{
  currentLang = lang;
  document.body.className = lang === "hi" ? "font-hi" : lang === "mr" ? "font-mr" : "font-en";
  document.querySelectorAll("[data-i18n]").forEach(el => {{
    const key = el.getAttribute("data-i18n");
    if (I18N[lang][key]) el.textContent = I18N[lang][key];
  }});
  document.querySelectorAll(".lang-toggle button").forEach(b => b.classList.toggle("active", b.dataset.lang === lang));
  render();
}}
document.querySelectorAll(".lang-toggle button").forEach(btn => btn.addEventListener("click", () => applyLang(btn.dataset.lang)));

function render() {{
  const t = I18N[currentLang];
  document.getElementById("stat-tigers").textContent = DATA.tiger_count;
  document.getElementById("stat-pending").textContent = DATA.pending_review_count;
  document.getElementById("stat-alerts").textContent = DATA.alert_count;
  document.getElementById("stat-images").textContent = DATA.images_processed;

  const tel = DATA.telemetry;
  document.getElementById("tel-stations").textContent = tel.total_stations;
  document.getElementById("tel-corebuffer").textContent = `${{tel.core_stations}}/${{tel.buffer_stations}}`;
  document.getElementById("tel-sightings").textContent = tel.total_sightings;
  document.getElementById("tel-confidence").textContent = tel.avg_confidence + "%";
  document.getElementById("tel-cleared").textContent = tel.total_quarantined;
  document.getElementById("tel-throughput").textContent = DATA.throughput + " " + t.img_per_min;

  const capEl = document.getElementById("captures-row");
  capEl.innerHTML = "";
  DATA.captures.forEach(c => {{
    const div = document.createElement("div");
    div.className = "capture-card";
    div.innerHTML = `
      <img src="${{c.image}}">
      <div class="capture-scan"></div>
      <div class="reticle tl"></div><div class="reticle tr"></div><div class="reticle bl"></div><div class="reticle br"></div>
      <div class="capture-meta"><span class="tname">${{c.tiger}}</span><span>${{t.station}} ${{c.station}}</span></div>`;
    capEl.appendChild(div);
  }});

  const alertsEl = document.getElementById("alerts-list");
  alertsEl.innerHTML = "";
  if (DATA.alerts.length === 0) {{
    alertsEl.innerHTML = `<div class="empty">${{t.no_alerts}}</div>`;
  }} else {{
    DATA.alerts.forEach(a => {{
      const div = document.createElement("div");
      div.className = "entry";
      div.innerHTML = `
        <span class="badge ${{a.artefact ? 'badge-check' : 'badge-alert'}}">${{a.artefact ? 'CHECK' : 'ALERT'}}</span>
        <div>
          <div class="entry-title">${{a.tiger}} — ${{a.type.replace(/_/g,' ')}}</div>
          <div class="entry-meta">
            <b>${{t.what_changed}}:</b> ${{a.what}}<br>
            ${{a.artefact ? `<i>${{t.artefact_note}}</i><br>` : ''}}
            <b>${{t.confidence}}:</b> ${{a.confidence}}
          </div>
        </div>`;
      alertsEl.appendChild(div);
    }});
  }}

  const reviewsEl = document.getElementById("reviews-list");
  reviewsEl.innerHTML = "";
  if (DATA.reviews.length === 0) {{
    reviewsEl.innerHTML = `<div class="empty">${{t.no_reviews}}</div>`;
  }} else {{
    DATA.reviews.forEach(r => {{
      const div = document.createElement("div");
      div.className = "entry";
      div.innerHTML = `<div><div class="entry-title">${{r.tiger}}</div>
        <div class="entry-meta">${{t.confirmed_by}} <b>${{r.reviewer}}</b> — ${{r.when}}</div></div>`;
      reviewsEl.appendChild(div);
    }});
  }}
}}

const map = L.map('map', {{ zoomControl: true }});
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 18
}}).addTo(map);

L.geoJSON(DATA.boundary, {{ style: {{ color: '#6FFFB0', weight: 2, dashArray: '6,6', fillOpacity: 0 }} }}).addTo(map);

if (DATA.tigers.length > 0) {{
  map.setView([DATA.tigers[0].lat, DATA.tigers[0].lon], 11);
  DATA.tigers.forEach((tiger, i) => {{
    const color = COLORS[i % COLORS.length];
    L.geoJSON(tiger.geojson, {{ style: {{ color: color, fillOpacity: 0.22, weight: 2 }} }}).addTo(map);
    tiger.points.forEach(p => {{
      L.circleMarker([p.lat, p.lon], {{ radius: 4, color: color, fillColor: color, fillOpacity: 0.9, weight: 1 }})
        .bindPopup(`<b>${{tiger.name}}</b><br>${{p.station}}`).addTo(map);
    }});
    L.marker([tiger.lat, tiger.lon]).addTo(map).bindPopup(`<b>${{tiger.name}}</b><br>${{tiger.area}} sq km`);
  }});
}} else {{
  map.setView([21.70, 79.35], 10);
}}

applyLang("en");
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
    print(f"  Tigers: {data['tiger_count']}, Captures embedded: {len(data['captures'])}, Alerts: {data['alert_count']}")


if __name__ == "__main__":
    main()