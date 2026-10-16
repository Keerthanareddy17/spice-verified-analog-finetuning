import zipfile

import pytest

from analogft.resultszip import import_results_zip, make_results_zip


def test_zip_roundtrip_excludes_weights(tmp_path):
    run = tmp_path / "src" / "r1"
    for rel in ("config.json", "eval/base/test/metrics.json", "logs/train_log.json", "figures/loss_curve.png",
                "checkpoints/checkpoint-50/optimizer.pt", "adapter/adapter_model.safetensors"):
        (run / rel).parent.mkdir(parents=True, exist_ok=True)
        (run / rel).write_text("x")
    z = make_results_zip(run)
    assert z == tmp_path / "src" / "r1_results.zip"
    names = zipfile.ZipFile(z).namelist()
    assert "r1/eval/base/test/metrics.json" in names and not any("checkpoint" in n or "adapter" in n for n in names)
    dest = tmp_path / "runs" / "phase3"
    files = import_results_zip(z, dest)
    assert len(files) == 4 and (dest / "r1" / "eval" / "base" / "test" / "metrics.json").exists()


def test_import_rejects_unsafe_entries(tmp_path):
    for bad in ("../evil.txt", "r1/adapter/w.safetensors", "r1/checkpoints/a"):
        z = tmp_path / "bad.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr(bad, "x")
        with pytest.raises(ValueError):
            import_results_zip(z, tmp_path / "out")


def test_import_dir(tmp_path):
    from analogft.resultszip import import_results_dir
    src = tmp_path / "r2"
    for rel in ("config.json", "eval/a.json", "adapter/w.safetensors"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    files = import_results_dir(src, tmp_path / "runs")
    assert len(files) == 2 and not (tmp_path / "runs" / "r2" / "adapter").exists()


def test_phase4_zip_roundtrip_excludes_weights_and_full_rollouts(tmp_path):
    from analogft.resultszip import import_phase4_zip, is_phase4_zip, make_phase4_zip
    p4 = tmp_path / "phase4"
    keep = ["agents/ft_recovery/steps.jsonl", "agents/ft_recovery/episodes.jsonl", "agents/ft_recovery/metrics.json",
            "rl_dataset/rl_train.stats.json", "rollouts/chunk_00/episodes.jsonl", "figures/a.png",
            "qwen25_05b_rl/config.json", "qwen25_05b_rl/eval/finetuned/test/metrics.json", "qwen25_05b_rl/logs/t.json"]
    drop = ["rl_dataset/rl_train.jsonl", "rollouts/chunk_00/steps.jsonl", "qwen25_05b_rl/adapter/w.safetensors",
            "qwen25_05b_rl/checkpoints/checkpoint-5/optimizer.pt", "agents/ft_recovery/extra.bin"]
    for rel in keep + drop:
        (p4 / rel).parent.mkdir(parents=True, exist_ok=True)
        (p4 / rel).write_text("x")
    z = make_phase4_zip(p4)
    assert is_phase4_zip(z)
    names = set(zipfile.ZipFile(z).namelist())
    assert names == {f"phase4/{k}" for k in keep}
    files = import_phase4_zip(z, tmp_path / "runs")
    assert len(files) == len(keep) and (tmp_path / "runs/phase4/agents/ft_recovery/metrics.json").exists()
