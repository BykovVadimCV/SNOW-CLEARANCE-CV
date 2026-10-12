# Stage 0: Foundations

Plan: [`docs/dataset_code_plan.md`](../dataset_code_plan.md), Part 2, Stage 0.

## Exit criteria

| Criterion | Status | Evidence / next action |
|---|---|---|
| Schema frozen | **Done** (label schema v1.0.0) | `src/snowcv/core/resources/labels.yaml` + `labels.lock.json`; `snowcv schema check` passes; tests fail on any unversioned edit |
| Manifest working | **Done** | `snowcv init` creates layout + `manifest.sqlite`; 60 tests in `tests/` |
| Client access path agreed | **Open**: needs the client | Send [`client_agreement.md`](client_agreement.md); fill the camera table |

## Work items

| Item | Owner | Status | Doc |
|---|---|---|---|
| M0 core (schema, manifest, layout, licence policy, config) | dev | Done | `src/snowcv/core/` |
| Request SAM 3 access | team | Open | [`access_requests.md`](access_requests.md) |
| Get Mapillary token | team | Open | [`access_requests.md`](access_requests.md) |
| Agree camera access, metric, threshold, snow definition, DPA (152-FZ art. 6 p. 3) | team + client | Open | [`client_agreement.md`](client_agreement.md) |
| Send lawyer the open questions | team | Open | [`legal_questions.md`](legal_questions.md) |
| Reconcile licence rules with `VERIFIED-FINDINGS-2.md` | dev | Open: file is not in this repo yet | `src/snowcv/core/licences.py` |

## What M0 gives later modules

- **Label schema** (`snowcv.core.load_schema()`): two uint8 PNG layers, surface (8 classes) and snow (5 classes), `255` = ignore; texture-bank material tags mapped to snow classes; `validate_mask`, `colorize`. Annotation conventions are in the YAML header.
- **Layout** (`snowcv.core.Layout`): the only place paths are built (`raw_client(camera, ts)`, `label_draft(id, layer)`, `texture(material, id)`, `dataset(N)` ...).
- **Manifest** (`snowcv.core.Manifest`): SQLite tables `assets`, `asset_parents`, `processing_history`, `meta`. At write time it enforces:
  - licence gate: commercial use and modification required, so NC and ND are dropped; BY-SA is admitted and flagged `share_alike`; unknown licences are rejected
  - attribution: an author is required when the licence needs credit; `attribution(asset_id)` walks all ancestors, so a synthetic image lists every photo and texture it used
  - privacy: client frames and own captures must be registered already blurred; Mapillary images may be `pending` but cannot enter a split until blurred
  - splits: TEST takes only client frames; VAL takes only client and own captures; synthetic, transplant and control assets can never enter val or test
  - leakage report (`snowcv manifest check-splits`): shared cameras, shared client days (Novosibirsk local time), and derived assets whose ancestors sit in a held-out split
  - dedup: exact (sha256, source id, path) at insert; `near_duplicates(phash)` for M1
  - a record of which label schema the manifest was created with; opening it with a different schema fails
- **Licence check** for harvesters: `snowcv licence "CC BY-SA 3.0 DE"` → `flag: ...`.

## Decisions taken in M0 (revisit if wrong)

1. **The snow layer marks all visible snow, including on `other` (cars, walls).** Metrics intersect it with the inspected surface classes. This gives one simple annotation rule, so the labels don't change if the metric does.
2. **Occluders are `other` in the surface layer.** No guessing what is under a parked car.
3. **Texture tags `ruts` and `dirty` render as `packed`; `plowed_edge` renders as `pile`.** M9/M10 can override this per scene.
4. **VAL takes client frames and own captures, not harvested web images.** Configurable in `config/default.yaml`.
5. **Day hold-out applies to client frames, in Asia/Novosibirsk local days.**
6. **GFDL-only images are rejected.** M1 should pick the CC licence of dual-licensed Commons files.
7. **Wikimedia `PD-*` templates other than plain "Public domain" are rejected as unknown.** M1 can add explicit mappings after legal review.
