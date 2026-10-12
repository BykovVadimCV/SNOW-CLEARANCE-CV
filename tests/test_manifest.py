import pytest

from snowcv.core import (
    AssetRecord,
    AssetRejectedError,
    Config,
    DuplicateAssetError,
    Kind,
    Manifest,
    PrivacyStatus,
    SchemaMismatchError,
    Split,
    SplitRuleError,
)
from snowcv.core.schema import parse_schema

from conftest import client_frame, fake_sha, harvested, synthetic

M = "test"


def test_roundtrip_and_history(manifest):
    rec = manifest.add_asset(harvested(meta={"query": "snow roof"}, phash="00ff00ff00ff00ff"), module=M, params={"q": 1})
    assert rec.asset_id == f"img_{rec.sha256[:16]}"
    got = manifest.get(rec.asset_id)
    assert got.licence == "CC-BY-4.0" and got.meta == {"query": "snow roof"}
    h = manifest.history(rec.asset_id)
    assert [e.step for e in h] == ["register"] and h[0].params == {"q": 1}
    manifest.add_history(rec.asset_id, "prelabel", module="M5.prelabel", params={"model": "sam2"})
    assert [e.step for e in manifest.history(rec.asset_id)] == ["register", "prelabel"]
    assert manifest.find("wikimedia", rec.source_id).asset_id == rec.asset_id


def test_reopen_persists_and_checks_schema(config, schema):
    with Manifest(config.manifest_path, schema, config) as m:
        rec = m.add_asset(harvested(), module=M)
    with Manifest(config.manifest_path, schema, config) as m:
        assert m.get(rec.asset_id).sha256 == rec.sha256
    import yaml
    from snowcv.core.schema import DEFAULT_SCHEMA_PATH

    raw = yaml.safe_load(DEFAULT_SCHEMA_PATH.read_text())
    raw["version"] = "2.0.0"
    with pytest.raises(SchemaMismatchError):
        Manifest(config.manifest_path, parse_schema(raw), config)


@pytest.mark.parametrize("licence", ["CC BY-NC 4.0", "CC BY-ND 4.0", "All rights reserved", "CLIENT-DPA"])
def test_licence_gate(manifest, licence):
    with pytest.raises(AssetRejectedError):
        manifest.add_asset(harvested(licence=licence), module=M)


def test_share_alike_flagged(manifest):
    rec = manifest.add_asset(harvested(licence="by-sa 4.0"), module=M)
    assert rec.licence_flag == "share_alike"


def test_share_alike_off(config, schema):
    config.licence_policy.allow_share_alike = False
    with Manifest(config.manifest_path, schema, config) as m, pytest.raises(AssetRejectedError):
        m.add_asset(harvested(licence="CC BY-SA 4.0"), module=M)


def test_attribution_needs_author(manifest):
    with pytest.raises(AssetRejectedError, match="attribution"):
        manifest.add_asset(harvested(author=None), module=M)
    manifest.add_asset(harvested(author=None, licence="CC0"), module=M)


def test_duplicates(manifest):
    a = manifest.add_asset(harvested(), module=M)
    with pytest.raises(DuplicateAssetError) as e:
        manifest.add_asset(harvested(sha256=a.sha256), module=M)
    assert e.value.existing_id == a.asset_id
    with pytest.raises(DuplicateAssetError):
        manifest.add_asset(harvested(source_id=a.source_id), module=M)


def test_near_duplicates(manifest):
    a = manifest.add_asset(harvested(phash="ffffffffffffffff"), module=M)
    manifest.add_asset(harvested(phash="0000000000000000"), module=M)
    assert manifest.near_duplicates("fffffffffffffffe", 4) == [(a.asset_id, 1)]


def test_client_rules(manifest):
    manifest.add_asset(client_frame(), module=M)
    with pytest.raises(AssetRejectedError, match="privacy"):
        manifest.add_asset(client_frame(privacy_status="not_required"), module=M)
    with pytest.raises(AssetRejectedError, match="privacy"):
        manifest.add_asset(client_frame(privacy_status="pending"), module=M)
    with pytest.raises(AssetRejectedError, match="timezone"):
        manifest.add_asset(client_frame(ts="2026-11-20T10:00:00"), module=M)
    with pytest.raises(AssetRejectedError, match="camera_id"):
        manifest.add_asset(client_frame(camera_id=None), module=M)
    with pytest.raises(AssetRejectedError, match="CLIENT-DPA"):
        manifest.add_asset(client_frame(licence="CC0"), module=M)


