"""Provenance manifest (SQLite).

One row per image and per texture patch: where it came from, under what
licence, who made it, when and by which camera it was captured, which split it
is in, and every processing step applied to it. Derived assets (texture
patches, synthetic renders, transplants) are linked to their parents so
attribution and test-set leakage can be traced through any number of steps.

Rules enforced at write time (so no module can bypass them):
  - third-party licences must allow commercial use and modification;
    share-alike is admitted with a flag (see licences.py)
  - client frames and own captures must be privacy-blurred before they are
    registered (M3 runs at ingest; originals are never stored)
  - synthetic / transplant / control assets need parents and can never enter
    val or test; test is real client frames only (configurable, never synthetic)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from snowcv import __version__
from snowcv.core.config import Config
from snowcv.core.enums import SYNTHETIC_ORIGINS, Kind, Origin, PrivacyStatus, Split
from snowcv.core.layout import check_id
from snowcv.core.licences import CLIENT_DPA, DERIVED, OWN, Decision, UnknownLicenceError, evaluate, parse_licence
from snowcv.core.schema import LabelSchema

MANIFEST_FORMAT = 1

_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


class ManifestError(RuntimeError):
    pass


class AssetRejectedError(ManifestError):
    """The asset breaks a provenance, licence or privacy rule."""


class DuplicateAssetError(ManifestError):
    def __init__(self, msg: str, existing_id: str):
        super().__init__(msg)
        self.existing_id = existing_id


class SplitRuleError(ManifestError):
    pass


class SchemaMismatchError(ManifestError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def parse_capture_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str | None = None  # default: img_/tex_ + first 16 hex of sha256
    kind: Kind = Kind.IMAGE
    origin: Origin
    source: str  # openverse, wikimedia, mapillary, polyhaven, ambientcg, client, own, m10_renderer, ...
    source_id: str | None = None  # id at the source (Openverse id, Commons title, Mapillary image id, ...)
    url: str | None = None  # landing page at the source
    author: str | None = None
    licence: str  # free text accepted; stored as canonical code
    licence_url: str | None = None
    licence_flag: str | None = None  # set by the manifest, e.g. "share_alike"
    capture_date: str | None = None  # ISO 8601; client frames must carry a UTC offset
    camera_id: str | None = None
    split: Split = Split.UNASSIGNED
    path: str  # POSIX, relative to the data root
    sha256: str
    phash: str | None = None  # 64-bit perceptual hash, 16 hex chars
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    privacy_status: PrivacyStatus = PrivacyStatus.NOT_REQUIRED
    meta: dict[str, Any] = Field(default_factory=dict)  # module-specific, e.g. px_per_metre, material
    created_at: str | None = None

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, v: str | None) -> str | None:
        return None if v is None else check_id(v, "asset_id")

    @field_validator("camera_id")
    @classmethod
    def _camera_id(cls, v: str | None) -> str | None:
        return None if v is None else check_id(v, "camera_id")

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if not _SOURCE_RE.match(v):
            raise ValueError(f"source {v!r} must be a lowercase slug")
        return v

    @field_validator("sha256")
    @classmethod
    def _sha(cls, v: str) -> str:
        v = v.lower()
        if not _HEX64.match(v):
            raise ValueError("sha256 must be 64 hex chars")
        return v

    @field_validator("phash")
    @classmethod
    def _phash(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.lower()
        if not _HEX16.match(v):
            raise ValueError("phash must be 16 hex chars (64-bit hash)")
        return v

    @field_validator("capture_date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        if v is not None:
            parse_capture_date(v)
        return v

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        p = PurePosixPath(v)
        if p.is_absolute() or ".." in p.parts or "\\" in v or not v:
            raise ValueError(f"path {v!r} must be relative to the data root, POSIX, without '..'")
        return p.as_posix()


@dataclass(frozen=True)
class HistoryEntry:
    step: str
    module: str
    tool_version: str
    params: dict
    at: str


@dataclass(frozen=True)
class Violation:
    rule: str  # "camera", "day", "ancestry", "privacy"
    detail: str
    asset_ids: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        sample = ", ".join(self.asset_ids[:5]) + (" ..." if len(self.asset_ids) > 5 else "")
        return f"[{self.rule}] {self.detail}" + (f" ({len(self.asset_ids)}: {sample})" if self.asset_ids else "")


def _enum_check(col: str, enum) -> str:
    values = ", ".join(f"'{e.value}'" for e in enum)
    return f"CHECK ({col} IN ({values}))"


_DDL = f"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    asset_id       TEXT PRIMARY KEY,
    kind           TEXT NOT NULL {_enum_check("kind", Kind)},
    origin         TEXT NOT NULL {_enum_check("origin", Origin)},
    source         TEXT NOT NULL,
    source_id      TEXT,
    url            TEXT,
    author         TEXT,
    licence        TEXT NOT NULL,
    licence_url    TEXT,
    licence_flag   TEXT,
    capture_date   TEXT,
    camera_id      TEXT,
    split          TEXT NOT NULL DEFAULT 'unassigned' {_enum_check("split", Split)},
    path           TEXT NOT NULL UNIQUE,
    sha256         TEXT NOT NULL UNIQUE,
    phash          TEXT,
    width          INTEGER,
    height         INTEGER,
    privacy_status TEXT NOT NULL {_enum_check("privacy_status", PrivacyStatus)},
    meta           TEXT NOT NULL DEFAULT '{{}}',
    created_at     TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_assets_origin ON assets(origin);
CREATE INDEX IF NOT EXISTS idx_assets_split  ON assets(split);
CREATE INDEX IF NOT EXISTS idx_assets_camera ON assets(camera_id);
CREATE TABLE IF NOT EXISTS asset_parents (
    child_id  TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    parent_id TEXT NOT NULL REFERENCES assets(asset_id),
    role      TEXT NOT NULL DEFAULT 'source',
    PRIMARY KEY (child_id, parent_id, role)
);
CREATE INDEX IF NOT EXISTS idx_parents_parent ON asset_parents(parent_id);
CREATE TABLE IF NOT EXISTS processing_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id     TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    step         TEXT NOT NULL,
    module       TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    params       TEXT NOT NULL DEFAULT '{{}}',
    at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_asset ON processing_history(asset_id);
"""

