"""
Nulls out T-SWASTIK's stored embedding so he's excluded from the matcher,
same as the other 4 demo tigers (none of whom have an embedding either).
Run once after undoing run 7 (or any time you want to reset him back to
manual-only matching).

Usage:
    python -m scripts.clear_swastik_embedding
"""

from src.db import get_connection

TIGER_ID = "T-SWASTIK"


def main():
    conn = get_connection()

    row = conn.execute(
        "SELECT embedding_vector IS NOT NULL FROM tigers WHERE tiger_id = ?", (TIGER_ID,)
    ).fetchone()

    if row is None:
        print(f"No tiger with id {TIGER_ID} found — nothing to do.")
        conn.close()
        return

    if row[0] == 0:
        print(f"{TIGER_ID} already has no stored embedding. Nothing to do.")
        conn.close()
        return

    conn.execute("UPDATE tigers SET embedding_vector = NULL WHERE tiger_id = ?", (TIGER_ID,))
    conn.commit()
    print(f"Cleared {TIGER_ID}'s embedding. He'll now only be matched manually, like the other 4.")
    conn.close()


if __name__ == "__main__":
    main()