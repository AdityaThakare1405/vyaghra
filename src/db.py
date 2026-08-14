"""
Database layer for Vyaghra.
Creates and connects to the SQLite database, defines the schema.
"""

import sqlite3
from src.config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    zone TEXT CHECK(zone IN ('core', 'buffer')),
    lat REAL,
    lon REAL,
    install_date TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT,
    images_processed INTEGER,
    images_quarantined INTEGER,
    space_freed_mb REAL,
    time_taken_sec REAL,
    throughput_img_per_min REAL
);

CREATE TABLE IF NOT EXISTS images (
    image_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_path TEXT,
    station_id TEXT,
    capture_timestamp TEXT,
    timestamp_confidence TEXT,
    gps_lat REAL,
    gps_lon REAL,
    classification TEXT CHECK(classification IN ('blank', 'subject', 'human')),
    classification_confidence REAL,
    quarantined INTEGER DEFAULT 0,
    run_id INTEGER,
    FOREIGN KEY(station_id) REFERENCES stations(station_id),
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS tigers (
    tiger_id TEXT PRIMARY KEY,
    first_enrolled_run_id INTEGER,
    embedding_vector BLOB,
    notes TEXT,
    FOREIGN KEY(first_enrolled_run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS sightings (
    sighting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER,
    tiger_id TEXT,
    match_confidence REAL,
    decision_source TEXT CHECK(decision_source IN ('auto', 'human')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    flank_usable INTEGER DEFAULT 1,
    FOREIGN KEY(image_id) REFERENCES images(image_id),
    FOREIGN KEY(tiger_id) REFERENCES tigers(tiger_id)
);

CREATE TABLE IF NOT EXISTS occupancy_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tiger_id TEXT,
    run_id INTEGER,
    centroid_lat REAL,
    centroid_lon REAL,
    area_sq_km REAL,
    home_range_geojson TEXT,
    station_list TEXT,
    FOREIGN KEY(tiger_id) REFERENCES tigers(tiger_id),
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tiger_id TEXT,
    run_id INTEGER,
    alert_type TEXT,
    what_changed TEXT,
    supporting_evidence TEXT,
    confidence_level TEXT,
    artefact_flag INTEGER DEFAULT 0,
    FOREIGN KEY(tiger_id) REFERENCES tigers(tiger_id),
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
"""


def get_connection():
    """Returns a connection to the Vyaghra SQLite database, creating the schema if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    return conn


if __name__ == "__main__":
    conn = get_connection()
    print(f"Database ready at: {DB_PATH}")
    conn.close()