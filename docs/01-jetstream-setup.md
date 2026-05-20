# Phase 0 — Jetstream environment setup

Brief for the Claude Code session running on Jetstream. The laptop side of
Phase 0 is complete. This document covers the GPU-box side: get
nerfstudio + gsplat installed and verified so Phase 1 (training a real
splat) can run.

## What's already true when you read this

- The repo has been cloned to `/media/volume/Tene_Volume/geosplat-inspector`.
- You are SSH'd in as `exouser`. You can `cd` into the repo.
- `CLAUDE.md` and `.claude/skills/splat-pipeline/` are available — read
  them for full project context.

## Pre-flight checks (do these first, fix before continuing)

1. `pwd` → should be `/media/volume/Tene_Volume/geosplat-inspector`.
   If not: `cd /media/volume/Tene_Volume/geosplat-inspector`.
2. `nvidia-smi` → at least one L40S visible, driver loaded.
3. `conda --version` → prints a version. If "command not found",
   install miniconda first:
   ```
   wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
   bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3
   source $HOME/miniconda3/bin/activate
   conda init bash && source ~/.bashrc
   ```
4. `df -h /media/volume/Tene_Volume` → at least 20 GB free.

## Steps

### 1. Create conda env

```
conda create -n geosplat python=3.11 -y
conda activate geosplat
```

### 2. Install PyTorch with CUDA 12.1

```
pip install torch==2.1.2 torchvision==0.16.2 \
    --index-url https://download.pytorch.org/whl/cu121
```

### 3. Verify the CUDA wheel landed (not CPU-only)

```
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count())"
```

Expected output: `2.1.2+cu121 True 4` (or however many GPUs `nvidia-smi`
reported).

If `cuda.is_available()` is False, you got the CPU wheel. Uninstall and
reinstall with the `--index-url` flag:

```
pip uninstall torch torchvision -y
pip install torch==2.1.2 torchvision==0.16.2 \
    --index-url https://download.pytorch.org/whl/cu121
```

### 4. Install nerfstudio (~10 min)

```
pip install nerfstudio
```

### 5. Verify CLI tools

```
ns-train --help | head -5
ns-process-data --help | head -5
ns-export --help | head -5
which ns-train
```

`which ns-train` should point inside the `geosplat` env, not a system path.

## Common failures (fix and continue)

- **`gsplat` CUDA build fails during nerfstudio install**: rebuild against
  the installed PyTorch:
  ```
  pip install gsplat --no-build-isolation
  ```
- **`torch.cuda.is_available()` returns False but `nvidia-smi` works**:
  CPU-only PyTorch installed. See step 3 reinstall block.
- **`ns-train --help` errors on import**: usually a gsplat/PyTorch ABI
  mismatch — reinstall gsplat with `--no-build-isolation`.

## Definition of done

All four checks pass:

- [ ] `conda activate geosplat` works (env is named `geosplat`)
- [ ] `python -c "import torch; print(torch.cuda.is_available())"` prints `True`
- [ ] `ns-train --help`, `ns-process-data --help`, `ns-export --help` all print help
- [ ] `which ns-train` shows a path inside the `geosplat` conda env

When all four are green, Phase 0 is complete. Move to Phase 1 (see
`docs/00-start-here.md` section 6).

## What NOT to do in this phase

- Don't record or process any video — that's Phase 1.
- Don't run `ns-train` on real data — Phase 1.
- Don't push code changes back unless adding genuinely useful helper
  scripts (and confirm with user first).
- Don't shelve the instance until the definition-of-done passes — if
  you shelve mid-install you'll waste re-setup time.
- Don't `pip install` packages outside the `geosplat` env.

## Cleanup after install

If miniconda was installed as part of this setup, the installer script
`~/Miniconda3-latest-Linux-x86_64.sh` (~156 MB) can be deleted once
`conda` is on the path:

```
rm ~/Miniconda3-latest-Linux-x86_64.sh
```
