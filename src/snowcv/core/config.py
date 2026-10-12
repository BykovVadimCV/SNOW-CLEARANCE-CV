"""Project configuration.

Load order: explicit path > $SNOWCV_CONFIG > built-in defaults.
Relative paths in a config file resolve against that file's directory.
$SNOWCV_DATA_ROOT overrides ``data_root`` (handy on GPU boxes / CI).
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from snowcv.core.enums import SYNTHETIC_ORIGINS, Origin, Split


class LicencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # BY-SA (incl. all Mapillary images) admitted but flagged until the lawyer
    # answers the share-alike scope question.
    allow_share_alike: bool = True
    allow_gfdl: bool = False


class SplitPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_origins: list[Origin] = [Origin.CLIENT]
    val_origins: list[Origin] = [Origin.CLIENT, Origin.OWN_CAPTURE]
    # Group keys that must not be shared between the paired splits.
    holdout_by: list[str] = ["camera", "day"]
    disjoint_pairs: list[tuple[Split, Split]] = [
        (Split.TEST, Split.TRAIN),
        (Split.TEST, Split.VAL),
        (Split.VAL, Split.TRAIN),
    ]

    @field_validator("test_origins", "val_origins")
    @classmethod
    def _no_synthetic(cls, v: list[Origin]) -> list[Origin]:
        bad = [o.value for o in v if o in SYNTHETIC_ORIGINS]
        if bad:
            raise ValueError(f"synthetic origins can never be in val/test: {bad}")
        return v

    @field_validator("holdout_by")
    @classmethod
    def _known_keys(cls, v: list[str]) -> list[str]:
        unknown = set(v) - {"camera", "day"}
        if unknown:
            raise ValueError(f"unknown holdout keys {sorted(unknown)}")
        return v


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_root: Path = Path("data")
    manifest_path: Path | None = None  # default: <data_root>/manifest.sqlite
    timezone: str = "Asia/Novosibirsk"  # day boundaries for split hold-out
    licence_policy: LicencePolicy = Field(default_factory=LicencePolicy)
    splits: SplitPolicy = Field(default_factory=SplitPolicy)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)  # raises on unknown zone
        return v

    @model_validator(mode="after")
    def _default_manifest(self) -> Config:
        if self.manifest_path is None:
            self.manifest_path = self.data_root / "manifest.sqlite"
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_config(path: str | Path | None = None) -> Config:
    path = path or os.environ.get("SNOWCV_CONFIG")
    raw: dict = {}
    base = Path.cwd()
    if path:
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        base = path.resolve().parent
    for key in ("data_root", "manifest_path"):
        if raw.get(key) is not None:
            p = Path(raw[key]).expanduser()
            raw[key] = p if p.is_absolute() else (base / p).resolve()
    if env_root := os.environ.get("SNOWCV_DATA_ROOT"):
        raw["data_root"] = Path(env_root).expanduser().resolve()
    if "data_root" not in raw:
        raw["data_root"] = (base / "data").resolve()
    return Config(**raw)
