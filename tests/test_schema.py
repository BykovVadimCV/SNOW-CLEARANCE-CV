import copy

import numpy as np
import pytest
import yaml

from snowcv.core.schema import (
    DEFAULT_SCHEMA_PATH,
    SchemaError,
    SchemaNotFrozenError,
    check_frozen,
    freeze,
    parse_schema,
)


@pytest.fixture
def raw():
    return yaml.safe_load(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_shipped_schema_is_frozen(schema):
    check_frozen(schema)


def test_plan_classes_present(schema):
    assert schema.surface.names == (
        "other",
        "parking_asphalt",
        "sidewalk",
        "yard_driveway",
        "roof_soft",
        "roof_external_drain",
        "roof_flat_internal",
        "storage_zone",
    )
    assert schema.snow.names == ("none", "fresh", "packed", "slush_ice", "pile")
    assert {"fresh", "packed", "ruts", "slush", "dirty", "plowed_edge", "pile"} == set(schema.material_names)


def test_hash_ignores_formatting(raw, schema):
    assert parse_schema(copy.deepcopy(raw)).sha256 == schema.sha256


def test_edit_breaks_freeze(raw, schema, tmp_path):
    lock = tmp_path / "lock.json"
    freeze(schema, lock)
    raw["layers"]["snow"]["classes"][1]["description"] = "changed"
    edited = parse_schema(raw)
    with pytest.raises(SchemaNotFrozenError):
        check_frozen(edited, lock)
    with pytest.raises(SchemaNotFrozenError, match="bump the version"):
        freeze(edited, lock)
    raw["version"] = "1.1.0"
    bumped = parse_schema(raw)
    freeze(bumped, lock)
    check_frozen(bumped, lock)


@pytest.mark.parametrize(
    "mutate, msg",
    [
        (lambda r: r["layers"]["snow"]["classes"].append(dict(r["layers"]["snow"]["classes"][1])), "duplicate"),
        (lambda r: r["layers"]["surface"]["classes"][1].update(id=255), "0..254"),
        (lambda r: r["layers"].pop("snow"), "missing layers"),
        (lambda r: r.update(version="1"), "MAJOR.MINOR.PATCH"),
        (lambda r: r["texture_materials"][0].update(snow_class="none"), "not a snow class"),
        (lambda r: r["layers"]["surface"]["classes"][2].update(name="Side Walk"), "snake_case"),
    ],
)
def test_invalid_schemas(raw, mutate, msg):
    mutate(raw)
    with pytest.raises(SchemaError, match=msg):
        parse_schema(raw)


def test_mask_validation_and_colorize(schema):
    mask = np.array([[0, 1], [4, 255]], dtype=np.uint8)
    schema.snow.validate_mask(mask)
    rgb = schema.snow.colorize(mask)
    assert rgb.shape == (2, 2, 3)
    assert tuple(rgb[0, 1]) == schema.snow.by_name("fresh").color
    with pytest.raises(ValueError, match="unknown class ids"):
        schema.snow.validate_mask(np.array([[9]], dtype=np.uint8))
    with pytest.raises(ValueError, match="uint8"):
        schema.snow.validate_mask(np.zeros((2, 2), dtype=np.int32))
