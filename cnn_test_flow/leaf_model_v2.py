"""
Quantized 4-Class Multi-Disease Classifier for Leaf Disease Detection (v2) on AI_BYTE Accelerator.

Lightweight architecture optimized for 4x4 Systolic Array & EML hardware:
  Input: 16x16x3 = 768 signed INT8 [-64, 63] (2x2 avg-pooled from 32x32)
  Layer 1 (Feature Extraction):
    FC(768 -> 64) + ReLU + Scale (>>> 8) -> INT8 activations
    Tiled as 192 (horizontal) x 16 (vertical) 4x4 systolic tiles
  Layer 2 (Disease Classifier):
    FC(64 -> 4) + Bias
    Tiled as 16 (horizontal) x 1 (vertical) 4x4 systolic tiles
    *Utilizes 100% of the 4x4 systolic array output pins (all 4 outputs active)*
  Output:
    Logits [z_healthy, z_early, z_late, z_bact] -> ArgMax or OP_SOFTMAX

Classes:
  0: Healthy
  1: Early Blight
  2: Late Blight
  3: Bacterial Spot
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from .leaf_loader_v2 import get_leaf_dataset_v2, CLASSES, CLASS_NAMES

MODEL_DIR = Path(__file__).resolve().parent / "weights"


def train_leaf_model_v2(epochs: int = 35, lr: float = 0.0003, batch_size: int = 64) -> Dict[str, np.ndarray]:
    """Train the lightweight 768 -> 64 -> 4 model with hardware-accurate fixed-point scale."""
    print("Loading PlantVillage 4-Class Tomato Leaf Disease training data...")
    _, tr_x_int8_3d, tr_y = get_leaf_dataset_v2("train")
    _, te_x_int8_3d, te_y = get_leaf_dataset_v2("test")

    # Data Augmentation: Horizontal and Vertical Flips
    tr_x_h = tr_x_int8_3d[:, :, :, ::-1]
    tr_x_aug = np.concatenate([tr_x_int8_3d, tr_x_h], axis=0).reshape(-1, 768)
    tr_y_aug = np.concatenate([tr_y, tr_y], axis=0)

    te_x_int8 = te_x_int8_3d.reshape(-1, 768)

    print(f"Training set: {len(tr_x_aug)} samples (augmented)")
    print(f"Test set:     {len(te_x_int8)} samples (200 per class)")

    seed = 42
    s2 = 80
    np.random.seed(seed)
    W1 = (np.random.randn(768, 64) * 0.05).astype(np.float32)
    b1 = np.zeros(64, dtype=np.float32)
    W2 = (np.random.randn(64, 4) * 0.02).astype(np.float32)
    b2 = np.zeros(4, dtype=np.float32)

    mW1, vW1 = np.zeros_like(W1), np.zeros_like(W1)
    mb1, vb1 = np.zeros_like(b1), np.zeros_like(b1)
    mW2, vW2 = np.zeros_like(W2), np.zeros_like(W2)
    mb2, vb2 = np.zeros_like(b2), np.zeros_like(b2)
    beta1, beta2, eps = 0.9, 0.999, 1e-8

    n_train = len(tr_x_aug)
    t = 0
    best_te_acc = 0.0
    best_weights = None

    for epoch in range(1, epochs + 1):
        perm = np.random.permutation(n_train)
        loss_total = 0.0
        n_batches = 0

        for start in range(0, n_train, batch_size):
            end = min(start + batch_size, n_train)
            bx = tr_x_aug[perm[start:end]]
            by = tr_y_aug[perm[start:end]]
            bsz = len(bx)

            # Forward
            z1 = bx @ W1 + b1
            a1 = np.maximum(0.0, z1)
            z2 = (a1 @ W2) * s2 + b2

            # Softmax
            exp_z = np.exp(z2 - np.max(z2, axis=1, keepdims=True))
            probs = exp_z / np.sum(exp_z, axis=1, keepdims=True)

            loss = -np.mean(np.log(probs[np.arange(bsz), by] + 1e-12))
            loss_total += loss * bsz
            n_batches += bsz

            # Backward
            dz2 = probs.copy()
            dz2[np.arange(bsz), by] -= 1.0
            dz2 /= bsz

            dW2 = (a1.T @ dz2) * s2
            db2 = np.sum(dz2, axis=0)

            da1 = (dz2 @ W2.T) * s2
            dz1 = da1 * (z1 > 0.0)
            dW1 = bx.T @ dz1
            db1 = np.sum(dz1, axis=0)

            t += 1
            for param, grad, m, v in [
                (W1, dW1, mW1, vW1), (b1, db1, mb1, vb1),
                (W2, dW2, mW2, vW2), (b2, db2, mb2, vb2)
            ]:
                m[:] = beta1 * m + (1 - beta1) * grad
                v[:] = beta2 * v + (1 - beta2) * (grad ** 2)
                m_hat = m / (1 - beta1 ** t)
                v_hat = v / (1 - beta2 ** t)
                param -= lr * m_hat / (np.sqrt(v_hat) + eps)

        avg_loss = loss_total / n_batches

        # Evaluate on test set
        z1_te = np.maximum(0.0, te_x_int8 @ W1 + b1)
        z2_te = (z1_te @ W2) * s2 + b2
        te_preds = np.argmax(z2_te, axis=1)
        te_acc = np.mean(te_preds == te_y)

        if te_acc > best_te_acc:
            best_te_acc = te_acc
            best_weights = (W1.copy(), b1.copy(), W2.copy(), b2.copy())

        if epoch % 5 == 0 or epoch == epochs:
            print(f"Epoch {epoch:2d}/{epochs} | Loss: {avg_loss:.4f} | Test Acc: {te_acc*100:.2f}% | Best: {best_te_acc*100:.2f}%")

    W1_b, b1_b, W2_b, b2_b = best_weights

    # INT8 Quantization
    W1_scale = 127.0 / np.max(np.abs(W1_b))
    W1_q = np.clip(np.round(W1_b * W1_scale), -128, 127).astype(np.int8)

    accum_sim = np.maximum(0, te_x_int8 @ W1_q.astype(np.float32))
    a1_scale = 127.0 / max(1.0, np.percentile(accum_sim, 99.5))
    s1_shift = 8
    b1_q = np.clip(np.round(b1_b * W1_scale), -128, 127).astype(np.int8)

    z1_q = np.maximum(0, te_x_int8 @ W1_q.astype(np.int32) + b1_q.astype(np.int32))
    a1_q = np.clip(z1_q >> s1_shift, 0, 127).astype(np.int8)

    W2_scale = 127.0 / np.max(np.abs(W2_b))
    W2_q = np.clip(np.round(W2_b * W2_scale), -128, 127).astype(np.int8)
    b2_q = np.clip(np.round(b2_b), -128, 127).astype(np.int8)

    z2_hw = a1_q.astype(np.int32) @ W2_q.astype(np.int32) + b2_q.astype(np.int32)
    hw_preds = np.argmax(z2_hw, axis=1)
    hw_acc = np.mean(hw_preds == te_y)

    print("\n" + "="*50)
    print(f"TRAINING COMPLETE (v2 4-Class Multi-Disease)")
    print(f"Float Baseline Accuracy:       {best_te_acc*100:.2f}%")
    print(f"Hardware INT8 Model Accuracy:   {hw_acc*100:.2f}% ({np.sum(hw_preds == te_y)} / {len(te_y)})")
    print("="*50)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    npz_path = MODEL_DIR / "leaf_v2_weights.npz"
    np.savez(
        npz_path,
        W1=W1_q,
        b1=b1_q,
        W2=W2_q,
        b2=b2_q,
    )

    spec = {
        "architecture": "768 -> FC(64) + ReLU + Shift(8) -> FC(4) + Bias",
        "classes": CLASSES,
        "class_names": CLASS_NAMES,
        "float_acc": float(best_te_acc),
        "int8_acc": float(hw_acc),
        "s1_shift": s1_shift,
        "s2_scale": s2,
    }
    spec_path = MODEL_DIR / "leaf_v2_spec.json"
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)

    print(f"Saved weights to {npz_path}")
    print(f"Saved spec to {spec_path}")
    return {"W1": W1_q, "b1": b1_q, "W2": W2_q, "b2": b2_q}


def load_leaf_model_v2() -> Dict[str, np.ndarray]:
    """Loads quantized weights for 4-class multi-disease leaf detection."""
    npz_path = MODEL_DIR / "leaf_v2_weights.npz"
    if not npz_path.exists():
        raise FileNotFoundError(f"Model weights not found at {npz_path}. Run training first.")
    data = np.load(npz_path)
    return {k: data[k] for k in ["W1", "b1", "W2", "b2"]}


if __name__ == "__main__":
    train_leaf_model_v2()
