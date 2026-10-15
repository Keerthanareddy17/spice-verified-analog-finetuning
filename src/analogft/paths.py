"""Single source of truth for every path in the project (Colab vs local aware).

Nothing else in the repo should hardcode an absolute path.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

PROJECT_NAME = "spice-verified-analog-finetuning"


def _detect_colab() -> bool:
    if os.environ.get("COLAB_RELEASE_TAG"):
        return True
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


IS_COLAB: bool = _detect_colab()
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
COLAB_DRIVE_ROOT = Path("/content/drive/MyDrive") / PROJECT_NAME


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:  # python-dotenv is optional on Colab
        pass


def _find_drive_local_dir() -> Path | None:
    """Locate the Google Drive for desktop copy of the project folder (Mac only)."""
    override = os.environ.get("DRIVE_LOCAL_DIR")
    if override:
        return Path(override).expanduser()
    pattern = str(Path.home() / "Library/CloudStorage/GoogleDrive-*/My Drive" / PROJECT_NAME)
    hits = sorted(glob.glob(pattern))
    return Path(hits[0]) if hits else None


def _resolve_storage_root() -> Path:
    override = os.environ.get("ANALOGFT_STORAGE_ROOT")
    if override:
        return Path(override).expanduser()
    if IS_COLAB:
        if not Path("/content/drive/MyDrive").exists():
            raise RuntimeError(
                "Google Drive is not mounted. Run "
                "`from google.colab import drive; drive.mount('/content/drive')` first."
            )
        return COLAB_DRIVE_ROOT
    return REPO_ROOT


_load_dotenv()
STORAGE_ROOT: Path = _resolve_storage_root()
DATA_DIR: Path = STORAGE_ROOT / "data"
RUNS_DIR: Path = STORAGE_ROOT / "runs"
RESULTS_DIR: Path = STORAGE_ROOT / "results"
FIGURES_DIR: Path = RESULTS_DIR / "figures"
MODELS_DIR: Path = REPO_ROOT / "models"
DRIVE_LOCAL_DIR: Path | None = None if IS_COLAB else _find_drive_local_dir()

# Local-only simulation cache: never synced to Drive, never committed.
CACHE_DIR: Path = (Path(os.environ.get("ANALOGFT_CACHE_DIR", "")).expanduser()
                   if os.environ.get("ANALOGFT_CACHE_DIR")
                   else (Path("/content/.simcache") if IS_COLAB else REPO_ROOT / ".simcache"))

for _d in (DATA_DIR, RUNS_DIR, RESULTS_DIR, FIGURES_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
