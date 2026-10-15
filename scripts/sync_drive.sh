#!/usr/bin/env bash
# Sync data/, runs/ or results/ between this repo and Google Drive for desktop.
# Usage: scripts/sync_drive.sh push|pull data|runs|results [--dry-run]
# Never uses --delete: nothing is ever removed on either side.
set -euo pipefail

PROJECT="spice-verified-analog-finetuning"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [[ -x "$PY" ]] || PY=python3  # needs the analogft package

usage() { echo "Usage: $0 push|pull data|runs|results [--dry-run]"; exit 2; }
[[ $# -ge 2 ]] || usage
DIRECTION="$1"; FOLDER="$2"; DRY=""
[[ "${3:-}" == "--dry-run" ]] && DRY="--dry-run"
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
  echo "Could not find the Google Drive for desktop folder."
  echo "Expected: ~/Library/CloudStorage/GoogleDrive-<email>/My Drive/$PROJECT"
  echo "Create that folder in Drive, or set DRIVE_LOCAL_DIR=/full/path in .env."
  exit 1
fi

LOCAL="$REPO/$FOLDER"; REMOTE="$DRIVE_LOCAL_DIR/$FOLDER"
mkdir -p "$LOCAL" "$REMOTE"
EXCLUDES=(--exclude=.DS_Store --exclude='.*.tmp')

if [[ "$DIRECTION" == "push" ]]; then
  [[ -z "$DRY" ]] && "$PY" "$REPO/scripts/write_manifest.py" "$LOCAL"
  echo "push: $LOCAL/ -> $REMOTE/ ${DRY}"
  rsync -av $DRY "${EXCLUDES[@]}" "$LOCAL/" "$REMOTE/"
  [[ -z "$DRY" ]] && echo "Pushed. Drive uploads in the background: wait for it to finish before running Colab (check manifest.json there)."
else
  echo "pull: $REMOTE/ -> $LOCAL/ ${DRY}"
  rsync -av $DRY "${EXCLUDES[@]}" "$REMOTE/" "$LOCAL/"
fi
