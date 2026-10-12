"""On-disk file layout under the data root. All modules build paths through here.

    <root>/
      manifest.sqlite                           (path set in Config)
      raw/harvested/<source>/<file>             M1
      raw/client/<camera_id>/<UTC timestamp>.jpg M2 (already blurred by M3)
      raw/own/<session_id>/<file>               own captures (already blurred)
      calib/<camera_or_image_id>.json           M4
      labels/draft/<image_id>_<layer>.png       M5, M6
      labels/final/<version>/<image_id>_<layer>.png  M7
      textures/<material>/<patch_id>.png        M8
      synthetic/<run_id>/...                    M10, M11
      datasets/v<N>/{train,val,test}/           M13
      reports/                                  M14
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from snowcv.core.schema import LabelSchema

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LABEL_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")

TOP_LEVEL_DIRS = (
    "raw/harvested",
    "raw/client",
    "raw/own",
    "calib",
    "labels/draft",
    "labels/final",
    "textures",
    "synthetic",
    "datasets",
    "reports",
)


def check_id(value: str, what: str = "id") -> str:
    """Ids become path components: restrict to a safe character set."""
    if not isinstance(value, str) or not _ID_RE.match(value) or ".." in value:
        raise ValueError(f"invalid {what} {value!r}: use [A-Za-z0-9._-], max 128 chars, no '..'")
    return value


class Layout:
    def __init__(self, root: str | Path, schema: LabelSchema):
        self.root = Path(root).resolve()
        self.schema = schema

    def ensure(self) -> None:
        for d in TOP_LEVEL_DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for m in self.schema.material_names:
            (self.root / "textures" / m).mkdir(parents=True, exist_ok=True)

    # raw ------------------------------------------------------------------

    def raw_harvested(self, source: str, filename: str | None = None) -> Path:
        d = self.root / "raw" / "harvested" / check_id(source, "source")
        return d / check_id(filename, "filename") if filename else d

    def raw_client(self, camera_id: str, ts: datetime, ext: str = "jpg") -> Path:
        if ts.tzinfo is None:
            raise ValueError("client frame timestamp must be timezone-aware")
        stamp = ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.root / "raw" / "client" / check_id(camera_id, "camera_id") / f"{stamp}.{ext}"

    def raw_own(self, session_id: str, filename: str | None = None) -> Path:
        d = self.root / "raw" / "own" / check_id(session_id, "session_id")
        return d / check_id(filename, "filename") if filename else d

    # geometry -------------------------------------------------------------

    def calib(self, target_id: str) -> Path:
        return self.root / "calib" / f"{check_id(target_id, 'calibration target id')}.json"

    # labels ---------------------------------------------------------------

    def label_draft(self, image_id: str, layer: str) -> Path:
        self.schema.layer(layer)
        return self.root / "labels" / "draft" / f"{check_id(image_id, 'image_id')}_{layer}.png"

    def label_final(self, version: str, image_id: str, layer: str) -> Path:
        if not _LABEL_VERSION_RE.match(version):
            raise ValueError(f"label version {version!r} must look like v1 or v1.2")
        self.schema.layer(layer)
        return self.root / "labels" / "final" / version / f"{check_id(image_id, 'image_id')}_{layer}.png"

    # textures / synthetic / datasets ---------------------------------------

    def texture(self, material: str, patch_id: str) -> Path:
        self.schema.material(material)
        return self.root / "textures" / material / f"{check_id(patch_id, 'patch_id')}.png"

    def synthetic_run(self, run_id: str) -> Path:
        return self.root / "synthetic" / check_id(run_id, "run_id")

    def dataset(self, version: int) -> Path:
        if not isinstance(version, int) or version < 0:
            raise ValueError("dataset version must be a non-negative int")
        return self.root / "datasets" / f"v{version}"

    def reports(self) -> Path:
        return self.root / "reports"

    # manifest paths --------------------------------------------------------

    def rel(self, path: str | Path) -> str:
        """Absolute path -> POSIX path relative to the data root (what the manifest stores)."""
        p = Path(path).resolve()
        try:
            return PurePosixPath(p.relative_to(self.root)).as_posix()
        except ValueError:
            raise ValueError(f"{p} is outside the data root {self.root}") from None

    def abs(self, rel_path: str) -> Path:
        p = (self.root / rel_path).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError(f"{rel_path!r} escapes the data root")
        return p
