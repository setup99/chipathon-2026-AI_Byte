"""
CIFAR-10 dataset loader, preprocessor, and INT8 quantizer for AI_BYTE CNN testing.
Downloads official CIFAR-10 python batches and prepares quantized test vectors.
"""
from __future__ import annotations

import os
import pickle
import tarfile
import urllib.request
from pathlib import Path
from typing import Tuple

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"
CIFAR_URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"

def download_and_extract_cifar(data_dir: Path = DATA_DIR) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    tar_path = data_dir / "cifar-10-python.tar.gz"
    extract_path = data_dir / "cifar-10-batches-py"
    
    if not extract_path.is_dir():
        if not tar_path.is_file():
            print(f"Downloading CIFAR-10 from {CIFAR_URL}...")
            urllib.request.urlretrieve(CIFAR_URL, tar_path)
            print(f"Saved {tar_path}")
        
        print(f"Extracting {tar_path}...")
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=data_dir)
            
    return extract_path

def load_raw_split(split: str = "test", data_dir: Path = DATA_DIR) -> Tuple[np.ndarray, np.ndarray]:
    """Load raw CIFAR-10 images (N, 3, 32, 32) uint8 and labels (N,) uint8."""
    extract_path = download_and_extract_cifar(data_dir)
    
    if split == "train":
        images = []
        labels = []
        for i in range(1, 6):
            with open(extract_path / f"data_batch_{i}", "rb") as f:
                batch = pickle.load(f, encoding="bytes")
                images.append(batch[b"data"])
                labels.extend(batch[b"labels"])
        images = np.vstack(images).reshape(-1, 3, 32, 32)
        labels = np.array(labels, dtype=np.uint8)
    else:
        with open(extract_path / "test_batch", "rb") as f:
            batch = pickle.load(f, encoding="bytes")
            images = batch[b"data"].reshape(-1, 3, 32, 32)
            labels = np.array(batch[b"labels"], dtype=np.uint8)
            
    # CIFAR-10 is stored as channels-first. Let's keep it (N, C, H, W).
    return images, labels

def preprocess_and_quantize(images: np.ndarray) -> np.ndarray:
    """
    Quantizes to signed INT8 [-64, 63] with zero centering.
    Input shape: (N, C, H, W) where C=3, H=32, W=32
    """
    int8_imgs = np.clip(np.round((images.astype(np.float32) / 255.0) * 126.0 - 63.0), -128, 127).astype(np.int8)
    return int8_imgs

def get_test_dataset(num_samples: int | None = None, data_dir: Path = DATA_DIR) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns (images_int8, labels):
    images_int8: (N, 3, 32, 32) int8
    labels: (N,) uint8
    """
    cache_file = data_dir / "cifar10_test_int8.npz"
    if cache_file.is_file():
        data = np.load(cache_file)
        imgs, lbls = data["images"], data["labels"]
    else:
        raw_imgs, lbls = load_raw_split("test", data_dir)
        imgs = preprocess_and_quantize(raw_imgs)
        data_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_file, images=imgs, labels=lbls)
        print(f"Cached {len(imgs)} test images to {cache_file}")

    if num_samples is not None:
        return imgs[:num_samples], lbls[:num_samples]
    return imgs, lbls

if __name__ == "__main__":
    imgs, lbls = get_test_dataset(10)
    print(f"Loaded {len(imgs)} samples: shape={imgs.shape}, dtype={imgs.dtype}")
    print(f"Label sample: {lbls[:10]}")
    print(f"Pixel range: min={imgs.min()}, max={imgs.max()}")

