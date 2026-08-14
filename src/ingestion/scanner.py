"""
Ingestion module: walks a raw image folder, extracts metadata,
and normalizes it into structured records ready for the database.
"""

from pathlib import Path
from datetime import datetime
import exifread

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def find_images(folder: Path):
    """Recursively find all image files in a folder, regardless of naming/structure."""
    folder = Path(folder)
    return [p for p in folder.rglob("*") if p.suffix.lower() in VALID_EXTENSIONS]


def extract_metadata(image_path: Path):
    """
    Extracts timestamp and GPS from EXIF if available.
    Returns a dict — never raises, since a single bad file must not crash a batch run.
    """
    record = {
        "original_path": str(image_path),
        "capture_timestamp": None,
        "timestamp_confidence": "unknown",
        "gps_lat": None,
        "gps_lon": None,
    }

    try:
        with open(image_path, "rb") as f:
            tags = exifread.process_file(f, details=False)

        dt_tag = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        if dt_tag:
            try:
                dt = datetime.strptime(str(dt_tag), "%Y:%m:%d %H:%M:%S")
                record["capture_timestamp"] = dt.isoformat()
                record["timestamp_confidence"] = _assess_timestamp_confidence(dt)
            except ValueError:
                record["timestamp_confidence"] = "unparseable"
        else:
            record["timestamp_confidence"] = "missing"

        lat = tags.get("GPS GPSLatitude")
        lon = tags.get("GPS GPSLongitude")
        if lat and lon:
            record["gps_lat"] = _convert_gps(lat)
            record["gps_lon"] = _convert_gps(lon)

    except Exception as e:
        record["timestamp_confidence"] = f"error: {e}"

    return record


def _assess_timestamp_confidence(dt: datetime) -> str:
    if dt.year < 2000:
        return "suspicious_reset"
    if dt.year > datetime.now().year + 1:
        return "suspicious_future"
    return "ok"


def _convert_gps(gps_tag) -> float:
    d, m, s = [float(x.num) / float(x.den) for x in gps_tag.values]
    return d + (m / 60.0) + (s / 3600.0)


if __name__ == "__main__":
    from src.config import SAMPLES_DIR

    images = find_images(SAMPLES_DIR)
    print(f"Found {len(images)} images in {SAMPLES_DIR}")

    for img in images[:5]:
        meta = extract_metadata(img)
        print(meta)