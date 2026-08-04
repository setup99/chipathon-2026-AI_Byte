# Control Unit (compute-only) — cocotb
#
#   make        # run tests, delete results.xml / waves
#   make clean

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
WAVES ?= 0

ROOT := $(abspath ..)
VENV := $(ROOT)/.venv
export PATH := $(VENV)/bin:$(PATH)
export PYTHONPATH := $(CURDIR):$(PYTHONPATH)
export COCOTB_REDUCED_LOG_FMT ?= 1

COCOTB_MAKEFILES := $(shell $(VENV)/bin/cocotb-config --makefiles)

.PHONY: all cocotb clean
all: cocotb

cocotb:
	$(MAKE) -f $(COCOTB_MAKEFILES)/Makefile.sim \
		SIM=$(SIM) TOPLEVEL_LANG=$(TOPLEVEL_LANG) WAVES=$(WAVES) \
		VERILOG_SOURCES="$(CURDIR)/ai_byte_control_unit.v" \
		COCOTB_TOPLEVEL=ai_byte_control_unit \
		COCOTB_TEST_MODULES=test_control_unit \
		SIM_BUILD=sim_build \
		COCOTB_RESULTS_FILE=results.xml
	$(RM) results.xml *.vcd *.fst

clean:
	$(RM) -rf sim_build results.xml *.vcd *.fst __pycache__
