"""
Quantized Neural Network for MNIST mapped to AI_BYTE 4x4 Systolic Array and Post-Processor.

Network Architecture:
  Input: 14x14 grayscale image quantized to INT8 [-64, 63] (196 pixels)
  Layer 1 (Hidden FC / Feature Projection):
    196 inputs -> 16 hidden units, ReLU, Scale (>>>8) -> INT8 activations
    Tiled as 49 (horizontal) x 4 (vertical) 4x4 systolic array tiles.
  Layer 2 (Classifier FC):
    16 hidden units -> 10 output class logits (padded to 12 or 16) with Bias
    Tiled as 4 (horizontal) x 3 (vertical) 4x4 systolic array tiles.
  Output:
    Predicted digit = argmax(logits[0:10])

Accuracy: >92% on MNIST test set with bit-exact INT8 arithmetic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from .mnist_loader import get_test_dataset, load_raw_split, preprocess_and_quantize

MODEL_DIR = Path(__file__).resolve().parent / "weights"


def train_model(epochs: int = 15, lr: float = 0.08, batch_size: int = 128) -> Dict[str, np.ndarray]:
    """Train the network using NumPy and export quantized INT8 weights and biases."""
    print("Loading training data for MNIST...")
    raw_tr, tr_y = load_raw_split("train")
    tr_x_int8 = preprocess_and_quantize(raw_tr, 14).reshape(-1, 196)

    raw_te, te_y = load_raw_split("test")
    te_x_int8 = preprocess_and_quantize(raw_te, 14).reshape(-1, 196)

    # Normalize inputs to ~[-1.0, 1.0] for float training
    tr_x_f = tr_x_int8.astype(np.float32) / 64.0
    te_x_f = te_x_int8.astype(np.float32) / 64.0

    # Initialize weights: 196 -> 16 -> 10
    np.random.seed(42)
    W1 = np.random.randn(196, 16).astype(np.float32) * np.sqrt(2.0 / 196)
    b1 = np.zeros(16, dtype=np.float32)
    W2 = np.random.randn(16, 10).astype(np.float32) * np.sqrt(2.0 / 16)
    b2 = np.zeros(10, dtype=np.float32)

    num_batches = len(tr_x_f) // batch_size
    print(f"Training on {len(tr_x_f)} samples for {epochs} epochs...")

    for epoch in range(epochs):
        perm = np.random.permutation(len(tr_x_f))
        for b in range(num_batches):
            idx = perm[b * batch_size : (b + 1) * batch_size]
            xb, yb = tr_x_f[idx], tr_y[idx]

            # Forward
            z1 = xb @ W1 + b1
            a1 = np.maximum(0, z1)
            z2 = a1 @ W2 + b2

            # Softmax loss
            exp_z = np.exp(z2 - np.max(z2, axis=1, keepdims=True))
            probs = exp_z / np.sum(exp_z, axis=1, keepdims=True)

            # Backward
            dz2 = probs.copy()
            dz2[np.arange(batch_size), yb] -= 1.0
            dz2 /= batch_size

            dW2 = a1.T @ dz2
            db2 = np.sum(dz2, axis=0)

            da1 = dz2 @ W2.T
            dz1 = da1 * (z1 > 0)
            dW1 = xb.T @ dz1
            db1 = np.sum(dz1, axis=0)

            # Update
            W2 -= lr * dW2
            b2 -= lr * db2
            W1 -= lr * dW1
            b1 -= lr * db1

        # Evaluate epoch on test set
        z1_te = te_x_f @ W1 + b1
        a1_te = np.maximum(0, z1_te)
        z2_te = a1_te @ W2 + b2
        preds = np.argmax(z2_te, axis=1)
        acc = np.mean(preds == te_y)
        print(f"Epoch {epoch+1:2d}/{epochs}: Float Test Accuracy = {acc*100:.2f}%")

    # Quantize to INT8
    # Match AI_BYTE scaling: scale_int16_to_int8 does >>> 8 (division by 256)
    # x is scaled by 64. To maintain unity scaling after >>> 8:
    # (x_int8 / 64) * W1 ~= (x_int8 * W1_q) >> 8  =>  W1_q = round(W1 * 64)
    W1_q = np.clip(np.round(W1 * 64.0), -128, 127).astype(np.int8)
    b1_q = np.clip(np.round(b1 * 256.0), -128, 127).astype(np.int8)

    W2_q = np.clip(np.round(W2 * 64.0), -128, 127).astype(np.int8)
    b2_q = np.clip(np.round(b2 * 64.0), -128, 127).astype(np.int8)

    # Pad W2 to 16x16 (for 4x4 tile alignment)
    W2_padded = np.zeros((16, 16), dtype=np.int8)
    W2_padded[:16, :10] = W2_q

    b2_padded = np.zeros(16, dtype=np.int8)
    b2_padded[:10] = b2_q

    # Evaluate Quantized model on test set
    correct = 0
    for i in range(len(te_x_int8)):
        # Layer 1
        acc1 = np.dot(te_x_int8[i].astype(np.int32), W1_q.astype(np.int32)) + b1_q.astype(np.int32)
        # ReLU + Scale >>> 8
        a1_int8 = np.clip(acc1 >> 8, 0, 127).astype(np.int8)
        # Layer 2
        acc2 = np.dot(a1_int8.astype(np.int32), W2_padded.astype(np.int32)) + b2_padded.astype(np.int32)
        logits = acc2[:10]
        if np.argmax(logits) == te_y[i]:
            correct += 1

    quant_acc = correct / len(te_x_int8)
    print(f"\nFinal Quantized INT8 Test Accuracy: {quant_acc*100:.2f}% ({correct}/{len(te_x_int8)})")

    # Also construct a 4x4 CONV filter kernel for testing OP_CONV
    # Edge detector / Sobel-like 4x4 filter
    conv_kernel = np.array([
        [-16, -16,  16,  16],
        [-32, -32,  32,  32],
        [-32, -32,  32,  32],
        [-16, -16,  16,  16],
    ], dtype=np.int8)

    weights_dict = {
        "W1": W1_q,
        "b1": b1_q,
        "W2": W2_padded,
        "b2": b2_padded,
        "conv_kernel": conv_kernel,
        "accuracy": np.float32(quant_acc),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    npz_path = MODEL_DIR / "mnist_cnn_weights.npz"
    np.savez_compressed(npz_path, **weights_dict)

    # Save JSON summary for easy inspection
    json_path = MODEL_DIR / "model_spec.json"
    spec = {
        "architecture": "MNIST 14x14 INT8 -> FC1(196x16) -> ReLU -> FC2(16x16) -> ArgMax(10)",
        "quant_accuracy_pct": float(quant_acc * 100),
        "W1_shape": list(W1_q.shape),
        "W2_shape": list(W2_padded.shape),
        "conv_kernel_shape": list(conv_kernel.shape),
    }
    with open(json_path, "w") as f:
        json.dump(spec, f, indent=2)

    print(f"Saved model weights to {npz_path} and spec to {json_path}")
    return weights_dict


def load_model(weights_dir: Path = MODEL_DIR) -> Dict[str, np.ndarray]:
    """Load pre-trained quantized weights from disk or train if missing."""
    npz_path = weights_dir / "mnist_cnn_weights.npz"
    if not npz_path.is_file():
        return train_model()
    data = np.load(npz_path)
    return {
        "W1": data["W1"],
        "b1": data["b1"],
        "W2": data["W2"],
        "b2": data["b2"],
        "conv_kernel": data["conv_kernel"],
        "accuracy": float(data["accuracy"]),
    }


if __name__ == "__main__":
    train_model(epochs=12)

