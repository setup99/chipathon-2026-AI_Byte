"""
Dataset loader for PlantVillage Leaf Disease v2 (Tomato: 4 Classes).
Classes:
  0: Healthy
  1: Early Blight
  2: Late Blight
  3: Bacterial Spot

Prepares raw images (3, 32, 32) uint8, downsampled (3, 16, 16), and INT8 quantized [-64, 63].
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple
import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"
NPZ_PATH = DATA_DIR / "plantvillage_leaf_tomato_v2.npz"

CLASSES = ["healthy", "early_blight", "late_blight", "bacterial_spot"]
CLASS_NAMES = ["Healthy", "Early Blight", "Late Blight", "Bacterial Spot"]


def load_raw_dataset(split: str = "test") -> Tuple[np.ndarray, np.ndarray]:
    """Loads raw (N, 3, 32, 32) uint8 images and (N,) labels."""
    if not NPZ_PATH.exists():
        raise FileNotFoundError(f"Dataset not found at {NPZ_PATH}")
    data = np.load(NPZ_PATH)
    if split == "train":
        return data["train_x"], data["train_y"]
    elif split == "test":
        return data["test_x"], data["test_y"]
    else:
        raise ValueError(f"Unknown split: {split}")


def downsample_16x16(images: np.ndarray) -> np.ndarray:
    """Downsample (N, 3, 32, 32) -> (N, 3, 16, 16) via 2x2 average pooling."""
    return images.reshape(-1, 3, 16, 2, 16, 2).mean(axis=(3, 5))


def quantize_int8(images: np.ndarray) -> np.ndarray:
    """Map [0, 255] float to signed INT8 [-64, 63]."""
    return np.clip(np.round((images / 255.0) * 126.0 - 63.0), -128, 127).astype(np.int8)


def get_leaf_dataset_v2(split: str = "test") -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns (raw_images_uint8, quantized_int8_16x16, labels):
      raw_images: (N, 3, 32, 32) uint8
      quantized_images: (N, 3, 16, 16) int8
      labels: (N,) uint8 (0=healthy, 1=early_blight, 2=late_blight, 3=bacterial_spot)
    """
    raw_imgs, lbls = load_raw_dataset(split)
    ds_imgs = downsample_16x16(raw_imgs)
    int8_imgs = quantize_int8(ds_imgs)
    return raw_imgs, int8_imgs, lbls
