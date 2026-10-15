# runs/

Training runs, checkpoints and agent traces (Phases 3-4). Gitignored except this file and `manifest.json`.

- **On Colab** `runs/` lives on the mounted Drive: `My Drive/spice-verified-analog-finetuning/runs/phase3/<run_name>/`
  (checkpoints/, adapter/, eval/, logs/, figures/). Colab writes there directly.
- **To the Mac, without weights** (DECISIONS D23): the last notebook cell zips eval/, logs/, figures/ and config.json into
  `runs/phase3/<run_name>_results.zip` on Drive. Download it from drive.google.com, then
  `python scripts/import_results_zip.py ~/Downloads/<run_name>_results.zip` unpacks it into `runs/phase3/<run_name>/`
  here, and `scripts/make_results_table.py` works unchanged. Adapters and checkpoints stay on Drive.
