"""
Deletes everything a specific pipeline run wrote to the database:
sightings -> tigers first-enrolled in that run -> images -> the run record
itself, in that order (matches the FK chain sightings->images->runs and
tigers->runs, so nothing is ever left dangling).

Usage:
    python -m scripts.undo_bad_run 7
    python -m scripts.undo_bad_run 7 --yes     # skip the confirmation prompt
"""

import argparse
from src.db import get_connection


def undo_run(run_id: int, auto_confirm: bool = False):
    conn = get_connection()

    run_row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run_row is None:
        print(f"No run with run_id={run_id} found. Nothing to do.")
        conn.close()
        return

    n_images = conn.execute(
        "SELECT count(*) FROM images WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    n_sightings = conn.execute(
        """SELECT count(*) FROM sightings
           WHERE image_id IN (SELECT image_id FROM images WHERE run_id = ?)""",
        (run_id,),
    ).fetchone()[0]
    bad_tigers = conn.execute(
        "SELECT tiger_id FROM tigers WHERE first_enrolled_run_id = ?", (run_id,)
    ).fetchall()

    print(f"Run {run_id}: {n_images} image(s), {n_sightings} sighting(s), "
          f"{len(bad_tigers)} tiger(s) first-enrolled here: "
          f"{[t[0] for t in bad_tigers]}")

    if not auto_confirm:
        answer = input("Delete all of the above? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted — nothing changed.")
            conn.close()
            return

    conn.execute(
        """DELETE FROM sightings
           WHERE image_id IN (SELECT image_id FROM images WHERE run_id = ?)""",
        (run_id,),
    )
    conn.execute("DELETE FROM tigers WHERE first_enrolled_run_id = ?", (run_id,))
    conn.execute("DELETE FROM images WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    conn.commit()

    fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_issues:
        print(f"WARNING: foreign_key_check found issues after delete: {fk_issues}")
    else:
        print(f"Run {run_id} fully removed. Foreign key check: clean.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=int, help="The run_id to undo")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    undo_run(args.run_id, auto_confirm=args.yes)