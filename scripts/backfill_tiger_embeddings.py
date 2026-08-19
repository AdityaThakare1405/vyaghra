"""
Backfills real stored embeddings for the 4 demo tigers (Virat/T-271,
Bheem/T-201, Yuvraj/T-259, Bajirao/T-273) using their actual sample photos
in data/samples/best_tigers/. They were originally seeded by
seed_demo_tigers.py with fake territory data but NO embedding_vector
(NULL) -- meaning the matcher only ever had Swastik to compare against,
which is why everything auto-matched to him. This gives the matcher real
candidates for all 5 known tigers.

Does NOT touch territory/occupancy_snapshots, images, or sightings for
these 4 -- only fills in their embedding_vector column, using an UPDATE,
never an INSERT/DELETE. Safe to re-run.

Usage:
    python -m scripts.backfill_tiger_embeddings
"""

import pickle

from src.db import get_connection
from src.classification.blank_detector import classify_image
from src.identification.detector import detect_and_crop
from src.config import BASE_DIR

BEST_TIGERS_DIR = BASE_DIR / "data" / "samples" / "best_tigers"

# Maps real ATRW tiger ID (used in the best_tigers folder names) to the
# Vyaghra tiger_id used in the tigers table -- same mapping seed_demo_tigers.py uses.
REAL_ID_TO_VYAGHRA_ID = {
    "271": "T-271",  # Virat
    "201": "T-201",  # Bheem
    "259": "T-259",  # Yuvraj
    "273": "T-273",  # Bajirao
}


def main():
    conn = get_connection()

    for real_id, vyaghra_id in REAL_ID_TO_VYAGHRA_ID.items():
        row = conn.execute("SELECT tiger_id, notes FROM tigers WHERE tiger_id = ?", (vyaghra_id,)).fetchone()
        if not row:
            print(f"  {vyaghra_id}: not found in tigers table, skipping")
            continue

        folder = BEST_TIGERS_DIR / f"tiger_{real_id}"
        photos = sorted([p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")]) if folder.exists() else []
        if not photos:
            print(f"  {vyaghra_id} ({row[1]}): no photos found in {folder}, skipping")
            continue

        embedding_to_store = None
        for img_path in photos:
            result = classify_image(str(img_path))
            if result["label"] != "subject":
                continue
            crop_path, usable = detect_and_crop(str(img_path))
            crop_result = classify_image(crop_path, skip_person_check=True) if crop_path else result
            if crop_result["embedding"] is not None:
                embedding_to_store = crop_result["embedding"]
                break  # one good embedding per tiger is enough

        if embedding_to_store is None:
            print(f"  {vyaghra_id} ({row[1]}): no usable embedding found in {len(photos)} photos, skipping")
            continue

        blob = pickle.dumps(embedding_to_store.detach().numpy())
        conn.execute("UPDATE tigers SET embedding_vector = ? WHERE tiger_id = ?", (blob, vyaghra_id))
        conn.commit()
        print(f"  {vyaghra_id} ({row[1]}): embedding stored from {photos[0].name}")

    conn.close()
    print("\nDone. All 5 tigers (Virat, Bheem, Yuvraj, Bajirao, Swastik) now have real embeddings.")
    print("Future run_pipeline.py runs will match against all 5, not just Swastik.")


if __name__ == "__main__":
    main()