# Prototypes (M9, M10)

These are the working prototypes the plan marks **(EXISTS)**, kept here unchanged as the starting point for Stage 3.
They are scripts, not part of the `snowcv` package. Stage 3 turns them into `snowcv.mask_generator` and `snowcv.renderer`.

| File | Module | What it does |
|---|---|---|
| `snowmask_proto.py` | M9 mask_generator | Procedural top-down snow material map on a toy lot. It simulates plow passes, windrows, occupied stalls, tyre tracks, footpaths, edge piles, and melt with slush rims. Bisection on a melt threshold hits a target coverage. |
| `render_snow_v2.py` | M10 renderer | Composites the material map onto a real snow-free lot photo in linear light. Includes illumination taken from the ground, perspective-correct mip-mapped textures, relief shading, thickness parallax, wet rims and context snow. Last step is camera matching: blur, noise and JPEG re-encode. |

## Running

```bash
pip install -e ".[proto]"           # adds opencv-python-headless, scipy, matplotlib
cd prototypes
python snowmask_proto.py            # -> snowmask_examples.png (works standalone)
python render_snow_v2.py            # needs the inputs below in the working directory
```

On 2026-10-12 `snowmask_proto.py` ran in about 6 s and hit 5.0 / 15.0 / 29.9 / 65.0 % for targets 5 / 15 / 30 / 65 %.

`render_snow_v2.py` has not been run in this repo because its inputs are not checked in:

| Input | What | Provenance |
|---|---|---|
| `lot.png` | Snow-free parking-lot photo, 1000x750 | **Unknown.** Needs source, author and licence before any render enters a dataset |
| `s02_diff.jpg` | Poly Haven `snow_02` diffuse (fresh) | CC0 |
| `s05_diff.jpg` | Poly Haven `snow_05` diffuse (dirty road snow) | CC0 |
| `hi_diff.jpg`, `hi_disp.jpg` | High-res snow crop (0.5 m at 512 px/m) and its displacement map | **Unknown.** Record the source |

Images and textures stay out of git. In Stage 1 they get manifest rows via M1, and renders reference them as parents (`Manifest.add_asset(..., parents=[(lot_id, "background"), (tex_id, "texture")])`), so attribution follows each output.

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
- **`COUNTED = (FRESH, PACKED, PILE)`:** the prototypes leave slush out of coverage. This is a metric decision, not a labelling one. The schema labels slush as its own class either way. Whether it counts is open in `docs/stage0/client_agreement.md` §D.
- **The renderer's label output (`label = vis_all > 0.5`) is binary.** It includes context snow beyond the lot, which matches the schema rule that all visible snow gets marked. Stage 3 should write the class-indexed `snow` mask and the `surface` mask instead.

## Known issues to fix in Stage 3 (beyond the plan's "To add" lists)

1. **Reported coverage drifts from the label.** `make_material` fixes coverage, then `render()` step 2 converts part of `PACKED` into `SLUSH` (wet ruts), which is not counted. Feathering and softening then move the footprint again.
   - The script prints both numbers. On the toy lot the wet-rut step alone costs up to 0.5 percentage points (65.0 → 64.4 % for "uncleared"), and more with the renderer's 10–20 tracks.
   - Fix: decide wet ruts inside the generator before coverage targeting, and report the coverage of the final label.
2. **Hard-coded scene.** These are all fixed to the one photo:
   - homography points (`SRC_PTS`/`DST_M`)
   - lot polygon and colour-heuristic obstacle masks
   - BEV extent
   - inspection zone rectangle
   - camera height `HC = 7.0`
   - ground albedo

   They come from M4 calibration (`calib/<id>.json`) and M7 surface labels instead.
3. **Tolerance.** `sample()` docstring says ±0.5 %, but the acceptance check is ±3 % (`abs(c - target) < 0.03`); the renderer uses the same 3 %. Pick one; near the client's decision threshold it should be tight.
4. **Module state.** The renderer sets `G.PX_PER_M` on the imported module and relies on module-level globals (`SURF`, `CTX`, `IMG`). Make these per-scene objects so several cameras can render in one process.
5. **Texture input.** Textures are loaded from fixed filenames with hand-set `px_per_metre`. They should come from the M8 bank (`textures/<material>/`), with `px_per_metre` taken from the manifest `meta`.
