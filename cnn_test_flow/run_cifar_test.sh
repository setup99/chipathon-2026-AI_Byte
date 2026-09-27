#!/usr/bin/env bash
# ==============================================================================
# AI_BYTE MNIST CNN Verification Script
# Runs either software Golden co-simulation or cycle-accurate RTL Cocotb test.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PDK_DEFAULT="${HOME}/.cache/ai-byte/pdk/gf180mcu"
PDK_ROOT="${PDK_ROOT:-${PDK_DEFAULT}}"
PDK="${PDK:-gf180mcuD}"
DOCKER_IMAGE="hpretl/iic-osic-tools:latest"

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --golden           Run fast software Golden model verification (Python/NumPy)"
    echo "  --rtl              Run full cycle-accurate Cocotb RTL test in Docker (Icarus Verilog)"
    echo "  --all              Run both Golden and RTL tests (default)"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  PDK_ROOT           Path to PDK root directory (default: ${PDK_DEFAULT})"
    echo "  PDK                PDK variant (default: gf180mcuD)"
    exit 0
}

MODE="all"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --golden)
            MODE="golden"
            shift
            ;;
        --rtl)
            MODE="rtl"
            shift
            ;;
        --all)
            MODE="all"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

run_golden() {
    echo "================================================================================"
    echo "Running AI_BYTE Golden Co-Simulation on CIFAR-10 Dataset..."
    echo "================================================================================"
    docker run --rm \
        -v "${REPO_ROOT}:/workspace" \
        -w /workspace \
        "${DOCKER_IMAGE}" -s bash -c \
        "PYTHONPATH=/workspace:/workspace/cocotb python3 -c '
from cnn_test_flow.cifar_model import load_cifar_model
from cnn_test_flow.cifar_loader import get_test_dataset
from cnn_test_flow.cifar_driver import AiByteCIFARRunner, GoldenBackend

print(\"Loading CIFAR-10 structural verification weights...\")
weights = load_cifar_model()

imgs, lbls = get_test_dataset(1)
runner = AiByteCIFARRunner(GoldenBackend(), weights)

pred, logits = runner.predict_image_sync(imgs[0])
print(f\"Golden Backend Structural Test on 1 CIFAR-10 image. Pred: {pred}\")
print(\"SUCCESS: Golden Co-Simulation Completed.\")
'"
}

run_rtl() {
    echo "================================================================================"
    echo "Running Cycle-Accurate Cocotb RTL Simulation on chip_top (Icarus Verilog)..."
    echo "================================================================================"
    if [ ! -d "${PDK_ROOT}" ]; then
        echo "Error: PDK not found at ${PDK_ROOT}."
        echo "Run 'make clone-pdk' from repo root first."
        exit 1
    fi

    docker run --rm \
        -v "${REPO_ROOT}:/workspace" \
        -v "${HOME}/.cache:${HOME}/.cache" \
        -w /workspace \
        -e PDK_ROOT="${PDK_ROOT}" \
        -e PDK="${PDK}" \
        "${DOCKER_IMAGE}" -s bash -c \
        "PYTHONPATH=/workspace:/workspace/cocotb PDK_ROOT=${PDK_ROOT} PDK=${PDK} COCOTB_TEST_MODULES=cnn_test_flow.test_cifar_cnn python3 cocotb/chip_top_tb.py"
}

case "${MODE}" in
    golden)
        run_golden
        ;;
    rtl)
        run_rtl
        ;;
    all)
        run_golden
        echo ""
        run_rtl
        ;;
esac

