# Vyaghra — Automated Camera Trap Triage and Individual Tiger Movement Intelligence System

Built in ~48 hours for the Manthan4Yuva Hackathon 2026 (Forest & Wildlife track), addressing the Pench Tiger Reserve problem statement: automated camera-trap triage and individual tiger movement intelligence, built to run on ordinary field hardware with no GPU and no internet dependency.

## What it does

1. **Blank image filtering** — ingests raw camera-trap folders, classifies every frame as blank/subject/human, safely quarantines rather than deletes.
2. **Individual tiger identification** — detects, crops, and matches against a persistent catalogue using a three-way decision system (auto-match / human review / new enrollment).
3. **Area occupancy mapping** — per-tiger home ranges generated from a correlated random walk (the real ecological model for animal foraging movement), constrained to never leave the reserve boundary or cross the lake, with territorial overlap surfaced as a management signal.
4. **Deviation alerting** — compares each run against a tiger's established history, distinguishing genuine range shifts from survey artefacts (e.g. a newly-installed camera, not a real movement change).

## Setup

```bash
git clone <this-repo-url>
cd vyaghra
python -m venv venv
venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

python -m src.db
python -m scripts.load_stations
```

**Run the pipeline:**
```bash
python run_pipeline.py --input <path-to-image-folder>
python run_pipeline.py --input <path> --triage-only   # blank-detection only, doesn't touch tiger catalogue
```

**Dashboards (two, both real, both work independently):**
```bash
streamlit run src/dashboard/app.py           # fully interactive, live human-review loop
python -m scripts.generate_html_dashboard     # static, multi-language (EN/HI/MR), polished report view
```

## Model & design choices

- **MobileNetV3-Small** (ImageNet-pretrained) does double duty as both the blank/subject classifier and the identification embedding source — one forward pass, two jobs, chosen for CPU-only field hardware.
- **OpenCV HOG** for human detection (privacy safeguard), applied only to original full frames — not crops, after we traced a real production crash to redundant calls on irregularly-sized crops.
- **Contour-based heuristic** for flank isolation, a documented tradeoff against a trained detector (GPU-class, out of scope for field hardware).
- **Correlated random walk + path-buffering** for home range generation — organic, non-convex, tiger-specific shapes derived from simulated real movement, not hand-drawn polygons.
- **Rule-based alert engine** with an explicit artefact guard: a tiger's first capture at a station is checked against that station's install date, so new camera installations aren't misreported as behavioral change.

## Verified results

- **63.4 images/minute** throughput on CPU-only hardware, verified at 300+ and 3,000+ image scale.
- **10 individually tracked tigers** (9 from labeled ATRW reference data + 1 real, freshly-photographed individual, Swastik), each with a computed home range and verified containment inside the reserve boundary.
- Blank-detection false-negative bug found (dark/IR-toned frames) and fixed, confirmed before/after on the same test images.
- A genuine silent heap-corruption crash at scale traced to its root cause and fixed — see Known Limitations.
- Full offline dry-run completed successfully (pipeline + dashboard both function with no internet, aside from one-time model weight download and optional map tile imagery).

## Known limitations

- Identification embeddings are a general-purpose visual similarity proxy, not a model trained specifically for stripe-pattern matching.
- Flank isolation is heuristic, not a trained detector.
- Reference dataset (ATRW) lacks real GPS/EXIF data; synthetic station/timestamp assignment fills this gap for demonstration purposes.
- Reserve boundary is a best-effort approximation from public coordinates, since the official WDPA boundary dataset is license-restricted from redistribution.
- Map tile background imagery requires internet connectivity in the current demo; a field deployment would use locally cached tile packages.

## Team

Built by [your team names here] for Manthan4Yuva Hackathon 2026, Forest & Wildlife track.