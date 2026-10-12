import pytest
from pydantic import ValidationError

from snowcv.core import Config, Origin, load_config


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("SNOWCV_CONFIG", raising=False)
    monkeypatch.delenv("SNOWCV_DATA_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.data_root == tmp_path / "data"
    assert cfg.manifest_path == tmp_path / "data" / "manifest.sqlite"
    assert cfg.splits.test_origins == [Origin.CLIENT]


def test_relative_to_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SNOWCV_DATA_ROOT", raising=False)
    (tmp_path / "cfg").mkdir()
    f = tmp_path / "cfg" / "c.yaml"
    f.write_text("data_root: ../store\nlicence_policy:\n  allow_share_alike: false\n")
    cfg = load_config(f)
    assert cfg.data_root == tmp_path / "store"
    assert cfg.licence_policy.allow_share_alike is False


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWCV_DATA_ROOT", str(tmp_path / "gpu"))
    assert load_config().data_root == tmp_path / "gpu"


def test_repo_default_config_loads(monkeypatch):
    monkeypatch.delenv("SNOWCV_DATA_ROOT", raising=False)
    from pathlib import Path

    cfg = load_config(Path(__file__).parents[1] / "config" / "default.yaml")
    assert cfg.data_root.name == "data"


def test_synthetic_never_in_test():
    with pytest.raises(ValidationError, match="never"):
        Config(splits={"test_origins": ["client", "synthetic"]})
    with pytest.raises(ValidationError):
        Config(unknown_key=1)
