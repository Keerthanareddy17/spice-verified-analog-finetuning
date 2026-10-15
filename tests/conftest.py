import pytest

from analogft import paths


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    """Every test gets its own empty simulation cache."""
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")
