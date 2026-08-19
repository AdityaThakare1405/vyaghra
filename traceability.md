# Vyaghra — Requirement Traceability Matrix

Maps every requirement in the problem statement to where it's implemented and
how it's demonstrated. Use this during judging/demo so nothing gets missed.

## Objective: "minimal human intervention"
| Requirement | Implementation | Evidence |
|---|---|---|
| Single command, raw folder in → full intelligence out | `run_pipeline.py` chains ingestion → classification → ID → occupancy → alerts in one call | `python run_pipeline.py --input <folder>` |

## 1. Blank image filtering and removal
| Requirement | Implementation | Evidence |
|---|---|---|
| Classify blank vs subject | `src/classification/blank_detector.py` — MobileNetV3-Small, top-5 ImageNet check | `run_pipeline.py` console log per image |
| Safe/reversible deletion | `data/quarantine/` (copy, not move) + `scripts/restore_quarantine.py` | `restore_all()` un-quarantines every flagged image |
| Confidence threshold gates the deletion | `config.BLANK_CONFIDENCE_THRESHOLD` (0.60), enforced in `run_pipeline.py` — only quarantines when `confidence >= threshold`; low-confidence blanks are kept, not deleted | `run_report_<id>.json` → `low_confidence_blanks_kept_for_review` |
| Report frames removed + space/time saved | `runs` table (`images_quarantined`, `space_freed_mb`, `time_taken_sec`, `throughput_img_per_min`) | Dashboard Overview page, Deliverable 01 |

## 2. Individual tiger identification
| Requirement | Implementation | Evidence |
|---|---|---|
| Detect animal, isolate flank | `src/identification/detector.py` — contour-based region isolation with implausible-crop fallback | `detect_and_crop()` |
| Match against growing catalogue | `src/identification/matcher.py` — cosine similarity vs. all known embeddings | `match_or_enroll()` |
| Auto-enroll new individuals | Similarity below `MATCH_REVIEW_LOWER` → `_enroll_new_tiger()` | New `T-XXXXXX` id in `tigers` table |
| Confident matches auto-applied | Similarity ≥ `MATCH_AUTO_THRESHOLD` (0.75) → `decision_source='auto'` | `sightings.decision_source` |
| Ambiguous → human review, never silently guessed | Mid-range similarity → `decision='needs_review'`, `tiger_id=NULL` | Review queue: `src/dashboard/app.py` (functional), static HTML shows the queue read-only |
| Persistent DB: individual ↔ image/station/timestamp/GPS | `sightings` ↔ `images` ↔ `stations`, one row per confirmed sighting | `outputs/vyaghra.db` schema (`src/db.py`) |

## 3. Tiger-wise area occupancy, regenerated every run
| Requirement | Implementation | Evidence |
|---|---|---|
| Locations captured | `sightings` → `images.gps_lat/lon` per tiger | `occupancy_snapshots.station_list` |
| Home range estimate | Minimum Convex Polygon in UTM 44N, Chaikin-smoothed | `src/occupancy/home_range.py` |
| Centroid + area | Computed per run, per tiger | `occupancy_snapshots.centroid_lat/lon`, `.area_sq_km` |
| Regenerated every run | `regenerate_all_occupancy()` called at the end of every **non-triage** `run_pipeline.py` run | New row per tiger per `run_id` in `occupancy_snapshots` |
| Map visualisation | Dashboard occupancy page (Folium/Leaflet) | `scripts/generate_html_dashboard.py` |
| Exported for forest dept staff | `scripts/export_report.py` → CSV + GeoJSON + PDF | `outputs/exports/` |
| Overlap between individuals visible | Polygon intersection check across all tigers | Dashboard "Overlaps" count |

## 4. Deviation and trend alerting
| Requirement | Implementation | Evidence |
|---|---|---|
| Range centroid shift threshold (15–20 km² core / 5 km buffer) | Zone-aware: area-diff in core, distance in buffer | `src/alerts/rules.py::_check_range_shift`, `config.py` thresholds |
| First capture at a new station | Diffs stations used per tiger against history | `_check_new_station` |
| Movement into buffer/village-adjacent stations | Point-in-polygon against reserve boundary + buffer ring | `_check_reserve_exit` (needs `pench_boundary_approx.geojson` / `pench_buffer_approx.geojson` — run `draw_map.py` + `import_drawn_shapes.py` first) |
| Prolonged absence | Compares days-since-last-seen against the tiger's historical average gap | `_check_absence` |
| Artefact guard (new camera ≠ deviation) | Station's `install_date` checked against tiger's first capture there | `_check_new_station`, `artefact_flag` column |
| Alert states what/evidence/confidence | Every `_raise_alert()` call sets all three | `alerts` table, dashboard Alerts page, `alerts_log.csv` |

## Constraints
| Requirement | Implementation | Evidence |
|---|---|---|
| No GPU, ordinary laptop | MobileNetV3-Small (CPU), no deep detector | `docs/README.md` §Model & Design Choices |
| Offline after first run | Weights cached after first download; everything else is local | `docs/README.md` §Setup note |
| Practical throughput at scale | Verified 63.4 img/min on 300 real images | `docs/README.md` §Testing & Validation |
| Clock drift / reset timestamps handled | `_assess_timestamp_confidence()` flags `suspicious_reset` / `suspicious_future` / `missing` | `images.timestamp_confidence` column |
| Messy folders / mixed SD cards | `find_images()` recursively walks regardless of structure | Verified on deliberately messy nested test folder |
| Human privacy | HOG+SVM person detector on full frames, excluded before ID stage | `blank_detector._detect_person()` |
| Every decision auditable/correctable | `decision_source`, `reviewed_by`, `reviewed_at` columns; `restore_quarantine.py`; `record_human_decision()` | `sightings` table |

## Known gaps (be upfront about these in the demo)
- Static HTML dashboard's review-queue button is read-only (no backend to write decisions) — the Streamlit app (`src/dashboard/app.py`) has the working review loop.
- `_check_reserve_exit` needs the hand-drawn/generated boundary + buffer GeoJSON files to exist, or it silently skips.
- Occupancy/re-ID accuracy is validated against ATRW, a general-purpose academic dataset without real field EXIF — see `docs/README.md` §Known Limitations for the full list.