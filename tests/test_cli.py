from snowcv.cli import main


def test_init_and_stats(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SNOWCV_CONFIG", raising=False)
    monkeypatch.setenv("SNOWCV_DATA_ROOT", str(tmp_path / "d"))
    assert main(["init"]) == 0
    assert (tmp_path / "d" / "manifest.sqlite").exists()
    assert (tmp_path / "d" / "raw" / "client").is_dir()
    assert main(["manifest", "stats"]) == 0
    assert main(["manifest", "check-splits"]) == 0
    assert main(["schema", "check"]) == 0
    assert main(["licence", "CC BY-NC 4.0"]) == 1
    assert main(["licence", "by-sa", "--version", "4.0"]) == 0
    assert "flag" in capsys.readouterr().out
