"""Stage 3 — Gaussian Splat training with gsplat."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from ..config import PipelineConfig
from ..logging_setup import get_logger
from ..utils.colmap_io import get_camera_center, qvec_to_rotmat, read_colmap_model


class TrainError(Exception):
    pass


STAGE_MARKER = "train_report.json"


# ---------------------------------------------------------------------------
# Gaussian model
# ---------------------------------------------------------------------------

@dataclass
class GaussianModel:
    """Holds all trainable Gaussian parameters on device."""

    means: torch.Tensor         # (N, 3)
    scales: torch.Tensor        # (N, 3) log-space
    rotations: torch.Tensor     # (N, 4) quaternion (wxyz)
    opacities: torch.Tensor     # (N, 1) logit
    sh_dc: torch.Tensor         # (N, 1, 3)
    sh_rest: torch.Tensor       # (N, K, 3) where K = (degree+1)^2 - 1

    # Densification accumulators (not parameters)
    grad_accum: torch.Tensor = field(default=None, repr=False)       # type: ignore[assignment]
    grad_count: torch.Tensor = field(default=None, repr=False)       # type: ignore[assignment]
    max_radii2D: torch.Tensor = field(default=None, repr=False)      # type: ignore[assignment]

    @property
    def num_gaussians(self) -> int:
        return self.means.shape[0]

    @property
    def sh_degree(self) -> int:
        k = self.sh_rest.shape[1]
        # k = (degree+1)^2 - 1 => degree = sqrt(k+1) - 1
        return int(math.sqrt(k + 1)) - 1

    def all_sh(self) -> torch.Tensor:
        """Concatenate DC and rest SH into (N, (degree+1)^2, 3)."""
        return torch.cat([self.sh_dc, self.sh_rest], dim=1)

    def param_groups(self, config: PipelineConfig) -> list[dict[str, Any]]:
        """Return optimizer parameter groups with per-parameter learning rates."""
        tc = config.train
        return [
            {"params": [self.means], "lr": tc.position_lr_init, "name": "means"},
            {"params": [self.sh_dc], "lr": tc.feature_lr, "name": "sh_dc"},
            {"params": [self.sh_rest], "lr": tc.feature_lr / 20.0, "name": "sh_rest"},
            {"params": [self.opacities], "lr": tc.opacity_lr, "name": "opacities"},
            {"params": [self.scales], "lr": tc.scaling_lr, "name": "scales"},
            {"params": [self.rotations], "lr": tc.rotation_lr, "name": "rotations"},
        ]

    def reset_densification_stats(self) -> None:
        n = self.num_gaussians
        device = self.means.device
        self.grad_accum = torch.zeros(n, 1, device=device)
        self.grad_count = torch.zeros(n, 1, device=device, dtype=torch.int32)
        self.max_radii2D = torch.zeros(n, device=device)


# ---------------------------------------------------------------------------
# Initialization from COLMAP
# ---------------------------------------------------------------------------

def init_from_colmap(model_dir: Path, sh_degree: int, device: str = "cuda") -> GaussianModel:
    """Initialize Gaussian model from COLMAP sparse reconstruction."""
    log = get_logger()
    cameras, images, points3D = read_colmap_model(model_dir)

    if len(points3D) < 10:
        raise TrainError(
            f"COLMAP model has only {len(points3D)} points. Need at least 10 "
            "for meaningful initialization."
        )

    # Extract positions and colors
    positions = np.array([p["xyz"] for p in points3D.values()], dtype=np.float32)
    colors = np.array([p["rgb"] for p in points3D.values()], dtype=np.float32) / 255.0

    n = positions.shape[0]
    log.info(f"Initializing {n} Gaussians from COLMAP sparse points")

    # Compute initial scales from nearest-neighbor distances
    from scipy.spatial import KDTree
    tree = KDTree(positions)
    dists, _ = tree.query(positions, k=4)  # k=4: self + 3 neighbors
    avg_dist = np.mean(dists[:, 1:], axis=1)  # skip self
    log_scales = np.log(np.clip(avg_dist, 1e-7, None))[:, None].repeat(3, axis=1).astype(np.float32)

    # Convert colors to SH DC coefficients
    # SH DC (degree 0) = (color - 0.5) / C0 where C0 = 0.28209479177387814
    C0 = 0.28209479177387814
    sh_dc = ((colors - 0.5) / C0).astype(np.float32)

    # Number of higher-order SH coefficients
    k = (sh_degree + 1) ** 2 - 1

    # Build model on device
    model = GaussianModel(
        means=torch.tensor(positions, device=device, dtype=torch.float32).requires_grad_(True),
        scales=torch.tensor(log_scales, device=device, dtype=torch.float32).requires_grad_(True),
        rotations=torch.tensor(
            np.tile([1.0, 0.0, 0.0, 0.0], (n, 1)).astype(np.float32),
            device=device,
        ).requires_grad_(True),
        opacities=torch.full(
            (n, 1), fill_value=_inverse_sigmoid(0.1),
            device=device, dtype=torch.float32,
        ).requires_grad_(True),
        sh_dc=torch.tensor(sh_dc[:, None, :], device=device, dtype=torch.float32).requires_grad_(True),
        sh_rest=torch.zeros(n, k, 3, device=device, dtype=torch.float32).requires_grad_(True),
    )
    model.reset_densification_stats()
    return model


def _inverse_sigmoid(x: float) -> float:
    return math.log(x / (1 - x))


# ---------------------------------------------------------------------------
# Camera / dataset loading
# ---------------------------------------------------------------------------

@dataclass
class CameraInfo:
    """A single training camera view."""
    width: int
    height: int
    K: np.ndarray          # (3, 3) intrinsic matrix
    world_to_cam: np.ndarray  # (4, 4) extrinsic matrix
    image_path: Path
    image_name: str


def load_cameras(model_dir: Path, images_dir: Path) -> list[CameraInfo]:
    """Load camera information from COLMAP model."""
    cameras_data, images_data, _ = read_colmap_model(model_dir)

    cam_infos: list[CameraInfo] = []
    for img in images_data.values():
        cam = cameras_data[img["camera_id"]]
        params = cam["params"]
        w, h = cam["width"], cam["height"]

        # Build intrinsic matrix based on camera model
        model_name = cam["model"]
        if model_name in ("SIMPLE_PINHOLE",):
            fx = fy = params[0]
            cx, cy = params[1], params[2]
        elif model_name in ("PINHOLE",):
            fx, fy = params[0], params[1]
            cx, cy = params[2], params[3]
        elif model_name in ("OPENCV", "SIMPLE_RADIAL", "RADIAL"):
            fx, fy = params[0], params[1] if len(params) > 1 else params[0]
            cx, cy = params[2] if len(params) > 2 else w / 2, params[3] if len(params) > 3 else h / 2
            if model_name == "SIMPLE_RADIAL":
                fx = fy = params[0]
                cx, cy = params[1], params[2]
            elif model_name == "RADIAL":
                fx = fy = params[0]
                cx, cy = params[1], params[2]
        else:
            # Fallback: assume first two params are fx, fy
            fx = params[0]
            fy = params[1] if len(params) > 1 else params[0]
            cx = params[2] if len(params) > 2 else w / 2.0
            cy = params[3] if len(params) > 3 else h / 2.0

        K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)

        # Build world-to-camera extrinsic (4x4)
        R = qvec_to_rotmat(img["qvec"])
        t = img["tvec"]
        w2c = np.eye(4, dtype=np.float64)
        w2c[:3, :3] = R
        w2c[:3, 3] = t

        image_path = images_dir / img["name"]
        cam_infos.append(CameraInfo(
            width=w, height=h, K=K, world_to_cam=w2c,
            image_path=image_path, image_name=img["name"],
        ))

    return cam_infos


def load_gt_image(cam: CameraInfo, device: str = "cuda") -> torch.Tensor:
    """Load ground-truth image as (1, H, W, 3) float32 tensor."""
    from PIL import Image
    img = Image.open(cam.image_path).convert("RGB")
    img_np = np.array(img, dtype=np.float32) / 255.0
    return torch.tensor(img_np, device=device, dtype=torch.float32).unsqueeze(0)


# ---------------------------------------------------------------------------
# Learning rate scheduling
# ---------------------------------------------------------------------------

def get_position_lr(step: int, config: PipelineConfig) -> float:
    tc = config.train
    if step >= tc.position_lr_max_steps:
        return tc.position_lr_final
    # Exponential decay
    t = step / tc.position_lr_max_steps
    lr = tc.position_lr_init * (tc.position_lr_final / tc.position_lr_init) ** t
    return lr


# ---------------------------------------------------------------------------
# SSIM loss
# ---------------------------------------------------------------------------

def _ssim(img1: torch.Tensor, img2: torch.Tensor, window_size: int = 11) -> torch.Tensor:
    """Compute SSIM between two (B, H, W, C) images. Returns scalar."""
    # Rearrange to (B, C, H, W) for conv2d
    img1 = img1.permute(0, 3, 1, 2)
    img2 = img2.permute(0, 3, 1, 2)
    C = img1.shape[1]

    # Gaussian window
    sigma = 1.5
    coords = torch.arange(window_size, dtype=torch.float32, device=img1.device) - window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * sigma ** 2))
    g = g / g.sum()
    window = g.unsqueeze(1) * g.unsqueeze(0)
    window = window.unsqueeze(0).unsqueeze(0).expand(C, 1, -1, -1)

    pad = window_size // 2
    mu1 = F.conv2d(img1, window, padding=pad, groups=C)
    mu2 = F.conv2d(img2, window, padding=pad, groups=C)

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = F.conv2d(img1 * img1, window, padding=pad, groups=C) - mu1_sq
    sigma2_sq = F.conv2d(img2 * img2, window, padding=pad, groups=C) - mu2_sq
    sigma12 = F.conv2d(img1 * img2, window, padding=pad, groups=C) - mu1_mu2

    C1 = 0.01 ** 2
    C2 = 0.03 ** 2

    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / \
               ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))

    return ssim_map.mean()


# ---------------------------------------------------------------------------
# Densification & pruning
# ---------------------------------------------------------------------------

def _densify_and_prune(
    model: GaussianModel,
    optimizer: torch.optim.Optimizer,
    config: PipelineConfig,
    iteration: int,
) -> dict[str, int]:
    """Perform adaptive density control: split, clone, prune."""
    tc = config.train
    stats = {"split": 0, "clone": 0, "prune": 0}

    avg_grad = model.grad_accum / model.grad_count.clamp(min=1)
    avg_grad = avg_grad.squeeze(-1)

    # Identify Gaussians with large positional gradients
    big_grad_mask = avg_grad >= tc.densify_grad_threshold

    # Split: large gradient AND large scale
    scales_exp = torch.exp(model.scales)
    large_scale_mask = scales_exp.max(dim=1).values > 0.01  # world-space threshold
    split_mask = big_grad_mask & large_scale_mask

    # Clone: large gradient AND small scale
    clone_mask = big_grad_mask & ~large_scale_mask

    # --- Clone ---
    if clone_mask.any():
        n_clone = clone_mask.sum().item()
        new_means = model.means[clone_mask].clone()
        new_scales = model.scales[clone_mask].clone()
        new_rotations = model.rotations[clone_mask].clone()
        new_opacities = model.opacities[clone_mask].clone()
        new_sh_dc = model.sh_dc[clone_mask].clone()
        new_sh_rest = model.sh_rest[clone_mask].clone()
        stats["clone"] = n_clone

    # --- Split ---
    if split_mask.any():
        n_split = split_mask.sum().item()
        # Split each Gaussian into 2 with reduced scale
        split_means = model.means[split_mask].repeat(2, 1)
        split_scales = model.scales[split_mask].repeat(2, 1) - math.log(1.6)  # reduce scale
        split_rotations = model.rotations[split_mask].repeat(2, 1)
        split_opacities = model.opacities[split_mask].repeat(2, 1)
        split_sh_dc = model.sh_dc[split_mask].repeat(2, 1, 1)
        split_sh_rest = model.sh_rest[split_mask].repeat(2, 1, 1)

        # Add noise to positions
        stds = torch.exp(model.scales[split_mask])
        noise = torch.randn_like(split_means) * stds.repeat(2, 1) * 0.5
        split_means = split_means + noise
        stats["split"] = n_split

    # --- Prune ---
    opacity_activated = torch.sigmoid(model.opacities.squeeze(-1))
    prune_mask = opacity_activated < tc.prune_opacity_threshold

    # Also prune overly large Gaussians
    scale_prune = scales_exp.max(dim=1).values > tc.prune_scale_threshold
    prune_mask = prune_mask | scale_prune

    # Remove split originals too
    if split_mask.any():
        prune_mask = prune_mask | split_mask

    keep_mask = ~prune_mask

    # --- Apply changes ---
    # Keep surviving Gaussians
    new_params = {
        "means": model.means[keep_mask],
        "scales": model.scales[keep_mask],
        "rotations": model.rotations[keep_mask],
        "opacities": model.opacities[keep_mask],
        "sh_dc": model.sh_dc[keep_mask],
        "sh_rest": model.sh_rest[keep_mask],
    }
    stats["prune"] = prune_mask.sum().item()

    # Append cloned and split Gaussians
    tensors_to_cat: dict[str, list[torch.Tensor]] = {k: [v] for k, v in new_params.items()}
    if clone_mask.any():
        tensors_to_cat["means"].append(new_means)
        tensors_to_cat["scales"].append(new_scales)
        tensors_to_cat["rotations"].append(new_rotations)
        tensors_to_cat["opacities"].append(new_opacities)
        tensors_to_cat["sh_dc"].append(new_sh_dc)
        tensors_to_cat["sh_rest"].append(new_sh_rest)
    if split_mask.any():
        tensors_to_cat["means"].append(split_means)
        tensors_to_cat["scales"].append(split_scales)
        tensors_to_cat["rotations"].append(split_rotations)
        tensors_to_cat["opacities"].append(split_opacities)
        tensors_to_cat["sh_dc"].append(split_sh_dc)
        tensors_to_cat["sh_rest"].append(split_sh_rest)

    final_params = {k: torch.cat(v, dim=0) for k, v in tensors_to_cat.items()}

    # Replace model parameters in-place and reset optimizer state
    _replace_params(model, optimizer, final_params)
    model.reset_densification_stats()

    return stats


def _replace_params(
    model: GaussianModel,
    optimizer: torch.optim.Optimizer,
    new_params: dict[str, torch.Tensor],
) -> None:
    """Replace model parameters and rebuild optimizer state.

    Clears all Adam momentum buffers since the Gaussian population changed.
    Preserves learning rates from existing param groups.
    """
    # Set new parameter tensors on the model
    for name in ["means", "scales", "rotations", "opacities", "sh_dc", "sh_rest"]:
        new_val = new_params[name].detach().requires_grad_(True)
        setattr(model, name, new_val)

    # Clear ALL optimizer state (momentum buffers are invalid after densification)
    optimizer.state.clear()

    # Update each param group to point at the new tensors
    for pg in optimizer.param_groups:
        param_name = pg["name"]
        pg["params"] = [getattr(model, param_name)]


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------

def save_checkpoint(
    model: GaussianModel,
    optimizer: torch.optim.Optimizer,
    iteration: int,
    config: PipelineConfig,
    path: Path,
) -> None:
    """Save training checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "iteration": iteration,
        "means": model.means.detach().cpu(),
        "scales": model.scales.detach().cpu(),
        "rotations": model.rotations.detach().cpu(),
        "opacities": model.opacities.detach().cpu(),
        "sh_dc": model.sh_dc.detach().cpu(),
        "sh_rest": model.sh_rest.detach().cpu(),
        "optimizer_state": optimizer.state_dict(),
    }, path)


