# Snow Clearance CV: dataset code plan

Modules to write for the first datasets, and the order to build them in.
Date: 2026-10-12. Stage progress is tracked in `docs/stage<N>/README.md`.

```
==========================================================================
PART 1. MODULES
==========================================================================

Each module: what it does / what it needs / what it outputs.
Modules marked (EXISTS) have a working prototype already.


M0. core
  Does:    Shared config, label schema, provenance manifest, file layout.
           Label schema has two layers:
             surface:  parking/asphalt, sidewalk, yard driveway,
                       roof_soft, roof_external_drain, roof_flat_internal,
                       storage_zone, other
             snow:     fresh, packed, slush_ice, pile, (none)
           Manifest stores, for every image and every texture patch:
           source, source id, URL, author, licence, capture date,
           camera id, split, processing history.
  Needs:   Nothing external. Write first; every other module uses it.
  Outputs: core package, schema file, manifest database (SQLite is enough).


M1. harvest_sources
  Does:    Pulls images with licence metadata from:
             - Openverse API (filter: commercial use AND modification allowed;
               drop BY-ND)
             - Wikimedia Commons API (categories: snow-covered roofs,
               snow removal, snow in Novosibirsk, etc.)
             - Mapillary API (winter months Nov-Mar for snowy scenes,
               summer months for backgrounds; Novosibirsk and similar cities)
             - Poly Haven / ambientCG (CC0 snow materials)
           Deduplicates (perceptual hash) and writes manifest rows.
  Needs:   Mapillary access token. Query lists per scene type.
           Licence filter rules from VERIFIED-FINDINGS-2.md.
  Outputs: raw/harvested/<source>/... + manifest rows.


M2. client_ingest
  Does:    Pulls frames from client cameras (RTSP / VMS export / snapshot
           API, whichever the client gives). Scheduler: snow-free frames now,
           one frame every 15-30 min through winter. Stores timestamp and
           camera id.
  Needs:   Access method and credentials from the client, storage,
           M3 run on every frame at ingest.
  Outputs: raw/client/<camera_id>/<timestamp>.jpg + manifest rows.


M3. privacy_filter
  Does:    Detects and blurs faces and licence plates at ingest, for client
           frames and own captures. Logs that blurring was applied.
           Required by 152-FZ processing terms and by Mapillary terms
           (no re-identification).
  Needs:   Face and plate detector with a commercial-friendly licence.
           NOT Ultralytics YOLO (AGPL-3.0).
  Outputs: Blurred frames; originals deleted or never stored.


M4. calibration
  Does:    a) Client cameras: small tool to click 4 ground points with known
              distances and draw the inspection zone and storage zones.
              Computes image <-> metric ground homography.
           b) Non-client images: automatic ground-plane estimate from
              Depth Anything V2 Small (Apache-2.0 only; larger checkpoints
              are non-commercial), lane/stall lines and vanishing points.
              Metric scale from objects of known size (car ~4.5 m,
              stall ~2.5 m). Falls back to image-space only if it fails.
  Needs:   Snow-free frames per camera; client site plans if available.
  Outputs: calib/<camera_or_image_id>.json (homography, zone polygons,
           camera height estimate, confidence).


M5. prelabel
  Does:    Draft masks for both label layers.
             - Text-prompted: SAM 3 (once access is granted) or
               Grounding DINO + SAM 2 (both Apache-2.0).
             - Optional offline helpers: OneFormer / Mask2Former
               (trained on non-commercial data: use for pre-labels only,
               never ship).
           Agreement check: keep a draft only if two methods agree
           (e.g. IoU > 0.7), otherwise send to manual queue.
  Needs:   GPU; model weights; prompt lists per class.
  Outputs: labels/draft/<image_id>_{surface,snow}.png + confidence.


M6. change_label
  Does:    For fixed cameras: compares a snowy frame with the clean
           reference frame of the same camera, isolates new bright/changed
           ground regions (illumination-normalised difference), refines
           boundaries with SAM 2, writes a draft snow mask. Same for own
           before/after capture pairs.
  Needs:   M2 frames, M4 zones, clean reference frames.
  Outputs: Draft snow masks for real winter frames.


M7. annotation_bridge
  Does:    Exports drafts to CVAT, imports corrected masks, runs QA
           (class consistency, holes, masks outside surface, coverage
           sanity), versions accepted labels.
  Needs:   CVAT instance, M5/M6 drafts.
  Outputs: labels/final/... with version tag.


M8. texture_harvester
  Does:    Builds the snow texture bank from harvested and own images:
             1. snow mask from M5 (ground snow only, large flat regions)
             2. rectify patch to top-down with M4 geometry, set metric scale
             3. remove source lighting (divide by low-frequency illumination)
             4. tag material (fresh / packed / ruts / slush / dirty /
                plowed edge / pile) with CLIP zero-shot + spot-check
             5. reject blurry, occluded, duplicate patches
  Needs:   M1 images, M4, M5.
  Outputs: textures/<material>/<patch_id>.png + px_per_metre + manifest
           (licence, author kept per patch for attribution).


M9. mask_generator  (EXISTS: snowmask_proto.py)
  Does:    Procedural snow material map in metric top-down space:
           plow passes, windrows, occupied stalls, tyre tracks, footpaths,
           edge piles, melt with slush rims; hits an exact target coverage.
  To add:  - layouts from real surface masks instead of a toy lot
           - roof rules (overhangs, gutters, >30 cm accumulation, icicles)
           - target-coverage sampler that oversamples around the client's
             decision threshold
           - thickness map output (cm) as metadata
  Needs:   M4 geometry, M7 surface labels.
  Outputs: material map, thickness map, exact coverage per surface class.


M10. renderer  (EXISTS: render_snow_v2.py)
  Does:    Composites snow onto snow-free backgrounds in linear light:
           lighting from the surface itself, textures from M8 sampled in
           ground coordinates, thickness parallax, wet rims, slush ruts,
           context snow beyond the zone.
  To add:  - read textures from M8 bank by material tag
           - per-camera geometry from M4 (remove hard-coded homography)
           - per-surface albedo (concrete, asphalt, roof membranes)
  Needs:   M4, M7, M8, M9.
  Outputs: image + surface mask + snow mask + coverage (ground m2) +
           generation parameters.


M11. transplant
  Does:    Cuts real labelled snow regions out of winter images, warps
           them through top-down space onto snow-free backgrounds of the
           same surface type, relights to the target scene.
  Needs:   M7 final labels on real winter images, M4, M10 lighting code.
  Outputs: Same format as M10. Target ~1/3 of the synthetic set.


M12. camera_model
  Does:    Fits client camera characteristics from their real frames
           (resolution, lens distortion, sharpness, noise vs brightness,
           colour cast, compression level, IR/night mode) and applies them
           to every non-client image: synthetic, harvested, own captures.
  Needs:   Real client frames (day, night, IR).
  Outputs: Camera profiles per camera; degradation function used by
           M10, M11, M13.


M13. dataset_builder
  Does:    Assembles versioned datasets:
             - TEST: real client frames only, held out by whole camera
               and whole day. Never synthetic.
             - VAL: real, separate cameras/days.
             - TRAIN: real labelled + M10 + M11 + harvested, mix ratios
               set in config.
             - Control composites: bare surface pasted through the same
               pipeline, labelled "no snow".
           Exports in the training framework's format, writes a dataset
           card (sources, licences, counts, coverage histograms).
  Needs:   Everything above.
  Outputs: datasets/v<N>/{train,val,test}/ + dataset_card.txt.


M14. qc_eval
  Does:    - Real-vs-synthetic classifier on crops around snow edges
             (near chance = good; saliency shows the artefact if not)
           - KID between real and synthetic snowy crops per scene type
           - Label checks: coverage in ground m2 matches generator value
           - Decision-level evaluation harness: flag precision / recall at
             the agreed threshold, coverage error, per camera and per
             condition (day/night/IR, fresh/packed/slush)
           - Ablation runner: real only / real + synthetic / synthetic only
  Needs:   M13 datasets, a baseline segmentation model.
  Outputs: Reports per dataset version.


Later (product, not dataset):
  M15. snowfall_timing - weather feed giving end-of-snowfall time, so the
       system can flag "snow present after the regulatory deadline"
       (GOST R 50597-2017 tables 8.1-8.4; Novosibirsk 12-hour rule).


==========================================================================
PART 2. STAGES
==========================================================================

Each stage: work / exit criteria.


STAGE 0. Foundations
  Work:  M0 (schema, manifest).
         Request SAM 3 access. Get Mapillary token.
         Agree with client: camera access method, metric, threshold,
         what counts as snow, data-processing assignment (152-FZ art. 6 p.3).
         Send lawyer the open questions (share-alike scope, models trained
         on non-commercial data).
  Exit:  Schema frozen. Manifest working. Client access path agreed.


STAGE 1. Backgrounds and geometry  (before first snow)
  Work:  M1 harvest (summer backgrounds + winter scenes + CC0 materials).
         M2 + M3: pull snow-free frames from every client camera.
         M4: calibrate every client camera, draw zones.
  Exit:  Every client camera has clean reference frames, calibration and
         zones. Harvested pool with licence on every row.


STAGE 2. Labels and texture bank v0
  Work:  M5 + M7: surface labels on backgrounds; snow + surface labels on
         harvested winter images.
         M8: texture bank v0 from harvested images.
  Exit:  Labelled surface masks for all client backgrounds.
         Texture bank covers all material tags with real patches.


STAGE 3. Synthetic v0 and first checks
  Work:  M9 + M10 upgrades (real layouts, M4 geometry, M8 textures).
         M12 first camera profiles from snow-free client frames.
         M13: dataset v0 (synthetic + harvested real, control composites).
         M14: real-vs-synthetic classifier, label checks.
         Train a baseline model as a pipeline smoke test.
  Exit:  Dataset v0 exists end to end. Known realism artefacts listed.


STAGE 4. First snow: real winter data
  Work:  M2 logging every 15-30 min on all client cameras.
         Own capture campaign: before/after clearing pairs from CCTV-like
         viewpoints; night shots.
         M6 + M7: change-detection labels on real frames.
         Build TEST and VAL from held-out cameras/days.
         M8: texture bank v1 with local Novosibirsk snow.
         M12: refit camera profiles with night/IR winter frames.
  Exit:  Real test set frozen (v1). Several hundred labelled real winter
         frames outside the test set.


STAGE 5. Transplant, ablation, iteration
  Work:  M11 transplant set.
         M13 dataset v1. M14 ablation: real / real+synthetic / synthetic.
         Fix the generator where the realism classifier or the error
         analysis points.
  Exit:  Measured gain (or no gain) from synthetic data on the real test
         set. Dataset v1 + dataset card.


STAGE 6. Through the winter
  Work:  Keep logging. Add hard cases (night, IR, slush, dirty snow,
         white markings, white roofs). Add operator verdicts as labels
         once the pilot runs, including a random sample of unflagged frames.
         Re-run M14 on each new dataset version.
  Exit:  Ongoing. Do not freeze the test set after the first snowfalls;
         early snow is wet and patchy and not representative.
```
