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
    echo "Running AI_BYTE Golden Co-Simulation on MNIST Dataset..."
    echo "================================================================================"
    docker run --rm \
        -v "${REPO_ROOT}:/workspace" \
        -w /workspace \
        "${DOCKER_IMAGE}" -s bash -c \
        "PYTHONPATH=/workspace:/workspace/cocotb python3 -c '
from cnn_test_flow.model import load_model
from cnn_test_flow.mnist_loader import get_test_dataset
from cnn_test_flow.cnn_driver import AiByteCNNRunner, GoldenBackend

print(\"Loading pre-trained quantized model...\")
weights = load_model()
print(f\"Model Quantized INT8 Test Accuracy: {weights[\"accuracy\"]*100:.2f}%\")

imgs, lbls = get_test_dataset(50)
runner = AiByteCNNRunner(GoldenBackend(), weights)

correct = 0
for i in range(len(imgs)):
    pred, _ = runner.predict_image_sync(imgs[i])
    if pred == lbls[i]:
        correct += 1

print(f\"Golden Backend Test on 50 MNIST digits: {correct}/{len(imgs)} correct ({correct/len(imgs)*100:.1f}%)\")
assert correct >= 45, \"Accuracy on test sample below expected threshold\"
print(\"SUCCESS: Golden Co-Simulation Passed.\")
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
        "PYTHONPATH=/workspace:/workspace/cocotb PDK_ROOT=${PDK_ROOT} PDK=${PDK} COCOTB_TEST_MODULES=cnn_test_flow.test_cnn_mnist python3 cocotb/chip_top_tb.py"
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

