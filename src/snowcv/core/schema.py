"""Label schema: two mask layers (surface, snow) plus texture-bank material tags.

The schema lives in ``resources/labels.yaml`` and is frozen by a content hash
stored in ``resources/labels.lock.json``. ``check_frozen`` fails if the YAML was
edited without a deliberate re-freeze, so masks written by different modules
and at different times always mean the same thing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

DEFAULT_SCHEMA_PATH = Path(str(resources.files("snowcv.core") / "resources" / "labels.yaml"))
DEFAULT_LOCK_PATH = DEFAULT_SCHEMA_PATH.with_name("labels.lock.json")


class SchemaError(ValueError):
    """The schema file is malformed."""


class SchemaNotFrozenError(RuntimeError):
    """The schema content does not match its lock file."""


@dataclass(frozen=True)
class LabelClass:
    id: int
    name: str
    color: tuple[int, int, int]
    description: str


@dataclass(frozen=True)
class Layer:
    name: str
    description: str
    classes: tuple[LabelClass, ...]
    ignore_index: int

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.classes)

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(c.id for c in self.classes)

    def by_name(self, name: str) -> LabelClass:
        for c in self.classes:
            if c.name == name:
                return c
        raise KeyError(f"layer {self.name!r} has no class {name!r}")

    def by_id(self, class_id: int) -> LabelClass:
        for c in self.classes:
            if c.id == class_id:
                return c
        raise KeyError(f"layer {self.name!r} has no class id {class_id}")

    def palette(self) -> np.ndarray:
        """256x3 uint8 lookup table: class id -> RGB. Ignore index is magenta."""
        lut = np.zeros((256, 3), dtype=np.uint8)
        lut[self.ignore_index] = (255, 0, 255)
        for c in self.classes:
            lut[c.id] = c.color
        return lut

    def validate_mask(self, mask: np.ndarray) -> None:
        """Raise ValueError if ``mask`` is not a valid encoded mask for this layer."""
        if mask.ndim != 2:
            raise ValueError(f"{self.name} mask must be 2-D, got shape {mask.shape}")
        if mask.dtype != np.uint8:
            raise ValueError(f"{self.name} mask must be uint8, got {mask.dtype}")
        allowed = np.array(sorted({*self.ids, self.ignore_index}), dtype=np.uint8)
        bad = np.setdiff1d(np.unique(mask), allowed)
        if bad.size:
            raise ValueError(f"{self.name} mask has unknown class ids {bad.tolist()}")

    def colorize(self, mask: np.ndarray) -> np.ndarray:
        """Encoded mask -> HxWx3 RGB preview."""
        self.validate_mask(mask)
        return self.palette()[mask]


@dataclass(frozen=True)
class TextureMaterial:
    name: str
    snow_class: str
    description: str


@dataclass(frozen=True)
class LabelSchema:
    version: str
    ignore_index: int
    layers: dict[str, Layer]
    texture_materials: tuple[TextureMaterial, ...]
    sha256: str

    @property
    def surface(self) -> Layer:
        return self.layers["surface"]

    @property
    def snow(self) -> Layer:
        return self.layers["snow"]

    def layer(self, name: str) -> Layer:
        try:
            return self.layers[name]
        except KeyError:
            raise KeyError(f"unknown layer {name!r}; have {sorted(self.layers)}") from None

    @property
    def material_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.texture_materials)

    def material(self, name: str) -> TextureMaterial:
        for m in self.texture_materials:
            if m.name == name:
                return m
        raise KeyError(f"unknown texture material {name!r}")


REQUIRED_LAYERS = ("surface", "snow")


def canonical_hash(data: dict) -> str:
    """Hash of the parsed schema, insensitive to YAML comments and formatting."""
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_class(raw: dict, layer: str) -> LabelClass:
    try:
        cid, name, color = raw["id"], raw["name"], raw["color"]
    except KeyError as e:
        raise SchemaError(f"layer {layer!r}: class missing field {e}") from None
    if not isinstance(cid, int) or not 0 <= cid <= 254:
        raise SchemaError(f"layer {layer!r}: class id {cid!r} must be an int in 0..254")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SchemaError(f"layer {layer!r}: class name {name!r} must be snake_case")
    if (
        not isinstance(color, list)
        or len(color) != 3
        or not all(isinstance(v, int) and 0 <= v <= 255 for v in color)
    ):
        raise SchemaError(f"layer {layer!r}: class {name!r} color must be [r, g, b] in 0..255")
    return LabelClass(id=cid, name=name, color=tuple(color), description=str(raw.get("description", "")).strip())


def parse_schema(data: dict) -> LabelSchema:
    version = str(data.get("version", ""))
    if not _VERSION_RE.match(version):
        raise SchemaError(f"version {version!r} must be MAJOR.MINOR.PATCH")
    ignore = data.get("ignore_index")
    if ignore != 255:
        raise SchemaError("ignore_index must be 255")

    raw_layers = data.get("layers") or {}
    missing = [n for n in REQUIRED_LAYERS if n not in raw_layers]
    if missing:
        raise SchemaError(f"missing layers: {missing}")

    layers: dict[str, Layer] = {}
    for lname, lraw in raw_layers.items():
        classes = tuple(_parse_class(c, lname) for c in lraw.get("classes") or [])
        if not classes:
            raise SchemaError(f"layer {lname!r} has no classes")
        ids = [c.id for c in classes]
        names = [c.name for c in classes]
        colors = [c.color for c in classes]
        for what, values in (("ids", ids), ("names", names), ("colors", colors)):
            if len(set(values)) != len(values):
                raise SchemaError(f"layer {lname!r}: duplicate class {what}")
        if ids[0] != 0:
            raise SchemaError(f"layer {lname!r}: first class must have id 0 (the background class)")
        layers[lname] = Layer(
            name=lname,
            description=str(lraw.get("description", "")).strip(),
            classes=classes,
            ignore_index=ignore,
        )

    snow_names = set(layers["snow"].names)
    materials = []
    for m in data.get("texture_materials") or []:
        name, snow_class = m.get("name"), m.get("snow_class")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise SchemaError(f"texture material name {name!r} must be snake_case")
        if snow_class not in snow_names or snow_class == layers["snow"].classes[0].name:
            raise SchemaError(f"texture material {name!r}: snow_class {snow_class!r} is not a snow class")
        materials.append(TextureMaterial(name, snow_class, str(m.get("description", "")).strip()))
    if len({m.name for m in materials}) != len(materials):
        raise SchemaError("duplicate texture material names")

    return LabelSchema(
        version=version,
        ignore_index=ignore,
        layers=layers,
        texture_materials=tuple(materials),
        sha256=canonical_hash(data),
    )


def load_schema(path: str | Path | None = None) -> LabelSchema:
    path = Path(path) if path else DEFAULT_SCHEMA_PATH
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: not a YAML mapping")
    return parse_schema(data)


def read_lock(lock_path: str | Path | None = None) -> dict | None:
    lock_path = Path(lock_path) if lock_path else DEFAULT_LOCK_PATH
    if not lock_path.exists():
        return None
    return json.loads(lock_path.read_text(encoding="utf-8"))


def check_frozen(schema: LabelSchema, lock_path: str | Path | None = None) -> None:
    """Raise SchemaNotFrozenError unless ``schema`` matches the lock file."""
    lock = read_lock(lock_path)
    if lock is None:
        raise SchemaNotFrozenError("no schema lock file; run `snowcv schema freeze`")
    if lock.get("sha256") != schema.sha256 or lock.get("version") != schema.version:
        raise SchemaNotFrozenError(
            f"schema content (v{schema.version}, {schema.sha256[:12]}) does not match lock "
            f"(v{lock.get('version')}, {str(lock.get('sha256'))[:12]}). "
            "If the change is intended: bump `version`, then run `snowcv schema freeze`."
        )


def freeze(schema: LabelSchema, lock_path: str | Path | None = None) -> Path:
    """Write the lock file. Refuses to re-freeze changed content under the same version."""
    lock_path = Path(lock_path) if lock_path else DEFAULT_LOCK_PATH
    lock = read_lock(lock_path)
    if lock and lock.get("version") == schema.version and lock.get("sha256") != schema.sha256:
        raise SchemaNotFrozenError(
            f"schema content changed but version is still {schema.version}; bump the version first"
        )
    lock_path.write_text(
        json.dumps({"version": schema.version, "sha256": schema.sha256}, indent=2) + "\n",
        encoding="utf-8",
    )
    return lock_path