def test_mapillary_privacy(manifest):
    with pytest.raises(AssetRejectedError):
        manifest.add_asset(harvested(source="mapillary", licence="CC BY-SA 4.0"), module=M)
    rec = manifest.add_asset(harvested(source="mapillary", licence="CC BY-SA 4.0", privacy_status="pending"), module=M)
    with pytest.raises(SplitRuleError, match="blur"):
        manifest.set_split(rec.asset_id, Split.TRAIN, module=M)
    with pytest.raises(AssetRejectedError):
        manifest.set_privacy(rec.asset_id, PrivacyStatus.NOT_REQUIRED, module=M)
    manifest.set_privacy(rec.asset_id, PrivacyStatus.BLURRED, module="M3.privacy_filter", params={"faces": 2})
    manifest.set_split(rec.asset_id, Split.TRAIN, module=M)
    assert [e.step for e in manifest.history(rec.asset_id)] == ["register", "privacy", "set_split"]


def test_split_rules(manifest):
    real = manifest.add_asset(client_frame(), module=M)
    web = manifest.add_asset(harvested(), module=M)
    syn = manifest.add_asset(synthetic(), parents=[(web.asset_id, "background")], module=M)
    manifest.set_split(real.asset_id, Split.TEST, module=M)
    manifest.set_split(syn.asset_id, Split.TRAIN, module=M)
    for split in (Split.VAL, Split.TEST):
        with pytest.raises(SplitRuleError):
            manifest.set_split(syn.asset_id, split, module=M)
    with pytest.raises(SplitRuleError, match="test accepts"):
        manifest.set_split(web.asset_id, Split.TEST, module=M)
    with pytest.raises(SplitRuleError):
        manifest.add_asset(synthetic(split="test"), parents=[web.asset_id], module=M)


def test_synthetic_needs_parents(manifest):
    with pytest.raises(AssetRejectedError, match="parent"):
        manifest.add_asset(synthetic(), module=M)
    with pytest.raises(AssetRejectedError, match="not in the manifest"):
        manifest.add_asset(synthetic(), parents=["img_missing"], module=M)


def test_texture_patch_and_attribution(manifest):
    src = manifest.add_asset(harvested(licence="CC BY-SA 4.0", author="A. Photographer"), module=M)
    bg = manifest.add_asset(harvested(licence="CC0", author=None), module=M)
    patch = manifest.add_asset(
        AssetRecord(
            kind=Kind.TEXTURE_PATCH,
            origin="harvested",
            source="m8_texture_harvester",
            licence="CC BY-SA 4.0",
            author="A. Photographer",
            path="textures/ruts/p1.png",
            sha256=fake_sha(),
            meta={"material": "ruts", "px_per_metre": 200.0},
        ),
        parents=[src.asset_id],
        module="M8.texture_harvester",
    )
    assert patch.asset_id.startswith("tex_")
    syn = manifest.add_asset(
        synthetic(), parents=[(bg.asset_id, "background"), (patch.asset_id, "texture")], module=M
    )
    assert set(manifest.ancestors(syn.asset_id)) == {bg.asset_id, patch.asset_id, src.asset_id}
    credits = manifest.attribution(syn.asset_id)
    assert {c["asset_id"] for c in credits} == {bg.asset_id, patch.asset_id, src.asset_id}
    assert any(c["share_alike"] for c in credits)

    with pytest.raises(AssetRejectedError, match="differs"):
        manifest.add_asset(
            AssetRecord(kind="texture_patch", origin="harvested", source="m8_texture_harvester", licence="CC0",
                        path="textures/ruts/p2.png", sha256=fake_sha()),
            parents=[src.asset_id], module=M,
        )
    with pytest.raises(AssetRejectedError, match="material"):
        manifest.add_asset(
            AssetRecord(kind="texture_patch", origin="harvested", source="m8_texture_harvester", licence="CC0",
                        path="textures/x/p3.png", sha256=fake_sha(), meta={"material": "gravel"}),
            parents=[bg.asset_id], module=M,
        )


def test_split_integrity(manifest):
    t1 = manifest.add_asset(client_frame("cam01", "2026-11-20T23:30:00+07:00", split="test"), module=M)
    manifest.add_asset(client_frame("cam02", "2026-11-21T09:00:00+07:00", split="train"), module=M)
    assert manifest.check_split_integrity() == []

    # same camera in train -> camera leak; same local day -> day leak (16:30Z == 23:30 local, 20 Nov)
    manifest.add_asset(client_frame("cam01", "2026-11-25T10:00:00+07:00", split="train"), module=M)
    manifest.add_asset(client_frame("cam03", "2026-11-20T16:45:00+00:00", split="train"), module=M)
    # a transplant built from a test frame, placed in train -> ancestry leak
    manifest.add_asset(synthetic(origin="transplant", split="train"), parents=[t1.asset_id], module=M)

    rules = sorted(v.rule for v in manifest.check_split_integrity())
    assert rules == ["ancestry", "camera", "day"]


def test_stats(manifest):
    manifest.add_asset(harvested(), module=M)
    manifest.add_asset(client_frame(), module=M)
    s = manifest.stats()
    assert s["total"] == 2 and s["origin"] == {"client": 1, "harvested": 1}


def test_module_required(manifest):
    with pytest.raises(ValueError, match="module"):
        manifest.add_asset(harvested(), module="")
