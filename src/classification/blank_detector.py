"""
Classification module: determines whether an image is blank, contains a
subject (animal), or contains a human — using a single pretrained
MobileNetV3-Small model plus OpenCV's built-in person detector.
"""

import cv2
import torch

# Force both OpenCV and PyTorch to single-threaded mode. On Windows, both
# libraries bundle their own copy of the OpenMP threading runtime, and
# letting them both multi-thread independently causes silent heap
# corruption crashes (Windows exit code 0xC0000374) after repeated calls —
# this is a known interaction issue, not a bug in our own logic.
cv2.setNumThreads(1)
torch.set_num_threads(1)

from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
from PIL import Image

from src.config import BLANK_CONFIDENCE_THRESHOLD

# Load model once, at import time.
_weights = MobileNet_V3_Small_Weights.DEFAULT
_model = mobilenet_v3_small(weights=_weights)
_model.eval()

_preprocess = _weights.transforms()
_categories = _weights.meta["categories"]

# ImageNet class indices for animals; 292 = tiger, 282 = tiger cat.
_ANIMAL_CLASS_RANGE = range(0, 398)
_TIGER_CLASSES = {282, 292}

_hog = cv2.HOGDescriptor()
_hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())


def _detect_person(image_bgr) -> bool:
    h, w = image_bgr.shape[:2]

    # HOG's detector has a fixed internal window size and can throw a
    # low-level C++ exception on images that are too small or unusually
    # shaped (which happens with tight crops). Skip the check safely in
    # that case rather than crashing the whole pipeline.
    if h < 64 or w < 64:
        return False

    try:
        resized = cv2.resize(image_bgr, (min(640, w), min(480, h)))
        boxes, weights = _hog.detectMultiScale(resized, winStride=(8, 8))
        if len(boxes) == 0:
            return False
        return max(weights) > 0.7 if len(weights) > 0 else False
    except cv2.error:
        # Defensive fallback: if HOG still fails for any other reason,
        # don't crash the batch run over a single problematic frame.
        return False


def classify_image(image_path: str, skip_person_check: bool = False):
    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        return {"label": "blank", "confidence": 0.0, "is_tiger_class": False, "embedding": None}

    if not skip_person_check and _detect_person(image_bgr):
        return {"label": "human", "confidence": 1.0, "is_tiger_class": False, "embedding": None}

    # ... rest of the function stays exactly the same

    # Contrast enhancement helps dark/low-light or IR-style camera-trap frames,
    # which are common in real field data and underrepresented in ImageNet's
    # mostly daylight-color training images.
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced_bgr = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

    image_pil = Image.fromarray(cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB))
    input_tensor = _preprocess(image_pil).unsqueeze(0)

    with torch.no_grad():
        features = _model.features(input_tensor)
        pooled = torch.nn.functional.adaptive_avg_pool2d(features, 1).flatten(1)
        logits = _model(input_tensor)
        probs = torch.nn.functional.softmax(logits, dim=1)[0]

    # Check the top-5 predictions, not just the single best guess — a
    # deliberately more forgiving check, since the evaluation criteria
    # specifically penalize false negatives (missing real subjects) more
    # than false positives (keeping an actually-blank frame a bit longer).
    top5_probs, top5_idx = torch.topk(probs, 5)

    is_animal = False
    best_animal_prob = 0.0
    is_tiger = False

    for prob, idx in zip(top5_probs.tolist(), top5_idx.tolist()):
        if idx in _ANIMAL_CLASS_RANGE and prob >= 0.15:
            is_animal = True
            best_animal_prob = max(best_animal_prob, prob)
        if idx in _TIGER_CLASSES:
            is_tiger = True

    label = "subject" if is_animal else "blank"
    confidence = round(best_animal_prob if is_animal else top5_probs[0].item(), 4)

    return {
        "label": label,
        "confidence": confidence,
        "is_tiger_class": is_tiger,
        "embedding": pooled.squeeze(0),
    }


if __name__ == "__main__":
    from src.config import SAMPLES_DIR
    from src.ingestion.scanner import find_images

    images = find_images(SAMPLES_DIR)
    print(f"Testing classifier on {len(images)} sample images...\n")

    for img in images:
        result = classify_image(str(img))
        print(f"{img.parent.name}/{img.name}: label={result['label']}, "
              f"confidence={result['confidence']}, is_tiger_class={result['is_tiger_class']}")