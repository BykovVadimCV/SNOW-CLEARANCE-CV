# Prototypes (M9, M10)

These are the working prototypes the plan marks **(EXISTS)**. They are the starting point for Stage 3, which turns them into `snowcv.mask_generator` and `snowcv.renderer`. They are scripts, not part of the `snowcv` package.

| File | Module | What it does |
|---|---|---|
| `snowmask_proto.py` | M9 mask_generator | Procedural top-down snow material map on a toy lot. It simulates plow passes, windrows, occupied stalls, tyre tracks, footpaths, edge piles, and melt with slush rims. Bisection on a melt threshold hits a target coverage. |
| `render_snow_v2.py` | M10 renderer | Composites the material map onto a real snow-free lot photo in linear light. Includes illumination from the ground, perspective-correct mip-mapped textures, relief shading, thickness parallax, wet rims and context snow. Last step is camera matching: blur, noise and JPEG re-encode. |
| `scenes/*.json` | | Per-photo settings: homography, BEV grid, lot outline and occluders, stall layout, albedo, lighting, textures |
| `fetch_inputs.py` | | Downloads and registers the renderer inputs with licence and author, and derives the texture tiles |

## Running

```bash
pip install -e ".[proto]"                       # adds opencv-python-headless, scipy, matplotlib
python prototypes/fetch_inputs.py               # ~20 s; fills data/ and the manifest
cd prototypes
python snowmask_proto.py                        # toy-lot generator demo -> snowmask_examples.png
python render_snow_v2.py --scene scenes/wet_prius.json \
    --out ../data/synthetic/proto_wet_prius_v1 --register
```

`--register` writes each render to the manifest as a `synthetic` asset. It is linked to the background photo and to every texture tile it used. `snowcv manifest show <id>` then lists the credits a render needs.

## Inputs (all with known provenance)

| Renderer input | Now | Licence | Manifest |
|---|---|---|---|
| `lot.png` (provenance unknown) | Commons "Wet Prius, alone in an empty parking lot (9927867963).jpg", Angelo DeSantis. Elevated, CCTV-like view; 1280 px thumbnail, worked at 1000×758 | CC BY 2.0, **credit required** | `img_3da7dd914aa0f69a` |
| `s02_diff.jpg` | Poly Haven `snow_02` diffuse (2×2 m), resized to 128 px/m | CC0 | parent + patch |
| `s05_diff.jpg` | Poly Haven `snow_05` diffuse (3×3 m, dirty road snow), 96 px/m. The crop keeps the strip between the tractor tracks (columns 80–200) | CC0 | parent + patch |
| `hi_diff.jpg` / `hi_disp.jpg` (provenance unknown) | 0.5 m crop of `snow_02` diffuse and displacement 4k, 512 px/m | CC0 | parent + patch |

Notes on the photo:
- The parked car's number plate is not legible at working resolution, and there are no people, so no blurring was needed. This is recorded in the manifest `meta`.
- Wikimedia rate-limits the API and full-size downloads for shared IPs, and asks bots to use standard thumbnail sizes. So `fetch_inputs.py` takes the 1280 px thumbnail, and author and licence metadata were confirmed through Openverse.

The original scene (`scenes/original_lot.json`) keeps the prototype's original values unchanged. It still needs `lot.png` and the old textures in the working directory, and those files remain unsourced.

## Calibrating the new scene (`scenes/wet_prius.json`, done by hand; M4 automates this)

1. **Line fitting.** Nine painted lines were fitted to sub-pixel accuracy: near stalls, the divider on both sides of the car, the far-row stalls and the curb.
2. **Stalls are perpendicular.** The stall lines look diagonal, but their vanishing point lies on the same horizon as the rows' vanishing point. So they are ordinary perpendicular stalls seen at an angle, and US standard stalls (9 × 18 ft = 2.74 × 5.49 m) set the metric scale.
3. **Joint least-squares homography.** One homography was fitted over all nine lines. The aisle width (fitted: 7.80 m, a normal two-way aisle) and the far-row offset were left free. Reprojection error is 1.9 px on average and 6.7 px at worst. A 4-point fit on one stall was accurate near the stall but put the far row 60% too deep.
4. **Independent check.** The Prius wheelbase measures 2.87 m against a real 2.70 m (+6%).
5. **Camera height: 6.0 ± 1 m.** This comes from roof parallax on the Prius: roof height 1.49 m, with the horizon taken from the same homography.

