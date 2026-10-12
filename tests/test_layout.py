from datetime import datetime, timedelta, timezone

import pytest

from snowcv.core import Layout


def test_paths(tmp_path, schema):
    lay = Layout(tmp_path, schema)
    lay.ensure()
    assert (tmp_path / "textures" / "slush").is_dir()
    ts = datetime(2026, 11, 20, 17, 30, tzinfo=timezone(timedelta(hours=7)))
    p = lay.raw_client("cam01", ts)
    assert lay.rel(p) == "raw/client/cam01/20261120T103000Z.jpg"
    assert lay.rel(lay.label_draft("img_ab", "snow")) == "labels/draft/img_ab_snow.png"
    assert lay.rel(lay.label_final("v1", "img_ab", "surface")) == "labels/final/v1/img_ab_surface.png"
    assert lay.rel(lay.texture("ruts", "tex_1")) == "textures/ruts/tex_1.png"
    assert lay.rel(lay.dataset(3)) == "datasets/v3"
    assert lay.rel(lay.calib("cam01")) == "calib/cam01.json"


def test_rejects_bad_input(tmp_path, schema):
    lay = Layout(tmp_path, schema)
    with pytest.raises(ValueError):
        lay.raw_harvested("../etc")
    with pytest.raises(ValueError):
        lay.raw_client("cam01", datetime(2026, 1, 1))  # naive
    with pytest.raises(KeyError):
        lay.label_draft("img", "depth")
    with pytest.raises(KeyError):
        lay.texture("gravel", "p1")
    with pytest.raises(ValueError):
        lay.rel("/somewhere/else.jpg")
    with pytest.raises(ValueError):
        lay.abs("../outside.jpg")
