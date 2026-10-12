"""Guard: prototype material codes must stay equal to the frozen snow-layer ids."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("cv2")
pytest.importorskip("scipy")

sys.path.insert(0, str(Path(__file__).parents[1] / "prototypes"))
import snowmask_proto as G  # noqa: E402


def test_material_codes_match_schema(schema):
    snow = schema.snow
    assert (G.BARE, G.FRESH, G.PACKED, G.SLUSH, G.PILE) == tuple(
        snow.by_name(n).id for n in ("none", "fresh", "packed", "slush_ice", "pile")
    )