The lens has uncorrected barrel distortion: vanishing points from different parts of the image disagree. Error therefore grows toward the far curb and the left edge. M4 needs a distortion model, and M12 needs one for camera matching.

## Results on the new scene

| Case | Target | Generator | After wet ruts | Final label (ground m²) |
|---|---|---|---|---|
| plowed | 8 % | 8.0 % | 8.0 % | 7.0 % |
| plowed+melt | 25 % | 24.9 % | 24.9 % | 23.0 % |
| partial | 50 % | 49.9 % | 47.3 % | 45.4 % |
| uncleared | 85 % | 84.9 % | 70.9 % | **67.6 %** |

## Alignment with the M0 schema (v1.0.0)

- **Material codes already match the snow layer ids:**

  | Prototype code | Value | Schema `snow` class |
  |---|---|---|
  | `BARE` | 0 | `none` |
  | `FRESH` | 1 | `fresh` |
  | `PACKED` | 2 | `packed` |
  | `SLUSH` | 3 | `slush_ice` |
  | `PILE` | 4 | `pile` |

  `tests/test_prototypes.py` fails if either side drifts.
- **`COUNTED = (FRESH, PACKED, PILE)`:** the prototypes leave slush out of coverage. This is a metric decision, not a labelling one; the schema labels slush as its own class either way. Whether it counts is open in `docs/stage0/client_agreement.md` §D.
- **The renderer's label output (`label = vis_all > 0.5`) is binary.** It includes context snow beyond the lot, which matches the schema rule that all visible snow gets marked. Stage 3 should write the class-indexed `snow` mask and the `surface` mask instead.

## Issues

| # | Issue | Status |
|---|---|---|
| 1 | **Reported coverage drifts from the label.** `make_material` fixes coverage, then `render()` turns part of `PACKED` into `SLUSH` (wet ruts, not counted), and feathering moves the footprint again. | **Confirmed and large on a real scene.** "Uncleared" targets 85 % and labels 67.6 % (−17 points; −14 from wet ruts alone). On the toy lot it was 0.5 points. Fix in Stage 3: decide wet ruts inside the generator before targeting, and report the final label's coverage. |
| 2 | Hard-coded scene: homography, lot polygon, colour-heuristic obstacles, BEV extent, zone, camera height, albedo, layout, pixel thresholds. | **Partly fixed.** All of these now come from `scenes/<name>.json`, and the renderer runs on a second photo. The calibration itself is still manual; M4 replaces it. |
| 3 | Tolerance: `sample()` docstring says ±0.5 %, code accepts ±3 %. | Open. |
| 4 | Module state: the renderer sets `G.PX_PER_M` and uses module globals. | Open. `setup(scene)` fills the globals, so it is still one scene per process. |
| 5 | Texture input from fixed filenames with hand-set px/m. | **Partly fixed.** Tiles live in `textures/<material>/` with `px_per_metre` in the manifest. The scene still repeats px/m; M8 should look tiles up by material tag. |
| 6 | *New:* wet ground darkened the car. Contact-darkening and wet rims were applied to any pixel next to snow, occluders included. | **Fixed:** limited to the lot surface. This also changes the original scene slightly; the curb and posts are no longer darkened. |
| 7 | *New:* specular / wet ground breaks the "lighting from the surface" estimate. Sky reflections become bright light and wet patches become shadows (5–95th percentile ground brightness spans 80×). | **Mitigated** per scene with `illum.band` (broad gradients only, clamped to ±20 % of the median) and an effective albedo. Large wet patches still faintly imprint through the snow. Stage 3 needs a proper albedo/shading split. |
| 8 | *New:* lens distortion is not modelled anywhere (homography only). | Open: M4 and M12. |
