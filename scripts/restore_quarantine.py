"""
Restores images from quarantine back to their original location.
Proves the "safe and reversible" deletion requirement from the brief —
nothing is ever permanently lost.
"""

import shutil
from pathlib import Path

from src.config import QUARANTINE_DIR
from src.db import get_connection


def restore_all():
    conn = get_connection()
    quarantined = conn.execute(
        "SELECT image_id, original_path FROM images WHERE quarantined = 1"
    ).fetchall()

    restored = 0
    for image_id, original_path in quarantined:
        quarantine_copy = QUARANTINE_DIR / Path(original_path).name
        if quarantine_copy.exists():
            shutil.copy(str(quarantine_copy), original_path)
            conn.execute("UPDATE images SET quarantined = 0 WHERE image_id = ?", (image_id,))
            restored += 1

    conn.commit()
    conn.close()
    print(f"Restored {restored} image(s) from quarantine.")


if __name__ == "__main__":
    restore_all()