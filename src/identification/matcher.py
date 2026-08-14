"""
Matching module: compares a new sighting's embedding against the persistent
catalogue of known tigers, and applies the brief's required three-way logic:
  - high similarity  -> auto-match to existing tiger
  - low similarity    -> auto-enroll as a new individual
  - in between         -> send to human review queue, never silently guessed
"""

import numpy as np
import pickle
import uuid

from sklearn.metrics.pairwise import cosine_similarity

from src.config import MATCH_AUTO_THRESHOLD, MATCH_REVIEW_LOWER
from src.db import get_connection


def _embedding_to_blob(embedding) -> bytes:
    array = embedding.detach().numpy() if hasattr(embedding, "detach") else np.array(embedding)
    return pickle.dumps(array)


def _blob_to_embedding(blob: bytes):
    return pickle.loads(blob)


def _get_all_tiger_embeddings(conn):
    rows = conn.execute("SELECT tiger_id, embedding_vector FROM tigers").fetchall()
    return [(tiger_id, _blob_to_embedding(blob)) for tiger_id, blob in rows if blob is not None]


def match_or_enroll(embedding, run_id: int):
    conn = get_connection()
    known = _get_all_tiger_embeddings(conn)

    new_vec = embedding.detach().numpy().reshape(1, -1) if hasattr(embedding, "detach") else np.array(embedding).reshape(1, -1)

    if not known:
        tiger_id = _enroll_new_tiger(conn, embedding, run_id)
        conn.close()
        return {"decision": "auto_enrolled", "tiger_id": tiger_id, "confidence": 1.0, "candidates": []}

    similarities = []
    for tiger_id, known_vec in known:
        sim = cosine_similarity(new_vec, known_vec.reshape(1, -1))[0][0]
        similarities.append((tiger_id, float(sim)))

    similarities.sort(key=lambda x: x[1], reverse=True)
    best_tiger_id, best_sim = similarities[0]

    if best_sim >= MATCH_AUTO_THRESHOLD:
        conn.close()
        return {"decision": "auto_match", "tiger_id": best_tiger_id, "confidence": best_sim, "candidates": []}

    elif best_sim >= MATCH_REVIEW_LOWER:
        conn.close()
        return {
            "decision": "needs_review",
            "tiger_id": None,
            "confidence": best_sim,
            "candidates": similarities[:3],
        }

    else:
        tiger_id = _enroll_new_tiger(conn, embedding, run_id)
        conn.close()
        return {"decision": "auto_enrolled", "tiger_id": tiger_id, "confidence": best_sim, "candidates": []}


def _enroll_new_tiger(conn, embedding, run_id: int) -> str:
    tiger_id = f"T-{uuid.uuid4().hex[:6].upper()}"
    blob = _embedding_to_blob(embedding)
    conn.execute(
        "INSERT INTO tigers (tiger_id, first_enrolled_run_id, embedding_vector) VALUES (?, ?, ?)",
        (tiger_id, run_id, blob),
    )
    conn.commit()
    return tiger_id


def record_human_decision(sighting_id: int, tiger_id: str, reviewer_name: str):
    conn = get_connection()
    conn.execute(
        """UPDATE sightings
           SET tiger_id = ?, decision_source = 'human', reviewed_by = ?, reviewed_at = datetime('now')
           WHERE sighting_id = ?""",
        (tiger_id, reviewer_name, sighting_id),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    from src.classification.blank_detector import classify_image
    from src.identification.detector import detect_and_crop
    from src.config import SAMPLES_DIR

    # Test using tiger_247's 5 known photos of the SAME individual.
    test_folder = SAMPLES_DIR / "tigers_multi" / "tiger_247"
    test_images = sorted(test_folder.glob("*.jpg"))

    print(f"Testing matcher on {len(test_images)} photos of the same real tiger (247):\n")

    # Insert a dummy run row so we have a valid run_id to reference.
    from src.db import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO runs (run_timestamp) VALUES (datetime('now'))")
    conn.commit()
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    for img_path in test_images:
        crop_path, usable = detect_and_crop(str(img_path))
        result = classify_image(crop_path)
        if result["embedding"] is None:
            print(f"{img_path.name}: skipped (no embedding)")
            continue
        match = match_or_enroll(result["embedding"], run_id)
        print(f"{img_path.name}: decision={match['decision']}, tiger_id={match['tiger_id']}, "
              f"confidence={match['confidence']:.3f}")