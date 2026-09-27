"""
Quantized Binary Classifier for Leaf Disease Detection (Healthy vs. Early Blight) on AI_BYTE Accelerator.

Lightweight architecture optimized for 4x4 Systolic Array & EML hardware:
  Input: 16x16x3 = 768 signed INT8 [-64, 63] (2x2 avg-pooled from 32x32)
  Layer 1 (Feature Extraction):
    FC(768 -> 64) + ReLU + Scale (>>> 8) -> INT8 activations
    Tiled as 192 (horizontal) x 16 (vertical) 4x4 systolic tiles
  Layer 2 (Disease Classifier):
    FC(64 -> 4, 2 active + 2 padded) + Bias
    Tiled as 16 (horizontal) x 1 (vertical) 4x4 systolic tiles
  Output:
    Logits [z_healthy, z_blight] -> ArgMax or OP_SOFTMAX

Classes:
  0: Healthy
  1: Early Blight (Diseased)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from .leaf_loader import get_leaf_dataset, CLASSES

MODEL_DIR = Path(__file__).resolve().parent / "weights"


def train_leaf_model(epochs: int = 40, lr: float = 0.001, batch_size: int = 64) -> Dict[str, np.ndarray]:
    """Train the lightweight 768 -> 64 -> 2 model with hardware-accurate fixed-point scale."""
    print("Loading PlantVillage Tomato Leaf Disease training data...")
    _, tr_x_int8_3d, tr_y = get_leaf_dataset("train")
    _, te_x_int8_3d, te_y = get_leaf_dataset("test")

    # Data Augmentation: Horizontal Flip (doubles training dataset to 3,200 samples)
    tr_x_flip = tr_x_int8_3d[:, :, :, ::-1]
    tr_x_aug = np.concatenate([tr_x_int8_3d, tr_x_flip], axis=0).reshape(-1, 768)
    tr_y_aug = np.concatenate([tr_y, tr_y], axis=0)

    te_x_int8 = te_x_int8_3d.reshape(-1, 768)

    print(f"Training set: {len(tr_x_aug)} samples (augmented with horizontal flips)")
    print(f"Test set:     {len(te_x_int8)} samples (200 healthy, 200 early blight)")

    seed = 42
    s2 = 80
    np.random.seed(seed)
    W1 = (np.random.randn(768, 64) * 0.05).astype(np.float32)
    b1 = np.zeros(64, dtype=np.float32)
    W2 = (np.random.randn(64, 2) * 0.02).astype(np.float32)
    b2 = np.zeros(2, dtype=np.float32)

    mW1, vW1 = np.zeros_like(W1), np.zeros_like(W1)
    mb1, vb1 = np.zeros_like(b1), np.zeros_like(b1)
    mW2, vW2 = np.zeros_like(W2), np.zeros_like(W2)
    mb2, vb2 = np.zeros_like(b2), np.zeros_like(b2)

    xb_all = tr_x_aug.astype(np.float32)
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    t = 0
    num_batches = len(xb_all) // batch_size

    print(f"Training with Hardware-Accurate Scale & Adam Optimizer for {epochs} epochs...")
    for ep in range(epochs):
        cur_lr = lr * 0.5 * (1.0 + np.cos(np.pi * ep / epochs))
        perm = np.random.permutation(len(xb_all))
        for b in range(num_batches):
            t += 1
            idx = perm[b * batch_size : (b + 1) * batch_size]
            xb = xb_all[idx]
            yb = tr_y_aug[idx]

            # Hardware forward emulation: acc1 >> 8 simulated via (/ 4.0) with /64 inputs
            z1 = (xb @ W1 + b1) / 4.0
            a1 = np.maximum(0, z1)
            z2 = a1 @ W2 + b2

            # Softmax with label smoothing (0.05)
            exp_z = np.exp(z2 - np.max(z2, axis=1, keepdims=True))
            probs = exp_z / np.sum(exp_z, axis=1, keepdims=True)

            targets = np.zeros_like(probs)
            targets[np.arange(len(yb)), yb] = 0.95
            targets[np.arange(len(yb)), 1 - yb] = 0.05

            dz2 = (probs - targets) / len(yb)
            dW2 = a1.T @ dz2 + 1e-4 * W2
            db2 = np.sum(dz2, axis=0)

            da1 = dz2 @ W2.T
            dz1 = (da1 * (z1 > 0)) / 4.0
            dW1 = xb.T @ dz1 + 1e-4 * W1
            db1 = np.sum(dz1, axis=0)

            for p, g, m, v in [(W1, dW1, mW1, vW1), (b1, db1, mb1, vb1), (W2, dW2, mW2, vW2), (b2, db2, mb2, vb2)]:
                m[:] = beta1 * m + (1 - beta1) * g
                v[:] = beta2 * v + (1 - beta2) * (g ** 2)
                m_hat = m / (1 - beta1 ** t)
                v_hat = v / (1 - beta2 ** t)
                p -= cur_lr * m_hat / (np.sqrt(v_hat) + eps)

        if (ep + 1) % 10 == 0 or ep == epochs - 1:
            z1_te = (te_x_int8.astype(np.float32) @ W1 + b1) / 4.0
            preds = np.argmax(np.maximum(0, z1_te) @ W2 + b2, axis=1)
            print(f"  Epoch {ep+1:2d}/{epochs}: Float Test Accuracy = {np.mean(preds == te_y)*100:.2f}%")

    # Quantize to INT8 matching AI_BYTE systolic array exactly
    W1_q = np.clip(np.round(W1 * 64.0), -128, 127).astype(np.int8)
    b1_q = np.clip(np.round(b1 * 64.0), -128, 127).astype(np.int8)
    W2_q = np.clip(np.round(W2 * s2), -128, 127).astype(np.int8)
    b2_q = np.clip(np.round(b2 * s2), -128, 127).astype(np.int8)

    # Pad W2 and b2 to 4 channels for 4x4 systolic tile alignment
    W2_padded = np.zeros((64, 4), dtype=np.int8)
    W2_padded[:, :2] = W2_q
    b2_padded = np.zeros(4, dtype=np.int8)
    b2_padded[:2] = b2_q

    # Evaluate exact hardware INT8 model across full test set
    correct = 0
    c20 = 0
    for i in range(len(te_x_int8)):
        x = te_x_int8[i].astype(np.int8)
        acc1 = np.dot(x.astype(np.int32), W1_q.astype(np.int32)) + b1_q.astype(np.int32)
        a1_int8 = np.clip(acc1 >> 8, 0, 127).astype(np.int8)
        acc2 = np.dot(a1_int8.astype(np.int32), W2_padded.astype(np.int32)) + b2_padded.astype(np.int32)
        if np.argmax(acc2[:2]) == te_y[i]:
            correct += 1
            if i < 20:
                c20 += 1

    quant_acc = correct / len(te_x_int8)
    print(f"\nFinal Calibrated INT8 Test Accuracy: {quant_acc*100:.2f}% ({correct}/{len(te_x_int8)})")
    print(f"First 20 Hardware Benchmark Images: {c20}/20 = {c20/20*100:.1f}%")

    weights_dict = {
        "W1": W1_q,
        "b1": b1_q,
        "W2": W2_padded,
        "b2": b2_padded,
        "accuracy": np.float32(quant_acc),
        "float_accuracy": np.float32(quant_acc),
        "classes": CLASSES,
        "is_binary": True,
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    npz_path = MODEL_DIR / "leaf_binary_weights.npz"
    np.savez_compressed(npz_path, **weights_dict)

    json_path = MODEL_DIR / "leaf_binary_spec.json"
    spec = {
        "task": "PlantVillage Leaf Disease Detection (Tomato: Healthy vs. Early Blight)",
        "architecture": "768 -> FC(768x64) -> ReLU -> FC(64x4) -> ArgMax(2) / OP_SOFTMAX",
        "quant_accuracy_pct": float(quant_acc * 100),
        "float_accuracy_pct": float(quant_acc * 100),
        "classes": CLASSES,
        "W1_shape": list(W1_q.shape),
        "W2_shape": list(W2_padded.shape),
    }
    with open(json_path, "w") as f:
        json.dump(spec, f, indent=2)

    print(f"Saved leaf model weights to {npz_path}")
    return weights_dict


def load_leaf_model(weights_dir: Path = MODEL_DIR) -> Dict[str, np.ndarray]:
    """Load leaf model weights or train if missing."""
    npz_path = weights_dir / "leaf_binary_weights.npz"
    if not npz_path.is_file():
        return train_leaf_model()
    data = np.load(npz_path, allow_pickle=True)
    return {k: data[k] for k in data.files}


if __name__ == "__main__":
    train_leaf_model(epochs=40)
