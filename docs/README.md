# Vyaghra — Automated Camera Trap Triage and Individual Tiger Movement Intelligence System

Built for the Manthan4Yuva Hackathon — Forest & Wildlife theme, addressing the Pench Tiger Reserve problem statement.

## Setup

**Requirements:** Python 3.11, no GPU required.

```bash
git clone <repo-url>
cd vyaghra
python -m venv venv
venv\Scripts\Activate.ps1        # Windows
# source venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

python -m src.db
python -m scripts.load_stations
```

**Running the pipeline:**
```bash
python run_pipeline.py --input <path-to-image-folder>
```

**Running the dashboard:**
```bash
streamlit run src/dashboard/app.py
```

**Note on internet access:** the pretrained model weights (~10MB) download once on first use. After that initial download, the entire pipeline runs fully offline — matching the brief's no-internet-connectivity field constraint.

---

## Model & Design Choices

### Blank/subject/human classification
We use a single pretrained **MobileNetV3-Small** (ImageNet weights) for two jobs at once: classifying frames as blank/subject, and generating the embedding used for identification. ImageNet's 1000 classes include a dedicated `tiger` class, giving genuine species-relevant signal with zero training required — appropriate given the CPU-only, no-GPU field hardware constraint, which rules out heavier detectors like MegaDetector.

We check the model's **top-5 predictions**, not just the top-1 guess, biasing toward keeping a frame when there's any reasonable animal signal — this deliberately favors false positives over false negatives, since the evaluation criteria specifically flag false negatives as the more costly error (a missed real sighting is worse than a blank frame that takes slightly longer to discard).

We also apply **CLAHE contrast enhancement** before classification, since real camera-trap data includes low-light/IR-style frames that are underrepresented in ImageNet's daylight-heavy training data. During testing, we found the classifier initially missed several genuine tiger frames that were dark/blue-tinted; this fix directly resolved that false-negative gap (confirmed before/after on the same test images).

### Human detection
OpenCV's built-in HOG + SVM person detector — no extra download needed, fully offline immediately. Used only on original full frames (not on cropped animal regions — see Known Limitations for why).

### Flank/subject region isolation
A contour-based heuristic (edge detection + largest contiguous region), rather than a trained detector. This is a deliberate tradeoff: a trained detector (e.g., MegaDetector) would be more accurate but is GPU-class and out of scope for the CPU-only constraint. Includes a sanity-check fallback to the full image if the detected region looks implausible (too small or an extreme aspect ratio).

### Identification / matching
Cosine similarity between MobileNetV3 embeddings, with a **three-way decision system** as required by the brief: high similarity auto-matches to an existing tiger, low similarity auto-enrolls a new individual, and mid-range similarity is sent to a human review queue rather than silently guessed. Tested against ATRW (Amur Tiger Re-identification dataset), correctly linking multiple real photos of the same labeled individual in the large majority of test cases.

### Occupancy
Minimum Convex Polygon (MCP) home range, computed per-tiger from all sightings, projected into UTM Zone 44N (appropriate for the Pench region) for accurate area calculation rather than computing directly in lat/lon degrees.

### Alerts
Rule-based diffing of each run's occupancy snapshot against the tiger's previous snapshot, covering all four required triggers (range shift, new station, buffer/village movement, prolonged absence). Includes an explicit **artefact guard**: a tiger's first capture at a station is checked against that station's install date, so a newly-installed camera doesn't get misreported as a genuine movement deviation — the exact example given in the brief.

---

## Testing & Validation

- **Blank detection:** tested on real ATRW tiger photos + real forest/nature photos as blanks. Initial false-negative issue found and fixed (see Known Limitations).
- **Throughput:** verified on a real 300-image production-scale run — **63.4 images/minute** on ordinary CPU-only hardware, no GPU. Extrapolated to the full ~3,400 image ATRW set: approximately 53 minutes, within a practical batch-processing window.
- **Robustness:** verified against a deliberately messy test folder — nested subfolders (simulating a mixed-up SD card), inconsistent filenames — all correctly discovered and processed without failure.
- **Identification accuracy:** tested against labeled ATRW photos of known individuals; correctly links repeated photos of the same tiger in the large majority of cases, with ambiguous cases correctly routed to human review rather than silently misassigned.

---

## Known Limitations

- **Identification embeddings are a general-purpose visual similarity proxy**, not a model trained specifically for stripe-pattern matching. Production systems for this exact problem (e.g., Wildbook/HotSpotter-style tools) use re-ID-specific matching. We chose this approach given the CPU-only constraint and 24-hour build window; it correctly links most repeat sightings of the same individual, but occasionally misses matches across very different poses/angles or lighting conditions.
- **Flank isolation is a contour-based heuristic**, not a trained detector, since a trained detector (e.g., MegaDetector) is GPU-class and out of scope for the field-hardware constraint.
- **Person detection is applied only to original full frames**, not to cropped animal regions — we found that running the HOG detector repeatedly on small, irregularly-sized crops caused unstable low-level crashes at scale; since privacy screening is only meaningful on the full original frame anyway, this is both a stability fix and the architecturally correct design.
- **Our test dataset (ATRW) lacks real GPS/timestamp EXIF data** (a limitation of the source academic dataset, not of our pipeline). For testing and demonstration purposes, sightings are assigned to synthetic station locations and timestamps; the pipeline is fully ready to use real EXIF data when available from actual field cameras.
- **Alert thresholds use fixed values** (per the brief's stated 15-20 sq km core / 5 km buffer ranges); a production deployment would likely tune these per-station-density and validate against real historical tiger movement data.