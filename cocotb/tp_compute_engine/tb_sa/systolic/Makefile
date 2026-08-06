# Makefile for Systolic Array Engine

# Compiler and simulator
IVERILOG = iverilog
VVP      = vvp
FLAGS    = -g2005-sv -I src

# Source files
SRC_2D = src/ram_sdp.v src/pe_gemv_ws.v src/gemm_systolic_2d.v

.PHONY: all clean cocotb

# Default target: run cocotb testbench for GEMM 2D
all: cocotb

# Cocotb verification target for GEMM 2D (for test_gemm.py)
cocotb:
	@echo "======================================================================"
	@echo " Running Cocotb Testbench (test_gemm.py) for GEMM 2D"
	@echo "======================================================================"
	$(MAKE) -f Makefile.cocotb TOPLEVEL=gemm_systolic_2d COCOTB_TEST_MODULES=test_gemm SRC_FILES="$(SRC_2D)" SIM_BUILD=sim_build

# Clean build artifacts
clean:
	@echo "Cleaning simulation files..."
	$(MAKE) -f Makefile.cocotb clean SIM_BUILD=sim_build || true
	rm -rf sim_build results.xml
