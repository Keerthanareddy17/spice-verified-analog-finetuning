#!/usr/bin/env bash
# Sync data/, runs/ or results/ between this repo and Google Drive for desktop.
# Usage: scripts/sync_drive.sh push|pull data|runs|results [--dry-run] [--metrics-only]
# --metrics-only (runs): skip checkpoints/, adapter/ and weight files; copy eval/, logs/, figures/ and configs only.
# NOTE: the Drive desktop app is optional now (DECISIONS D23); without it this script explains the zip route and exits.
# Never uses --delete: nothing is ever removed on either side.
set -euo pipefail

PROJECT="spice-verified-analog-finetuning"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [[ -x "$PY" ]] || PY=python3
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"  # analogft without relying on the editable install (its .pth can get the macOS hidden flag and be ignored)

usage() { echo "Usage: $0 push|pull data|runs|results [--dry-run] [--metrics-only]"; exit 2; }
[[ $# -ge 2 ]] || usage
DIRECTION="$1"; FOLDER="$2"; DRY=""; METRICS_ONLY=""
for opt in "${@:3}"; do
  case "$opt" in
    --dry-run) DRY="--dry-run" ;;
    --metrics-only) METRICS_ONLY=1 ;;
    *) usage ;;
  esac
done
[[ "$DIRECTION" == "push" || "$DIRECTION" == "pull" ]] || usage
[[ "$FOLDER" == "data" || "$FOLDER" == "runs" || "$FOLDER" == "results" ]] || usage

# DRIVE_LOCAL_DIR: from the environment, else from .env, else auto-detect.
if [[ -z "${DRIVE_LOCAL_DIR:-}" && -f "$REPO/.env" ]]; then
  DRIVE_LOCAL_DIR="$(grep -E '^DRIVE_LOCAL_DIR=' "$REPO/.env" | head -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)"
fi
if [[ -z "${DRIVE_LOCAL_DIR:-}" ]]; then
  for d in "$HOME"/Library/CloudStorage/GoogleDrive-*/"My Drive/$PROJECT"; do
    [[ -d "$d" ]] && { DRIVE_LOCAL_DIR="$d"; break; }
  done
fi
if [[ -z "${DRIVE_LOCAL_DIR:-}" || ! -d "$DRIVE_LOCAL_DIR" ]]; then
  echo "Drive desktop app not installed (no Google Drive for desktop folder found); use the zip download route:"
  echo "  data    -> committed to git (data/phase2/*.jsonl), Colab gets it from the clone"
  echo "  results -> the notebook writes <run>_results.zip to Drive; download it from drive.google.com, then run"
  echo "             python scripts/import_results_zip.py ~/Downloads/<run>_results.zip"
  echo "(Optional: if you reinstall the app, set DRIVE_LOCAL_DIR=/full/path in .env and this script works again.)"
  exit 1
fi

LOCAL="$REPO/$FOLDER"; REMOTE="$DRIVE_LOCAL_DIR/$FOLDER"
mkdir -p "$LOCAL" "$REMOTE"
EXCLUDES=(--exclude=.DS_Store --exclude='.*.tmp')
if [[ -n "$METRICS_ONLY" ]]; then  # no model weights on the Mac
  EXCLUDES+=(--exclude='checkpoints/' --exclude='adapter/' --exclude='*.safetensors' --exclude='*.bin' --exclude='*.pt' --exclude='*.pth' --exclude='optimizer*' --exclude='*.ckpt')
fi

if [[ "$DIRECTION" == "push" ]]; then
  [[ -z "$DRY" ]] && "$PY" "$REPO/scripts/write_manifest.py" "$LOCAL"
  echo "push: $LOCAL/ -> $REMOTE/ ${DRY}"
  rsync -av $DRY "${EXCLUDES[@]}" "$LOCAL/" "$REMOTE/"
  [[ -z "$DRY" ]] && echo "Pushed. Drive uploads in the background: wait for it to finish before running Colab (check manifest.json there)."
else
  echo "pull: $REMOTE/ -> $LOCAL/ ${DRY}"
  rsync -av $DRY "${EXCLUDES[@]}" "$REMOTE/" "$LOCAL/"
fi
