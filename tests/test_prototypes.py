"""Guards for the M9/M10 prototypes: material codes vs the frozen schema, and scene files."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("cv2")
pytest.importorskip("scipy")

PROTO = Path(__file__).parents[1] / "prototypes"
sys.path.insert(0, str(PROTO))
import snowmask_proto as G  # noqa: E402

REQUIRED = {"name", "image", "bev", "ground_albedo", "inspection_zone_m", "camera_height_m", "surface", "layout",
            "track_aisle_min_y_m", "context", "noise_roi", "textures"}


def test_material_codes_match_schema(schema):
    snow = schema.snow
    assert (G.BARE, G.FRESH, G.PACKED, G.SLUSH, G.PILE) == tuple(
        snow.by_name(n).id for n in ("none", "fresh", "packed", "slush_ice", "pile")
    )


@pytest.mark.parametrize("scene", sorted((PROTO / "scenes").glob("*.json")), ids=lambda p: p.stem)
def test_scene_files(scene):
    d = json.loads(scene.read_text())
    assert REQUIRED <= set(d), REQUIRED - set(d)
    assert ("H_i2m" in d) != ("src_px" in d and "dst_m" in d), "give either H_i2m or src_px+dst_m"
    assert set(d["textures"]) == {"fresh", "dirty", "hi_diff", "hi_disp"}
    x0, y0, x1, y1 = d["inspection_zone_m"]
    b = d["bev"]
    assert b["x0_m"] <= x0 < x1 <= b["x0_m"] + b["width_m"]
    assert b["y0_m"] <= y0 < y1 <= b["y0_m"] + b["height_m"]
    for row in d["layout"]["stall_rows"]:
        assert row["y_m"][0] < row["y_m"][1] and row["x_m"][0] < row["x_m"][1]


def test_original_scene_keeps_prototype_layout():
    """The pre-refactor generator loop, reproduced from scenes/original_lot.json."""
    d = json.loads((PROTO / "scenes" / "original_lot.json").read_text())
    rows, aisles, y = [], [[11.0, 17.0]], 0.0
    while y > -100:
        rows += [[y, y + 5.5], [y + 5.5, y + 11.0]]
        aisles.append([y - 7.7, y])
        y -= 18.7
    flat = lambda pairs: [v for pair in pairs for v in pair]
    assert flat(r["y_m"] for r in d["layout"]["stall_rows"]) == pytest.approx(flat(rows))
    assert flat(d["layout"]["aisles_m"]) == pytest.approx(flat(aisles))


def test_renderer_imports_without_inputs():
    import render_snow_v2 as R  # inputs are loaded by setup(), not at import time

    assert callable(R.setup)