def load_checkpoint(
    path: Path,
    config: PipelineConfig,
    device: str = "cuda",
) -> tuple[GaussianModel, dict, int]:
    """Load checkpoint. Returns (model, optimizer_state_dict, iteration)."""
    data = torch.load(path, map_location=device, weights_only=True)

    model = GaussianModel(
        means=data["means"].to(device).requires_grad_(True),
        scales=data["scales"].to(device).requires_grad_(True),
        rotations=data["rotations"].to(device).requires_grad_(True),
        opacities=data["opacities"].to(device).requires_grad_(True),
        sh_dc=data["sh_dc"].to(device).requires_grad_(True),
        sh_rest=data["sh_rest"].to(device).requires_grad_(True),
    )
    model.reset_densification_stats()

    return model, data.get("optimizer_state"), data["iteration"]


# ---------------------------------------------------------------------------
# Main training loop
# ---------------------------------------------------------------------------

def is_complete(run_dir: Path) -> bool:
    marker = run_dir / STAGE_MARKER
    model_path = run_dir / "train" / "final_model.pt"
    return marker.exists() and model_path.exists()


def run_train(config: PipelineConfig, run_dir: Path) -> dict:
    """Run the Gaussian splat training stage."""
    log = get_logger()

    if config.run.resume and is_complete(run_dir):
        log.info("[bold green]Stage 3 (Train): skipping — already complete[/]")
        with open(run_dir / STAGE_MARKER) as f:
            return json.load(f)

    log.info("[bold cyan]Stage 3 (Train): starting[/]")

    # Verify torch + CUDA
    if not torch.cuda.is_available():
        raise TrainError(
            "CUDA is not available. GPU required for training. "
            "Check your CUDA and PyTorch installation."
        )

    device = "cuda"
    tc = config.train

    # Import gsplat
    try:
        from gsplat import rasterization
    except ImportError:
        raise TrainError(
            "gsplat not installed. Install: pip install gsplat. "
            "Requires CUDA toolkit matching your PyTorch version."
        )

    # Load COLMAP model and cameras
    model_dir = run_dir / "sparse" / "0"
    images_dir = run_dir / "images"
    cam_infos = load_cameras(model_dir, images_dir)
    log.info(f"Loaded {len(cam_infos)} training cameras")

    # Check for checkpoint to resume from
    train_dir = run_dir / "train"
    ckpt_dir = train_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    start_iter = 0
    optimizer_state = None

    existing_ckpts = sorted(ckpt_dir.glob("iter_*.pt"))
    if config.run.resume and existing_ckpts:
        latest_ckpt = existing_ckpts[-1]
        log.info(f"Resuming from checkpoint: {latest_ckpt.name}")
        model, optimizer_state, start_iter = load_checkpoint(latest_ckpt, config, device)
        start_iter += 1  # Start from next iteration
    else:
        model = init_from_colmap(model_dir, tc.sh_degree, device)

    # Setup optimizer
    optimizer = torch.optim.Adam(model.param_groups(config), eps=1e-15)
    if optimizer_state is not None:
        try:
            optimizer.load_state_dict(optimizer_state)
        except Exception as e:
            log.warning(f"Could not restore optimizer state: {e}. Starting fresh optimizer.")

    # Set random seed
    torch.manual_seed(config.run.seed)
    np.random.seed(config.run.seed)

    # Background color
    bg_color = torch.tensor(
        [1.0, 1.0, 1.0] if tc.white_background else [0.0, 0.0, 0.0],
        device=device,
    )

    # Training metrics log
    metrics_log: list[dict] = []
    t_start = time.time()

    log.info(
        f"Training: {tc.iterations} iterations, {model.num_gaussians} initial Gaussians, "
        f"SH degree {tc.sh_degree}"
    )

    for iteration in range(start_iter, tc.iterations):
        # Update position learning rate
        lr = get_position_lr(iteration, config)
        for pg in optimizer.param_groups:
            if pg["name"] == "means":
                pg["lr"] = lr

        # Random camera
        cam_idx = np.random.randint(len(cam_infos))
        cam = cam_infos[cam_idx]

        # Load ground truth
        gt_image = load_gt_image(cam, device)  # (1, H, W, 3)

        # Prepare camera matrices
        viewmat = torch.tensor(cam.world_to_cam, device=device, dtype=torch.float32).unsqueeze(0)
        K = torch.tensor(cam.K, device=device, dtype=torch.float32).unsqueeze(0)

        # Render
        sh_coeffs = model.all_sh()  # (N, (degree+1)^2, 3)

        try:
            renders, alphas, meta = rasterization(
                means=model.means,
                quats=model.rotations,
                scales=torch.exp(model.scales),
                opacities=torch.sigmoid(model.opacities.squeeze(-1)),
                colors=sh_coeffs,
                viewmats=viewmat,
                Ks=K,
                width=cam.width,
                height=cam.height,
                sh_degree=tc.sh_degree,
                backgrounds=bg_color.unsqueeze(0),
            )
        except torch.cuda.OutOfMemoryError:
            raise TrainError(
                f"CUDA out of memory with {model.num_gaussians} Gaussians. "
                "Try reducing image resolution (ingest.images.max_dimension) or "
                "increasing prune aggressiveness (train.prune_opacity_threshold)."
            )

        rendered = renders[..., :3]  # (1, H, W, 3)

        # Loss: L1 + SSIM
        l1_loss = F.l1_loss(rendered, gt_image)
        ssim_val = _ssim(rendered, gt_image)
        loss = (1.0 - tc.loss_lambda_dssim) * l1_loss + tc.loss_lambda_dssim * (1.0 - ssim_val)

        # Check for NaN
        if torch.isnan(loss):
            # Save last valid state
            save_checkpoint(model, optimizer, iteration, config, ckpt_dir / f"iter_{iteration}_nan.pt")
            raise TrainError(
                f"NaN loss detected at iteration {iteration}. "
                f"Last valid checkpoint saved. This may indicate learning rate issues "
                f"or degenerate Gaussians."
            )

        loss.backward()

        # Accumulate gradients for densification
        if model.means.grad is not None:
            grad_norm = model.means.grad.norm(dim=-1, keepdim=True)
            model.grad_accum[:model.num_gaussians] += grad_norm.detach()
            model.grad_count[:model.num_gaussians] += 1

        optimizer.step()
        optimizer.zero_grad(set_to_none=True)

        # Densification
        if tc.densify_from_iter <= iteration < tc.densify_until_iter:
            if iteration % tc.densify_interval == 0 and iteration > 0:
                density_stats = _densify_and_prune(model, optimizer, config, iteration)
                log.info(
                    f"  Densify @{iteration}: "
                    f"+{density_stats['clone']} clone, +{density_stats['split']} split, "
                    f"-{density_stats['prune']} prune -> {model.num_gaussians} total"
                )

        # Logging
        if iteration % tc.log_interval == 0:
            psnr = 10.0 * math.log10(1.0 / max(l1_loss.item(), 1e-10))
            entry = {
                "iteration": iteration,
                "loss": round(loss.item(), 6),
                "l1_loss": round(l1_loss.item(), 6),
                "ssim": round(ssim_val.item(), 4),
                "psnr": round(psnr, 2),
                "num_gaussians": model.num_gaussians,
                "lr": lr,
            }
            metrics_log.append(entry)

            if iteration % (tc.log_interval * 10) == 0:
                elapsed = time.time() - t_start
                log.info(
                    f"  iter {iteration}/{tc.iterations}: loss={loss.item():.4f}, "
                    f"psnr={psnr:.1f}, gaussians={model.num_gaussians}, "
                    f"elapsed={elapsed:.0f}s"
                )

        # Checkpoint
        if iteration > 0 and iteration % tc.checkpoint_interval == 0:
            ckpt_path = ckpt_dir / f"iter_{iteration}.pt"
            save_checkpoint(model, optimizer, iteration, config, ckpt_path)
            log.info(f"  Checkpoint saved: {ckpt_path.name}")

    # Save final model
    final_path = train_dir / "final_model.pt"
    save_checkpoint(model, optimizer, tc.iterations, config, final_path)

    # Save metrics
    metrics_path = train_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics_log, f, indent=2)

    # Compute final stats
    elapsed = time.time() - t_start
    final_metrics = metrics_log[-1] if metrics_log else {}

    report = {
        "iterations": tc.iterations,
        "final_gaussians": model.num_gaussians,
        "final_loss": final_metrics.get("loss", 0),
        "final_psnr": final_metrics.get("psnr", 0),
        "final_ssim": final_metrics.get("ssim", 0),
        "training_time_seconds": round(elapsed, 1),
        "resumed_from_iteration": start_iter,
    }

    report_path = run_dir / STAGE_MARKER
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    log.info(
        f"[bold green]Stage 3 (Train): complete — {model.num_gaussians} Gaussians, "
        f"PSNR={report['final_psnr']}, {elapsed:.0f}s[/]"
    )
    return report
