"""Small zip of a run's results (no checkpoints, no adapter) for moving run output off the Colab Drive by download.

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


# ----- Phase 4 (runs/phase4/): agent traces + metrics, RL stats/eval/logs/figures; never weights or full rollouts ----

PHASE4 = "phase4"
_P4_AGENT_FILES = ("steps.jsonl", "episodes.jsonl", "metrics.json")


def _wanted4(rel: str) -> bool:
    """Is this path (relative to runs/phase4/) allowed in a results zip?"""
    parts = rel.split("/")
    if "checkpoints" in parts or "adapter" in parts or rel.endswith((".safetensors", ".bin", ".pt", "rl_train.jsonl")):
        return False
    if parts[0] == "agents":
        return len(parts) == 3 and parts[2] in _P4_AGENT_FILES
    if parts[0] == "figures" or rel in ("rl_dataset/rl_train.stats.json", "rollouts_summary.json"):
        return True
    if parts[0] == "rollouts":                      # per-chunk episode records only (steps carry full states: large)
        return len(parts) == 3 and parts[2] == "episodes.jsonl"
    return len(parts) >= 2 and parts[0] not in ("agents", "rollouts", "rl_dataset") and \
        (rel == f"{parts[0]}/config.json" or parts[1] in ("eval", "logs", "figures"))


def make_phase4_zip(phase4_dir: Path, out_zip: Path | None = None) -> Path:
    """Zip runs/phase4/ (allowed files only) into <phase4_dir>_results.zip; entries are stored as phase4/<rel>."""
    phase4_dir = Path(phase4_dir)
    out_zip = Path(out_zip) if out_zip else phase4_dir.parent / f"{phase4_dir.name}_results.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(phase4_dir.rglob("*")):
            rel = p.relative_to(phase4_dir).as_posix()
            if p.is_file() and _wanted4(rel):
                z.write(p, f"{PHASE4}/{rel}")
    return out_zip


def import_phase4_zip(zip_path: Path, runs_dir: Path) -> list[Path]:
    """Unpack a phase4 results zip into runs_dir (-> runs_dir/phase4/...), refusing anything not allowed."""
    runs_dir = Path(runs_dir).resolve()
    written = []
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for n in names:
            parts = Path(n).parts
            if parts[0] != PHASE4 or ".." in parts or Path(n).is_absolute() or not _wanted4("/".join(parts[1:])):
                raise ValueError(f"unexpected entry in results zip: {n}")
        for n in names:
            target = (runs_dir / n).resolve()
            if runs_dir not in target.parents:
                raise ValueError(f"unsafe path in zip: {n}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
            written.append(target)
    return written


def import_phase4_dir(src_dir: Path, runs_dir: Path) -> list[Path]:
    """Same for a folder named phase4 that the browser already unpacked."""
    src_dir, runs_dir = Path(src_dir), Path(runs_dir)
    written = []
    for p in sorted(src_dir.rglob("*")):
        rel = p.relative_to(src_dir).as_posix()
        if p.is_file() and _wanted4(rel):
            target = runs_dir / PHASE4 / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
            written.append(target)
    return written


def is_phase4_zip(zip_path: Path) -> bool:
    with zipfile.ZipFile(zip_path) as z:
        return any(n.startswith(PHASE4 + "/") for n in z.namelist())
