# data/

Phase 2 dataset, tracked in git (see `docs/DECISIONS.md`, D23): `phase2/{train,val,test}.jsonl`, `phase2/episodes_*.jsonl`,
`phase2/build_stats.json`, `samples/` and `manifest.json` (file names, sizes, row counts), about 23 MB in total.
Everything else under `data/` (for example `phase2_pilot/`) is untracked. The dataset card is `docs/DATASET_CARD.md`.

- **Regenerate:** `scripts/build_dataset.py`, then `scripts/relabel_dataset.py` (tie-break) and `scripts/write_manifest.py data`.
- **Colab:** notebooks read the data from the repository checkout and verify it against `manifest.json` with `verify_manifest`.
