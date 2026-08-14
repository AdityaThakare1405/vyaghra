"""
Classification module: determines whether an image is blank, contains a
subject (animal), or contains a human — using a single pretrained
MobileNetV3-Small model plus OpenCV's built-in person detector.
"""

import cv2
import torch
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
    resized = cv2.resize(image_bgr, (min(640, image_bgr.shape[1]), min(480, image_bgr.shape[0])))
    boxes, weights = _hog.detectMultiScale(resized, winStride=(8, 8))
    if len(boxes) == 0:
        return False
    # Only count it as a real person if HOG is genuinely confident —
    # this cuts down false positives on animal shapes/backgrounds.
    return max(weights) > 0.7 if len(weights) > 0 else False


def classify_image(image_path: str):
    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        return {"label": "blank", "confidence": 0.0, "is_tiger_class": False, "embedding": None}

    if _detect_person(image_bgr):
        return {"label": "human", "confidence": 1.0, "is_tiger_class": False, "embedding": None}

    image_pil = Image.open(image_path).convert("RGB")
    input_tensor = _preprocess(image_pil).unsqueeze(0)

    with torch.no_grad():
        features = _model.features(input_tensor)
        pooled = torch.nn.functional.adaptive_avg_pool2d(features, 1).flatten(1)
        logits = _model(input_tensor)
        probs = torch.nn.functional.softmax(logits, dim=1)[0]

    top_prob, top_idx = torch.max(probs, dim=0)
    top_idx = top_idx.item()
    top_prob = top_prob.item()

    is_animal = top_idx in _ANIMAL_CLASS_RANGE and top_prob >= BLANK_CONFIDENCE_THRESHOLD
    is_tiger = top_idx in _TIGER_CLASSES

    label = "subject" if is_animal else "blank"

    return {
        "label": label,
        "confidence": round(top_prob, 4),
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