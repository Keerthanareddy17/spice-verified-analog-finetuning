# runs/

Training runs, checkpoints and agent traces (Phases 3-4). Untracked except this file and `manifest.json`.

- **Colab:** `runs/` is on the mounted Drive path, e.g. `runs/phase3/<run_name>/` (checkpoints/, adapter/, eval/, logs/, figures/)
  and `runs/phase4/` (agents/, rollouts/, rl_dataset/, the RL run).
- **Results archives:** the notebooks write weights-free archives (`runs/phase3/<run_name>_results.zip`,
  `runs/phase4_results.zip`; eval, logs, figures, config, traces and metrics; no checkpoints or adapters).
  `python scripts/import_results_zip.py <archive>` unpacks them into the layout above, after which
  `scripts/make_results_table.py` and `scripts/make_phase4_table.py` run unchanged (D23, D31).
