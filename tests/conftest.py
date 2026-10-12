import hashlib
import itertools

import pytest

from snowcv.core import AssetRecord, Config, Manifest, load_schema

_counter = itertools.count()


@pytest.fixture(scope="session")
def schema():
    return load_schema()


@pytest.fixture
def config(tmp_path):
    return Config(data_root=tmp_path / "data")


@pytest.fixture
def manifest(config, schema):
    m = Manifest(config.manifest_path, schema, config)
    yield m
    m.close()


def fake_sha() -> str:
    return hashlib.sha256(str(next(_counter)).encode()).hexdigest()


def harvested(**kw) -> AssetRecord:
    n = next(_counter)
    base = dict(
        origin="harvested",
        source="wikimedia",
        source_id=f"File:Snow_{n}.jpg",
        url=f"https://commons.wikimedia.org/wiki/File:Snow_{n}.jpg",
        author="Jane Doe",
        licence="CC BY 4.0",
        path=f"raw/harvested/wikimedia/snow_{n}.jpg",
        sha256=fake_sha(),
    )
    base.update(kw)
    return AssetRecord(**base)


def client_frame(camera="cam01", ts="2026-11-20T10:00:00+07:00", **kw) -> AssetRecord:
    n = next(_counter)
    base = dict(
        origin="client",
        source="client",
        source_id=f"{camera}/{ts}/{n}",
        licence="CLIENT-DPA",
        camera_id=camera,
        capture_date=ts,
        path=f"raw/client/{camera}/{n}.jpg",
        sha256=fake_sha(),
        privacy_status="blurred",
    )
    base.update(kw)
    return AssetRecord(**base)


def synthetic(**kw) -> AssetRecord:
    n = next(_counter)
    base = dict(
        origin="synthetic",
        source="m10_renderer",
        licence="DERIVED",
        path=f"synthetic/run1/{n}.png",
        sha256=fake_sha(),
    )
    base.update(kw)
    return AssetRecord(**base)
