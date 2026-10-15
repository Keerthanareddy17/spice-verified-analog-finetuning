# data/

Phase 2 dataset. **Committed to git** (DECISIONS D23): `phase2/{train,val,test}.jsonl`, `phase2/episodes_*.jsonl`,
`phase2/build_stats.json`, `samples/` and `manifest.json` (file names, sizes, row counts). About 23 MB in total.
Everything else under `data/` (for example `phase2_pilot/`) is gitignored.

- **Mac:** the files are in the working tree; regenerate with `scripts/build_dataset.py`, `scripts/relabel_dataset.py`,
  then `python scripts/write_manifest.py data` and commit.
- **Colab:** the notebook clones the repo, so it reads `/content/spice-verified-analog-finetuning/data` (an exact, versioned
  snapshot) and checks it against `manifest.json` with `verify_manifest`. Nothing is uploaded to Drive for data.
