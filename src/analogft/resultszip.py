"""Small zip of a run's results (no checkpoints, no adapter) for moving Colab output to the Mac by download.

Zip layout: <run_name>/{config.json, eval/..., logs/..., figures/...}, so unpacking into runs/phase3/ recreates the run folder.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

INCLUDE = ("config.json", "eval/", "logs/", "figures/")


def _wanted(rel: str) -> bool:
    return rel == "config.json" or any(rel.startswith(p) for p in INCLUDE if p.endswith("/"))


def make_results_zip(run_dir: Path, out_zip: Path | None = None) -> Path:
    """Zip config, eval/, logs/ and figures/ of run_dir into <run_dir>_results.zip (next to the run folder)."""
    run_dir = Path(run_dir)
    out_zip = Path(out_zip) if out_zip else run_dir.parent / f"{run_dir.name}_results.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(run_dir.rglob("*")):
            rel = p.relative_to(run_dir).as_posix()
            if p.is_file() and _wanted(rel):
                z.write(p, f"{run_dir.name}/{rel}")
    return out_zip


def import_results_zip(zip_path: Path, dest_dir: Path, overwrite: bool = True) -> list[Path]:
    """Unpack a results zip into dest_dir (normally runs/phase3). Refuses anything outside the allowed layout."""
    dest_dir = Path(dest_dir).resolve()
    written = []
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for n in names:
            parts = Path(n).parts
            if len(parts) < 2 or ".." in parts or Path(n).is_absolute() or not _wanted("/".join(parts[1:])):
                raise ValueError(f"unexpected entry in results zip: {n}")
        for n in names:
            target = (dest_dir / n).resolve()
            if dest_dir not in target.parents:
                raise ValueError(f"unsafe path in zip: {n}")
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
            written.append(target)
    return written


def import_results_dir(src_dir: Path, dest_dir: Path) -> list[Path]:
    """Same as import_results_zip for a folder the browser already unpacked (its name is the run name).

    Only config.json, eval/, logs/ and figures/ are copied; anything else (e.g. weights) is ignored.
    """
    src_dir, dest_dir = Path(src_dir), Path(dest_dir)
    written = []
    for p in sorted(src_dir.rglob("*")):
        rel = p.relative_to(src_dir).as_posix()
        if p.is_file() and _wanted(rel):
            target = dest_dir / src_dir.name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
            written.append(target)
    return written
