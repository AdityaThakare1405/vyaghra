"""
One-time loader: reads data/samples/stations.csv and inserts the rows
into the stations table.
"""

import csv
from pathlib import Path

from src.db import get_connection
from src.config import SAMPLES_DIR

CSV_PATH = SAMPLES_DIR / "stations.csv"


def load_stations():
    conn = get_connection()

    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            conn.execute(
                """INSERT OR REPLACE INTO stations (station_id, zone, lat, lon, install_date)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["station_id"], row["zone"], float(row["lat"]), float(row["lon"]), row["install_date"]),
            )
            count += 1

    conn.commit()
    conn.close()
    print(f"Loaded {count} stations into the database.")


if __name__ == "__main__":
    load_stations()