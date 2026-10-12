"""Enumerations shared by the manifest, config and later modules."""

from __future__ import annotations

from enum import Enum


class Kind(str, Enum):
    IMAGE = "image"
    TEXTURE_PATCH = "texture_patch"


class Origin(str, Enum):
    HARVESTED = "harvested"  # M1: Openverse, Wikimedia, Mapillary, Poly Haven, ambientCG
    CLIENT = "client"  # M2: client cameras
    OWN_CAPTURE = "own_capture"  # our own photo campaigns
    SYNTHETIC = "synthetic"  # M10 renders
    TRANSPLANT = "transplant"  # M11 real-snow transplants
    CONTROL = "control"  # M13 bare-surface control composites


SYNTHETIC_ORIGINS = frozenset({Origin.SYNTHETIC, Origin.TRANSPLANT, Origin.CONTROL})
REAL_ORIGINS = frozenset(set(Origin) - SYNTHETIC_ORIGINS)


class Split(str, Enum):
    UNASSIGNED = "unassigned"
    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class PrivacyStatus(str, Enum):
    NOT_REQUIRED = "not_required"  # e.g. CC0 material photos, rooftop shots without people
    PENDING = "pending"  # awaiting M3 (allowed only for harvested images)
    BLURRED = "blurred"  # M3 applied; originals not kept