_COLUMNS = tuple(AssetRecord.model_fields)


class Manifest:
    def __init__(self, path: str | Path, schema: LabelSchema, config: Config | None = None):
        self.path = Path(path)
        self.schema = schema
        self.config = config or Config()
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._init_db()

    @classmethod
    def open(cls, config: Config, schema: LabelSchema) -> Manifest:
        return cls(config.manifest_path, schema, config)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Manifest:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # setup ---------------------------------------------------------------

    def _init_db(self) -> None:
        with self.conn:
            self.conn.executescript(_DDL)
            meta = dict(self.conn.execute("SELECT key, value FROM meta").fetchall())
            if not meta:
                self.conn.executemany(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    [
                        ("manifest_format", str(MANIFEST_FORMAT)),
                        ("label_schema_version", self.schema.version),
                        ("label_schema_sha256", self.schema.sha256),
                        ("created_at", _utcnow()),
                    ],
                )
                return
        if int(meta["manifest_format"]) != MANIFEST_FORMAT:
            raise SchemaMismatchError(f"manifest format {meta['manifest_format']} != {MANIFEST_FORMAT}")
        if meta["label_schema_sha256"] != self.schema.sha256:
            raise SchemaMismatchError(
                f"manifest was created with label schema v{meta['label_schema_version']} "
                f"({meta['label_schema_sha256'][:12]}); loaded schema is v{self.schema.version} "
                f"({self.schema.sha256[:12]}). Migrate labels before switching schemas."
            )

    def info(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT key, value FROM meta").fetchall())

    # writes --------------------------------------------------------------

    def add_asset(
        self,
        record: AssetRecord,
        *,
        parents: Sequence[str | tuple[str, str]] = (),
        module: str,
        params: dict | None = None,
    ) -> AssetRecord:
        """Validate and insert one asset, its parent links and a 'register' history entry."""
        rec = record.model_copy(deep=True)
        parent_links = [(p, "source") if isinstance(p, str) else (p[0], p[1]) for p in parents]
        self._validate(rec, parent_links)
        if rec.asset_id is None:
            prefix = "tex" if rec.kind is Kind.TEXTURE_PATCH else "img"
            rec.asset_id = f"{prefix}_{rec.sha256[:16]}"
        rec.created_at = _utcnow()

        self._check_duplicates(rec)
        row = rec.model_dump(mode="json")
        row["meta"] = json.dumps(row["meta"], sort_keys=True, ensure_ascii=False)
        cols = ", ".join(_COLUMNS)
        marks = ", ".join(f":{c}" for c in _COLUMNS)
        with self.conn:
            self.conn.execute(f"INSERT INTO assets ({cols}) VALUES ({marks})", row)
            self.conn.executemany(
                "INSERT INTO asset_parents(child_id, parent_id, role) VALUES (?, ?, ?)",
                [(rec.asset_id, pid, role) for pid, role in parent_links],
            )
            self._history(rec.asset_id, "register", module, params or {})
        return rec

    def add_history(self, asset_id: str, step: str, *, module: str, params: dict | None = None) -> None:
        self.get(asset_id)
        with self.conn:
            self._history(asset_id, step, module, params or {})

    def set_split(self, asset_id: str, split: Split, *, module: str, reason: str = "") -> None:
        rec = self.get(asset_id)
        split = Split(split)
        self._check_split(rec, split)
        with self.conn:
            self.conn.execute("UPDATE assets SET split = ? WHERE asset_id = ?", (split.value, asset_id))
            self._history(asset_id, "set_split", module, {"from": rec.split.value, "to": split.value, "reason": reason})

    def set_privacy(self, asset_id: str, status: PrivacyStatus, *, module: str, params: dict | None = None) -> None:
        """Record an M3 result (e.g. Mapillary images blurred after harvest)."""
        rec = self.get(asset_id)
        status = PrivacyStatus(status)
        if rec.privacy_status is PrivacyStatus.BLURRED and status is not PrivacyStatus.BLURRED:
            raise AssetRejectedError("cannot downgrade privacy status of a blurred asset")
        if status is PrivacyStatus.NOT_REQUIRED and self._privacy_required(rec):
            raise AssetRejectedError(f"{rec.origin.value}/{rec.source} assets always require blurring")
        with self.conn:
            self.conn.execute("UPDATE assets SET privacy_status = ? WHERE asset_id = ?", (status.value, asset_id))
            self._history(asset_id, "privacy", module, {"status": status.value, **(params or {})})

    def _history(self, asset_id: str, step: str, module: str, params: dict) -> None:
        if not module:
            raise ValueError("module is required for processing history (e.g. 'M1.harvest_sources')")
        self.conn.execute(
            "INSERT INTO processing_history(asset_id, step, module, tool_version, params, at) VALUES (?,?,?,?,?,?)",
            (asset_id, step, module, __version__, json.dumps(params, sort_keys=True, default=str), _utcnow()),
        )

    # validation ------------------------------------------------------------

    @staticmethod
    def _privacy_required(rec: AssetRecord) -> bool:
        return rec.origin in (Origin.CLIENT, Origin.OWN_CAPTURE) or rec.source == "mapillary"

    def _validate(self, rec: AssetRecord, parents: list[tuple[str, str]]) -> None:
        try:
            lic = parse_licence(rec.licence)
        except UnknownLicenceError as e:
            raise AssetRejectedError(str(e)) from None
        rec.licence = lic.code
        rec.licence_flag = lic.flag

        expected_internal = {Origin.CLIENT: CLIENT_DPA, Origin.OWN_CAPTURE: OWN}
        if rec.origin in SYNTHETIC_ORIGINS:
            expected_internal[rec.origin] = DERIVED

        if rec.origin is Origin.HARVESTED:
            if lic.internal:
                raise AssetRejectedError(f"harvested asset cannot carry internal licence {lic.code}")
            pol = self.config.licence_policy
            decision, reason = evaluate(lic, allow_share_alike=pol.allow_share_alike, allow_gfdl=pol.allow_gfdl)
            if decision is Decision.REJECT:
                raise AssetRejectedError(f"licence rejected: {reason}")
            if rec.kind is Kind.IMAGE and not (rec.source_id and rec.url):
                raise AssetRejectedError("harvested images need source_id and url")
            if lic.attribution and not rec.author:
                raise AssetRejectedError(
                    f"{lic.code} requires attribution: set author (use 'Unknown (not supplied)' only if the source has none)"
                )
        elif lic is not expected_internal[rec.origin]:
            raise AssetRejectedError(
                f"{rec.origin.value} assets must use licence {expected_internal[rec.origin].code}, got {lic.code}"
            )

        if rec.kind is Kind.IMAGE and rec.origin is Origin.CLIENT:
            if not rec.camera_id:
                raise AssetRejectedError("client frames need camera_id")
            if not rec.capture_date or parse_capture_date(rec.capture_date).tzinfo is None:
                raise AssetRejectedError("client frames need a timezone-aware capture_date")
        if rec.kind is Kind.IMAGE and rec.origin is Origin.OWN_CAPTURE and not rec.capture_date:
            raise AssetRejectedError("own captures need capture_date")

        if self._privacy_required(rec):
            allowed = {PrivacyStatus.BLURRED} | ({PrivacyStatus.PENDING} if rec.origin is Origin.HARVESTED else set())
            if rec.privacy_status not in allowed:
                raise AssetRejectedError(
                    f"{rec.origin.value}/{rec.source} assets must be registered with privacy_status in "
                    f"{sorted(s.value for s in allowed)} (M3 runs before storage)"
                )
        elif rec.privacy_status is PrivacyStatus.PENDING and rec.origin is not Origin.HARVESTED:
            raise AssetRejectedError("privacy_status 'pending' is only allowed for harvested images")

        if rec.origin in SYNTHETIC_ORIGINS and not parents:
            raise AssetRejectedError(f"{rec.origin.value} assets need at least one parent")
        if rec.kind is Kind.TEXTURE_PATCH:
            if not parents:
                raise AssetRejectedError("texture patches need the source image as parent")
            if rec.origin in SYNTHETIC_ORIGINS:
                raise AssetRejectedError("texture patches must come from real images")
            material = rec.meta.get("material")
            if material is not None and material not in self.schema.material_names:
                raise AssetRejectedError(f"unknown texture material {material!r}")

        for pid, role in parents:
            try:
                parent = self.get(pid)
            except KeyError:
                raise AssetRejectedError(f"parent {pid!r} is not in the manifest") from None
            if not role or not _SOURCE_RE.match(role):
                raise AssetRejectedError(f"parent role {role!r} must be a lowercase slug")
            if rec.kind is Kind.TEXTURE_PATCH and parent.licence != rec.licence:
                raise AssetRejectedError(
                    f"texture patch licence {rec.licence} differs from parent {pid} licence {parent.licence}"
                )

        self._check_split(rec, rec.split)

    def _check_split(self, rec: AssetRecord, split: Split) -> None:
        if split is Split.UNASSIGNED:
            return
        if rec.privacy_status is PrivacyStatus.PENDING:
            raise SplitRuleError(f"{rec.asset_id or rec.path}: blur it (M3) before assigning a split")
        if split is Split.TRAIN:
            return
        if rec.origin in SYNTHETIC_ORIGINS:
            raise SplitRuleError(f"{rec.origin.value} assets can never be in {split.value}")
        if rec.kind is not Kind.IMAGE:
            raise SplitRuleError("only images can be in val/test")
        allowed = self.config.splits.test_origins if split is Split.TEST else self.config.splits.val_origins
        if rec.origin not in allowed:
            raise SplitRuleError(
                f"{split.value} accepts origins {[o.value for o in allowed]}, got {rec.origin.value}"
            )

    def _check_duplicates(self, rec: AssetRecord) -> None:
        row = self.conn.execute("SELECT asset_id FROM assets WHERE sha256 = ?", (rec.sha256,)).fetchone()
        if row:
            raise DuplicateAssetError(f"identical file already registered as {row[0]}", row[0])
        row = self.conn.execute("SELECT asset_id FROM assets WHERE asset_id = ?", (rec.asset_id,)).fetchone()
        if row:
            raise DuplicateAssetError(f"asset_id {rec.asset_id} already exists", row[0])
        if rec.source_id is not None:
            row = self.conn.execute(
                "SELECT asset_id FROM assets WHERE source = ? AND source_id = ?", (rec.source, rec.source_id)
            ).fetchone()
            if row:
                raise DuplicateAssetError(f"{rec.source}:{rec.source_id} already registered as {row[0]}", row[0])
        row = self.conn.execute("SELECT asset_id FROM assets WHERE path = ?", (rec.path,)).fetchone()
        if row:
            raise DuplicateAssetError(f"path {rec.path} already registered as {row[0]}", row[0])

    # reads -----------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> AssetRecord:
        d = dict(row)
        d["meta"] = json.loads(d["meta"])
        return AssetRecord(**d)

    def get(self, asset_id: str) -> AssetRecord:
        row = self.conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return self._row_to_record(row)

    def find(self, source: str, source_id: str) -> AssetRecord | None:
        row = self.conn.execute(
            "SELECT * FROM assets WHERE source = ? AND source_id = ?", (source, source_id)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def find_by_sha256(self, sha256: str) -> AssetRecord | None:
        row = self.conn.execute("SELECT * FROM assets WHERE sha256 = ?", (sha256.lower(),)).fetchone()
        return self._row_to_record(row) if row else None

    def query(self, **filters: Any) -> Iterator[AssetRecord]:
        """Filter on equality of any asset column, e.g. query(origin=Origin.CLIENT, split=Split.TEST)."""
        unknown = set(filters) - set(_COLUMNS)
        if unknown:
            raise ValueError(f"unknown columns {sorted(unknown)}")
        where = " AND ".join(f"{k} = ?" for k in filters) or "1"
        values = [v.value if hasattr(v, "value") else v for v in filters.values()]
        for row in self.conn.execute(f"SELECT * FROM assets WHERE {where} ORDER BY asset_id", values):
            yield self._row_to_record(row)

    def history(self, asset_id: str) -> list[HistoryEntry]:
        rows = self.conn.execute(
            "SELECT step, module, tool_version, params, at FROM processing_history WHERE asset_id = ? ORDER BY id",
            (asset_id,),
        ).fetchall()
        return [HistoryEntry(r["step"], r["module"], r["tool_version"], json.loads(r["params"]), r["at"]) for r in rows]

    def parents(self, asset_id: str) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT parent_id, role FROM asset_parents WHERE child_id = ? ORDER BY parent_id, role", (asset_id,)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def ancestors(self, asset_id: str) -> list[str]:
        rows = self.conn.execute(
            """
            WITH RECURSIVE anc(id) AS (
                SELECT parent_id FROM asset_parents WHERE child_id = ?
                UNION
                SELECT p.parent_id FROM asset_parents p JOIN anc ON p.child_id = anc.id
            )
            SELECT id FROM anc ORDER BY id
            """,
            (asset_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def descendants(self, asset_ids: Iterable[str]) -> list[str]:
        ids = list(asset_ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"""
            WITH RECURSIVE des(id) AS (
                SELECT child_id FROM asset_parents WHERE parent_id IN ({marks})
                UNION
                SELECT c.child_id FROM asset_parents c JOIN des ON c.parent_id = des.id
            )
            SELECT id FROM des ORDER BY id
            """,
            ids,
        ).fetchall()
        return [r[0] for r in rows]

    def attribution(self, asset_id: str) -> list[dict[str, Any]]:
        """Third-party works an asset is built from (itself included) that need credit or carry SA terms."""
        out = []
        for aid in [asset_id, *self.ancestors(asset_id)]:
            rec = self.get(aid)
            lic = parse_licence(rec.licence)
            if lic.internal:
                continue
            out.append(
                {
                    "asset_id": aid,
                    "source": rec.source,
                    "source_id": rec.source_id,
                    "url": rec.url,
                    "author": rec.author,
                    "licence": rec.licence,
                    "licence_url": rec.licence_url,
                    "attribution_required": lic.attribution,
                    "share_alike": lic.share_alike,
                }
            )
        return out

    def near_duplicates(self, phash: str, max_distance: int = 6) -> list[tuple[str, int]]:
        """Assets whose perceptual hash is within ``max_distance`` bits (linear scan; fine below ~1e6 rows)."""
        target = int(phash, 16)
        hits = []
        for aid, other in self.conn.execute("SELECT asset_id, phash FROM assets WHERE phash IS NOT NULL"):
            d = (target ^ int(other, 16)).bit_count()
            if d <= max_distance:
                hits.append((aid, d))
        return sorted(hits, key=lambda t: (t[1], t[0]))

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {"total": self.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]}
        for col in ("kind", "origin", "source", "split", "licence", "licence_flag", "privacy_status"):
            rows = self.conn.execute(f"SELECT {col}, COUNT(*) FROM assets GROUP BY {col} ORDER BY {col}").fetchall()
            out[col] = {str(k): n for k, n in rows}
        return out

    # split integrity -------------------------------------------------------

    def _local_day(self, capture_date: str) -> str:
        dt = parse_capture_date(capture_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.config.tz)
        return dt.astimezone(self.config.tz).date().isoformat()

    def check_split_integrity(self) -> list[Violation]:
        """Leakage between splits: shared cameras, shared client capture days, and derived assets
        (texture patches, transplants) whose ancestors sit in a held-out split."""
        violations: list[Violation] = []
        pol = self.config.splits

        by_split: dict[Split, list[AssetRecord]] = {s: [] for s in Split}
        for rec in self.query():
            by_split[rec.split].append(rec)

        for held, other in pol.disjoint_pairs:
            held, other = Split(held), Split(other)
            if "camera" in pol.holdout_by:
                cams_held = {r.camera_id for r in by_split[held] if r.camera_id}
                shared = cams_held & {r.camera_id for r in by_split[other] if r.camera_id}
                for cam in sorted(shared):
                    ids = tuple(r.asset_id for r in by_split[other] if r.camera_id == cam)
                    violations.append(Violation("camera", f"camera {cam} in both {held.value} and {other.value}", ids))
            if "day" in pol.holdout_by:

                def days(recs: list[AssetRecord]) -> dict[str, list[str]]:
                    out: dict[str, list[str]] = {}
                    for r in recs:
                        if r.origin is Origin.CLIENT and r.capture_date:
                            out.setdefault(self._local_day(r.capture_date), []).append(r.asset_id)
                    return out

                d_held, d_other = days(by_split[held]), days(by_split[other])
                for day in sorted(set(d_held) & set(d_other)):
                    violations.append(
                        Violation("day", f"client day {day} in both {held.value} and {other.value}", tuple(d_other[day]))
                    )
            leaked = [
                aid for aid in self.descendants(r.asset_id for r in by_split[held]) if self.get(aid).split is other
            ]
            if leaked:
                violations.append(
                    Violation("ancestry", f"{other.value} assets derived from {held.value} assets", tuple(leaked))
                )

        pending = tuple(r.asset_id for s in (Split.TRAIN, Split.VAL, Split.TEST) for r in by_split[s]
                        if r.privacy_status is PrivacyStatus.PENDING)
        if pending:
            violations.append(Violation("privacy", "assets in a split still awaiting blurring", pending))
        return violations
