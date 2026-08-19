"""
Central configuration for the Vyaghra pipeline.
Every module should import constants from here instead of hardcoding values.
"""

from pathlib import Path

# ── Paths ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

RAW_DATA_DIR = BASE_DIR / "data" / "raw"
QUARANTINE_DIR = BASE_DIR / "data" / "quarantine"
SAMPLES_DIR = BASE_DIR / "data" / "samples"
OUTPUTS_DIR = BASE_DIR / "outputs"
DB_PATH = BASE_DIR / "outputs" / "vyaghra.db"

for p in [RAW_DATA_DIR, QUARANTINE_DIR, OUTPUTS_DIR]:
    p.mkdir(parents=True, exist_ok=True)

# ── Blank / subject / human classification ───────────
BLANK_CONFIDENCE_THRESHOLD = 0.60

# ── Tiger ID matching thresholds ─────────────────────
MATCH_AUTO_THRESHOLD = 0.75
MATCH_REVIEW_LOWER = 0.45

# ── Occupancy / alerting thresholds ──────────────────
# Brief specifies a 15-20 sq km RANGE for core-zone alerts: below 15 -> no
# alert, 15-20 -> medium confidence, above 20 -> high confidence.
CORE_ZONE_SHIFT_THRESHOLD_SQKM = 15
CORE_ZONE_SHIFT_THRESHOLD_SQKM_HIGH = 20
# Buffer zone uses straight-line centroid distance instead of area, since
# near village-adjacent stations precise distance matters more than area.
BUFFER_ZONE_SHIFT_THRESHOLD_KM = 5
ABSENCE_MULTIPLIER = 3

# Width (km) of the buffer ring drawn/generated around the reserve boundary.
# Used only when the user does not hand-draw an explicit buffer polygon in
# scripts/draw_map.py (see scripts/import_drawn_shapes.py).
RESERVE_BUFFER_WIDTH_KM = 5

# ── Misc ───────────────────────────────────────────────
RANDOM_SEED = 42