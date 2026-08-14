"""
Detection/crop module: isolates the most likely "subject region" (flank
area) of an image, using a contour-based heuristic rather than a trained
object detector.

Design note: a trained detector (e.g., MegaDetector) would be more accurate
but is GPU-class and out of scope for the CPU-only field-hardware
constraint. This heuristic is a deliberate, documented tradeoff — see
docs/README.md "Known Limitations".

Crops are saved to a separate data/crops/ folder (NOT alongside the
originals) so that re-running this module never picks up its own output
as new input.
"""

import cv2
import numpy as np
from pathlib import Path

from src.config import BASE_DIR

CROPS_DIR = BASE_DIR / "data" / "crops"
CROPS_DIR.mkdir(parents=True, exist_ok=True)


def detect_and_crop(image_path: str):
    """
    Finds the largest contiguous foreground region and crops to it.
    Falls back to the full image if no plausible region is found.

    Returns:
        crop_path (str) — path to the saved crop (or full image fallback)
        flank_usable (bool) — True if a crop/image was produced at all
    """
    image = cv2.imread(image_path)
    if image is None:
        return None, False

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    kernel = np.ones((7, 7), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    image_area = image.shape[0] * image.shape[1]
    original_name = Path(image_path).stem
    crop_path = str(CROPS_DIR / f"{original_name}_crop.jpg")

    if not contours:
        # No contour found at all -> use the whole image rather than nothing.
        cv2.imwrite(crop_path, image)
        return crop_path, True

    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    x, y, w, h = cv2.boundingRect(largest)

    area_ratio = area / image_area
    aspect_ratio = w / h if h > 0 else 0

    # Sanity check: a real animal crop shouldn't be tiny or absurdly thin/wide.
    # If the heuristic's guess looks implausible, fall back to the full image
    # instead of a clearly wrong crop.
    if area_ratio < 0.02 or area_ratio > 0.95 or aspect_ratio < 0.2 or aspect_ratio > 5:
        cv2.imwrite(crop_path, image)
        return crop_path, True

    cropped = image[y:y + h, x:x + w]
    cv2.imwrite(crop_path, cropped)
    return crop_path, True


if __name__ == "__main__":
    from src.config import SAMPLES_DIR
    from src.ingestion.scanner import find_images

    images = find_images(SAMPLES_DIR)
    tiger_images = [img for img in images if "tiger" in str(img)]

    print(f"Processing {len(tiger_images[:20])} tiger images...\n")

    for img in tiger_images[:20]:
        crop_path, usable = detect_and_crop(str(img))
        print(f"{img.name}: crop={crop_path}, usable={usable}")