"""
MNIST dataset loader, preprocessor, and INT8 quantizer for AI_BYTE CNN testing.
Downloads official MNIST gz files and prepares quantized test vectors.
"""
from __future__ import annotations

import gzip
import os
import urllib.request
from pathlib import Path
from typing import Tuple

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"

MNIST_URLS = {
    "train_img": "https://storage.googleapis.com/cvdf-datasets/mnist/train-images-idx3-ubyte.gz",
    "train_lbl": "https://storage.googleapis.com/cvdf-datasets/mnist/train-labels-idx1-ubyte.gz",
    "test_img": "https://storage.googleapis.com/cvdf-datasets/mnist/t10k-images-idx3-ubyte.gz",
    "test_lbl": "https://storage.googleapis.com/cvdf-datasets/mnist/t10k-labels-idx1-ubyte.gz",
}


def download_mnist(data_dir: Path = DATA_DIR) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, url in MNIST_URLS.items():
        fname = url.split("/")[-1]
        dest = data_dir / fname
        if not dest.is_file():
            print(f"Downloading {fname} from {url}...")
            urllib.request.urlretrieve(url, dest)
            print(f"Saved {dest} ({dest.stat().st_size} bytes)")


def load_raw_split(split: str = "test", data_dir: Path = DATA_DIR) -> Tuple[np.ndarray, np.ndarray]:
    """Load raw MNIST images (N, 28, 28) uint8 and labels (N,) uint8."""
    download_mnist(data_dir)
    img_fname = "t10k-images-idx3-ubyte.gz" if split == "test" else "train-images-idx3-ubyte.gz"
    lbl_fname = "t10k-labels-idx1-ubyte.gz" if split == "test" else "train-labels-idx1-ubyte.gz"

    with gzip.open(data_dir / img_fname, "rb") as f:
        images = np.frombuffer(f.read(), dtype=np.uint8, offset=16).reshape(-1, 28, 28)
    with gzip.open(data_dir / lbl_fname, "rb") as f:
        labels = np.frombuffer(f.read(), dtype=np.uint8, offset=8)

    return images, labels


def preprocess_and_quantize(images: np.ndarray, target_size: int = 14) -> np.ndarray:
    """
    Downsamples 28x28 images to target_size (e.g. 14x14) via 2x2 average pooling,
    then quantizes to signed INT8 [-128, 127] with zero centering.
    """
    if target_size == 14:
        # 2x2 average pooling from 28x28 -> 14x14
        h, w = images.shape[1], images.shape[2]
        downsampled = images.reshape(-1, target_size, 2, target_size, 2).mean(axis=(2, 4))
    else:
        downsampled = images.astype(np.float32)

    # Scale [0, 255] -> signed INT8 [-64, 63] (or [-128, 127])
    # Mapping to [-64, 63] gives a balanced dynamic range suitable for INT8 dot products
    # without premature INT16 overflow before accumulation
    int8_imgs = np.clip(np.round((downsampled / 255.0) * 126.0 - 63.0), -128, 127).astype(np.int8)
    return int8_imgs


def get_test_dataset(num_samples: int | None = None, data_dir: Path = DATA_DIR) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns (images_int8, labels):
    images_int8: (N, 14, 14) int8
    labels: (N,) uint8
    Cached in data/mnist_test_14x14_int8.npz
    """
    cache_file = data_dir / "mnist_test_14x14_int8.npz"
    if cache_file.is_file():
        data = np.load(cache_file)
        imgs, lbls = data["images"], data["labels"]
    else:
        raw_imgs, lbls = load_raw_split("test", data_dir)
        imgs = preprocess_and_quantize(raw_imgs, target_size=14)
        data_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_file, images=imgs, labels=lbls)
        print(f"Cached {len(imgs)} test images to {cache_file}")

    if num_samples is not None:
        return imgs[:num_samples], lbls[:num_samples]
    return imgs, lbls


if __name__ == "__main__":
    imgs, lbls = get_test_dataset(100)
    print(f"Loaded {len(imgs)} samples: shape={imgs.shape}, dtype={imgs.dtype}")
    print(f"Label sample: {lbls[:10]}")
    print(f"Pixel range: min={imgs.min()}, max={imgs.max()}")

